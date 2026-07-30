/* =====================================================
   STATE AND ELEMENTS
===================================================== */

let historyPoints = [];
let selectedVariable = null;
let selectedUnit = "";

const variableSelect =
    document.getElementById("variableSelect");

const chart =
    document.getElementById("historyChart");

const chartStatus =
    document.getElementById("chartStatus");
const alertCard =
    document.getElementById(
        "alertCard"
    );

const alertToggle =
    document.getElementById(
        "alertToggle"
    );

const alertCount =
    document.getElementById(
        "alertCount"
    );

const alertToggleIcon =
    document.getElementById(
        "alertToggleIcon"
    );

const alertList =
    document.getElementById(
        "alertList"
    );

/* =====================================================
   alert TOGGLE
===================================================== */
async function loadAbnormalHistory() {
    try {
        const response = await fetch(
            "/web_api/api/history/alerts"
        );

        const result =
            await response.json();

        if (
            !response.ok ||
            !result.ok
        ) {
            throw new Error(
                result.message ||
                "Cannot load abnormal history"
            );
        }

        const items =
            Array.isArray(result.items)
                ? result.items
                : [];

        alertCount.innerText =
            items.length;

        alertList.innerHTML = "";

        if (items.length === 0) {
            alertCard.hidden = true;
            return;
        }

        alertCard.hidden = false;

        items.forEach(
            function (item) {
                alertList.appendChild(
                    createAlertItem(item)
                );
            }
        );

    } catch (error) {
        console.error(
            "Cannot load abnormal history:",
            error
        );

        alertCard.hidden = true;
    }
}


function createAlertItem(item) {
    const container =
        document.createElement("article");

    container.className =
        "alert-item";

    const toggleButton =
        document.createElement("button");

    toggleButton.type =
        "button";

    toggleButton.className =
        "alert-item-toggle";

    toggleButton.setAttribute(
        "aria-expanded",
        "false"
    );

    toggleButton.innerHTML = `
        <span>
            <strong>
                Run #${escapeHtml(item.id)}
            </strong>

            <span>
                ${escapeHtml(
                    item.ocr_time ||
                    item.created_at ||
                    "-"
                )}
            </span>
        </span>

        <span>
            ${escapeHtml(
                item.status ||
                "ALERT"
            )}
            ▼
        </span>
    `;

    const detail =
        document.createElement("div");

    detail.className =
        "alert-item-detail";

    detail.hidden = true;

    detail.innerHTML = `
        <div class="empty-box">
            Loading...
        </div>
    `;

    toggleButton.addEventListener(
        "click",
        async function () {
            const shouldOpen =
                detail.hidden;

            detail.hidden =
                !shouldOpen;

            toggleButton.setAttribute(
                "aria-expanded",
                String(shouldOpen)
            );

            if (
                shouldOpen &&
                detail.dataset.loaded !== "true"
            ) {
                await loadAlertDetail(
                    item.id,
                    detail
                );
            }
        }
    );

    container.appendChild(
        toggleButton
    );

    container.appendChild(
        detail
    );

    return container;
}


