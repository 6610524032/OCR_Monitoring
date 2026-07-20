/* =====================================================
   GLOBAL STATE
===================================================== */

const savedRois = window.SAVED_ROIS || [];

let rawPoints = [];
let sortedPoints = [];

let manualBoxes = [];
let drawMode = false;
let isDrawingBox = false;
let startPoint = null;
let currentPoint = null;

const hmiImage = document.getElementById("hmiImage");
const drawCanvas = document.getElementById("drawCanvas");
let drawCtx = null;

const roiImage = document.getElementById("roiImage");
const roiCanvas = document.getElementById("roiCanvas");
let roiCtx = null;


/* =====================================================
   CANVAS HELPERS
===================================================== */

/*
ทำให้ Canvas มีขนาดเท่ากับภาพที่แสดงจริง
และเลื่อนไปทับตำแหน่งของภาพภายใน Container
*/
function setupCanvasForImage(image, canvas) {
    if (!image || !canvas) {
        return null;
    }

    if (
        !image.complete ||
        image.naturalWidth <= 0 ||
        image.naturalHeight <= 0
    ) {
        return null;
    }

    const width = Math.round(image.clientWidth);
    const height = Math.round(image.clientHeight);

    if (width <= 0 || height <= 0) {
        return null;
    }

    canvas.width = width;
    canvas.height = height;

    canvas.style.width = width + "px";
    canvas.style.height = height + "px";

    canvas.style.left = image.offsetLeft + "px";
    canvas.style.top = image.offsetTop + "px";

    return canvas.getContext("2d");
}


function resizeAllCanvases() {
    if (hmiImage && drawCanvas) {
        drawCtx = setupCanvasForImage(
            hmiImage,
            drawCanvas
        );

        drawCalibrationPoints();
    }

    if (roiImage && roiCanvas) {
        roiCtx = setupCanvasForImage(
            roiImage,
            roiCanvas
        );

        drawRoiCanvas();
    }
}


/*
แปลงพิกัด Mouse บนภาพที่แสดง
ให้เป็นพิกัดจริงของไฟล์ภาพ

มีการ Clamp พิกัดไม่ให้ออกนอกขอบภาพ
*/
function getImagePoint(event, image) {
    if (
        !image ||
        image.naturalWidth <= 0 ||
        image.naturalHeight <= 0
    ) {
        return null;
    }

    const rect = image.getBoundingClientRect();

    if (rect.width <= 0 || rect.height <= 0) {
        return null;
    }

    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;

    const displayX = Math.max(
        0,
        Math.min(mouseX, rect.width)
    );

    const displayY = Math.max(
        0,
        Math.min(mouseY, rect.height)
    );

    const scaleX =
        image.naturalWidth /
        rect.width;

    const scaleY =
        image.naturalHeight /
        rect.height;

    const realX = Math.max(
        0,
        Math.min(
            Math.round(displayX * scaleX),
            image.naturalWidth - 1
        )
    );

    const realY = Math.max(
        0,
        Math.min(
            Math.round(displayY * scaleY),
            image.naturalHeight - 1
        )
    );

    return {
        displayX,
        displayY,
        realX,
        realY
    };
}


/*
แปลงพิกัดจริงของภาพ
กลับเป็นพิกัดบน Canvas
*/
function realPointToDisplay(
    realX,
    realY,
    image
) {
    if (
        !image ||
        image.naturalWidth <= 0 ||
        image.naturalHeight <= 0
    ) {
        return {
            displayX: 0,
            displayY: 0
        };
    }

    const scaleX =
        image.clientWidth /
        image.naturalWidth;

    const scaleY =
        image.clientHeight /
        image.naturalHeight;

    return {
        displayX: realX * scaleX,
        displayY: realY * scaleY
    };
}


/* =====================================================
   CALIBRATION
===================================================== */

