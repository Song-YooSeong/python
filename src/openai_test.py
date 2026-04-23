from openai import OpenAI

def call_hcx_api(system_query:str, user_query: str):
    client = OpenAI(api_key="nv-a5f1ea734dde48d3832118b3b6c19011eY1N",
                    base_url="https://clovastudio.stream.ntruss.com/v1/openai")

    resp = client.chat.completions.create(
        model="HCX-005",  # 예: HCX-005 등 CLOVA Studio 모델명
        messages=[
            {"role": "system", "content": system_query},
            {"role": "user", "content": user_query}
        ],
        #max_tokens=20480,
        temperature=0.2,        
    )
    return resp.choices[0].message.content


def main():
    while True:
        system_qry = "당신은 모든 질문에 대해서 최신의 정보를 제공해야 하며, 학습된 데이터가 없으면 웹에서 검색해서 결과를 알려줘야 합니다."
        user_qry = input("\n\n질문을 입력하세요:->")
        resp = call_hcx_api(system_qry, user_qry)
        if resp is None:
            print("[응답 없음]")

        print(resp)

if __name__ == "__main__":
    main()