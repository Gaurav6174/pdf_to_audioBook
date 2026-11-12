const dropZone      = document.getElementById("dropZone");
const pdfInput      = document.getElementById("pdfInput");
const fileSelected  = document.getElementById("fileSelected");
const fileName      = document.getElementById("fileName");

const engineSelect  = document.getElementById("engineSelect");
const voiceSelect   = document.getElementById("voiceSelect");
const resetToggle   = document.getElementById("resetToggle");

const ENGINE_VOICES = {
    zonos2: [
        { value: "AmericanMale", label: "American Male (Default) ★" },
        { value: "AmericanFemale", label: "American Female" },
        { value: "BritishFemale", label: "British Female" }
    ],
    bark: [
        { value: "v2/en_speaker_6", label: "en_speaker_6 — Male, Natural ★" },
        { value: "v2/en_speaker_0", label: "en_speaker_0 — Male, Deep" },
        { value: "v2/en_speaker_1", label: "en_speaker_1 — Male, Neutral" },
        { value: "v2/en_speaker_2", label: "en_speaker_2 — Male, Clear" },
        { value: "v2/en_speaker_3", label: "en_speaker_3 — Male, Expressive" },
        { value: "v2/en_speaker_4", label: "en_speaker_4 — Male, Soft" },
        { value: "v2/en_speaker_5", label: "en_speaker_5 — Female, Neutral" },
        { value: "v2/en_speaker_7", label: "en_speaker_7 — Female, Clear" },
        { value: "v2/en_speaker_8", label: "en_speaker_8 — Female, Expressive" },
        { value: "v2/en_speaker_9", label: "en_speaker_9 — Female, Soft" }
    ]
};

function updateVoiceOptions() {
    const engine = engineSelect ? engineSelect.value : "zonos2";
    const voices = ENGINE_VOICES[engine] || ENGINE_VOICES.zonos2;
    voiceSelect.innerHTML = "";
    voices.forEach((v, idx) => {
        const opt = document.createElement("option");
        opt.value = v.value;
        opt.textContent = v.label;
        if (idx === 0) opt.selected = true;
        voiceSelect.appendChild(opt);
    });
    updateTerminalHint();
}

const btnGenerate   = document.getElementById("btnGenerate");
const btnStop       = document.getElementById("btnStop");
const btnMerge      = document.getElementById("btnMerge");
const btnClear      = document.getElementById("btnClear");
const btnDownload   = document.getElementById("btnDownload");

const statusPill    = document.getElementById("statusPill");
const statusDot     = document.getElementById("statusDot");
const statusText    = document.getElementById("statusText");

const headerWave    = document.getElementById("headerWave");

const progressFill    = document.getElementById("progressFill");
const progressScanner = document.getElementById("progressScanner");
const progressPercent = document.getElementById("progressPercent");
const progressEta     = document.getElementById("progressEta");

const stages = {
    1: document.getElementById("stage1"),
    2: document.getElementById("stage2"),
    3: document.getElementById("stage3"),
    4: document.getElementById("stage4"),
};

const logContainer  = document.getElementById("logContainer");
const autoScroll    = document.getElementById("autoScroll");

const resultCard    = document.getElementById("resultCard");
const resultIcon    = document.getElementById("resultIcon");
const resultText    = document.getElementById("resultText");
const resultSub     = document.getElementById("resultSub");

const terminalCmd   = document.getElementById("terminalCmd");


let selectedFile  = null;
let isRunning     = false;
let eventSource   = null;
let currentStage  = 0;


dropZone.addEventListener("click", () => pdfInput.click());

dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");

    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFileSelect(files[0]);
    }
});

pdfInput.addEventListener("change", () => {
    if (pdfInput.files.length > 0) {
        handleFileSelect(pdfInput.files[0]);
    }
});