if (hmiImage) {
    hmiImage.onload = function () {
        drawCtx = setupCanvasForImage(
            hmiImage,
            drawCanvas
        );

        drawCalibrationPoints();
    };

    if (
        hmiImage.complete &&
        hmiImage.naturalWidth > 0
    ) {
        drawCtx = setupCanvasForImage(
            hmiImage,
            drawCanvas
        );

        drawCalibrationPoints();
    }

    hmiImage.addEventListener(
        "click",
        function (event) {
            if (rawPoints.length >= 4) {
                alert("เลือกครบ 4 จุดแล้ว");
                return;
            }

            const point = getImagePoint(
                event,
                hmiImage
            );

            if (!point) {
                return;
            }

            /*
            เก็บพิกัดจริงเป็นหลัก
            ไม่พึ่งพา displayX/displayY เดิม
            เพราะขนาดภาพอาจเปลี่ยนตามหน้าจอ
            */
            rawPoints.push({
                realX: point.realX,
                realY: point.realY
            });

            if (rawPoints.length === 4) {
                sortedPoints = sortCorners(
                    rawPoints
                );
            } else {
                sortedPoints = [...rawPoints];
            }

            updatePointText();
            drawCalibrationPoints();
        }
    );
}


function sortCorners(points) {
    const pts = [...points];

    const sortedByY = [...pts].sort(
        function (a, b) {
            return a.realY - b.realY;
        }
    );

    const top = sortedByY
        .slice(0, 2)
        .sort(function (a, b) {
            return a.realX - b.realX;
        });

    const bottom = sortedByY
        .slice(2, 4)
        .sort(function (a, b) {
            return a.realX - b.realX;
        });

    return [
        top[0],
        top[1],
        bottom[1],
        bottom[0]
    ];
}


function updatePointText() {
    for (let i = 1; i <= 4; i++) {
        const point = sortedPoints[i - 1];

        const element = document.getElementById(
            "point" + i
        );

        if (!element) {
            continue;
        }

        if (point) {
            element.innerText =
                "(" +
                point.realX +
                ", " +
                point.realY +
                ")";
        } else {
            element.innerText = "-";
        }
    }

    const saveBtn =
        document.getElementById("saveBtn");

    if (saveBtn) {
        saveBtn.disabled =
            rawPoints.length !== 4;
    }
}


function drawCalibrationPoints() {
    if (
        !drawCtx ||
        !drawCanvas ||
        !hmiImage ||
        hmiImage.naturalWidth <= 0
    ) {
        return;
    }

    drawCtx.clearRect(
        0,
        0,
        drawCanvas.width,
        drawCanvas.height
    );

    const sourceList =
        rawPoints.length === 4
            ? sortedPoints
            : rawPoints;

    const drawList = sourceList.map(
        function (point) {
            const display =
                realPointToDisplay(
                    point.realX,
                    point.realY,
                    hmiImage
                );

            return {
                realX: point.realX,
                realY: point.realY,
                displayX: display.displayX,
                displayY: display.displayY
            };
        }
    );

    if (drawList.length >= 2) {
        drawCtx.beginPath();
        drawCtx.strokeStyle = "#22c55e";
        drawCtx.lineWidth = 3;

        drawCtx.moveTo(
            drawList[0].displayX,
            drawList[0].displayY
        );

        for (
            let i = 1;
            i < drawList.length;
            i++
        ) {
            drawCtx.lineTo(
                drawList[i].displayX,
                drawList[i].displayY
            );
        }

        if (drawList.length === 4) {
            drawCtx.lineTo(
                drawList[0].displayX,
                drawList[0].displayY
            );
        }

        drawCtx.stroke();
    }

    for (
        let i = 0;
        i < drawList.length;
        i++
    ) {
        const point = drawList[i];

        drawCtx.beginPath();
        drawCtx.fillStyle = "#ef4444";

        drawCtx.arc(
            point.displayX,
            point.displayY,
            6,
            0,
            Math.PI * 2
        );

        drawCtx.fill();

        drawCtx.fillStyle = "#111827";
        drawCtx.font = "18px Arial";

        drawCtx.fillText(
            "P" + (i + 1),
            point.displayX + 10,
            point.displayY - 10
        );
    }
}


const resetBtn =
    document.getElementById("resetBtn");

if (resetBtn) {
    resetBtn.addEventListener(
        "click",
        function () {
            rawPoints = [];
            sortedPoints = [];

            updatePointText();

            if (drawCtx && drawCanvas) {
                drawCtx.clearRect(
                    0,
                    0,
                    drawCanvas.width,
                    drawCanvas.height
                );
            }
        }
    );
}


const saveBtn =
    document.getElementById("saveBtn");

