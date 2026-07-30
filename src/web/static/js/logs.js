/* =====================================================
   CONFIGURATION
===================================================== */

const AUTO_REFRESH_INTERVAL_MS =
    5000;


/* =====================================================
   ELEMENTS
===================================================== */

const lineCountSelect =
    document.getElementById(
        "lineCountSelect"
    );

const levelFilterSelect =
    document.getElementById(
        "levelFilterSelect"
    );

const autoRefreshCheckbox =
    document.getElementById(
        "autoRefreshCheckbox"
    );

const refreshLogsBtn =
    document.getElementById(
        "refreshLogsBtn"
    );

const logsStatus =
    document.getElementById(
        "logsStatus"
    );

const logsCount =
    document.getElementById(
        "logsCount"
    );

const logsViewer =
    document.getElementById(
        "logsViewer"
    );


/* =====================================================
   STATE
===================================================== */

let allLogLines = [];
let autoRefreshTimer = null;
let isLoadingLogs = false;


/* =====================================================
   STATUS
===================================================== */

function updateLogsStatus(
    message,
    statusClass
) {
    if (!logsStatus) {
        return;
    }

    logsStatus.innerText =
        message;

    logsStatus.classList.remove(
        "loading",
        "ready",
        "empty",
        "error"
    );

    logsStatus.classList.add(
        statusClass
    );
}


/* =====================================================
   FILTER
===================================================== */

function getSelectedLogLevel() {
    if (!levelFilterSelect) {
        return "ALL";
    }

    return String(
        levelFilterSelect.value ||
        "ALL"
    ).toUpperCase();
}


function lineMatchesLevel(
    line,
    level
) {
    if (level === "ALL") {
        return true;
    }

    const normalizedLine =
        String(line).toUpperCase();

    const patterns = [
        `[${level}]`,
        ` ${level} `,
        `-${level}-`,
        `${level}:`
    ];

    return patterns.some(
        function (pattern) {
            return normalizedLine.includes(
                pattern
            );
        }
    );
}


function getFilteredLines() {
    const selectedLevel =
        getSelectedLogLevel();

    return allLogLines.filter(
        function (line) {
            return lineMatchesLevel(
                line,
                selectedLevel
            );
        }
    );
}


/* =====================================================
   RENDER
===================================================== */

function renderLogs() {
    if (
        !logsViewer ||
        !logsCount
    ) {
        return;
    }

    const filteredLines =
        getFilteredLines();

    const wasNearBottom =
        (
            logsViewer.scrollHeight -
            logsViewer.scrollTop -
            logsViewer.clientHeight
        ) < 80;

    if (filteredLines.length === 0) {
        logsViewer.textContent =
            "No log data found.";

        logsCount.innerText =
            "0 lines";

        updateLogsStatus(
            "No log data",
            "empty"
        );

        return;
    }

    logsViewer.textContent =
        filteredLines.join("\n");

    logsCount.innerText =
        `${filteredLines.length} lines`;

    updateLogsStatus(
        "Logs loaded",
        "ready"
    );

    if (wasNearBottom) {
        logsViewer.scrollTop =
            logsViewer.scrollHeight;
    }
}


/* =====================================================
   LOAD LOGS
===================================================== */

async function loadLogs() {
    if (
        isLoadingLogs ||
        !lineCountSelect
    ) {
        return;
    }

    const lineCount =
        Number(
            lineCountSelect.value
        ) || 500;

    isLoadingLogs = true;

    if (refreshLogsBtn) {
        refreshLogsBtn.disabled =
            true;

        refreshLogsBtn.innerText =
            "Loading...";
    }

    updateLogsStatus(
        "Loading logs...",
        "loading"
    );

    try {
        const response = await fetch(
            "/web_api/api/system/logs" +
            "?lines=" +
            encodeURIComponent(
                lineCount
            ),
            {
                method: "GET",
                cache: "no-store"
            }
        );

        let result;

        try {
            result =
                await response.json();

        } catch (jsonError) {
            throw new Error(
                "Log API returned an invalid response"
            );
        }

        if (
            !response.ok ||
            !result.ok
        ) {
            throw new Error(
                result.message ||
                "Cannot load application logs"
            );
        }

        allLogLines =
            Array.isArray(
                result.lines
            )
                ? result.lines.map(
                    function (line) {
                        return String(line);
                    }
                )
                : [];

        renderLogs();

    } catch (error) {
        console.error(
            "Load logs error:",
            error
        );

        allLogLines = [];

        if (logsViewer) {
            logsViewer.textContent =
                error.message ||
                "Cannot load application logs";
        }

        if (logsCount) {
            logsCount.innerText =
                "0 lines";
        }

        updateLogsStatus(
            "Cannot load logs",
            "error"
        );

    } finally {
        isLoadingLogs = false;

        if (refreshLogsBtn) {
            refreshLogsBtn.disabled =
                false;

            refreshLogsBtn.innerText =
                "Refresh";
        }
    }
}


/* =====================================================
   AUTO REFRESH
===================================================== */

function stopAutoRefresh() {
    if (!autoRefreshTimer) {
        return;
    }

    clearInterval(
        autoRefreshTimer
    );

    autoRefreshTimer = null;
}


function startAutoRefresh() {
    stopAutoRefresh();

    if (
        !autoRefreshCheckbox ||
        !autoRefreshCheckbox.checked
    ) {
        return;
    }

    autoRefreshTimer = setInterval(
        loadLogs,
        AUTO_REFRESH_INTERVAL_MS
    );
}


/* =====================================================
   EVENTS
===================================================== */

if (refreshLogsBtn) {
    refreshLogsBtn.addEventListener(
        "click",
        loadLogs
    );
}


if (lineCountSelect) {
    lineCountSelect.addEventListener(
        "change",
        async function () {
            await loadLogs();
        }
    );
}


if (levelFilterSelect) {
    levelFilterSelect.addEventListener(
        "change",
        renderLogs
    );
}


if (autoRefreshCheckbox) {
    autoRefreshCheckbox.addEventListener(
        "change",
        function () {
            if (
                autoRefreshCheckbox.checked
            ) {
                loadLogs();
                startAutoRefresh();

            } else {
                stopAutoRefresh();
            }
        }
    );
}


/* =====================================================
   PAGE VISIBILITY
===================================================== */

document.addEventListener(
    "visibilitychange",
    function () {
        if (document.hidden) {
            stopAutoRefresh();
            return;
        }

        loadLogs();
        startAutoRefresh();
    }
);


/* =====================================================
   START PAGE
===================================================== */

loadLogs();
startAutoRefresh();