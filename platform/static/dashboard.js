/*
    대시보드 동작 로직.

    브라우저는 아래 순서로 데이터를 가져옵니다.
    1. /api/v1/overview: 요약 수치, 최근 알림, 최근 로그
    2. /api/v1/resources: 자산 목록
    3. 알림의 [가이드] 버튼 클릭 시 /api/v1/guides/generate 호출

    프론트엔드 프레임워크 없이 fetch API만 사용해 초보자도 흐름을 쉽게 볼 수 있게 했습니다.
*/

const state = {
    overview: null,
    resources: [],
};

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("refreshButton").addEventListener("click", loadDashboard);
    loadDashboard();

    // 샘플 Collector가 5초마다 데이터를 만들기 때문에, 화면도 5초마다 갱신합니다.
    setInterval(loadDashboard, 5000);
});

async function loadDashboard() {
    const [overview, resources] = await Promise.all([
        fetchJson("/api/v1/overview"),
        fetchJson("/api/v1/resources"),
    ]);

    state.overview = overview;
    state.resources = resources;

    renderSummary(overview);
    renderResources(resources);
    renderRisks(overview.top_risks || []);
    renderAlerts(overview.recent_alerts || []);
    renderLogs(overview.recent_logs || []);
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
        headers: {"Content-Type": "application/json"},
        ...options,
    });
    if (!response.ok) {
        throw new Error(`${url} 요청 실패: ${response.status}`);
    }
    return response.json();
}

function renderSummary(overview) {
    document.getElementById("resourceCount").textContent = overview.resource_count;
    document.getElementById("openAlertCount").textContent = overview.open_alert_count;
    document.getElementById("criticalAlertCount").textContent = overview.critical_alert_count;
    document.getElementById("averageRiskScore").textContent = overview.average_risk_score;
}

function renderResources(resources) {
    const rows = resources.map((resource) => `
        <tr>
            <td>${escapeHtml(resource.resource_id)}</td>
            <td>${escapeHtml(resource.resource_type)}</td>
            <td>${escapeHtml(resource.service)}</td>
            <td>${escapeHtml(resource.ip)}</td>
        </tr>
    `);
    document.getElementById("resourceRows").innerHTML = rows.join("");
}

function renderRisks(predictions) {
    const list = predictions.map((prediction) => `
        <div class="risk-item">
            <strong>
                <span>${escapeHtml(prediction.resource_id)}</span>
                <span>${prediction.risk_score}</span>
            </strong>
            <div class="muted">${escapeHtml(prediction.summary)}</div>
            <div class="risk-meter"><span style="width: ${prediction.risk_score}%"></span></div>
        </div>
    `);
    document.getElementById("riskList").innerHTML = list.join("") || `<div class="muted">예측 데이터가 없습니다.</div>`;
}

function renderAlerts(alerts) {
    const rows = alerts.map((alert) => `
        <tr>
            <td><span class="badge ${alert.severity}">${alert.severity}</span></td>
            <td>${escapeHtml(alert.resource_id)}</td>
            <td>${escapeHtml(alert.metric_name)}</td>
            <td>${escapeHtml(alert.message)}</td>
            <td><button type="button" onclick="loadGuide('${alert.alert_id}', '${alert.resource_id}', '${escapeHtml(alert.metric_name)}')">가이드</button></td>
        </tr>
    `);
    document.getElementById("alertRows").innerHTML = rows.join("") || `<tr><td colspan="5" class="muted">열린 알림이 없습니다.</td></tr>`;
}

function renderLogs(logs) {
    const items = logs.map((log) => `
        <div class="log-line">
            <strong>${escapeHtml(log.level)}</strong>
            <span class="muted">${escapeHtml(log.resource_id)}</span>
            <div>${escapeHtml(log.message)}</div>
        </div>
    `);
    document.getElementById("logList").innerHTML = items.join("") || `<div class="muted">로그가 없습니다.</div>`;
}

async function loadGuide(alertId, resourceId, symptom) {
    const guide = await fetchJson("/api/v1/guides/generate", {
        method: "POST",
        body: JSON.stringify({
            alert_id: alertId,
            resource_id: resourceId,
            symptom: symptom,
        }),
    });
    renderGuide(guide);
}

function renderGuide(guide) {
    document.getElementById("guideBox").innerHTML = `
        <h3>${escapeHtml(guide.title)}</h3>
        <p>${escapeHtml(guide.summary)}</p>
        <h4>원인 후보</h4>
        <ol>${guide.cause_candidates.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>
        <h4>확인 명령어</h4>
        <ul>${guide.check_commands.map((item) => `<li><code>${escapeHtml(item)}</code></li>`).join("")}</ul>
        <h4>조치 절차</h4>
        <ol>${guide.action_steps.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>
        <h4>롤백 절차</h4>
        <ol>${guide.rollback_steps.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>
    `;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
