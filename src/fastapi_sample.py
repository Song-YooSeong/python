from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
import requests
import json

app = FastAPI()

OLLAMA_URL = "http://localhost:11434/api/generate"


@app.post("/chat")
async def chat(
    request: Request,
    timeout: int = Query(160),        # timeout 설정 가능
    stream: bool = Query(False)      # stream 여부 설정
):
    prompt = None

    # 1. query
    prompt = request.query_params.get("prompt")

    # 2. body
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("prompt"):
            prompt = body.get("prompt")
    except:
        pass

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 값이 필요합니다.")

    try:
        # 🔥 stream=False → 일반 응답
        if not stream:
            res = requests.post(
                OLLAMA_URL,
                json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": False
                },
                timeout=timeout
            )
            res.raise_for_status()
            return JSONResponse(content=res.json())

        # 🔥 stream=True → 스트리밍 처리
        def generate():
            with requests.post(
                OLLAMA_URL,
                json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": True
                },
                stream=True,
                timeout=timeout
            ) as res:

                res.raise_for_status()

                for line in res.iter_lines():
                    if line:
                        try:
                            data = json.loads(line.decode("utf-8"))
                            yield f"data: {json.dumps(data)}\n\n"
                        except Exception:
                            continue

        return StreamingResponse(generate(), media_type="text/event-stream")

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Ollama 호출 실패: {str(e)}")