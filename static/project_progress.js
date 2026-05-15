// ---------------------------------------------------------------------------
// 1. HTML 요소 찾기
// ---------------------------------------------------------------------------
// document.querySelector("#아이디")는 HTML에서 해당 id를 가진 태그를 찾아옵니다.
// 아래 변수들은 이후 등록, 수정, 삭제, 검색 기능에서 계속 사용됩니다.
const form = document.querySelector("#taskForm");
const tableBody = document.querySelector("#taskTable");
const emptyState = document.querySelector("#emptyState");
const saveBtn = document.querySelector("#saveBtn");
const resetBtn = document.querySelector("#resetBtn");
const copyBtn = document.querySelector("#copyBtn");
const searchInput = document.querySelector("#searchInput");
const statusFilter = document.querySelector("#statusFilter");

// 서버에서 받아온 작업 목록을 메모리에 보관하는 배열입니다.
// 검색/필터/테이블 다시 그리기는 이 배열을 기준으로 처리합니다.
let tasks = [];

// 화면 메시지를 한 곳에 모아두면 나중에 문구를 바꾸기 쉽습니다.
const LABELS = {
  save: "등록",
  update: "수정",
  delete: "삭제",
  newTask: "새 Task",
  noPrevious: "복사할 이전 라인이 없어 새 Task를 생성합니다.",
  deleteConfirm: "선택한 작업을 삭제할까요?",
  saveError: "저장 중 오류가 발생했습니다.",
  deleteError: "삭제 중 오류가 발생했습니다.",
  copyError: "이전 라인 복사 중 오류가 발생했습니다.",
};

// 입력 폼과 서버 데이터에서 사용되는 필드 이름입니다.
// 수정 버튼을 눌렀을 때 이 목록을 돌면서 폼에 값을 채웁니다.
const fields = [
  "project",
  "task",
  "plan_start_date",
  "plan_end_date",
  "actual_start_date",
  "actual_end_date",
  "owner",
  "deliverable",
  "note",
];


// ---------------------------------------------------------------------------
// 2. 입력 폼 처리
// ---------------------------------------------------------------------------
function payloadFromForm() {
  // 폼에 입력된 값을 서버로 보낼 JSON 객체로 만듭니다.
  // 상태/계획진척률/실제진척률/공정준수율은 여기서 보내지 않습니다.
  // 해당 값들은 서버가 날짜를 기준으로 자동 계산합니다.
  return {
    project: document.querySelector("#project").value.trim(),
    task: document.querySelector("#task").value.trim(),
    plan_start_date: document.querySelector("#plan_start_date").value || null,
    plan_end_date: document.querySelector("#plan_end_date").value || null,
    actual_start_date: document.querySelector("#actual_start_date").value || null,
    actual_end_date: document.querySelector("#actual_end_date").value || null,
    owner: document.querySelector("#owner").value.trim(),
    deliverable: document.querySelector("#deliverable").value.trim(),
    note: document.querySelector("#note").value.trim(),
  };
}

function resetForm() {
  // 입력 폼을 비우고, 수정 모드에서 등록 모드로 되돌립니다.
  form.reset();
  document.querySelector("#taskId").value = "";
  saveBtn.textContent = LABELS.save;
}

function fillForm(task) {
  // 테이블에서 수정 버튼을 누르면 해당 작업의 값을 입력 폼에 채웁니다.
  // hidden input인 taskId에 id가 들어가면 저장 시 PUT API를 호출합니다.
  document.querySelector("#taskId").value = task.id;
  fields.forEach((field) => {
    const input = document.querySelector(`#${field}`);
    input.value = task[field] ?? "";
  });
  saveBtn.textContent = LABELS.update;
  window.scrollTo({ top: 0, behavior: "smooth" });
}


// ---------------------------------------------------------------------------
// 3. 표시용 HTML 만들기
// ---------------------------------------------------------------------------
function statusLabel(status) {
  // 서버는 상태를 green/yellow/red 코드로 보내고, 화면은 한글로 보여줍니다.
  return {
    green: "초록",
    yellow: "노랑",
    red: "빨강",
  }[status] || "빨강";
}