if (saveBtn) {
    saveBtn.addEventListener(
        "click",
        async function () {
            if (sortedPoints.length !== 4) {
                alert(
                    "กรุณาเลือกให้ครบ 4 จุดก่อน"
                );
                return;
            }

            const imagePathElement =
                document.getElementById(
                    "imagePath"
                );

            if (!imagePathElement) {
                alert("ไม่พบชื่อภาพ");
                return;
            }

            const imagePath =
                imagePathElement.innerText.trim();

            try {
                const response = await fetch(
                    "/web_api/api/save_calibration",
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json"
                        },
                        body: JSON.stringify({
                            image_path: imagePath,
                            points: [
                                {
                                    x: sortedPoints[0].realX,
                                    y: sortedPoints[0].realY
                                },
                                {
                                    x: sortedPoints[1].realX,
                                    y: sortedPoints[1].realY
                                },
                                {
                                    x: sortedPoints[2].realX,
                                    y: sortedPoints[2].realY
                                },
                                {
                                    x: sortedPoints[3].realX,
                                    y: sortedPoints[3].realY
                                }
                            ]
                        })
                    }
                );

                const result =
                    await response.json();

                if (!result.ok) {
                    alert(
                        result.message ||
                        "Save Calibration failed"
                    );
                    return;
                }

                const status =
                    document.getElementById(
                        "testStatus"
                    );

                if (status) {
                    status.innerText =
                        "Creating calibration...";
                }

                const testResponse =
                    await fetch(
                        "/web_api/api/test_calibration",
                        {
                            method: "POST"
                        }
                    );

                const testResult =
                    await testResponse.json();

                if (testResult.ok) {
                    location.reload();
                } else {
                    alert(
                        testResult.message ||
                        "Calibration test failed"
                    );
                }
            } catch (error) {
                console.error(error);

                alert(
                    "Cannot save calibration"
                );
            }
        }
    );
}


/* =====================================================
   RESET CONFIGURATION
===================================================== */

const resetAllBtn =
    document.getElementById("resetAllBtn");

if (resetAllBtn) {
    resetAllBtn.addEventListener(
        "click",
        async function () {
            const ok = confirm(
                "ต้องการล้าง Calibration และ User Tags ทั้งหมดใช่ไหม?"
            );

            if (!ok) {
                return;
            }

            try {
                const response = await fetch(
                    "/web_api/api/reset_configuration",
                    {
                        method: "POST"
                    }
                );

                const result =
                    await response.json();

                if (result.ok) {
                    alert(
                        "Reset configuration complete"
                    );

                    location.reload();
                } else {
                    alert(
                        result.message ||
                        "Reset failed"
                    );
                }
            } catch (error) {
                console.error(error);
                alert("Reset failed");
            }
        }
    );
}


/* =====================================================
   ROI DRAWING
===================================================== */

if (roiImage) {
    roiImage.onload = function () {
        roiCtx = setupCanvasForImage(
            roiImage,
            roiCanvas
        );

        drawRoiCanvas();
    };

    if (
        roiImage.complete &&
        roiImage.naturalWidth > 0
    ) {
        roiCtx = setupCanvasForImage(
            roiImage,
            roiCanvas
        );

        drawRoiCanvas();
    }

    roiImage.addEventListener(
        "mousedown",
        function (event) {
            if (!drawMode) {
                return;
            }

            event.preventDefault();

            const point = getImagePoint(
                event,
                roiImage
            );

            if (!point) {
                return;
            }

            isDrawingBox = true;
            startPoint = point;
            currentPoint = point;

            drawRoiCanvas();
        }
    );

    roiImage.addEventListener(
        "mousemove",
        function (event) {
            if (
                !drawMode ||
                !isDrawingBox
            ) {
                return;
            }

            const point = getImagePoint(
                event,
                roiImage
            );

            if (!point) {
                return;
            }

            currentPoint = point;

            drawRoiCanvas();
            drawPreviewBox();
        }
    );

    roiImage.addEventListener(
        "mouseup",
        function (event) {
            if (
                !drawMode ||
                !isDrawingBox
            ) {
                return;
            }

            const point = getImagePoint(
                event,
                roiImage
            );

            if (!point) {
                cancelCurrentBox();
                return;
            }

            currentPoint = point;
            finishBox();
        }
    );

    roiImage.addEventListener(
        "mouseleave",
        function () {
            if (
                !drawMode ||
                !isDrawingBox
            ) {
                return;
            }

            cancelCurrentBox();
        }
    );
}