function handleFileSelect(file) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
        addLog("Only PDF files are supported.", "error");
        return;
    }

    selectedFile = file;

    fileName.textContent = file.name;
    fileSelected.style.display = "flex";

    updateTerminalHint();

    addLog(`File selected: ${file.name}`, "info");
}


function updateTerminalHint() {
    const pdf    = selectedFile ? `input/${selectedFile.name}` : "input/book.pdf";
    const engine = engineSelect ? engineSelect.value : "zonos2";
    const voice  = voiceSelect.value;
    const reset  = resetToggle.checked;

    let cmd = `python main.py --pdf ${pdf} --engine ${engine} --voice ${voice}`;
    if (reset) cmd += " --reset";

    terminalCmd.textContent = cmd;
}

if (engineSelect) {
    engineSelect.addEventListener("change", () => {
        updateVoiceOptions();
        addLog(`Engine switched to: ${engineSelect.value.toUpperCase()}`, "info");
    });
}
voiceSelect.addEventListener("change",  updateTerminalHint);
resetToggle.addEventListener("change",  updateTerminalHint);

updateTerminalHint();


btnGenerate.addEventListener("click", async () => {

    if (!selectedFile) {
        addLog("Please select a PDF file first.", "error");
        dropZone.style.animation = "none";
        setTimeout(() => {
            dropZone.style.borderColor = "var(--error)";
            setTimeout(() => {
                dropZone.style.borderColor = "";
            }, 1500);
        }, 10);
        return;
    }

    if (isRunning) {
        addLog("A job is already running.", "info");
        return;
    }

    const formData = new FormData();
    formData.append("pdf",    selectedFile);
    formData.append("engine", engineSelect ? engineSelect.value : "zonos2");
    formData.append("voice",  voiceSelect.value);
    formData.append("reset",  resetToggle.checked ? "true" : "false");

    resetUI();
    setRunningState(true);
    addLog(`Starting pipeline for: ${selectedFile.name}`, "info");

    try {
        const response = await fetch("/upload", {
            method: "POST",
            body:   formData
        });

        const data = await response.json();

        if (!data.success) {
            addLog(`Upload failed: ${data.error}`, "error");
            setRunningState(false);
            return;
        }

        addLog(`Upload successful. Pipeline started.`, "info");

        openEventStream();

    } catch (err) {
        addLog(`Could not connect to server: ${err.message}`, "error");
        setRunningState(false);
    }
});


btnMerge.addEventListener("click", async () => {

    if (isRunning) {
        addLog("A job is already running.", "info");
        return;
    }

    resetUI();
    setRunningState(true);
    addLog("Merge-only mode: stitching existing chunks...", "info");

    try {
        const response = await fetch("/merge", { method: "POST" });
        const data = await response.json();

        if (!data.success) {
            addLog(`Merge failed: ${data.error}`, "error");
            setRunningState(false);
            return;
        }

        openEventStream();

    } catch (err) {
        addLog(`Could not connect to server: ${err.message}`, "error");
        setRunningState(false);
    }
});


btnDownload.addEventListener("click", () => {
    window.location.href = "/download";
});


btnStop.addEventListener("click", async () => {
    if (!isRunning) return;
    addLog("Sending stop signal...", "info");
    try {
        await fetch("/stop", { method: "POST" });
    } catch (err) {
        addLog(`Could not send stop signal: ${err.message}`, "error");
    }
});


btnClear.addEventListener("click", async () => {
    if (isRunning) {
        addLog("Cannot clear while a job is running.", "info");
        return;
    }
    addLog("Clearing output files...", "info");
    try {
        const response = await fetch("/clear", { method: "POST" });
        const data = await response.json();
        if (data.success) {
            addLog("Output cleared. Chunks, final WAV and progress deleted.", "success");
            btnDownload.disabled = true;
            resultCard.style.display = "none";
        } else {
            addLog(`Clear failed: ${data.error}`, "error");
        }
    } catch (err) {
        addLog(`Could not clear output: ${err.message}`, "error");
    }
});