function signalCell(status, complianceRate) {
  // 공정준수율에 따라 신호등 모양을 만듭니다.
  // 실제 색상은 project_progress.css의 .signal.green 같은 CSS가 담당합니다.
  const signal = ["green", "yellow", "red"].includes(status) ? status : "red";
  return `
    <span class="signal ${signal}" title="${statusLabel(signal)} ${complianceRate}%">
      <span class="lamp"></span>
      <span>${statusLabel(signal)}</span>
    </span>
  `;
}

function rateClass(value) {
  // 공정준수율 숫자의 색상을 바꾸기 위한 CSS 클래스입니다.
  if (value >= 90) return "high";
  if (value >= 70) return "mid";
  return "low";
}

function progressCell(value, plan = false) {
  // 계획진척률/실제진척률을 막대 그래프로 보여줍니다.
  // plan=true면 계획진척률 색상, false면 실제진척률 색상을 사용합니다.
  const safeValue = Math.min(100, Math.max(0, Number(value || 0)));
  return `
    <div class="progress">
      <div class="bar"><div class="fill ${plan ? "plan" : ""}" style="width:${safeValue}%"></div></div>
      <span>${safeValue}%</span>
    </div>
  `;
}

function escapeHtml(value) {
  // 사용자가 입력한 값에 HTML 태그가 섞여 있어도 화면 구조가 깨지지 않도록 보호합니다.
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}


// ---------------------------------------------------------------------------
// 4. 검색, 필터, 테이블 그리기
// ---------------------------------------------------------------------------
function filteredTasks() {
  // 검색어와 신호등 필터를 적용한 작업 목록만 반환합니다.
  const keyword = searchInput.value.trim().toLowerCase();
  const status = statusFilter.value;

  return tasks.filter((task) => {
    const matchesStatus = !status || task.status === status;
    const text = `${task.project} ${task.task} ${task.owner} ${task.deliverable} ${task.note}`.toLowerCase();
    return matchesStatus && (!keyword || text.includes(keyword));
  });
}

function renderSummary(items) {
  // 상단 요약 영역의 전체 건수, 평균 실제진척률, 평균 공정준수율을 계산합니다.
  const count = items.length;
  const average = (key) => {
    if (!count) return 0;
    return Math.round(items.reduce((sum, item) => sum + Number(item[key] || 0), 0) / count);
  };

  document.querySelector("#totalCount").textContent = count;
  document.querySelector("#avgActual").textContent = average("actual_progress_rate");
  document.querySelector("#avgCompliance").textContent = average("completion_compliance_rate");
}

