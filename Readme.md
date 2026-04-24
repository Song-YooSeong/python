# 🚀 AI Chat API Server - Design Document



## 📌 1. 개요

본 시스템은 vLLM 기반의 LLM을 활용하여
OpenAI API 호환 Chat API를 제공하는 서버이다.

---

## 🧭 2. 요구사항

### 기능 요구사항
- Chat Completion API 제공
- Streaming(SSE) 지원
- 다중 모델 라우팅

### 비기능 요구사항
- 1,000명 동시 접속 처리
- 낮은 응답 지연 (TTFT < 2초)
- 확장 가능한 구조

---

## 🏗 3. 전체 아키텍처

```text
Client
  ↓
Spring Boot API Gateway
  ↓
vLLM Server
  ↓
LLM Model (Qwen / GPT)
```
---
```text
이거는 테스트 임.