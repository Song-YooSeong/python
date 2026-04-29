"""Rule, Anomaly Detection, Failure Prediction 로직.

이 파일은 설계서 5장의 AI 분석 계층을 단순한 Python 코드로 구현합니다.
운영용 AI 모델은 더 복잡할 수 있지만, 처음에는 아래처럼 이해 가능한 규칙과
통계 기반 탐지부터 시작하는 것이 좋습니다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean, pstdev

from .models import Alert, Metric, Prediction, Severity
from .storage import InMemoryStore


RULE_THRESHOLDS: dict[str, tuple[float, Severity, str]] = {
    # metric_name: (임계치, 심각도, 사용자 메시지)
    "cpu_usage": (90.0, Severity.CRITICAL, "CPU 사용률이 90%를 초과했습니다."),
    "memory_usage": (95.0, Severity.CRITICAL, "Memory 사용률이 95%를 초과했습니다."),
    "disk_usage": (85.0, Severity.WARNING, "Disk 사용률이 85%를 초과했습니다."),
    "traffic_usage": (90.0, Severity.WARNING, "회선/포트 트래픽 사용률이 90%를 초과했습니다."),
    "api_latency": (1000.0, Severity.WARNING, "API 응답 시간이 1초를 초과했습니다."),
    "error_rate": (5.0, Severity.CRITICAL, "Error Rate가 5%를 초과했습니다."),
    "nic_errors": (10.0, Severity.WARNING, "NIC Error가 증가했습니다."),
}


def evaluate_rule(store: InMemoryStore, metric: Metric) -> Alert | None:
    """단일 메트릭에 대해 임계치 기반 Rule을 평가합니다."""
    rule = RULE_THRESHOLDS.get(metric.metric_name)
    if rule is None:
        return None

    threshold, severity, message = rule
    if metric.value <= threshold:
        return None

    alert = Alert(
        alert_id=store.make_alert_id(),
        severity=severity,
        resource_id=metric.resource_id,
        metric_name=metric.metric_name,
        message=message,
        created_at=datetime.now(timezone.utc),
        evidence={"value": metric.value, "threshold": threshold, "unit": metric.unit},
    )
    return store.add_alert(alert)


def detect_anomaly(store: InMemoryStore, metric: Metric) -> Alert | None:
    """최근 데이터의 평균/표준편차와 비교해 이상 징후를 찾습니다.

    방식:
    1. 같은 자산/같은 지표의 최근 30개 데이터를 가져옵니다.
    2. 마지막 값을 제외한 과거 값으로 평균과 표준편차를 계산합니다.
    3. 현재 값이 평균보다 3 표준편차 이상 높으면 이상으로 판단합니다.

    이 방식은 Z-Score의 간단한 버전입니다.
    """
    series = store.get_series(metric.resource_id, metric.metric_name, limit=30)
    if len(series) < 8:
        # 데이터가 너무 적으면 "평소 패턴"을 알 수 없으므로 판단하지 않습니다.
        return None

    history = [item.value for item in series[:-1]]
    baseline = mean(history)
    deviation = pstdev(history)
    if deviation == 0:
        return None

    z_score = (metric.value - baseline) / deviation
    if z_score < 3:
        return None

    alert = Alert(
        alert_id=store.make_alert_id(),
        severity=Severity.WARNING,
        resource_id=metric.resource_id,
        metric_name=metric.metric_name,
        message=f"{metric.metric_name} 값이 평소 패턴보다 크게 높습니다.",
        created_at=datetime.now(timezone.utc),
        evidence={"value": metric.value, "baseline": round(baseline, 2), "z_score": round(z_score, 2)},
    )
    return store.add_alert(alert)


def predict_resource_risk(store: InMemoryStore, resource_id: str) -> Prediction:
    """자산 하나의 장애 위험도를 0~100점으로 계산합니다.

    설계서의 Risk Score 개념을 단순화했습니다.
    - Resource Usage Score: CPU/Memory/Disk/API/Error 현재 사용률
    - Trend Score: 최근 값이 상승 중인지
    - Anomaly Score: 열린 알림이 있는지
    """
    risk_score = 0
    reasons: list[str] = []

    for metric_name in ("cpu_usage", "memory_usage", "disk_usage", "traffic_usage", "api_latency", "error_rate"):
        series = store.get_series(resource_id, metric_name, limit=10)
        if not series:
            continue

        latest = series[-1].value
        usage_points = _usage_points(metric_name, latest)
        if usage_points:
            risk_score += usage_points
            reasons.append(f"{metric_name} 현재 값 {latest:.1f}{series[-1].unit}로 위험 점수 {usage_points}점")

        if len(series) >= 5 and series[-1].value > series[0].value * 1.2:
            risk_score += 10
            reasons.append(f"{metric_name} 최근 상승 추세 감지")

    open_alerts = [alert for alert in store.list_alerts(limit=200) if alert.resource_id == resource_id]
    if open_alerts:
        risk_score += min(20, len(open_alerts) * 5)
        reasons.append(f"열린 알림 {len(open_alerts)}건 존재")

    risk_score = min(100, risk_score)
    severity = Severity.CRITICAL if risk_score >= 80 else Severity.WARNING if risk_score >= 50 else Severity.INFO
    summary = "즉시 조치 필요" if severity == Severity.CRITICAL else "주의 관찰 필요" if severity == Severity.WARNING else "정상 범위"

    if not reasons:
        reasons.append("위험 신호가 충분히 감지되지 않았습니다.")

    prediction = Prediction(
        resource_id=resource_id,
        risk_score=risk_score,
        severity=severity,
        summary=summary,
        reasons=reasons,
        predicted_at=datetime.now(timezone.utc),
    )
    return store.save_prediction(prediction)


def refresh_all_predictions(store: InMemoryStore) -> list[Prediction]:
    """등록된 모든 자산의 위험도를 다시 계산합니다."""
    return [predict_resource_risk(store, resource.resource_id) for resource in store.list_resources()]


def _usage_points(metric_name: str, value: float) -> int:
    """지표별 현재 값에서 위험 점수를 계산합니다."""
    if metric_name == "api_latency":
        if value >= 1500:
            return 25
        if value >= 800:
            return 15
        return 0

    if metric_name == "error_rate":
        if value >= 10:
            return 30
        if value >= 3:
            return 15
        return 0

    if value >= 95:
        return 30
    if value >= 85:
        return 20
    if value >= 70:
        return 10
    return 0