function cancelCurrentBox() {
    isDrawingBox = false;
    startPoint = null;
    currentPoint = null;

    drawRoiCanvas();
}


const drawRoiBtn =
    document.getElementById("drawRoiBtn");

if (drawRoiBtn) {
    drawRoiBtn.addEventListener(
        "click",
        function () {
            drawMode = !drawMode;

            const modeText =
                document.getElementById(
                    "modeText"
                );

            if (drawMode) {
                drawRoiBtn.classList.add(
                    "active"
                );

                drawRoiBtn.innerText =
                    "Drawing ROI ON";

                if (modeText) {
                    modeText.innerText =
                        "Draw Mode ON";
                }
            } else {
                drawRoiBtn.classList.remove(
                    "active"
                );

                drawRoiBtn.innerText =
                    "Draw ROI";

                if (modeText) {
                    modeText.innerText =
                        "Draw Mode OFF";
                }

                cancelCurrentBox();
            }
        }
    );
}


function drawSavedRois() {
    if (
        !roiCtx ||
        !roiImage ||
        roiImage.naturalWidth <= 0
    ) {
        return;
    }

    const scaleX =
        roiImage.clientWidth /
        roiImage.naturalWidth;

    const scaleY =
        roiImage.clientHeight /
        roiImage.naturalHeight;

    savedRois.forEach(function (roi) {
        if (!roi.id) {
            return;
        }

        const x = roi.x1 * scaleX;
        const y = roi.y1 * scaleY;

        const w =
            (roi.x2 - roi.x1) *
            scaleX;

        const h =
            (roi.y2 - roi.y1) *
            scaleY;

        roiCtx.strokeStyle = "#22c55e";
        roiCtx.lineWidth = 2;

        roiCtx.strokeRect(
            x,
            y,
            w,
            h
        );

        roiCtx.fillStyle = "#22c55e";
        roiCtx.font = "14px Arial";

        roiCtx.fillText(
            roi.display_name || "",
            x + 4,
            Math.max(14, y - 6)
        );
    });
}


function drawRoiCanvas() {
    if (
        !roiCtx ||
        !roiCanvas ||
        !roiImage ||
        roiImage.naturalWidth <= 0
    ) {
        return;
    }

    roiCtx.clearRect(
        0,
        0,
        roiCanvas.width,
        roiCanvas.height
    );

    drawSavedRois();

    const scaleX =
        roiImage.clientWidth /
        roiImage.naturalWidth;

    const scaleY =
        roiImage.clientHeight /
        roiImage.naturalHeight;

    manualBoxes.forEach(
        function (box, index) {
            const x = box.x1 * scaleX;
            const y = box.y1 * scaleY;

            const w =
                (box.x2 - box.x1) *
                scaleX;

            const h =
                (box.y2 - box.y1) *
                scaleY;

            if (box.status === "pending") {
                roiCtx.strokeStyle =
                    "#dc2626";

                roiCtx.fillStyle =
                    "#dc2626";
            } else if (
                box.status === "done"
            ) {
                roiCtx.strokeStyle =
                    "#16a34a";

                roiCtx.fillStyle =
                    "#16a34a";
            } else {
                roiCtx.strokeStyle =
                    "#6b7280";

                roiCtx.fillStyle =
                    "#6b7280";
            }

            roiCtx.lineWidth = 3;

            roiCtx.strokeRect(
                x,
                y,
                w,
                h
            );

            roiCtx.font =
                "16px Arial";

            roiCtx.fillText(
                formatNo(index),
                x + 4,
                Math.max(16, y - 6)
            );
        }
    );
}


function drawPreviewBox() {
    if (
        !roiCtx ||
        !startPoint ||
        !currentPoint
    ) {
        return;
    }

    const x = Math.min(
        startPoint.displayX,
        currentPoint.displayX
    );

    const y = Math.min(
        startPoint.displayY,
        currentPoint.displayY
    );

    const w = Math.abs(
        currentPoint.displayX -
        startPoint.displayX
    );

    const h = Math.abs(
        currentPoint.displayY -
        startPoint.displayY
    );

    roiCtx.strokeStyle = "#7c3aed";
    roiCtx.lineWidth = 3;

    roiCtx.setLineDash([8, 5]);

    roiCtx.strokeRect(
        x,
        y,
        w,
        h
    );

    roiCtx.setLineDash([]);
}


