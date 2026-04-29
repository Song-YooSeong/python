"""샘플 Collector와 초기 데이터 생성.

실제 플랫폼에서는 Node Exporter, SNMP Exporter, Fluent Bit, OpenTelemetry 등이
수집 계층을 담당합니다. 이 MVP에서는 외부 시스템이 없어도 흐름을 볼 수 있도록
Python 코드가 가짜 메트릭과 로그를 주기적으로 생성합니다.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from .analysis import detect_anomaly, evaluate_rule, refresh_all_predictions
from .models import LogEvent, Resource, ResourceType
from .normalizer import normalize_agent_payload, normalize_snmp_payload
from .storage import InMemoryStore


def seed_resources(store: InMemoryStore) -> None:
    """MVP에서 사용할 샘플 자산을 등록합니다."""
    for resource in (
        Resource(resource_id="server-01", resource_type=ResourceType.SERVER, hostname="server-01", ip="192.168.10.11", service="Order API", tags=["linux", "api"]),
        Resource(resource_id="server-02", resource_type=ResourceType.SERVER, hostname="server-02", ip="192.168.10.12", service="Payment API", tags=["linux", "api"]),
        Resource(resource_id="switch-01", resource_type=ResourceType.NETWORK, hostname="switch-01", ip="192.168.1.10", service="IDC Network", tags=["snmp"]),
        Resource(resource_id="db-01", resource_type=ResourceType.DATABASE, hostname="db-01", ip="192.168.20.21", service="Order DB", tags=["postgresql"]),
        Resource(resource_id="order-api", resource_type=ResourceType.APPLICATION, hostname="order-api", ip="10.10.1.15", service="Order API", tags=["fastapi"]),
    ):
        store.upsert_resource(resource)


def seed_initial_metrics(store: InMemoryStore) -> None:
    """대시보드가 처음부터 비어 보이지 않도록 초기 메트릭을 넣습니다."""
    for _ in range(12):
        collect_once(store)
    refresh_all_predictions(store)


async def run_demo_collector(store: InMemoryStore, interval_seconds: int = 5) -> None:
    """백그라운드에서 샘플 메트릭을 계속 생성합니다."""
    while True:
        collect_once(store)
        refresh_all_predictions(store)
        await asyncio.sleep(interval_seconds)


def collect_once(store: InMemoryStore) -> None:
    """Collector가 한 번 수집하고 분석까지 수행하는 전체 흐름.

    실행 순서:
    1. 샘플 원본 payload를 만듭니다.
    2. Normalizer가 MetricCreate 목록으로 바꿉니다.
    3. Store에 Metric을 저장합니다.
    4. Rule Engine과 Anomaly Detection을 실행합니다.
    5. 필요하면 샘플 로그를 저장합니다.
    """
    for payload in _sample_agent_payloads():
        for metric_create in normalize_agent_payload(payload):
            metric = store.add_metric(metric_create)
            evaluate_rule(store, metric)
            detect_anomaly(store, metric)

    for payload in _sample_snmp_payloads():
        for metric_create in normalize_snmp_payload(payload):
            metric = store.add_metric(metric_create)
            evaluate_rule(store, metric)
            detect_anomaly(store, metric)

    _append_sample_logs(store)


def _sample_agent_payloads() -> list[dict[str, object]]:
    """서버/애플리케이션 에이전트가 보낼 법한 원본 payload를 만듭니다."""
    now = datetime.now(timezone.utc)
    return [
        {
            "host": "server-01",
            "cpu_idle": random.uniform(5, 45),
            "memory_used_percent": random.uniform(55, 92),
            "disk_used_percent": random.uniform(70, 91),
            "network_in_mbps": random.uniform(80, 300),
            "timestamp": now,
        },
        {
            "host": "server-02",
            "cpu_idle": random.uniform(20, 70),
            "memory_used_percent": random.uniform(45, 80),
            "disk_used_percent": random.uniform(40, 70),
            "network_in_mbps": random.uniform(30, 180),
            "timestamp": now,
        },
        {
            "host": "db-01",
            "cpu_idle": random.uniform(8, 55),
            "memory_used_percent": random.uniform(60, 94),
            "disk_used_percent": random.uniform(65, 88),
            "timestamp": now,
        },
        {
            "host": "order-api",
            "api_latency_ms": random.choice([random.uniform(120, 450), random.uniform(900, 1800)]),
            "error_rate_percent": random.choice([random.uniform(0, 2), random.uniform(4, 9)]),
            "timestamp": now,
        },
    ]


def _sample_snmp_payloads() -> list[dict[str, object]]:
    """네트워크 장비 SNMP Collector가 보낼 법한 원본 payload를 만듭니다."""
    return [
        {
            "device": "switch-01",
            "port": "Gi1/0/1",
            "traffic_usage_percent": random.uniform(35, 96),
            "nic_errors": random.choice([0, 0, 1, 2, 15]),
            "timestamp": datetime.now(timezone.utc),
        }
    ]


def _append_sample_logs(store: InMemoryStore) -> None:
    """메트릭과 함께 볼 수 있는 샘플 로그를 저장합니다."""
    if random.random() < 0.35:
        store.add_log(
            LogEvent(
                resource_id="order-api",
                level=random.choice(["INFO", "WARN", "ERROR"]),
                message=random.choice(
                    [
                        "request completed",
                        "database query took longer than expected",
                        "upstream timeout detected",
                        "connection pool usage is high",
                    ]
                ),
                timestamp=datetime.now(timezone.utc),
                source="demo-log-collector",
            )
        )