async function loadAlertDetail(
    runId,
    detailElement
) {
    try {
        const response = await fetch(
            "/web_api/api/history/run/" +
            runId
        );

        const result =
            await response.json();

        if (
            !response.ok ||
            !result.ok
        ) {
            throw new Error(
                result.message ||
                "Cannot load alert detail"
            );
        }

        const run =
            result.run;

        const values =
            Array.isArray(result.values)
                ? result.values
                : [];

        const imageUrl =
            run.calibrated_image_url ||
            run.raw_image_url ||
            "";

        const valueRows =
            values.length > 0
                ? values.map(
                    function (item) {
                        return `
                            <tr>
                                <td>
                                    ${escapeHtml(
                                        item.tag_name ??
                                        "-"
                                    )}
                                </td>

                                <td>
                                    ${escapeHtml(
                                        item.value ??
                                        "-"
                                    )}
                                </td>

                                <td>
                                    ${escapeHtml(
                                        item.unit ??
                                        "-"
                                    )}
                                </td>
                            </tr>
                        `;
                    }
                ).join("")
                : `
                    <tr>
                        <td colspan="3">
                            No OCR values found
                        </td>
                    </tr>
                `;

        detailElement.innerHTML = `
            <div class="alert-status">
                <p>
                    <strong>Status:</strong>
                    ${escapeHtml(
                        run.status ||
                        "ALERT"
                    )}
                </p>

                ${
                    run.missing_tags
                        ? `
                            <p>
                                <strong>
                                    Missing Tags:
                                </strong>

                                ${escapeHtml(
                                    run.missing_tags
                                )}
                            </p>
                        `
                        : ""
                }

                ${
                    run.alert_message
                        ? `
                            <p>
                                <strong>
                                    Message:
                                </strong>

                                ${escapeHtml(
                                    run.alert_message
                                )}
                            </p>
                        `
                        : ""
                }
            </div>

            ${
                imageUrl
                    ? `
                        <img
                            class="alert-image"
                            src="${imageUrl}?t=${Date.now()}"
                            alt="OCR alert image"
                        >
                    `
                    : `
                        <div class="empty-box">
                            No image found
                        </div>
                    `
            }

            <div class="alert-table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Tag</th>
                            <th>Value</th>
                            <th>Unit</th>
                        </tr>
                    </thead>

                    <tbody>
                        ${valueRows}
                    </tbody>
                </table>
            </div>
        `;

        detailElement.dataset.loaded =
            "true";

    } catch (error) {
        console.error(
            "Cannot load abnormal detail:",
            error
        );

        detailElement.innerHTML = `
            <div class="empty-box">
                Cannot load abnormal detail
            </div>
        `;
    }
}
/* =====================================================
   LOAD VARIABLES
===================================================== */

async function loadVariables() {
    try {
        const response = await fetch(
            "/web_api/api/history/variables"
        );

        const result = await response.json();

        variableSelect.innerHTML = "";

        if (
            !response.ok ||
            !result.ok ||
            !Array.isArray(result.variables) ||
            result.variables.length === 0
        ) {
            chartStatus.innerText =
                "No variables found. Please save tags first.";

            return;
        }

        result.variables.forEach(
            function (item) {
                const option =
                    document.createElement("option");

                option.value =
                    item.tag_name;

                option.textContent =
                    item.unit
                        ? `${item.tag_name} (${item.unit})`
                        : item.tag_name;

                option.dataset.unit =
                    item.unit || "";

                variableSelect.appendChild(
                    option
                );
            }
        );

        selectedVariable =
            variableSelect.value;

        selectedUnit =
            variableSelect.options[
                variableSelect.selectedIndex
            ].dataset.unit || "";

        await loadHistoryData();

    } catch (error) {
        console.error(
            "Cannot load history variables:",
            error
        );

        chartStatus.innerText =
            "Cannot load history variables";
    }
}


variableSelect.addEventListener(
    "change",
    async function () {
        selectedVariable =
            variableSelect.value;

        selectedUnit =
            variableSelect.options[
                variableSelect.selectedIndex
            ].dataset.unit || "";

        await loadHistoryData();
    }
);


/* =====================================================
   LOAD HISTORY DATA
===================================================== */

async function loadHistoryData() {
    if (!selectedVariable) {
        return;
    }

    chart.style.display = "none";
    chartStatus.style.display = "block";
    chartStatus.innerText =
        "Loading history data...";

    try {
        const url =
            "/web_api/api/history/data" +
            "?tag_name=" +
            encodeURIComponent(
                selectedVariable
            );

        const response =
            await fetch(url);

        const result =
            await response.json();

        if (
            !response.ok ||
            !result.ok
        ) {
            chartStatus.innerText =
                result.message ||
                "Cannot load history data";

            return;
        }

        historyPoints =
            Array.isArray(result.points)
                ? result.points
                : [];

        drawChart();

    } catch (error) {
        console.error(
            "Cannot load history data:",
            error
        );

        chartStatus.innerText =
            "Cannot load history data";
    }
}


