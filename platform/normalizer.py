"""수집 원본 데이터를 공통 Metric 구조로 바꾸는 정규화 계층.

설계서 4.4의 예시처럼 장비마다 원본 필드가 다를 수 있습니다.
이 파일은 그런 차이를 숨기고, 분석 엔진이 항상 MetricCreate만 보도록 만듭니다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import MetricCreate


def normalize_agent_payload(payload: dict[str, Any]) -> list[MetricCreate]:
    """서버 에이전트가 보낸 원본 payload를 표준 메트릭 목록으로 변환합니다.

    입력 예:
    {
        "host": "server-01",
        "cpu_idle": 12.5,
        "memory_used_percent": 71.2,
        "disk_used_percent": 82.1
    }

    출력 예:
    MetricCreate(resource_id="server-01", metric_name="cpu_usage", value=87.5, unit="%")
    """

    resource_id = str(payload["host"])
    timestamp = payload.get("timestamp") or datetime.now(timezone.utc)
    metrics: list[MetricCreate] = []

    if "cpu_idle" in payload:
        # 많은 OS 도구는 CPU 사용률이 아니라 idle 값을 줍니다.
        # 관제에서는 사용률이 더 직관적이므로 100 - idle로 바꿉니다.
        metrics.append(
            MetricCreate(
                resource_id=resource_id,
                metric_name="cpu_usage",
                value=100 - float(payload["cpu_idle"]),
                unit="%",
                timestamp=timestamp,
            )
        )

    for source_name, metric_name in (
        ("memory_used_percent", "memory_usage"),
        ("disk_used_percent", "disk_usage"),
        ("network_in_mbps", "network_in"),
        ("api_latency_ms", "api_latency"),
        ("error_rate_percent", "error_rate"),
    ):
        if source_name in payload:
            metrics.append(
                MetricCreate(
                    resource_id=resource_id,
                    metric_name=metric_name,
                    value=float(payload[source_name]),
                    unit="ms" if metric_name == "api_latency" else ("Mbps" if "network" in metric_name else "%"),
                    timestamp=timestamp,
                )
            )

    return metrics


def normalize_snmp_payload(payload: dict[str, Any]) -> list[MetricCreate]:
    """네트워크 장비 SNMP 원본 payload를 표준 메트릭으로 변환합니다."""
    resource_id = str(payload["device"])
    timestamp = payload.get("timestamp") or datetime.now(timezone.utc)
    return [
        MetricCreate(
            resource_id=resource_id,
            metric_name="traffic_usage",
            value=float(payload.get("traffic_usage_percent", 0)),
            unit="%",
            timestamp=timestamp,
            labels={"port": str(payload.get("port", "unknown"))},
        ),
        MetricCreate(
            resource_id=resource_id,
            metric_name="nic_errors",
            value=float(payload.get("nic_errors", 0)),
            unit="count",
            timestamp=timestamp,
            labels={"port": str(payload.get("port", "unknown"))},
        ),
    ]
