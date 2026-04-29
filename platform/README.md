# AI 기반 인프라 모니터링 플랫폼 PoC

이 폴더는 `infra_monitoring_ai_platform_architecture.md` 설계서를 바탕으로 만든 실행 가능한 MVP 예제입니다.

## 애플리케이션 흐름

```text
샘플 Collector
→ Normalizer
→ InMemoryStore
→ Rule / Anomaly / Prediction
→ Alert / Guide API
→ Web Dashboard
```

## 주요 파일

- `main.py`: FastAPI 앱 진입점, API 라우팅, 대시보드 연결
- `models.py`: Resource, Metric, Alert, Prediction, Guide 같은 데이터 모델
- `storage.py`: 외부 DB 대신 사용하는 인메모리 저장소
- `normalizer.py`: 수집 원본 데이터를 표준 Metric 구조로 변환
- `collectors.py`: 샘플 자산과 샘플 메트릭/로그 생성
- `analysis.py`: 임계치 Rule, Z-Score 이상 감지, 위험도 예측
- `guide.py`: 장애 조치 가이드 생성
- `templates/dashboard.html`: 대시보드 HTML
- `static/dashboard.css`: 대시보드 스타일
- `static/dashboard.js`: 대시보드 API 호출과 화면 갱신

## 실행

```powershell
C:\Users\USER\AppData\Local\Programs\Python\Python313\python.exe -m uvicorn platform.main:app --reload --host 127.0.0.1 --port 8000
```

브라우저에서 확인:

```text
http://127.0.0.1:8000
```

API 문서:

```text
http://127.0.0.1:8000/docs
```

## 설계서와의 매핑

| 설계서 계층 | PoC 구현 |
|---|---|
| 수집 계층 | `collectors.py` |
| 정규화 계층 | `normalizer.py` |
| 저장 계층 | `storage.py` |
| Rule Engine | `analysis.evaluate_rule` |
| Anomaly Detection | `analysis.detect_anomaly` |
| Failure Prediction | `analysis.predict_resource_risk` |
| RAG/Guide | `guide.generate_guide` |
| Backend API | `main.py` |
| Dashboard | `templates/`, `static/` |

## 운영 확장 방향

현재 PoC는 학습과 시연을 위해 모든 데이터를 메모리에 저장합니다.
운영 환경으로 확장할 때는 다음 순서가 자연스럽습니다.

1. `storage.py`를 PostgreSQL/Prometheus/OpenSearch 저장소로 교체
2. `collectors.py`를 실제 Agent, SNMP, Log Collector 연동으로 교체
3. `guide.py`를 Vector DB와 LLM 기반 RAG로 확장
4. `analysis.py`의 통계 로직을 scikit-learn/PyTorch 모델로 확장
5. 승인 기반 자동 조치 Orchestrator 추가
