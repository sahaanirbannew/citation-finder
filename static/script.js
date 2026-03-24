const descriptionInput = document.getElementById("case-description");
const findButton = document.getElementById("find-button");
const toggleLogsButton = document.getElementById("toggle-logs");
const logsPanel = document.getElementById("logs-panel");
const logsOutput = document.getElementById("logs-output");
const statusLine = document.getElementById("status-line");
const indianKanoonLink = document.getElementById("indiankanoon-link");
const indianCourtLink = document.getElementById("indian-court-link");
const activityDot = document.getElementById("activity-dot");
const activityText = document.getElementById("activity-text");
const elapsedLine = document.getElementById("elapsed-line");

let activeJobId = null;
let pollTimer = null;

function setLink(node, value) {
    if (value) {
        node.href = value;
        node.textContent = value;
    } else {
        node.removeAttribute("href");
        node.textContent = "-";
    }
}

function setActivity(state, text) {
    activityDot.className = `activity-dot ${state}`;
    activityText.textContent = text;
}

function stopPolling() {
    if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
    }
}

function formatElapsed(seconds) {
    const value = Number(seconds || 0);
    return `${value.toFixed(1)}s`;
}

function renderSnapshot(snapshot) {
    const result = snapshot.result || {};
    setLink(indianKanoonLink, result.indiankanoon_link);
    setLink(indianCourtLink, result.indian_court_link);
    logsOutput.textContent = snapshot.scrape_log_text || "No scrape links yet.";
    logsOutput.scrollTop = logsOutput.scrollHeight;
    elapsedLine.textContent = `Elapsed Time: ${formatElapsed(snapshot.elapsed_seconds)}`;

    if (snapshot.status === "running" || snapshot.status === "queued") {
        setActivity("running", "Working. Logs are updating live.");
        statusLine.textContent = `Job ${snapshot.status}. Trace events: ${snapshot.trace_events.length}.`;
        return;
    }

    if (snapshot.status === "completed") {
        setActivity("done", "Finished.");
        statusLine.textContent = result.status === "matched"
            ? "Match found."
            : (result.message || "No validated final link found.");
        findButton.disabled = false;
        activeJobId = null;
        return;
    }

    setActivity("error", "Failed.");
    statusLine.textContent = snapshot.error || "The job failed.";
    findButton.disabled = false;
    activeJobId = null;
}

async function pollJob() {
    if (!activeJobId) {
        return;
    }

    try {
        // Poll once per second so the logs and elapsed timer feel live.
        const response = await fetch(`/api/find/${activeJobId}`);
        const snapshot = await response.json();
        if (!response.ok) {
            throw new Error(snapshot.message || "Could not fetch job status.");
        }

        renderSnapshot(snapshot);

        if (snapshot.status === "running" || snapshot.status === "queued") {
            pollTimer = setTimeout(pollJob, 1000);
        } else {
            stopPolling();
        }
    } catch (error) {
        setActivity("error", "Polling failed.");
        statusLine.textContent = `Status polling failed: ${error.message}`;
        findButton.disabled = false;
        activeJobId = null;
        stopPolling();
    }
}

async function runSearch() {
    const caseDescription = descriptionInput.value.trim();
    if (!caseDescription) {
        statusLine.textContent = "Enter a case description first.";
        return;
    }

    stopPolling();
    activeJobId = null;
    findButton.disabled = true;
    setLink(indianKanoonLink, "");
    setLink(indianCourtLink, "");
    logsOutput.textContent = "Starting job...";
    setActivity("running", "Starting search job...");
    elapsedLine.textContent = "Elapsed Time: 0.0s";
    statusLine.textContent = "Creating background job...";

    try {
        // Start the crawl and then switch the UI into live-polling mode.
        const response = await fetch("/api/find", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ case_description: caseDescription }),
        });
        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message || "Request failed.");
        }

        activeJobId = result.job_id;
        statusLine.textContent = `Job accepted. ID: ${result.job_id}`;
        logsOutput.textContent = "Job accepted. Waiting for first trace events...";
        pollJob();
    } catch (error) {
        setActivity("error", "Failed to start.");
        statusLine.textContent = `Request failed: ${error.message}`;
        logsOutput.textContent = `ERROR\n${error.message}`;
        findButton.disabled = false;
    }
}

findButton.addEventListener("click", runSearch);
toggleLogsButton.addEventListener("click", () => {
    logsPanel.classList.toggle("hidden");
});
