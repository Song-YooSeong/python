from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaLLM

# 1. 문서 로드
loader = TextLoader("c:/study/python/data.txt", encoding="utf-8")
documents = loader.load()

# 2. 문서 분할
text_splitter = CharacterTextSplitter(
    chunk_size=300,
    chunk_overlap=30,
)
split_docs = text_splitter.split_documents(documents)

# 3. 임베딩 모델
embedding = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# 4. 벡터 DB 생성
db = Chroma.from_documents(split_docs, embedding)

# 5. 검색기
retriever = db.as_retriever(search_kwargs={"k": 3})

# 6. Ollama LLM 연결
llm = OllamaLLM(model="gemma:2b")

while True:
    query = input("질문: ").strip()

    if not query:
        continue

    if query.lower() in ["exit", "quit", "q"]:
        print("종료합니다.")
        break

    # 최신 LangChain 방식
    retrieved_docs = retriever.invoke(query)

    context = "\n\n".join([d.page_content for d in retrieved_docs])

    prompt = f"""
너는 문서를 기반으로 답변하는 도우미다.
아래 문맥만 참고해서 질문에 답해라.
문맥에 없는 내용은 추측하지 말고, 모르면 모른다고 답해라.

[문맥]
{context}

[질문]
{query}

[답변]
""".strip()

    answer = llm.invoke(prompt)

    print("\n답변:")
    print(answer)
    print("-" * 60)