/* =====================================================
   DRAW CHART
===================================================== */

function drawChart() {
    chart.innerHTML = "";

    const numericPoints =
        historyPoints
            .map(
                function (point) {
                    return {
                        ...point,
                        value: Number(
                            point.value
                        )
                    };
                }
            )
            .filter(
                function (point) {
                    return (
                        point.value !== null &&
                        !Number.isNaN(
                            point.value
                        )
                    );
                }
            );

    if (numericPoints.length === 0) {
        chart.style.display = "none";
        chartStatus.style.display =
            "block";

        chartStatus.innerText =
            "No numeric data found for " +
            selectedVariable;

        return;
    }

    chartStatus.style.display = "none";
    chart.style.display = "block";

    const width = 1000;
    const height = 460;

    const margin = {
        left: 70,
        right: 30,
        top: 35,
        bottom: 65
    };

    const plotWidth =
        width -
        margin.left -
        margin.right;

    const plotHeight =
        height -
        margin.top -
        margin.bottom;

    let minValue = Math.min(
        ...numericPoints.map(
            function (point) {
                return point.value;
            }
        )
    );

    let maxValue = Math.max(
        ...numericPoints.map(
            function (point) {
                return point.value;
            }
        )
    );

    if (minValue === maxValue) {
        minValue -= 1;
        maxValue += 1;
    }

    const paddingValue =
        (maxValue - minValue) *
        0.12;

    minValue -= paddingValue;
    maxValue += paddingValue;


    function xScale(index) {
        if (numericPoints.length === 1) {
            return (
                margin.left +
                plotWidth / 2
            );
        }

        return (
            margin.left +
            (
                index /
                (
                    numericPoints.length -
                    1
                )
            ) *
            plotWidth
        );
    }


    function yScale(value) {
        return (
            margin.top +
            (
                (
                    maxValue -
                    value
                ) /
                (
                    maxValue -
                    minValue
                )
            ) *
            plotHeight
        );
    }


    drawGrid(
        margin,
        plotWidth,
        plotHeight,
        minValue,
        maxValue
    );

    drawLine(
        numericPoints,
        xScale,
        yScale
    );

    drawPoints(
        numericPoints,
        xScale,
        yScale
    );

    drawXAxisLabels(
        numericPoints,
        xScale,
        height
    );
}


/* =====================================================
   SVG HELPERS
===================================================== */

function createSvgElement(
    tagName
) {
    return document.createElementNS(
        "http://www.w3.org/2000/svg",
        tagName
    );
}


function drawGrid(
    margin,
    plotWidth,
    plotHeight,
    minValue,
    maxValue
) {
    for (
        let index = 0;
        index <= 5;
        index++
    ) {
        const y =
            margin.top +
            (
                index / 5
            ) *
            plotHeight;

        const value =
            maxValue -
            (
                index / 5
            ) *
            (
                maxValue -
                minValue
            );

        const line =
            createSvgElement("line");

        line.setAttribute(
            "x1",
            margin.left
        );

        line.setAttribute(
            "x2",
            margin.left +
            plotWidth
        );

        line.setAttribute(
            "y1",
            y
        );

        line.setAttribute(
            "y2",
            y
        );

        line.setAttribute(
            "class",
            "grid-line"
        );

        chart.appendChild(line);


        const label =
            createSvgElement("text");

        label.setAttribute(
            "x",
            margin.left - 12
        );

        label.setAttribute(
            "y",
            y + 4
        );

        label.setAttribute(
            "text-anchor",
            "end"
        );

        label.setAttribute(
            "class",
            "axis-text"
        );

        label.textContent =
            formatNumber(value);

        chart.appendChild(label);
    }


    const yAxis =
        createSvgElement("line");

    yAxis.setAttribute(
        "x1",
        margin.left
    );

    yAxis.setAttribute(
        "x2",
        margin.left
    );

    yAxis.setAttribute(
        "y1",
        margin.top
    );

    yAxis.setAttribute(
        "y2",
        margin.top +
        plotHeight
    );

    yAxis.setAttribute(
        "class",
        "axis-line"
    );

    chart.appendChild(yAxis);


    const xAxis =
        createSvgElement("line");

    xAxis.setAttribute(
        "x1",
        margin.left
    );

    xAxis.setAttribute(
        "x2",
        margin.left +
        plotWidth
    );

    xAxis.setAttribute(
        "y1",
        margin.top +
        plotHeight
    );

    xAxis.setAttribute(
        "y2",
        margin.top +
        plotHeight
    );

    xAxis.setAttribute(
        "class",
        "axis-line"
    );

    chart.appendChild(xAxis);


    const title =
        createSvgElement("text");

    title.setAttribute(
        "x",
        margin.left
    );

    title.setAttribute(
        "y",
        22
    );

    title.setAttribute(
        "class",
        "axis-text"
    );

    title.textContent =
        selectedVariable +
        (
            selectedUnit
                ? ` (${selectedUnit})`
                : ""
        ) +
        " vs Time";

    chart.appendChild(title);
}


