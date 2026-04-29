"""간단한 인메모리 저장소.

운영 환경에서는 이 역할이 여러 저장소로 나뉩니다.
- Metric: Prometheus, VictoriaMetrics, InfluxDB
- Log: OpenSearch, Elasticsearch
- Resource/Alert/Incident: PostgreSQL
- Guide 문서: Vector DB 또는 문서 DB

하지만 MVP에서는 서버를 바로 실행해 보는 것이 중요하므로 Python 리스트와 dict로
저장소를 구현합니다. 이 방식은 가볍고 이해하기 쉽지만, 서버 재시작 시 데이터가
사라지고 여러 프로세스에서 공유되지 않습니다.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from .models import Alert, AlertStatus, Incident, LogEvent, Metric, MetricCreate, Prediction, Resource


class InMemoryStore:
    """플랫폼의 모든 데이터를 보관하는 저장소 객체.

    FastAPI 앱은 실행 중 하나의 store 인스턴스를 만들고, 모든 API와 백그라운드
    수집기가 같은 store를 공유합니다.
    """

    def __init__(self, max_metrics_per_series: int = 300) -> None:
        # 동시에 API 요청과 백그라운드 수집기가 store를 만질 수 있으므로 Lock을 둡니다.
        self._lock = RLock()
        self.max_metrics_per_series = max_metrics_per_series
        self.resources: dict[str, Resource] = {}
        self.metrics: dict[tuple[str, str], deque[Metric]] = defaultdict(
            lambda: deque(maxlen=self.max_metrics_per_series)
        )
        self.logs: deque[LogEvent] = deque(maxlen=1000)
        self.alerts: dict[str, Alert] = {}
        self.predictions: dict[str, Prediction] = {}
        self.incidents: dict[str, Incident] = {}

    def upsert_resource(self, resource: Resource) -> Resource:
        """자산을 새로 등록하거나 같은 ID의 기존 자산을 갱신합니다."""
        with self._lock:
            self.resources[resource.resource_id] = resource
            return resource

    def list_resources(self) -> list[Resource]:
        """등록된 자산 목록을 ID 순서로 반환합니다."""
        with self._lock:
            return sorted(self.resources.values(), key=lambda item: item.resource_id)

    def get_resource(self, resource_id: str) -> Resource | None:
        """자산 ID로 자산을 찾습니다."""
        with self._lock:
            return self.resources.get(resource_id)

    def add_metric(self, metric_create: MetricCreate) -> Metric:
        """새 메트릭 한 건을 저장합니다."""
        metric = Metric(
            resource_id=metric_create.resource_id,
            metric_name=metric_create.metric_name,
            value=metric_create.value,
            unit=metric_create.unit,
            timestamp=metric_create.timestamp or datetime.now(timezone.utc),
            labels=metric_create.labels,
        )
        with self._lock:
            self.metrics[(metric.resource_id, metric.metric_name)].append(metric)
            return metric

    def list_metrics(
        self,
        resource_id: str | None = None,
        metric_name: str | None = None,
        limit: int = 100,
    ) -> list[Metric]:
        """조건에 맞는 최근 메트릭을 반환합니다."""
        with self._lock:
            selected: list[Metric] = []
            for (series_resource_id, series_metric_name), series in self.metrics.items():
                if resource_id and series_resource_id != resource_id:
                    continue
                if metric_name and series_metric_name != metric_name:
                    continue
                selected.extend(series)

        selected.sort(key=lambda item: item.timestamp, reverse=True)
        return selected[:limit]

    def get_series(self, resource_id: str, metric_name: str, limit: int = 60) -> list[Metric]:
        """특정 자산/지표의 최근 시계열 데이터를 오래된 순서부터 반환합니다."""
        with self._lock:
            series = list(self.metrics.get((resource_id, metric_name), []))
        return series[-limit:]

    def add_log(self, log_event: LogEvent) -> LogEvent:
        """로그 한 줄을 저장합니다."""
        with self._lock:
            self.logs.append(log_event)
            return log_event

    def list_logs(self, resource_id: str | None = None, limit: int = 100) -> list[LogEvent]:
        """최근 로그를 반환합니다."""
        with self._lock:
            logs = list(self.logs)
        if resource_id:
            logs = [log for log in logs if log.resource_id == resource_id]
        logs.sort(key=lambda item: item.timestamp, reverse=True)
        return logs[:limit]

    def add_alert(self, alert: Alert) -> Alert:
        """알림을 저장합니다.

        같은 자산/지표/메시지의 열린 알림이 이미 있으면 중복 생성을 막고 기존 알림을
        반환합니다. 운영 환경에서 알림 폭주를 줄이는 가장 기본적인 장치입니다.
        """
        with self._lock:
            for existing in self.alerts.values():
                if (
                    existing.status == AlertStatus.OPEN
                    and existing.resource_id == alert.resource_id
                    and existing.metric_name == alert.metric_name
                    and existing.message == alert.message
                ):
                    return existing
            self.alerts[alert.alert_id] = alert
            return alert

    def make_alert_id(self) -> str:
        """사람이 읽기 쉬운 알림 ID를 만듭니다."""
        return f"ALT-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"

    def list_alerts(self, status: AlertStatus | None = None, limit: int = 100) -> list[Alert]:
        """알림 목록을 최신순으로 반환합니다."""
        with self._lock:
            alerts = list(self.alerts.values())
        if status:
            alerts = [alert for alert in alerts if alert.status == status]
        alerts.sort(key=lambda item: item.created_at, reverse=True)
        return alerts[:limit]

    def save_prediction(self, prediction: Prediction) -> Prediction:
        """자산별 최신 예측 결과를 저장합니다."""
        with self._lock:
            self.predictions[prediction.resource_id] = prediction
            return prediction

    def list_predictions(self) -> list[Prediction]:
        """모든 자산의 최신 예측 결과를 위험도 높은 순서로 반환합니다."""
        with self._lock:
            predictions = list(self.predictions.values())
        predictions.sort(key=lambda item: item.risk_score, reverse=True)
        return predictions

    def get_prediction(self, resource_id: str) -> Prediction | None:
        """특정 자산의 최신 예측 결과를 반환합니다."""
        with self._lock:
            return self.predictions.get(resource_id)
