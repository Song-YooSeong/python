"""플랫폼 전체에서 사용하는 데이터 모델 정의.

초보자를 위한 설명
-----------------
FastAPI는 요청과 응답 데이터를 Python 객체로 다루기 위해 Pydantic 모델을
자주 사용합니다. 이 파일은 문서 10장의 Resource, Metric, Alert, Incident
모델을 실제 코드로 옮긴 곳입니다.

데이터 흐름에서 이 모델들이 쓰이는 위치는 다음과 같습니다.
1. Collector가 MetricCreate, LogEvent를 만듭니다.
2. Normalizer가 원본 데이터를 Metric 형태로 표준화합니다.
3. Rule/Anomaly/Prediction 엔진이 Metric을 읽어 Alert와 Prediction을 만듭니다.
4. API와 대시보드는 Resource, Metric, Alert, Prediction, Guide를 사용자에게 보여줍니다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """알림 심각도.

    문자열 Enum으로 만들면 API 응답 JSON에서 "warning"처럼 읽기 쉬운 값으로
    내려갑니다.
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ResourceType(str, Enum):
    """모니터링 대상의 큰 분류."""

    SERVER = "server"
    NETWORK = "network"
    DATABASE = "database"
    APPLICATION = "application"
    STORAGE = "storage"


class AlertStatus(str, Enum):
    """알림의 처리 상태."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"


class Resource(BaseModel):
    """모니터링 대상 자산.

    예: server-01, switch-01, order-api 같은 대상 하나를 표현합니다.
    """

    resource_id: str
    resource_type: ResourceType
    hostname: str
    ip: str = ""
    owner: str = "infra-team"
    location: str = "unknown"
    service: str = "common"
    tags: list[str] = Field(default_factory=list)


class Metric(BaseModel):
    """표준화된 시계열 메트릭 한 건.

    모든 수집기는 서로 다른 원본 형식을 가져올 수 있지만, 저장과 분석 단계에서는
    이 공통 구조만 사용합니다. 이것이 설계서의 "정규화 계층"입니다.
    """

    resource_id: str
    metric_name: str
    value: float
    unit: str
    timestamp: datetime
    labels: dict[str, str] = Field(default_factory=dict)


class MetricCreate(BaseModel):
    """API나 Collector가 새 메트릭을 넣을 때 사용하는 입력 모델."""

    resource_id: str
    metric_name: str
    value: float
    unit: str = ""
    timestamp: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class LogEvent(BaseModel):
    """시스템/애플리케이션 로그 한 줄."""

    resource_id: str
    level: str = "INFO"
    message: str
    timestamp: datetime
    source: str = "collector"
    context: dict[str, Any] = Field(default_factory=dict)


class Alert(BaseModel):
    """Rule 또는 AI 분석 결과로 생성되는 알림."""

    alert_id: str
    severity: Severity
    resource_id: str
    metric_name: str
    message: str
    status: AlertStatus = AlertStatus.OPEN
    created_at: datetime
    evidence: dict[str, Any] = Field(default_factory=dict)


class Prediction(BaseModel):
    """장애 위험도 예측 결과.

    risk_score는 0~100점이며 높을수록 장애 가능성이 크다는 뜻입니다.
    """

    resource_id: str
    risk_score: int
    severity: Severity
    summary: str
    reasons: list[str]
    predicted_at: datetime


class Incident(BaseModel):
    """장애 이력 또는 현재 장애 후보."""

    incident_id: str
    title: str
    severity: Severity
    affected_service: str
    resource_id: str
    root_cause: str = ""
    recommended_action: str = ""
    created_at: datetime


class GuideRequest(BaseModel):
    """장애 조치 가이드 생성 요청."""

    alert_id: str | None = None
    resource_id: str
    symptom: str


class GuideResponse(BaseModel):
    """운영자가 볼 장애 조치 가이드."""

    title: str
    severity: Severity
    resource_id: str
    summary: str
    cause_candidates: list[str]
    check_commands: list[str]
    action_steps: list[str]
    rollback_steps: list[str]
    related_documents: list[str]
