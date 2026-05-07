// ---------------------------------------------------------------------------
// 화면 요소 가져오기
// ---------------------------------------------------------------------------
// HTML의 id와 JavaScript 변수를 1:1로 연결합니다.
// 이후 코드에서는 document.getElementById를 반복하지 않고 이 변수들을 사용합니다.
const startButton = document.getElementById("startButton");
const stopButton = document.getElementById("stopButton");
const saveRecordingButton = document.getElementById("saveRecordingButton");
const downloadSummaryButton = document.getElementById("downloadSummaryButton");
const uploadSummaryButton = document.getElementById("uploadSummaryButton");
const audioFileInput = document.getElementById("audioFileInput");
const copySummaryButton = document.getElementById("copySummaryButton");
const clearSummaryButton = document.getElementById("clearSummaryButton");
const clearErrorButton = document.getElementById("clearErrorButton");
const errorPanel = document.getElementById("errorPanel");
const statusBadge = document.getElementById("statusBadge");
const statusText = document.getElementById("statusText");
const summaryText = document.getElementById("summaryText");
const transcriptText = document.getElementById("transcriptText");
const summaryMeta = document.getElementById("summaryMeta");
const transcriptMeta = document.getElementById("transcriptMeta");
const errorText = document.getElementById("errorText");
const errorMeta = document.getElementById("errorMeta");
const uploadMeta = document.getElementById("uploadMeta");
const languageInput = document.getElementById("languageInput");
const promptInput = document.getElementById("promptInput");
const meetingTitleInput = document.getElementById("meetingTitleInput");
const summaryFocusInput = document.getElementById("summaryFocusInput");

// ---------------------------------------------------------------------------
// 녹음 상태를 기억하는 전역 변수
// ---------------------------------------------------------------------------
// mediaRecorder: 브라우저의 녹음기 객체입니다.
// mediaStream: 마이크에서 들어오는 실제 오디오 스트림입니다.
// recordedChunks: 녹음된 조각 Blob들을 순서대로 담아두는 배열입니다.
let mediaRecorder = null;
let mediaStream = null;
let recordedChunks = [];
let recorderMimeType = "";
let errorCount = 0;

function showErrorPanel() {
    errorPanel.classList.remove("hidden");
}

function hideErrorPanel() {
    errorPanel.classList.add("hidden");
}

function setStatus(state, message) {
    // badge의 class를 바꾸면 CSS에서 색상이 자동으로 바뀝니다.
    statusBadge.className = `badge ${state}`;
    const labels = {
        idle: "대기 중",
        recording: "녹음 중",
        sending: "처리 중",
        error: "오류",
    };
    statusBadge.textContent = labels[state] || state;
    statusText.textContent = message;
}