function openEventStream() {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource("/stream");

    eventSource.onmessage = (event) => {

        let data;
        try {
            data = JSON.parse(event.data);
        } catch (e) {
            return;
        }

        if (data.type === "heartbeat") return;

        const logType = data.status === "error"    ? "error"
                      : data.status === "complete" ? "complete"
                      : "info";

        addLog(data.message, logType, data.time);

        if (data.percent !== null && data.percent !== undefined) {
            updateProgress(data.percent);
        }

        if (data.eta) {
            progressEta.textContent = data.eta;
        }

        updateStageFromMessage(data.message);

        if (data.status === "complete") {
            handleComplete(data.message);
        } else if (data.status === "error") {
            handleError(data.message);
        } else if (data.status === "stopped") {
            handleStopped(data.message);
        }
    };

    eventSource.onerror = () => {
        if (isRunning) {
            addLog("Lost connection to server. Check if Flask is running.", "error");
            setRunningState(false);
        }
        eventSource.close();
    };
}


function updateStageFromMessage(message) {
    const msg = message.toLowerCase();

    if (msg.includes("stage 1") || msg.includes("extracting")) {
        activateStage(1);
    } else if (msg.includes("stage 2") || msg.includes("processing text")) {
        activateStage(2);
    } else if (msg.includes("stage 3") || msg.includes("generating") || msg.includes("loading bark")) {
        activateStage(3);
    } else if (msg.includes("stage 4") || msg.includes("merging")) {
        activateStage(4);
    }
}

function activateStage(stageNum) {
    if (stageNum <= currentStage) return;
    currentStage = stageNum;

    for (let i = 1; i < stageNum; i++) {
        stages[i].classList.remove("active");
        stages[i].classList.add("done");
    }

    stages[stageNum].classList.remove("done");
    stages[stageNum].classList.add("active");
}


function updateProgress(percent) {
    progressFill.style.width    = `${percent}%`;
    progressPercent.textContent = `${percent}%`;

    if (percent > 0 && percent < 100) {
        progressScanner.classList.add("active");
    } else {
        progressScanner.classList.remove("active");
    }
}


function addLog(message, type = "info", time = null) {
    const timestamp = time || new Date().toTimeString().slice(0, 8);

    const entry = document.createElement("div");
    entry.className = `log-entry log-${type}`;

    entry.innerHTML = `
        <span class="log-time">${timestamp}</span>
        <span class="log-msg">${message}</span>
    `;

    const idleEntry = logContainer.querySelector(".log-idle");
    if (idleEntry) idleEntry.remove();

    logContainer.appendChild(entry);

    if (autoScroll.checked) {
        logContainer.scrollTop = logContainer.scrollHeight;
    }
}


function setRunningState(running) {
    isRunning = running;

    btnGenerate.disabled = running;
    btnMerge.disabled    = running;
    btnClear.disabled    = running;

    if (running) {
        btnStop.classList.add("visible");
    } else {
        btnStop.classList.remove("visible");
    }

    statusPill.className = "status-pill" + (running ? " running" : "");
    statusText.textContent = running ? "RUNNING" : "IDLE";

    if (running) {
        headerWave.classList.add("active");
        progressScanner.classList.add("active");
    } else {
        headerWave.classList.remove("active");
        progressScanner.classList.remove("active");
    }
}


function handleComplete(message) {
    if (eventSource) eventSource.close();

    setRunningState(false);

    for (let i = 1; i <= 4; i++) {
        stages[i].classList.remove("active");
        stages[i].classList.add("done");
    }

    updateProgress(100);
    progressEta.textContent = "Complete!";

    statusPill.className = "status-pill complete";
    statusText.textContent = "COMPLETE";

    btnDownload.disabled = false;

    resultCard.style.display = "block";
    resultCard.className = "card result-card";
    resultIcon.textContent  = "";
    resultText.textContent  = "Audiobook Ready!";
    resultSub.textContent   = message;

    addLog("All done! Click DOWNLOAD AUDIOBOOK to save your file.", "complete");
}


