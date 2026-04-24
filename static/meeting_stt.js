/*
프로그램 흐름 설명
1. 페이지가 열리면 WebSocket 연결을 준비하고 기본 설정을 서버에 보냅니다.
2. 사용자가 실시간 녹음을 시작하면:
   - 한 레코더는 짧은 청크를 만들어 서버로 보내 실시간 전사를 수행합니다.
   - 다른 레코더는 전체 녹음 내용을 모아 나중에 파일로 저장할 수 있게 보관합니다.
3. 서버가 돌려준 Whisper segment를 화면에서 발화 블록으로 묶어
   "화자 n: 내용" 형식으로 줄바꿈해 회의록에 누적합니다.
4. 업로드 전사를 사용하면 선택한 파일들을 순서대로 서버로 보내고,
   받은 전사 결과를 같은 회의록 영역에 이어서 추가합니다.
5. 사용자는 회의록 복사, 회의록 지우기, 오류 로그 지우기,
   녹음 파일 저장 기능을 버튼으로 사용할 수 있습니다.

이 파일이 정상 동작하려면 필요한 것
1. 이 JavaScript 파일은 단독 실행 파일이 아니라 브라우저에서 동작하는 화면 제어 코드입니다.
2. 따라서 아래 조건이 먼저 만족되어야 합니다.
   - src/realtime_stt_app.py 서버가 실행 중일 것
   - templates/meeting_stt.html 이 정상적으로 브라우저에 열릴 것
   - 브라우저가 WebSocket, fetch, MediaRecorder, clipboard API를 지원할 것
3. 권장 브라우저
   - 최신 Chrome
   - 최신 Microsoft Edge
4. 추가 설치가 필요한 JavaScript 패키지는 없습니다.
   - 이 파일은 npm, yarn, vite 없이 브라우저 기본 기능만 사용합니다.

실행 방법 요약
1. Python 서버를 먼저 실행합니다.
2. 브라우저에서 http://127.0.0.1:8010 에 접속합니다.
3. 브라우저가 마이크 권한을 요청하면 허용합니다.
4. 실시간 녹음 또는 파일 업로드 기능을 사용합니다.

문제 발생 시 확인할 것
1. WebSocket 연결 실패: 서버가 실행 중인지 확인합니다.
2. 녹음 시작 실패: 브라우저 마이크 권한이 허용되었는지 확인합니다.
3. 파일 업로드 실패: 서버에 python-multipart와 whisper가 설치되었는지 확인합니다.
*/

const startButton = document.getElementById("startButton");
const stopButton = document.getElementById("stopButton");
const saveRecordingButton = document.getElementById("saveRecordingButton");
const downloadButton = document.getElementById("downloadButton");
const uploadTranscribeButton = document.getElementById("uploadTranscribeButton");
const audioFileInput = document.getElementById("audioFileInput");
const modelSelect = document.getElementById("modelSelect");
const copyTranscriptButton = document.getElementById("copyTranscriptButton");
const clearTranscriptButton = document.getElementById("clearTranscriptButton");
const clearErrorButton = document.getElementById("clearErrorButton");
const errorPanel = document.getElementById("errorPanel");
const statusBadge = document.getElementById("statusBadge");
const statusText = document.getElementById("statusText");
const transcriptText = document.getElementById("transcriptText");
const transcriptMeta = document.getElementById("transcriptMeta");
const errorText = document.getElementById("errorText");
const errorMeta = document.getElementById("errorMeta");
const uploadMeta = document.getElementById("uploadMeta");
const languageInput = document.getElementById("languageInput");
const promptInput = document.getElementById("promptInput");
const chunkSecondsInput = document.getElementById("chunkSecondsInput");

let mediaRecorder = null;
let archiveRecorder = null;
let mediaStream = null;
let websocket = null;
let transcriptCount = 0;
let errorCount = 0;
let recordingActive = false;
let recorderMimeType = "";
let chunkDurationMs = 1000;
let segmentTimerId = null;
let archiveChunks = [];
let speakerCursor = 0;

function showErrorPanel() {
    errorPanel.classList.remove("hidden");
}

function hideErrorPanel() {
    errorPanel.classList.add("hidden");
}