function render() {
  // 현재 tasks 배열을 기준으로 테이블 전체를 다시 그립니다.
  // 등록/수정/삭제/검색/필터가 발생하면 이 함수가 호출됩니다.
  const items = filteredTasks();
  tableBody.innerHTML = "";
  emptyState.classList.toggle("visible", items.length === 0);

  items.forEach((task) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="text">${escapeHtml(task.project)}</td>
      <td class="text">${escapeHtml(task.task)}</td>
      <td>${signalCell(task.status, task.completion_compliance_rate)}</td>
      <td>${task.plan_start_date || ""}</td>
      <td>${task.plan_end_date || ""}</td>
      <td>${progressCell(task.plan_progress_rate, true)}</td>
      <td>${task.actual_start_date || ""}</td>
      <td>${task.actual_end_date || ""}</td>
      <td>${progressCell(task.actual_progress_rate)}</td>
      <td><span class="rate ${rateClass(task.completion_compliance_rate)}">${task.completion_compliance_rate}%</span></td>
      <td>${escapeHtml(task.owner)}</td>
      <td class="text">${escapeHtml(task.deliverable)}</td>
      <td class="text">${escapeHtml(task.note)}</td>
      <td>
        <div class="row-actions">
          <button type="button" data-edit="${task.id}">${LABELS.update}</button>
          <button type="button" class="delete" data-delete="${task.id}">${LABELS.delete}</button>
        </div>
      </td>
    `;
    tableBody.appendChild(row);
  });

  renderSummary(items);
}


// ---------------------------------------------------------------------------
// 5. 서버 API 호출
// ---------------------------------------------------------------------------
async function loadTasks() {
  // 서버에서 작업 목록을 가져온 뒤 화면을 다시 그립니다.
  const response = await fetch("/api/tasks");
  tasks = await response.json();
  render();
}

async function saveTask(event) {
  // 등록 또는 수정 버튼을 눌렀을 때 실행됩니다.
  // taskId가 있으면 기존 작업 수정(PUT), 없으면 새 작업 등록(POST)입니다.
  event.preventDefault();
  const id = document.querySelector("#taskId").value;
  const response = await fetch(id ? `/api/tasks/${id}` : "/api/tasks", {
    method: id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payloadFromForm()),
  });

  if (!response.ok) {
    const error = await response.json();
    alert(error.detail || LABELS.saveError);
    return;
  }

  resetForm();
  await loadTasks();
}

async function copyPreviousTask() {
  // 이전라인 복사 버튼 기능입니다.
  // 마지막 작업을 그대로 복사해서 새 작업으로 등록하고, 새로 만든 작업을 수정 폼에 올립니다.
  const source = tasks[tasks.length - 1] || {
    project: "",
    task: LABELS.newTask,
    plan_start_date: null,
    plan_end_date: null,
    actual_start_date: null,
    actual_end_date: null,
    owner: "",
    deliverable: "",
    note: "",
  };
  if (!tasks.length) alert(LABELS.noPrevious);

  const payload = {
    project: source.project || "",
    task: source.task || LABELS.newTask,
    plan_start_date: source.plan_start_date || null,
    plan_end_date: source.plan_end_date || null,
    actual_start_date: source.actual_start_date || null,
    actual_end_date: source.actual_end_date || null,
    owner: source.owner || "",
    deliverable: source.deliverable || "",
    note: source.note || "",
  };

  const response = await fetch("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json();
    alert(error.detail || LABELS.copyError);
    return;
  }

  const created = await response.json();
  await loadTasks();
  fillForm(created);
}

async function deleteTask(id) {
  // 삭제 버튼을 누르면 확인창을 보여준 뒤 DELETE API를 호출합니다.
  if (!confirm(LABELS.deleteConfirm)) return;

  const response = await fetch(`/api/tasks/${id}`, { method: "DELETE" });
  if (!response.ok) {
    const error = await response.json();
    alert(error.detail || LABELS.deleteError);
    return;
  }

  await loadTasks();
}


// ---------------------------------------------------------------------------
// 6. 이벤트 연결
// ---------------------------------------------------------------------------
// 아래 코드는 버튼 클릭, 폼 제출, 검색어 입력 같은 사용자의 행동과 함수를 연결합니다.
form.addEventListener("submit", saveTask);
resetBtn.addEventListener("click", resetForm);
copyBtn.addEventListener("click", copyPreviousTask);
searchInput.addEventListener("input", render);
statusFilter.addEventListener("change", render);

tableBody.addEventListener("click", (event) => {
  // 수정/삭제 버튼은 테이블 행이 만들어질 때 동적으로 생성됩니다.
  // 그래서 버튼 각각에 이벤트를 붙이지 않고, tbody에서 클릭을 한 번에 받아 처리합니다.
  const editId = event.target.dataset.edit;
  const deleteId = event.target.dataset.delete;

  if (editId) {
    const task = tasks.find((item) => String(item.id) === editId);
    if (task) fillForm(task);
  }
  if (deleteId) {
    deleteTask(deleteId);
  }
});

// 화면이 처음 열리면 서버에서 데이터를 읽어와 테이블을 표시합니다.
loadTasks();
