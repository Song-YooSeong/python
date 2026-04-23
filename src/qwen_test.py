import requests
import json
import os
import platform
import urllib3
import time

# 로컬PC 에서 WSL 환경의 Ubuntu 로 접속해서 Qwen 을 설치 후 테스트 하는 프로그램.

def clear_screen():
    os.system("cls" if platform.system() == "Windows" else "clear")

def call_vllm_stream(system_qry, user_qry):
    #url = f"{BASE_URL}/chat/completions"
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    url = "https://172.17.207.50:8443/v1/chat/completions"
    MODEL = "Qwen3-0.6B"

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_qry},
            {"role": "user", "content": user_qry},
        ],
        "max_tokens": 256,
        "stream": True ,
        "temperature": 0.4,
        "top_p":0.9,
    }

    with requests.post(url, json=payload, stream=True, verify=False) as r:
        r.raise_for_status()

        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue

            if line.startswith("data: "):
                data = line[len("data: "):]

                if data == "[DONE]":
                    break

                obj = json.loads(data)

                delta = obj["choices"][0]["delta"].get("content")
                if delta:
                    print(delta, end="", flush=True)

    print("\n--- stream end ---")
    return delta
    
def call_vllm(system_qry, user_qry):
    #url = f"{BASE_URL}/chat/completions"
    #url = "https://172.17.207.50:8443/v1/chat/completions"
    url = "https://172.17.207.50:8443/v1/chat/completions"
    MODEL = "Qwen3-0.6B"

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_qry},
            {"role": "user", "content": user_qry},
        ],
        "max_tokens": 256,
        "stream": False ,
        "temperature": 0.4,
        "top_p":0.9,
    }

    r = requests.post(url, headers={"Content-Type": "application/json"},
                      data=json.dumps(payload), timeout=60, verify=False)

    # ✅ 여기서 원인 바로 확인
    print("HTTP", r.status_code)
    #print("RAW:", r.text)

    r.raise_for_status()
    result = r.json()

    # ✅ 정상/에러 분기 처리
    if "choices" not in result:
        raise RuntimeError(f"No 'choices' in response. Got keys={list(result.keys())}")

    return result["choices"][0]["message"]["content"]

def main():
    while True:
        system_qry = "당신은 모든 질문에 대해서 최신의 정보를 제공해야 하며, 학습된 데이터가 없으면 웹에서 검색해서 결과를 알려줘야 합니다.\n" \
        "추론과정이나 답변은 항상 한국어로 답변 해 주세요"
        user_qry = input("\n\n질문을 입력하세요:->")

        start = time.perf_counter()
        resp = call_vllm_stream(system_qry, user_qry)
        end = time.perf_counter()

        print(f"STREAM 실행시간: {end - start:.3f} 초")

        #resp = call_vllm_stream(system_qry, user_qry)
        #clear_screen()
        if resp is None:
            print("[응답 없음]")

        print(resp)

        start = time.perf_counter()
        resp = call_vllm(system_qry, user_qry)
        end = time.perf_counter()

        print(f"NON STREAM 실행시간: {end - start:.3f} 초")

        #resp = call_vllm_stream(system_qry, user_qry)
        #clear_screen()
        if resp is None:
            print("[응답 없음]")


if __name__ == "__main__":
    main()