function formatNo(index) {
    return (
        "No." +
        String(index + 1).padStart(
            2,
            "0"
        )
    );
}


function finishBox() {
    isDrawingBox = false;

    if (!startPoint || !currentPoint) {
        return;
    }

    const x1 = Math.min(
        startPoint.realX,
        currentPoint.realX
    );

    const y1 = Math.min(
        startPoint.realY,
        currentPoint.realY
    );

    const x2 = Math.max(
        startPoint.realX,
        currentPoint.realX
    );

    const y2 = Math.max(
        startPoint.realY,
        currentPoint.realY
    );

    const w = x2 - x1;
    const h = y2 - y1;

    startPoint = null;
    currentPoint = null;

    /*
    ป้องกัน ROI เล็กเกินไป
    ซึ่งมักทำให้ OCR อ่านผิด
    */
    if (w < 5 || h < 5) {
        drawRoiCanvas();
        return;
    }

    const box = {
        id:
            Date.now() +
            "_" +
            Math.random(),

        x1: Math.round(x1),
        y1: Math.round(y1),
        x2: Math.round(x2),
        y2: Math.round(y2),

        value: "Reading...",
        tag_name: "",
        unit: "",
        status: "pending"
    };

    manualBoxes.push(box);

    drawRoiCanvas();
    updateRoiTable();
    readBoxWithOCR(box);
}


/* =====================================================
   OCR QUEUE
===================================================== */

async function readBoxWithOCR(box) {
    try {
        const result =
            await readManualRoiWithOCR(
                box.x1,
                box.y1,
                box.x2,
                box.y2
            );

        if (result.ok) {
            box.value =
                result.text ||
                "UNKNOWN";

            box.status = "done";
        } else {
            box.value = "OCR ERROR";
            box.status = "error";
        }
    } catch (error) {
        console.error(error);

        box.value = "OCR ERROR";
        box.status = "error";
    }

    drawRoiCanvas();
    updateRoiTable();
}


async function readManualRoiWithOCR(
    x1,
    y1,
    x2,
    y2
) {
    if (!roiImage) {
        return {
            ok: false,
            message: "ROI image missing"
        };
    }

    const imageName =
        roiImage.dataset.currentImage;

    const response = await fetch(
        "/web_api/api/read_manual_roi",
        {
            method: "POST",
            headers: {
                "Content-Type":
                    "application/json"
            },
            body: JSON.stringify({
                image: imageName,
                x1: x1,
                y1: y1,
                x2: x2,
                y2: y2
            })
        }
    );

    return await response.json();
}


/* =====================================================
   ROI TABLE
===================================================== */

function updateRoiTable() {
    const tbody =
        document.querySelector(
            "#roiTable tbody"
        );

    const roiCount =
        document.getElementById(
            "roiCount"
        );

    if (!tbody) {
        return;
    }

    tbody.innerHTML = "";

    manualBoxes.forEach(
        function (box, index) {
            const row =
                document.createElement(
                    "tr"
                );

            let statusClass =
                "badge-pending";

            let statusText =
                "Reading";

            if (box.status === "done") {
                statusClass =
                    "badge-done";

                statusText =
                    "Ready";
            } else if (
                box.status === "error"
            ) {
                statusClass =
                    "badge-error";

                statusText =
                    "Error";
            }

            row.innerHTML = `
                <td>
                    <b>${formatNo(index)}</b><br>

                    <span class="badge ${statusClass}">
                        ${statusText}
                    </span>
                </td>

                <td>
                    ${escapeHtml(box.value)}
                </td>

                <td>
                    <input
                        type="text"
                        value="${escapeHtml(box.tag_name)}"
                        data-box-id="${box.id}"
                        data-field="tag_name"
                        placeholder="เช่น Current"
                    >
                </td>

                <td>
                    <input
                        type="text"
                        value="${escapeHtml(box.unit)}"
                        data-box-id="${box.id}"
                        data-field="unit"
                        placeholder="เช่น A"
                    >
                </td>

                <td>
                    <button
                        type="button"
                        class="delete-btn"
                        title="Delete"
                        onclick="deleteBox('${box.id}')"
                    >
                        ✕
                    </button>
                </td>
            `;

            tbody.appendChild(row);
        }
    );

    if (roiCount) {
        roiCount.innerText =
            manualBoxes.length;
    }

    bindTableInputs();
}