function setStatus(state, message) {
    statusBadge.className = `badge ${state}`;
    const labels = {
        idle: "대기 중",
        recording: "녹음 중",
        sending: "전송 중",
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

function getSelectedModel() {
    return modelSelect.value || "medium";
}

function getSupportedMimeType() {
    const mimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
    ];
    return mimeTypes.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function appendError(title, message, detail, extra) {
    errorCount += 1;
    showErrorPanel();

    const entry = [
        `[${formatNow()}] ${title}`,
        message || "오류 메시지가 없습니다.",
        extra || "",
        detail || "",
    ]
        .filter(Boolean)
        .join("\n");

    errorText.value = errorText.value
        ? `${errorText.value}\n\n${entry}`
        : entry;
    errorText.scrollTop = errorText.scrollHeight;
    errorMeta.textContent = `${errorCount}개의 오류 로그가 기록되었습니다.`;
}

function clearTranscript() {
    transcriptText.value = "";
    transcriptCount = 0;
    speakerCursor = 0;
    transcriptMeta.textContent = "전사된 내용만 발화자별 줄바꿈 형식으로 누적됩니다.";
}

function clearErrors() {
    errorText.value = "";
    errorCount = 0;
    errorMeta.textContent = "오류가 발생하면 상세 정보가 기록됩니다.";
    hideErrorPanel();
}

async function copyTranscript() {
    const text = transcriptText.value.trim();
    if (!text) {
        setStatus("idle", "복사할 회의록이 없습니다.");
        return;
    }

    try {
        await navigator.clipboard.writeText(text);
        setStatus("idle", "회의록을 클립보드에 복사했습니다.");
    } catch (error) {
        console.error(error);
        appendError("복사 실패", error.message || "회의록 복사에 실패했습니다.", "", "");
        setStatus("error", "회의록 복사 중 오류가 발생했습니다.");
    }
}

function downloadTranscript() {
    const allText = [
        "[회의록]",
        transcriptText.value.trim(),
        "",
        "[오류 로그]",
        errorText.value.trim(),
    ].join("\n");

    const blob = new Blob([allText], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `meeting-transcript-${Date.now()}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
}

function saveRecordingToFile() {
    if (archiveChunks.length === 0) {
        setStatus("idle", "저장할 녹음 파일이 없습니다.");
        return;
    }

    const blob = new Blob(archiveChunks, { type: recorderMimeType || "audio/webm" });
    const extension = recorderMimeType.includes("mp4") ? "mp4" : "webm";
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `meeting-recording-${Date.now()}.${extension}`;
    anchor.click();
    URL.revokeObjectURL(url);
    setStatus("idle", "현재까지 녹음된 파일을 저장했습니다.");
}

function normalizeText(text) {
    return (text || "").replace(/\s+/g, " ").trim();
}

function buildSpeakerParagraphs(segments, fallbackText) {
    if (!Array.isArray(segments) || segments.length === 0) {
        const plainText = normalizeText(fallbackText);
        return plainText ? [plainText] : [];
    }

    const blocks = [];
    let currentBlock = null;
    let nextSpeakerId = speakerCursor + 1;
    let previousEnd = null;

    for (const segment of segments) {
        const segmentText = normalizeText(segment.text);
        if (!segmentText) {
            continue;
        }

        const start = Number(segment.start ?? 0);
        const end = Number(segment.end ?? start);
        const hasLongPause = previousEnd !== null && start - previousEnd >= 1.2;

        if (!currentBlock || hasLongPause) {
            currentBlock = {
                speakerId: nextSpeakerId,
                textParts: [segmentText],
            };
            blocks.push(currentBlock);
            nextSpeakerId += 1;
        } else {
            currentBlock.textParts.push(segmentText);
        }

        previousEnd = end;
    }

    if (blocks.length === 0) {
        const plainText = normalizeText(fallbackText);
        return plainText ? [plainText] : [];
    }

    speakerCursor = blocks[blocks.length - 1].speakerId;
    return blocks.map((block) => `화자 ${block.speakerId}: ${block.textParts.join(" ")}`);
}

function appendTranscriptFromSegments(segments, fallbackText) {
    const paragraphs = buildSpeakerParagraphs(segments, fallbackText);
    if (paragraphs.length === 0) {
        return;
    }

    transcriptCount += paragraphs.length;
    const nextText = paragraphs.join("\n\n");
    transcriptText.value = transcriptText.value
        ? `${transcriptText.value}\n\n${nextText}`
        : nextText;
    transcriptText.scrollTop = transcriptText.scrollHeight;
    transcriptMeta.textContent = `${transcriptCount}개의 발화 블록이 누적되었습니다.`;
}

function sendConfig() {
    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
        return;
    }

    websocket.send(JSON.stringify({
        type: "config",
        language: languageInput.value.trim() || "ko",
        prompt: promptInput.value.trim(),
        model_name: getSelectedModel(),
    }));
}

function ensureWebSocketConnection() {
    if (websocket && websocket.readyState === WebSocket.OPEN) {
        return Promise.resolve(websocket);
    }

    return new Promise((resolve, reject) => {
        const ws = new WebSocket(window.STT_APP_CONFIG.websocketUrl);
        websocket = ws;

        ws.addEventListener("open", () => {
            setStatus("idle", "WebSocket 연결이 완료되었습니다.");
            sendConfig();
            resolve(ws);
        }, { once: true });

        ws.addEventListener("message", (event) => {
            const payload = JSON.parse(event.data);

            if (payload.type === "ready") {
                setStatus("idle", payload.message || "연결 준비가 완료되었습니다.");
                return;
            }

            if (payload.type === "config_ack") {
                setStatus("idle", `모델 ${payload.model} 설정이 적용되었습니다.`);
                return;
            }

            if (payload.type === "transcript") {
                appendTranscriptFromSegments(payload.segments, payload.text);
                setStatus("recording", "회의 음성을 계속 수집하고 있습니다.");
                return;
            }

            if (payload.type === "error") {
                appendError(payload.title, payload.message, payload.detail, payload.extra);
                setStatus("error", payload.message || "서버 오류가 발생했습니다.");
                return;
            }

            if (payload.type === "info") {
                appendError("안내", payload.message, "", "");
            }
        });

        ws.addEventListener("close", () => {
            websocket = null;
            if (!recordingActive) {
                setStatus("idle", "WebSocket 연결이 종료되었습니다.");
            }
        });

        ws.addEventListener("error", () => {
            appendError("WebSocket 연결 오류", "서버와 연결하는 중 오류가 발생했습니다.", "", "");
            setStatus("error", "WebSocket 연결 오류가 발생했습니다.");
            reject(new Error("WebSocket connection error"));
        }, { once: true });
    });
}

function scheduleSegmentStop(recorder) {
    segmentTimerId = window.setTimeout(() => {
        if (mediaRecorder === recorder && recorder.state === "recording") {
            recorder.stop();
        }
    }, chunkDurationMs);
}

function clearSegmentTimer() {
    if (segmentTimerId !== null) {
        window.clearTimeout(segmentTimerId);
        segmentTimerId = null;
    }
}

async function sendAudioBlob(blob) {
    if (!blob || blob.size === 0) {
        return;
    }

    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
        appendError("전송 실패", "WebSocket 연결이 없어 음성 청크를 보낼 수 없습니다.", "", "");
        setStatus("error", "WebSocket 연결이 없습니다.");
        return;
    }

    setStatus("sending", "음성 청크를 서버로 전송하고 있습니다.");
    const buffer = await blob.arrayBuffer();
    websocket.send(buffer);
}

function startArchiveRecorder() {
    archiveChunks = [];

    archiveRecorder = recorderMimeType
        ? new MediaRecorder(mediaStream, { mimeType: recorderMimeType })
        : new MediaRecorder(mediaStream);

    archiveRecorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size > 0) {
            archiveChunks.push(event.data);
            saveRecordingButton.disabled = false;
        }
    });

    // timeslice를 주면 녹음 중간에도 조각이 쌓여 현재까지 녹음본을 저장할 수 있습니다.
    archiveRecorder.start(1000);
}

function stopArchiveRecorder() {
    if (archiveRecorder && archiveRecorder.state !== "inactive") {
        archiveRecorder.stop();
    }
    archiveRecorder = null;
}

function finalizeRecordingStop() {
    clearSegmentTimer();
    stopArchiveRecorder();

    if (mediaStream) {
        mediaStream.getTracks().forEach((track) => track.stop());
    }

    mediaRecorder = null;
    mediaStream = null;
    recordingActive = false;
    startButton.disabled = false;
    stopButton.disabled = true;
    setStatus("idle", "녹음을 중지했습니다.");
}

function startRecorderSegment() {
    if (!mediaStream || !recordingActive) {
        return;
    }

    const recorder = recorderMimeType
        ? new MediaRecorder(mediaStream, { mimeType: recorderMimeType })
        : new MediaRecorder(mediaStream);

    mediaRecorder = recorder;

    recorder.addEventListener("dataavailable", async (event) => {
        try {
            await sendAudioBlob(event.data);
        } catch (error) {
            console.error(error);
            appendError("청크 전송 실패", error.message || "음성 청크 전송에 실패했습니다.", "", "");
            setStatus("error", "음성 청크 전송에 실패했습니다.");
        }
    });

    recorder.addEventListener("stop", () => {
        clearSegmentTimer();

        if (recordingActive) {
            startRecorderSegment();
            setStatus("recording", "회의 음성을 계속 수집하고 있습니다.");
            return;
        }

        finalizeRecordingStop();
    }, { once: true });

    recorder.start();
    scheduleSegmentStop(recorder);
}

async function startRecording() {
    try {
        await ensureWebSocketConnection();
        sendConfig();

        recorderMimeType = getSupportedMimeType();
        chunkDurationMs = Math.max(1, Math.min(5, Number(chunkSecondsInput.value) || 1)) * 1000;
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordingActive = true;
        archiveChunks = [];
        saveRecordingButton.disabled = true;

        startArchiveRecorder();
        startRecorderSegment();

        startButton.disabled = true;
        stopButton.disabled = false;
        setStatus("recording", "회의 음성을 수집하고 있습니다.");
    } catch (error) {
        console.error(error);
        appendError("녹음 시작 실패", error.message || "녹음을 시작하지 못했습니다.", "", "");
        setStatus("error", "녹음 시작 중 오류가 발생했습니다.");
    }
}

function stopRecording() {
    recordingActive = false;

    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
        return;
    }

    finalizeRecordingStop();
}

async function transcribeSelectedFile() {
    const files = Array.from(audioFileInput.files || []);
    if (files.length === 0) {
        setStatus("idle", "먼저 전사할 음성 파일을 선택해 주세요.");
        return;
    }

    uploadTranscribeButton.disabled = true;
    setStatus("sending", "선택한 파일들을 순서대로 전사하고 있습니다.");

    try {
        for (let index = 0; index < files.length; index += 1) {
            const file = files[index];
            const formData = new FormData();
            formData.append("audio_file", file);
            formData.append("language", languageInput.value.trim() || "ko");
            formData.append("prompt", promptInput.value.trim());
            formData.append("model_name", getSelectedModel());

            uploadMeta.textContent = `${index + 1}/${files.length} ${file.name} 파일을 전사하고 있습니다.`;

            const response = await fetch(window.STT_APP_CONFIG.fileTranscribeUrl, {
                method: "POST",
                body: formData,
            });

            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.detail || "파일 전사에 실패했습니다.");
            }

            appendTranscriptFromSegments(payload.segments, payload.text);
        }

        uploadMeta.textContent = `${files.length}개 파일 전사가 완료되었습니다.`;
        setStatus("idle", "선택한 파일 전사가 완료되었습니다.");
    } catch (error) {
        console.error(error);
        appendError("파일 전사 실패", error.message || "업로드 파일 전사에 실패했습니다.", "", "");
        uploadMeta.textContent = "음성 파일을 선택한 뒤 서버로 전송하면 전사 결과가 회의록 영역에 추가됩니다.";
        setStatus("error", "업로드 파일 전사 중 오류가 발생했습니다.");
    } finally {
        uploadTranscribeButton.disabled = false;
    }
}

startButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", stopRecording);
saveRecordingButton.addEventListener("click", saveRecordingToFile);
downloadButton.addEventListener("click", downloadTranscript);
uploadTranscribeButton.addEventListener("click", transcribeSelectedFile);
copyTranscriptButton.addEventListener("click", copyTranscript);
clearTranscriptButton.addEventListener("click", clearTranscript);
clearErrorButton.addEventListener("click", clearErrors);
languageInput.addEventListener("change", sendConfig);
promptInput.addEventListener("change", sendConfig);
modelSelect.addEventListener("change", sendConfig);

ensureWebSocketConnection().catch(() => {
    setStatus("error", "초기 WebSocket 연결에 실패했습니다.");
});
