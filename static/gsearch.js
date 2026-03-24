const gsearchDescription = document.getElementById("gsearch-description");
const gsearchButton = document.getElementById("gsearch-button");
const gsearchResults = document.getElementById("gsearch-results");
const gsearchStatusLine = document.getElementById("gsearch-status-line");
const gsearchLogsOutput = document.getElementById("gsearch-logs-output");
const gsearchToggleLogs = document.getElementById("gsearch-toggle-logs");
const gsearchLogsPanel = document.getElementById("gsearch-logs-panel");
const gsearchActivityDot = document.getElementById("gsearch-activity-dot");
const gsearchActivityText = document.getElementById("gsearch-activity-text");
const gsearchMatch = document.getElementById("gsearch-match");

function setGsearchActivity(state, text) {
    gsearchActivityDot.className = `activity-dot ${state}`;
    gsearchActivityText.textContent = text;
}

function renderResults(results) {
    const labels = ["A.", "B.", "C.", "D.", "E.", "F.", "G.", "H.", "I.", "J."];
    gsearchResults.innerHTML = "";
    for (let index = 0; index < 10; index += 1) {
        const row = document.createElement("div");
        const result = results[index];
        if (result) {
            const suffix = result.validation_status ? ` [${result.validation_status}]` : "";
            row.innerHTML = `${labels[index]} <a class="result-link" href="${result.url}" target="_blank" rel="noreferrer">${result.title}</a>${suffix}`;
        } else {
            row.textContent = labels[index];
        }
        gsearchResults.appendChild(row);
    }
}

async function runGsearch() {
    const caseDescription = gsearchDescription.value.trim();
    if (!caseDescription) {
        gsearchStatusLine.textContent = "Enter a case description first.";
        return;
    }

    gsearchButton.disabled = true;
    setGsearchActivity("running", "Running Google Search via Gemini...");
    gsearchStatusLine.textContent = "Searching...";
    gsearchMatch.textContent = "Validated match: -";
    gsearchLogsOutput.textContent = "Searching...";
    renderResults([]);

    try {
        const response = await fetch("/api/gsearch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ case_description: caseDescription }),
        });
        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message || "Request failed.");
        }

        renderResults(result.results || []);
        gsearchLogsOutput.textContent = result.log_text || "No logs returned.";
        if (result.validated_match) {
            gsearchMatch.innerHTML = `Validated match: <a class="result-link" href="${result.validated_match.url}" target="_blank" rel="noreferrer">${result.validated_match.url}</a>`;
            gsearchStatusLine.textContent = `Retrieved ${result.results.length} Google results and found a validated match.`;
        } else {
            gsearchStatusLine.textContent = `Retrieved ${result.results.length} Google results. No validated match found.`;
        }
        setGsearchActivity("done", "Finished.");
    } catch (error) {
        gsearchStatusLine.textContent = `Request failed: ${error.message}`;
        gsearchLogsOutput.textContent = `ERROR\n${error.message}`;
        setGsearchActivity("error", "Failed.");
    } finally {
        gsearchButton.disabled = false;
    }
}

gsearchButton.addEventListener("click", runGsearch);
gsearchToggleLogs.addEventListener("click", () => {
    gsearchLogsPanel.classList.toggle("hidden");
});