function formatNow() {
    return new Date().toLocaleTimeString("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    });
}

function getSupportedMimeType() {
    // 브라우저마다 지원하는 녹음 포맷이 다릅니다.
    // 위에서부터 선호하는 순서로 검사해 처음 지원되는 값을 사용합니다.
    const mimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
    ];
    return mimeTypes.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function getRecordingExtension() {
    return recorderMimeType.includes("mp4") ? "mp4" : "webm";
}

function getRecordingBlob() {
    if (recordedChunks.length === 0) {
        return null;
    }
    return new Blob(recordedChunks, { type: recorderMimeType || "audio/webm" });
}

function appendError(title, message, detail) {
    // 화면 하단 오류 패널에 오류를 누적합니다.
    // 사용자가 여러 번 시도하다 실패해도 이전 오류 기록을 볼 수 있게 합니다.
    errorCount += 1;
    showErrorPanel();

    const entry = [
        `[${formatNow()}] ${title}`,
        message || "오류 메시지가 없습니다.",
        detail || "",
    ]
        .filter(Boolean)
        .join("\n");

    errorText.value = errorText.value ? `${errorText.value}\n\n${entry}` : entry;
    errorText.scrollTop = errorText.scrollHeight;
    errorMeta.textContent = `${errorCount}개의 오류 로그가 기록되었습니다.`;
}

function clearErrors() {
    errorText.value = "";
    errorCount = 0;
    errorMeta.textContent = "오류가 발생하면 상세 정보가 기록됩니다.";
    hideErrorPanel();
}

function clearResults() {
    summaryText.value = "";
    transcriptText.value = "";
    summaryMeta.textContent = "요약 결과가 여기에 표시됩니다.";
    transcriptMeta.textContent = "업로드한 녹음 파일의 전사 원문이 표시됩니다.";
}

async function copySummary() {
    const text = summaryText.value.trim();
    if (!text) {
        setStatus("idle", "복사할 요약 결과가 없습니다.");
        return;
    }

    try {
        await navigator.clipboard.writeText(text);
        setStatus("idle", "요약 결과를 클립보드에 복사했습니다.");
    } catch (error) {
        appendError("복사 실패", error.message || "요약 복사에 실패했습니다.");
        setStatus("error", "요약 복사 중 오류가 발생했습니다.");
    }
}

function downloadSummary() {
    const allText = [
        "[회의자료 요약]",
        summaryText.value.trim(),
        "",
        "[원문 전사]",
        transcriptText.value.trim(),
    ].join("\n");

    if (!summaryText.value.trim() && !transcriptText.value.trim()) {
        setStatus("idle", "다운로드할 회의자료가 없습니다.");
        return;
    }

    // 브라우저 안에서 텍스트 파일을 만들고 가짜 링크를 클릭해 다운로드를 시작합니다.
    const blob = new Blob([allText], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `meeting-summary-${Date.now()}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
}

function saveRecordingToFile() {
    const blob = getRecordingBlob();
    if (!blob) {
        setStatus("idle", "저장할 녹음 파일이 없습니다.");
        return;
    }

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `meeting-recording-${Date.now()}.${getRecordingExtension()}`;
    anchor.click();
    URL.revokeObjectURL(url);
    setStatus("idle", "녹음 파일을 저장했습니다. 저장한 파일을 아래에서 업로드해 주세요.");
}

async function startRecording() {
    try {
        if (!navigator.mediaDevices || !window.MediaRecorder) {
            throw new Error("이 브라우저는 MediaRecorder 녹음을 지원하지 않습니다.");
        }

        recorderMimeType = getSupportedMimeType();

        // getUserMedia를 호출하면 브라우저가 마이크 권한을 요청합니다.
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordedChunks = [];

        mediaRecorder = recorderMimeType
            ? new MediaRecorder(mediaStream, { mimeType: recorderMimeType })
            : new MediaRecorder(mediaStream);

        // 녹음 데이터가 생길 때마다 recordedChunks에 쌓습니다.
        mediaRecorder.addEventListener("dataavailable", (event) => {
            if (event.data && event.data.size > 0) {
                recordedChunks.push(event.data);
                saveRecordingButton.disabled = false;
            }
        });

        // 사용자가 녹음을 멈추면 마이크 리소스를 해제하고 버튼 상태를 되돌립니다.
        mediaRecorder.addEventListener("stop", () => {
            if (mediaStream) {
                mediaStream.getTracks().forEach((track) => track.stop());
            }
            mediaStream = null;
            mediaRecorder = null;
            startButton.disabled = false;
            stopButton.disabled = true;
            setStatus("idle", "녹음을 중지했습니다. 녹음 파일을 저장한 뒤 업로드해 주세요.");
        }, { once: true });

        // 1초마다 dataavailable 이벤트가 발생하게 하여 녹음 조각을 모읍니다.
        mediaRecorder.start(1000);
        startButton.disabled = true;
        stopButton.disabled = false;
        saveRecordingButton.disabled = true;
        setStatus("recording", "회의 음성을 녹음하고 있습니다.");
    } catch (error) {
        appendError("녹음 시작 실패", error.message || "녹음을 시작하지 못했습니다.");
        setStatus("error", "녹음 시작 중 오류가 발생했습니다.");
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
        return;
    }
    setStatus("idle", "진행 중인 녹음이 없습니다.");
}

async function summarizeSelectedFile() {
    const file = audioFileInput.files && audioFileInput.files[0];
    if (!file) {
        setStatus("idle", "먼저 요약할 녹음 파일을 선택해 주세요.");
        return;
    }

    uploadSummaryButton.disabled = true;
    setStatus("sending", "녹음 파일을 업로드하고 전사와 요약을 생성하고 있습니다.");
    uploadMeta.textContent = `${file.name} 파일을 처리하고 있습니다.`;

    try {
        // multipart/form-data 형식으로 파일과 입력값을 함께 보냅니다.
        // FastAPI의 summarize_recording() 함수가 같은 이름의 매개변수로 받습니다.
        const formData = new FormData();
        formData.append("audio_file", file);
        formData.append("language", languageInput.value.trim() || "ko");
        formData.append("transcription_prompt", promptInput.value.trim());
        formData.append("meeting_title", meetingTitleInput.value.trim());
        formData.append("summary_focus", summaryFocusInput.value.trim());

        const response = await fetch(window.MEETING_APP_CONFIG.summarizeUrl, {
            method: "POST",
            body: formData,
        });

        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "회의자료 요약 생성에 실패했습니다.");
        }

        summaryText.value = payload.summary || "";
        transcriptText.value = payload.transcript || "";
        summaryMeta.textContent = `${payload.source_name || file.name} 파일의 회의자료 요약을 완료했습니다.`;
        transcriptMeta.textContent = "전사 원문 생성을 완료했습니다.";
        uploadMeta.textContent = "회의자료 요약 생성을 완료했습니다.";
        setStatus("idle", "회의자료 요약을 완료했습니다.");
    } catch (error) {
        appendError("회의자료 요약 실패", error.message || "업로드 파일 처리에 실패했습니다.");
        uploadMeta.textContent = "녹음 파일을 선택하면 회의 전사와 요약을 생성합니다.";
        setStatus("error", "회의자료 요약 중 오류가 발생했습니다.");
    } finally {
        uploadSummaryButton.disabled = false;
    }
}

// ---------------------------------------------------------------------------
// 버튼과 함수 연결
// ---------------------------------------------------------------------------
// 사용자가 버튼을 클릭하면 어떤 함수가 실행될지 등록하는 부분입니다.
startButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", stopRecording);
saveRecordingButton.addEventListener("click", saveRecordingToFile);
downloadSummaryButton.addEventListener("click", downloadSummary);
uploadSummaryButton.addEventListener("click", summarizeSelectedFile);
copySummaryButton.addEventListener("click", copySummary);
clearSummaryButton.addEventListener("click", clearResults);
clearErrorButton.addEventListener("click", clearErrors);

window.addEventListener("beforeunload", () => {
    // 사용자가 페이지를 닫거나 새로고침할 때 녹음 중이면 마이크 사용을 정리합니다.
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
    }

    if (mediaStream) {
        mediaStream.getTracks().forEach((track) => track.stop());
    }
});