function drawLine(
    points,
    xScale,
    yScale
) {
    const path =
        createSvgElement("path");

    let pathData = "";

    points.forEach(
        function (
            point,
            index
        ) {
            const x =
                xScale(index);

            const y =
                yScale(
                    point.value
                );

            if (index === 0) {
                pathData +=
                    `M ${x} ${y}`;

            } else {
                pathData +=
                    ` L ${x} ${y}`;
            }
        }
    );

    path.setAttribute(
        "d",
        pathData
    );

    path.setAttribute(
        "class",
        "chart-line"
    );

    chart.appendChild(path);
}


function drawPoints(
    points,
    xScale,
    yScale
) {
    points.forEach(
        function (
            point,
            index
        ) {
            const x =
                xScale(index);

            const y =
                yScale(
                    point.value
                );

            const circle =
                createSvgElement(
                    "circle"
                );

            circle.setAttribute(
                "cx",
                x
            );

            circle.setAttribute(
                "cy",
                y
            );

            circle.setAttribute(
                "r",
                6
            );

            circle.setAttribute(
                "class",
                "point"
            );

            circle.setAttribute(
                "fill",
                point.is_normal
                    ? "#2563eb"
                    : "#dc2626"
            );

            circle.addEventListener(
                "click",
                function () {
                    openRunDetail(
                        point.run_id
                    );
                }
            );


            const tooltip =
                createSvgElement(
                    "title"
                );

            tooltip.textContent =
                point.ocr_time +
                " | " +
                selectedVariable +
                " = " +
                point.value +
                (
                    selectedUnit
                        ? ` ${selectedUnit}`
                        : ""
                ) +
                " | Status: " +
                point.status;

            circle.appendChild(
                tooltip
            );

            chart.appendChild(
                circle
            );
        }
    );
}


function drawXAxisLabels(
    points,
    xScale,
    height
) {
    const maxLabels = 8;

    const step = Math.max(
        1,
        Math.ceil(
            points.length /
            maxLabels
        )
    );

    points.forEach(
        function (
            point,
            index
        ) {
            if (
                index % step !== 0 &&
                index !==
                    points.length - 1
            ) {
                return;
            }

            const x =
                xScale(index);

            const label =
                createSvgElement(
                    "text"
                );

            label.setAttribute(
                "x",
                x
            );

            label.setAttribute(
                "y",
                height - 32
            );

            label.setAttribute(
                "text-anchor",
                "middle"
            );

            label.setAttribute(
                "class",
                "axis-text"
            );

            label.textContent =
                point.time_label;

            chart.appendChild(
                label
            );
        }
    );
}


function formatNumber(value) {
    if (Math.abs(value) >= 100) {
        return value.toFixed(0);
    }

    if (Math.abs(value) >= 10) {
        return value.toFixed(1);
    }

    return value.toFixed(3);
}


/* =====================================================
   READ-ONLY RUN DETAIL
===================================================== */

