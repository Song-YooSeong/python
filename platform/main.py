"""FastAPI 애플리케이션 진입점.

실행 방법:
    uvicorn platform.main:app --reload

애플리케이션 흐름
----------------
1. 서버가 시작되면 lifespan()에서 샘플 자산과 초기 메트릭을 생성합니다.
2. 백그라운드 Collector가 5초마다 메트릭/로그를 추가합니다.
3. 메트릭이 들어올 때마다 Rule Engine과 Anomaly Detection이 알림을 만듭니다.
4. Prediction Engine이 자산별 위험도를 계산합니다.
5. 사용자는 웹 대시보드 또는 REST API로 자산, 메트릭, 알림, 예측, 가이드를 조회합니다.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .analysis import detect_anomaly, evaluate_rule, refresh_all_predictions
from .collectors import run_demo_collector, seed_initial_metrics, seed_resources
from .guide import generate_guide
from .models import Alert, AlertStatus, GuideRequest, GuideResponse, LogEvent, Metric, MetricCreate, Prediction, Resource
from .storage import InMemoryStore


store = InMemoryStore()
templates = Jinja2Templates(directory="platform/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 서버 시작/종료 시 실행되는 수명주기 함수."""
    seed_resources(store)
    seed_initial_metrics(store)
    collector_task = asyncio.create_task(run_demo_collector(store))
    try:
        yield
    finally:
        collector_task.cancel()
        try:
            await collector_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="AI Infra Monitoring Platform PoC",
    description="인프라 통합 모니터링, 알림, 장애 예측, 조치 가이드 MVP",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory="platform/static"), name="static")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    """브라우저에서 보는 통합 대시보드 화면."""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    """로드밸런서나 운영자가 서버 생존 여부를 확인하는 엔드포인트."""
    return {"status": "ok"}


@app.get("/api/v1/resources", response_model=list[Resource])
def list_resources() -> list[Resource]:
    """등록된 모니터링 자산 목록을 반환합니다."""
    return store.list_resources()


@app.post("/api/v1/resources", response_model=Resource)
def upsert_resource(resource: Resource) -> Resource:
    """자산을 등록하거나 갱신합니다."""
    return store.upsert_resource(resource)


@app.get("/api/v1/metrics", response_model=list[Metric])
def list_metrics(
    resource_id: str | None = None,
    metric: str | None = Query(default=None, description="metric_name 필터"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Metric]:
    """메트릭 목록을 최신순으로 조회합니다."""
    return store.list_metrics(resource_id=resource_id, metric_name=metric, limit=limit)


@app.post("/api/v1/metrics", response_model=Metric)
def ingest_metric(metric_create: MetricCreate) -> Metric:
    """외부 Collector가 메트릭을 넣는 수집 API.

    메트릭 저장 후 즉시 Rule/Anomaly 분석을 수행하므로, API로 넣은 데이터도
    대시보드 알림과 예측에 반영됩니다.
    """
    metric = store.add_metric(metric_create)
    evaluate_rule(store, metric)
    detect_anomaly(store, metric)
    refresh_all_predictions(store)
    return metric


@app.get("/api/v1/alerts", response_model=list[Alert])
def list_alerts(
    status: AlertStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Alert]:
    """알림 목록을 최신순으로 조회합니다."""
    return store.list_alerts(status=status, limit=limit)


@app.get("/api/v1/predictions", response_model=list[Prediction])
def list_predictions() -> list[Prediction]:
    """자산별 최신 장애 위험도 예측 결과를 조회합니다."""
    return store.list_predictions()


@app.get("/api/v1/predictions/{resource_id}", response_model=Prediction)
def get_prediction(resource_id: str) -> Prediction:
    """특정 자산의 장애 위험도를 조회합니다."""
    prediction = store.get_prediction(resource_id)
    if prediction is None:
        raise HTTPException(status_code=404, detail="prediction not found")
    return prediction


@app.get("/api/v1/logs", response_model=list[LogEvent])
def list_logs(
    resource_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[LogEvent]:
    """최근 로그를 조회합니다."""
    return store.list_logs(resource_id=resource_id, limit=limit)


@app.post("/api/v1/guides/generate", response_model=GuideResponse)
def create_guide(request: GuideRequest) -> GuideResponse:
    """알림/증상 기반 장애 조치 가이드를 생성합니다."""
    if store.get_resource(request.resource_id) is None:
        raise HTTPException(status_code=404, detail="resource not found")
    return generate_guide(store, request)


@app.get("/api/v1/overview")
def overview() -> dict[str, object]:
    """대시보드 첫 화면에 필요한 요약 정보를 한 번에 제공합니다."""
    resources = store.list_resources()
    alerts = store.list_alerts(status=AlertStatus.OPEN, limit=200)
    predictions = store.list_predictions()
    critical_count = sum(1 for alert in alerts if alert.severity == "critical")
    warning_count = sum(1 for alert in alerts if alert.severity == "warning")
    average_risk = round(sum(item.risk_score for item in predictions) / len(predictions), 1) if predictions else 0

    return {
        "resource_count": len(resources),
        "open_alert_count": len(alerts),
        "critical_alert_count": critical_count,
        "warning_alert_count": warning_count,
        "average_risk_score": average_risk,
        "top_risks": predictions[:5],
        "recent_alerts": alerts[:10],
        "recent_logs": store.list_logs(limit=10),
    }
