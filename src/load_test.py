import asyncio
import random
import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd
import httpx


@dataclass
class Config:
    excel_path: str = "queries.xlsx"
    sheet_name: Optional[str] = None  # None이면 첫 시트
    user_col: str = "user"
    system_col: str = "system"

    base_url: str = "https://172.17.207.50:8443"
    endpoint: str = "/v1/chat/completions"
    api_key: Optional[str] = None  # 필요 없으면 None

    model: str = "Qwen3-0.6B"
    max_tokens: int = 256
    temperature: float = 0.4
    top_p: float = 0.9
    top_k: int = 10
    presence_penalty: float = 0.2


    # 부하 설정(기본값설정)
    total_requests: int = 10          # 총 요청 수
    concurrency: int = 15              # 동시 요청 수
    ramp_up_seconds: float = 3.0       # 램프업(초). 0이면 즉시
    timeout_seconds: float = 600.0

    # TLS/인증서
    verify_tls: bool = False           # 자체서명 인증서면 False 권장
    # 로그/결과
    out_csv: str = "loadtest_results.csv"


def load_queries(cfg: Config) -> List[Dict[str, str]]:
    df = pd.read_excel(cfg.excel_path, sheet_name=cfg.sheet_name, engine="openpyxl")
    if cfg.user_col not in df.columns:
        raise ValueError(f"엑셀에 '{cfg.user_col}' 컬럼이 필요합니다. 현재 컬럼: {list(df.columns)}")

    # system 컬럼은 없을 수 있음
    has_system = cfg.system_col in df.columns

    rows = []
    for _, r in df.iterrows():
        user = str(r[cfg.user_col]).strip()
        if not user or user.lower() == "nan":
            continue
        system = ""
        if has_system:
            system = str(r[cfg.system_col]).strip()
            if system.lower() == "nan":
                system = ""
        rows.append({"system": system, "user": user})

    if not rows:
        raise ValueError("유효한 user 질의가 없습니다. 엑셀 내용을 확인하세요.")
    return rows


def percentile_ms(values_s: List[float], p: float) -> float:
    if not values_s:
        return float("nan")
    return float(np.percentile(np.array(values_s) * 1000.0, p))


async def one_request(
    client: httpx.AsyncClient,
    cfg: Config,
    q: Dict[str, str],
    default_system: str,
) -> Dict[str, Any]:
    url = cfg.base_url.rstrip("/") + cfg.endpoint

    system_msg = q["system"] if q["system"] else default_system
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": q["user"]},
        ],
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "stream": False,
    }

    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    t0 = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, headers=headers)
        dt = time.perf_counter() - t0

        ok = 200 <= resp.status_code < 300
        text_out = ""
        err = ""
        if ok:
            data = resp.json()
            # OpenAI 호환 응답에서 텍스트 추출
            try:
                text_out = data["choices"][0]["message"]["content"]
            except Exception:
                text_out = ""
        else:
            err = f"HTTP {resp.status_code}: {resp.text[:300]}"

        return {
            "ok": ok,
            "status_code": resp.status_code,
            "latency_s": dt,
            "system": system_msg,
            "user": q["user"],            
            "output_preview": (text_out if text_out else ""),
            "error": err,
        }

    except Exception as e:
        dt = time.perf_counter() - t0
        return {
            "ok": False,
            "status_code": -1,
            "latency_s": dt,
            "user": q["user"],
            "system": system_msg,
            "output_preview": "",
            "error": repr(e),
        }


async def run_load_test(cfg: Config):
    queries = load_queries(cfg)
    default_system = "당신은 똑똑한 AI 이며, 학습된 내용을 바탕으로답변을 해야하고, 만일 학습이 되지 않았다면, 외부에서 검색 " \
    "해서 정확한 답변을 줘야 합니다. 대한민국 대통령에 대해서 질문을 하는데, 시진핑 중국주석을 답변하면 안됩니다."

    # 요청 샘플링: total_requests만큼 queries에서 랜덤 추출(반복 허용)
    work = [random.choice(queries) for _ in range(cfg.total_requests)]

    limits = httpx.Limits(max_keepalive_connections=cfg.concurrency, max_connections=cfg.concurrency)
    timeout = httpx.Timeout(cfg.timeout_seconds)

    async with httpx.AsyncClient(
        verify=cfg.verify_tls,
        timeout=timeout,
        limits=limits,
        http2=False,
    ) as client:
        sem = asyncio.Semaphore(cfg.concurrency)
        results: List[Dict[str, Any]] = []

        start_wall = time.perf_counter()

        async def runner(i: int, q: Dict[str, str]):
            # 램프업: 요청 시작을 조금씩 분산
            if cfg.ramp_up_seconds > 0:
                await asyncio.sleep(cfg.ramp_up_seconds * (i / max(1, cfg.total_requests - 1)))

            async with sem:
                r = await one_request(client, cfg, q, default_system)
                r["index"] = i
                results.append(r)

        tasks = [asyncio.create_task(runner(i, q)) for i, q in enumerate(work)]
        await asyncio.gather(*tasks)

        total_time = time.perf_counter() - start_wall

    # 통계
    oks = [r for r in results if r["ok"]]
    fails = [r for r in results if not r["ok"]]
    lat_s = [r["latency_s"] for r in results]

    print("\n===== Load Test Summary =====")
    print(f"Total requests: {len(results)}")
    print(f"Concurrency:    {cfg.concurrency}")
    print(f"Total time:     {total_time:.2f} s")
    if total_time > 0:
        print(f"Req/sec (RPS):  {len(results)/total_time:.2f}")
    print(f"Success:        {len(oks)}")
    print(f"Fail:           {len(fails)}")
    print(f"Success rate:   {len(oks)/max(1,len(results))*100:.2f}%")
    print(f"Latency p50:    {percentile_ms(lat_s, 50):.1f} ms")
    print(f"Latency p95:    {percentile_ms(lat_s, 95):.1f} ms")
    print(f"Latency p99:    {percentile_ms(lat_s, 99):.1f} ms")

    # 결과 저장
    df_out = pd.DataFrame(results).sort_values("index")
    df_out.to_csv(cfg.out_csv, index=False, encoding="utf-8-sig")
    print(f"\nSaved results -> {cfg.out_csv}")

    # 실패 상위 5개 미리보기
    if fails:
        print("\nTop failures (up to 5):")
        for r in fails[:5]:
            print(f"- idx={r['index']} latency={r['latency_s']:.2f}s err={r['error'][:200]}")


if __name__ == "__main__":
    cfg = Config(
        excel_path="queries.xlsx",
        base_url="https://172.17.207.50:8443",
        model="./models/Qwen2.5-1.5B-Instruct",
        total_requests=200, #총요청수
        concurrency=10, #동시요청수
        sheet_name="Sheet1",
        ramp_up_seconds=1.0, # 응답 후 대기시간
        verify_tls=False,  # 자체서명 cert면 False
    )
    asyncio.run(run_load_test(cfg))