async function openRunDetail(
    runId
) {
    try {
        const response = await fetch(
            "/web_api/api/history/run/" +
            runId
        );

        const result =
            await response.json();

        if (
            !response.ok ||
            !result.ok
        ) {
            alert(
                result.message ||
                "Cannot load OCR detail"
            );

            return;
        }

        const run =
            result.run;

        const values =
            Array.isArray(
                result.values
            )
                ? result.values
                : [];

        document.getElementById(
            "modalTitle"
        ).innerText =
            "OCR Detail - Run #" +
            run.id;

        document.getElementById(
            "modalSubtitle"
        ).innerText =
            run.ocr_time || "-";


        const statusElement =
            document.getElementById(
                "modalStatus"
            );

        statusElement.innerHTML =
            "<p>" +
                "<b>Status:</b> " +
                "<span class='" +
                    (
                        run.is_normal
                            ? "status-normal"
                            : "status-warning"
                    ) +
                "'>" +
                    escapeHtml(
                        run.status ||
                        "UNKNOWN"
                    ) +
                "</span>" +
            "</p>" +
            (
                run.missing_tags
                    ? (
                        "<p>" +
                            "<b>Missing Tags:</b> " +
                            escapeHtml(
                                run.missing_tags
                            ) +
                        "</p>"
                    )
                    : ""
            );


        const modalImage =
            document.getElementById(
                "modalImage"
            );

        const modalNoImage =
            document.getElementById(
                "modalNoImage"
            );

        const imageUrl =
            run.calibrated_image_url ||
            run.raw_image_url ||
            "";

        if (imageUrl) {
            modalImage.src =
                imageUrl +
                "?t=" +
                Date.now();

            modalImage.style.display =
                "block";

            modalNoImage.style.display =
                "none";

        } else {
            modalImage.removeAttribute(
                "src"
            );

            modalImage.style.display =
                "none";

            modalNoImage.style.display =
                "block";
        }


        const tableBody =
            document.getElementById(
                "modalValues"
            );

        tableBody.innerHTML = "";

        if (values.length === 0) {
            const emptyRow =
                document.createElement(
                    "tr"
                );

            emptyRow.innerHTML = `
                <td colspan="3">
                    No OCR values found
                </td>
            `;

            tableBody.appendChild(
                emptyRow
            );

        } else {
            values.forEach(
                function (item) {
                    const row =
                        document.createElement(
                            "tr"
                        );

                    row.innerHTML = `
                        <td>
                            ${escapeHtml(
                                item.tag_name ||
                                "-"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                item.value ||
                                "-"
                            )}
                        </td>

                        <td>
                            ${escapeHtml(
                                item.unit ||
                                "-"
                            )}
                        </td>
                    `;

                    tableBody.appendChild(
                        row
                    );
                }
            );
        }


        document.getElementById(
            "detailModalBg"
        ).style.display =
            "block";

    } catch (error) {
        console.error(
            "Cannot load OCR detail:",
            error
        );

        alert(
            "Cannot load OCR detail"
        );
    }
}


function closeModal() {
    document.getElementById(
        "detailModalBg"
    ).style.display =
        "none";
}


/* =====================================================
   TEXT SAFETY
===================================================== */

function escapeHtml(text) {
    return String(
        text ?? ""
    )
        .replaceAll(
            "&",
            "&amp;"
        )
        .replaceAll(
            "<",
            "&lt;"
        )
        .replaceAll(
            ">",
            "&gt;"
        )
        .replaceAll(
            '"',
            "&quot;"
        )
        .replaceAll(
            "'",
            "&#039;"
        );
}


/* =====================================================
   ALERT DROPDOWN
===================================================== */

alertToggle.addEventListener(
    "click",
    function () {
        const shouldOpen =
            alertList.hidden;

        alertList.hidden =
            !shouldOpen;

        alertToggle.setAttribute(
            "aria-expanded",
            String(shouldOpen)
        );

        alertToggleIcon.innerText =
            shouldOpen
                ? "▲ ซ่อนรายการ"
                : "▼ ดูรายการ";
    }
);


/* =====================================================
   START PAGE
===================================================== */

loadAbnormalHistory();
loadVariables();