function bindTableInputs() {
    const inputs =
        document.querySelectorAll(
            "#roiTable input[data-box-id]"
        );

    inputs.forEach(function (input) {
        input.addEventListener(
            "input",
            function () {
                const boxId =
                    input.dataset.boxId;

                const field =
                    input.dataset.field;

                const box =
                    manualBoxes.find(
                        function (item) {
                            return (
                                item.id ===
                                boxId
                            );
                        }
                    );

                if (box) {
                    box[field] =
                        input.value;
                }
            }
        );
    });
}


function deleteBox(boxId) {
    manualBoxes =
        manualBoxes.filter(
            function (box) {
                return (
                    box.id !== boxId
                );
            }
        );

    drawRoiCanvas();
    updateRoiTable();
}


function escapeHtml(text) {
    return String(text || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


/* =====================================================
   SAVE TAGS
===================================================== */

const saveAllBtn =
    document.getElementById(
        "saveAllBtn"
    );

if (saveAllBtn) {
    saveAllBtn.addEventListener(
        "click",
        async function () {
            if (manualBoxes.length === 0) {
                alert(
                    "กรุณาวาด ROI ก่อน"
                );
                return;
            }

            const notReady =
                manualBoxes.some(
                    function (box) {
                        return (
                            box.status ===
                            "pending"
                        );
                    }
                );

            if (notReady) {
                alert(
                    "ยังมี ROI ที่กำลังอ่าน OCR อยู่ กรุณารอสักครู่"
                );
                return;
            }

            const tagsToSave = [];

            for (
                const box of manualBoxes
            ) {
                if (
                    !box.tag_name.trim()
                ) {
                    alert(
                        "กรุณาใส่ Tag Name ให้ครบทุกช่อง"
                    );
                    return;
                }

                tagsToSave.push({
                    tag_name:
                        box.tag_name.trim(),

                    unit:
                        box.unit.trim(),

                    x1: box.x1,
                    y1: box.y1,
                    x2: box.x2,
                    y2: box.y2
                });
            }

            try {
                const response =
                    await fetch(
                        "/web_api/api/save_user_tags",
                        {
                            method: "POST",
                            headers: {
                                "Content-Type":
                                    "application/json"
                            },
                            body: JSON.stringify({
                                tags: tagsToSave
                            })
                        }
                    );

                const result =
                    await response.json();

                if (result.ok) {
                    alert(
                        "Save All Tags สำเร็จ"
                    );

                    location.reload();
                } else {
                    alert(
                        result.message ||
                        "Save failed"
                    );
                }
            } catch (error) {
                console.error(error);
                alert("Save failed");
            }
        }
    );
}


/* =====================================================
   AUTO REFRESH IMAGES
===================================================== */

async function checkLatestRawImage() {
    if (!hmiImage) {
        return;
    }

    if (rawPoints.length > 0) {
        return;
    }

    try {
        const response = await fetch(
            "/web_api/api/latest_raw_image"
        );

        const result =
            await response.json();

        if (
            !result.ok ||
            !result.image
        ) {
            return;
        }

        if (
            hmiImage.dataset.currentImage ===
            result.image
        ) {
            return;
        }

        hmiImage.dataset.currentImage =
            result.image;

        hmiImage.onload = function () {
            drawCtx =
                setupCanvasForImage(
                    hmiImage,
                    drawCanvas
                );

            drawCalibrationPoints();
        };

        hmiImage.src =
            result.image_url +
            "?t=" +
            new Date().getTime();
    } catch (error) {
        console.error(
            "Latest raw image error:",
            error
        );
    }
}


async function checkLatestCalibratedImage() {
    if (!roiImage) {
        return;
    }

    if (manualBoxes.length > 0) {
        return;
    }

    try {
        const response = await fetch(
            "/web_api/api/latest_calibrated_image"
        );

        const result =
            await response.json();

        if (
            !result.ok ||
            !result.image
        ) {
            return;
        }

        if (
            roiImage.dataset.currentImage ===
            result.image
        ) {
            return;
        }

        roiImage.dataset.currentImage =
            result.image;

        roiImage.onload = function () {
            roiCtx =
                setupCanvasForImage(
                    roiImage,
                    roiCanvas
                );

            drawRoiCanvas();
        };

        const cacheKey =
            "?t=" +
            new Date().getTime();

        roiImage.src =
            result.image_url +
            cacheKey;

        const preview =
            document.getElementById(
                "calibratedPreview"
            );

        if (preview) {
            preview.src =
                result.image_url +
                cacheKey;
        }
    } catch (error) {
        console.error(
            "Latest calibrated image error:",
            error
        );
    }
}


/* =====================================================
   RESIZE HANDLING
===================================================== */

let resizeTimer = null;

window.addEventListener(
    "resize",
    function () {
        clearTimeout(resizeTimer);

        resizeTimer = setTimeout(
            function () {
                resizeAllCanvases();
            },
            100
        );
    }
);


if (
    roiImage &&
    typeof ResizeObserver !== "undefined"
) {
    const roiResizeObserver =
        new ResizeObserver(
            function () {
                roiCtx =
                    setupCanvasForImage(
                        roiImage,
                        roiCanvas
                    );

                drawRoiCanvas();
            }
        );

    roiResizeObserver.observe(
        roiImage
    );
}


if (
    hmiImage &&
    typeof ResizeObserver !== "undefined"
) {
    const calibrationResizeObserver =
        new ResizeObserver(
            function () {
                drawCtx =
                    setupCanvasForImage(
                        hmiImage,
                        drawCanvas
                    );

                drawCalibrationPoints();
            }
        );

    calibrationResizeObserver.observe(
        hmiImage
    );
}


/* =====================================================
   PERIODIC REFRESH
===================================================== */

setInterval(
    checkLatestRawImage,
    10000
);

setInterval(
    checkLatestCalibratedImage,
    10000
);

/* =====================================================
   CAMERA SETTINGS
===================================================== */

const saveCameraBtn =
    document.getElementById(
        "saveCameraBtn"
    );

if (saveCameraBtn) {

    saveCameraBtn.addEventListener(
        "click",
        async function () {

            const payload = {

                camera_name:
                    document.getElementById(
                        "cameraName"
                    ).value.trim(),

                camera_ip:
                    document.getElementById(
                        "cameraIp"
                    ).value.trim(),

                camera_port:
                    parseInt(
                        document.getElementById(
                            "cameraPort"
                        ).value,
                        10
                    ) || 554,

                camera_username:
                    document.getElementById(
                        "cameraUsername"
                    ).value.trim(),

                camera_password:
                    document.getElementById(
                        "cameraPassword"
                    ).value,

                rtsp_path:
                    document.getElementById(
                        "cameraRtspPath"
                    ).value.trim()
            };

            try {

                const response =
                    await fetch(
                        "/web_api/api/camera/config",
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify(
                                payload
                            )
                        }
                    );

                const result =
                    await response.json();

                if (result.ok) {

                    alert(
                        "Camera configuration saved."
                    );

                } else {

                    alert(
                        result.message ||
                        "Save failed"
                    );

                }

            } catch (error) {

                console.error(error);

                alert(
                    "Cannot save camera configuration."
                );

            }

        }
    );

}


/* =====================================================
   LOAD CAMERA CONFIGURATION
===================================================== */

async function loadCameraConfiguration() {

    try {

        const response =
            await fetch(
                "/web_api/api/camera/config"
            );

        const result =
            await response.json();

        if (!result.ok) {
            return;
        }

        const camera = result.camera;

        document.getElementById(
            "cameraName"
        ).value = camera.camera_name || "";

        document.getElementById(
            "cameraIp"
        ).value = camera.camera_ip || "";

        document.getElementById(
            "cameraPort"
        ).value = camera.camera_port || 554;

        document.getElementById(
            "cameraUsername"
        ).value = camera.camera_username || "";

        document.getElementById(
            "cameraPassword"
        ).value = camera.camera_password || "";

        document.getElementById(
            "cameraRtspPath"
        ).value = camera.rtsp_path || "";

    } catch (error) {

        console.error(
            "Cannot load camera configuration:",
            error
        );

    }

}

loadCameraConfiguration();