function handleError(message) {
    if (eventSource) eventSource.close();

    setRunningState(false);

    statusPill.className = "status-pill error";
    statusText.textContent = "ERROR";

    resultCard.style.display = "block";
    resultCard.className = "card result-card error";
    resultIcon.textContent = "";
    resultText.textContent = "Something went wrong";
    resultSub.textContent  = "Check logs/run.log for full details.";

    addLog(`${message}`, "error");
}


function handleStopped(message) {
    if (eventSource) eventSource.close();

    setRunningState(false);

    statusPill.className   = "status-pill";
    statusText.textContent = "STOPPED";

    addLog("Generation stopped by user.", "info");
}


function resetUI() {
    logContainer.innerHTML = "";

    updateProgress(0);
    progressEta.textContent = "—";

    currentStage = 0;
    for (let i = 1; i <= 4; i++) {
        stages[i].classList.remove("active", "done");
    }

    resultCard.style.display = "none";

    btnDownload.disabled = true;
}


async function checkInitialStatus() {
    try {
        const response = await fetch("/status");
        const data     = await response.json();

        if (data.is_running) {
            addLog("Job already in progress. Reconnecting...", "info");
            setRunningState(true);
            openEventStream();

        } else if (data.last_result.status === "complete") {
            btnDownload.disabled = false;
            resultCard.style.display = "block";
            resultIcon.textContent   = "";
            resultText.textContent   = "Previous audiobook ready!";
            resultSub.textContent    = "Click download to save it.";
            updateProgress(100);
            addLog("Previous run completed. Audiobook available for download.", "complete");

        } else if (data.last_result.status === "error") {
            addLog("Previous run encountered an error. Ready for new job.", "info");
        }

    } catch (err) {
    }
}

checkInitialStatus();


/* ── GPU MONITOR ──────────────────────────────────── */

const gpuName       = document.getElementById("gpuName");
const gpuTemp       = document.getElementById("gpuTemp");
const gpuUtil       = document.getElementById("gpuUtil");
const gpuMemUsed    = document.getElementById("gpuMemUsed");
const gpuMemTotal   = document.getElementById("gpuMemTotal");
const gpuTempBar    = document.getElementById("gpuTempBar");
const gpuUtilBar    = document.getElementById("gpuUtilBar");
const gpuMemBar     = document.getElementById("gpuMemBar");
const gpuUnavail    = document.getElementById("gpuUnavailable");
const gpuMetricsEl  = document.getElementById("gpuMetrics");

async function updateGpuStats() {
    try {
        const response = await fetch("/gpu_stats");
        const data = await response.json();

        if (!data.available) {
            gpuUnavail.style.display   = "block";
            gpuMetricsEl.style.display = "none";
            return;
        }

        gpuUnavail.style.display   = "none";
        gpuMetricsEl.style.display = "block";

        gpuName.textContent     = data.name;
        gpuTemp.textContent     = `${data.temperature}°C`;
        gpuUtil.textContent     = `${data.utilization}%`;
        gpuMemUsed.textContent  = `${data.memory_used} MiB`;
        gpuMemTotal.textContent = `${data.memory_total} MiB`;

        // Temperature bar — colour shifts green → gold → red
        const tempPct   = Math.min(100, data.temperature);
        const tempColor = data.temperature >= 80 ? "var(--error)"
                        : data.temperature >= 65 ? "var(--accent)"
                        : "var(--success)";
        gpuTempBar.style.width      = `${tempPct}%`;
        gpuTempBar.style.background = tempColor;

        gpuUtilBar.style.width = `${data.utilization}%`;

        const memPct = Math.round((data.memory_used / data.memory_total) * 100);
        gpuMemBar.style.width = `${memPct}%`;

    } catch { /* server unreachable — do nothing */ }
}

// Poll every 2 s, start immediately
updateGpuStats();
setInterval(updateGpuStats, 2000);
