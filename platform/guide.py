"""장애 조치 가이드 생성 로직.

운영 환경의 RAG는 Vector DB와 LLM을 사용하지만, 이 MVP는 규칙 기반 문서 검색으로
같은 흐름을 흉내 냅니다. 즉, 장애 증상 키워드를 보고 가장 관련 있는 Runbook을
찾아 GuideResponse로 조립합니다.
"""

from __future__ import annotations

from .models import GuideRequest, GuideResponse, Severity
from .storage import InMemoryStore


RUNBOOKS = [
    {
        "keywords": ["cpu", "CPU", "과부하"],
        "title": "CPU 과부하 조치 가이드",
        "causes": ["프로세스 폭주", "배치 작업 집중", "트래픽 급증", "DB 쿼리 비용 증가"],
        "commands": ["top", "ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%cpu | head", "sar -u 1 5"],
        "actions": ["CPU 상위 프로세스를 확인합니다.", "최근 배포/배치 실행 여부를 확인합니다.", "필요 시 서비스 스케일아웃 또는 프로세스 재시작을 검토합니다."],
        "rollback": ["재시작 후 상태가 악화되면 이전 버전으로 롤백합니다.", "스케일아웃 변경을 원복합니다."],
        "docs": ["runbooks/cpu-high.md"],
    },
    {
        "keywords": ["disk", "Disk", "디스크", "용량"],
        "title": "디스크 용량 부족 조치 가이드",
        "causes": ["로그 파일 증가", "임시 파일 누적", "백업 파일 미정리", "데이터 파티션 증가"],
        "commands": ["df -h", "du -sh /var/log/* | sort -h", "find /tmp -type f -mtime +7"],
        "actions": ["사용률이 높은 파티션을 확인합니다.", "불필요한 로그/임시 파일을 정리합니다.", "증가 추세가 지속되면 디스크 증설을 요청합니다."],
        "rollback": ["삭제한 파일 목록을 확인합니다.", "필요 시 백업에서 복구합니다."],
        "docs": ["runbooks/disk-full.md"],
    },
    {
        "keywords": ["latency", "Latency", "응답", "지연", "api"],
        "title": "API 응답 지연 조치 가이드",
        "causes": ["애플리케이션 과부하", "DB 지연", "외부 API 지연", "네트워크 지연"],
        "commands": ["curl -w '@curl-format.txt' -o /dev/null -s <URL>", "netstat -anp", "tail -n 200 app.log"],
        "actions": ["응답 지연 구간이 App/DB/외부 API 중 어디인지 분리합니다.", "에러 로그와 최근 배포 이력을 확인합니다.", "DB Query Time과 Connection Pool 상태를 확인합니다."],
        "rollback": ["최근 배포가 원인이면 이전 버전으로 재배포합니다.", "임시 우회 라우팅을 해제합니다."],
        "docs": ["runbooks/api-latency.md"],
    },
    {
        "keywords": ["memory", "Memory", "메모리", "swap"],
        "title": "메모리 부족 조치 가이드",
        "causes": ["메모리 누수", "트래픽 증가", "캐시 과다 사용", "JVM Heap 설정 오류"],
        "commands": ["free -m", "vmstat 1 5", "ps -eo pid,cmd,%mem --sort=-%mem | head"],
        "actions": ["메모리 상위 프로세스를 확인합니다.", "Swap 사용량과 OOM 로그를 확인합니다.", "필요 시 Heap/캐시 설정 조정 또는 재시작을 검토합니다."],
        "rollback": ["설정 변경 전 값을 복원합니다.", "재시작 후 모니터링 지표를 확인합니다."],
        "docs": ["runbooks/memory-high.md"],
    },
]


def generate_guide(store: InMemoryStore, request: GuideRequest) -> GuideResponse:
    """증상과 알림 정보를 바탕으로 장애 조치 가이드를 생성합니다."""
    symptom = request.symptom
    alert = None
    if request.alert_id:
        alert = next((item for item in store.list_alerts(limit=500) if item.alert_id == request.alert_id), None)
        if alert:
            symptom = f"{symptom} {alert.metric_name} {alert.message}"

    runbook = _find_runbook(symptom)
    severity = alert.severity if alert else Severity.WARNING

    return GuideResponse(
        title=runbook["title"],
        severity=severity,
        resource_id=request.resource_id,
        summary=f"{request.resource_id}에서 '{request.symptom}' 증상이 보고되었습니다.",
        cause_candidates=runbook["causes"],
        check_commands=runbook["commands"],
        action_steps=runbook["actions"],
        rollback_steps=runbook["rollback"],
        related_documents=runbook["docs"],
    )


def _find_runbook(symptom: str) -> dict[str, list[str] | str]:
    """증상 문자열에 포함된 키워드로 가장 적합한 Runbook을 찾습니다."""
    for runbook in RUNBOOKS:
        if any(keyword.lower() in symptom.lower() for keyword in runbook["keywords"]):
            return runbook
    return {
        "title": "일반 장애 초동 조치 가이드",
        "causes": ["최근 변경", "자원 부족", "네트워크 지연", "외부 연계 장애"],
        "commands": ["uptime", "df -h", "free -m", "tail -n 200 /var/log/syslog"],
        "actions": ["영향 범위를 확인합니다.", "최근 변경과 배포 이력을 확인합니다.", "관련 로그와 메트릭을 함께 확인합니다."],
        "rollback": ["최근 변경사항을 원복합니다.", "원복 후 지표가 정상화되는지 확인합니다."],
        "docs": ["runbooks/general-troubleshooting.md"],
    }
