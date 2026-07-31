/* =====================================================
   GLOBAL STATE
===================================================== */

const savedRois =
    Array.isArray(window.SAVED_ROIS)
        ? window.SAVED_ROIS
        : [];

let rawPoints = [];
let sortedPoints = [];

let manualBoxes =
    savedRois.map(
        function (roi) {
            return {
                id:
                    roi.id ??
                    createClientBoxId(),

                x1: Number(
                    roi.x1 ??
                    roi.roi_x1 ??
                    0
                ),

                y1: Number(
                    roi.y1 ??
                    roi.roi_y1 ??
                    0
                ),

                x2: Number(
                    roi.x2 ??
                    roi.roi_x2 ??
                    0
                ),

                y2: Number(
                    roi.y2 ??
                    roi.roi_y2 ??
                    0
                ),

                value:
                    roi.value ??
                    "Saved",

                tag_name:
                    roi.tag_name ??
                    roi.display_name ??
                    "",

                unit:
                    roi.unit ??
                    "",

                sensor_api_key:
                    roi.sensor_api_key ??
                    "",

                status: "done"
            };
        }
    )
    .filter(
        function (box) {
            return (
                [
                    box.x1,
                    box.y1,
                    box.x2,
                    box.y2
                ].every(
                    Number.isFinite
                ) &&
                box.x1 >= 0 &&
                box.y1 >= 0 &&
                box.x2 > box.x1 &&
                box.y2 > box.y1
            );
        }
    );

let tagsDirty = false;
let tagsSaving = false;
let drawMode = false;
let isDrawingBox = false;

let isOcrModelReady = false;
let ocrStatusInterval = null;

const OCR_STATUS_CHECK_INTERVAL_MS = 2000;

let startPoint = null;
let currentPoint = null;

const hmiImage = document.getElementById("hmiImage");
const drawCanvas = document.getElementById("drawCanvas");
let drawCtx = null;

const roiImage = document.getElementById("roiImage");
const roiCanvas = document.getElementById("roiCanvas");
let roiCtx = null;


/* =====================================================
   REQUEST HELPERS
===================================================== */

const DEFAULT_REQUEST_TIMEOUT_MS = 30000;
const LONG_REQUEST_TIMEOUT_MS = 70000;
const POLL_REQUEST_TIMEOUT_MS = 10000;
const IMAGE_LOAD_TIMEOUT_MS = 15000;

const MANUAL_OCR_RETRY_DELAY_MS = 2000;
const MANUAL_OCR_RETRY_LIMIT = 15;

let ocrStatusRequestInFlight = false;
let rawImageRequestInFlight = false;
let calibratedImageRequestInFlight = false;
let resetConfigurationInFlight = false;
let cameraRequestInFlight = false;


class SettingsRequestError extends Error {
    constructor(
        message,
        status = 0,
        payload = null
    ) {
        super(message);

        this.name = "SettingsRequestError";
        this.status = status;
        this.payload = payload;
    }
}


function getPageCsrfToken() {
    const metaToken =
        document.querySelector(
            'meta[name="csrf-token"]'
        );

    if (
        metaToken &&
        typeof metaToken.content === "string" &&
        metaToken.content
    ) {
        return metaToken.content;
    }

    const inputToken =
        document.querySelector(
            'input[name="csrf_token"]'
        );

    if (
        inputToken &&
        typeof inputToken.value === "string" &&
        inputToken.value
    ) {
        return inputToken.value;
    }

    if (
        typeof window.CSRF_TOKEN === "string" &&
        window.CSRF_TOKEN
    ) {
        return window.CSRF_TOKEN;
    }

    return "";
}


function redirectToLogin() {
    const nextPath =
        window.location.pathname +
        window.location.search;

    window.location.assign(
        "/login?next=" +
        encodeURIComponent(nextPath)
    );
}


async function requestJson(
    url,
    options = {}
) {
    const controller =
        new AbortController();

    const timeoutMs =
        Number.isFinite(options.timeoutMs)
            ? Math.max(
                1000,
                options.timeoutMs
            )
            : DEFAULT_REQUEST_TIMEOUT_MS;

    const timeoutId = window.setTimeout(
        function () {
            controller.abort();
        },
        timeoutMs
    );

    const method =
        String(
            options.method || "GET"
        ).toUpperCase();

    const headers = {
        Accept: "application/json",
        ...(options.headers || {})
    };

    const fetchOptions = {
        method,
        headers,
        cache:
            options.cache ||
            "no-store",
        credentials: "same-origin",
        signal: controller.signal
    };

    if (
        Object.prototype.hasOwnProperty.call(
            options,
            "json"
        )
    ) {
        headers["Content-Type"] =
            "application/json";

        fetchOptions.body = JSON.stringify(
            options.json
        );
    } else if (
        Object.prototype.hasOwnProperty.call(
            options,
            "body"
        )
    ) {
        fetchOptions.body =
            options.body;
    }

    if (
        !["GET", "HEAD", "OPTIONS"].includes(
            method
        )
    ) {
        const csrfToken =
            getPageCsrfToken();

        if (csrfToken) {
            headers["X-CSRF-Token"] =
                csrfToken;
        }
    }

    try {
        const response = await fetch(
            url,
            fetchOptions
        );

        const responseText =
            await response.text();

        let result = {};

        if (responseText.trim()) {
            try {
                result = JSON.parse(
                    responseText
                );
            } catch (_error) {
                throw new SettingsRequestError(
                    "Server returned an invalid JSON response.",
                    response.status,
                    null
                );
            }
        }

        if (
            !result ||
            typeof result !== "object" ||
            Array.isArray(result)
        ) {
            throw new SettingsRequestError(
                "Server response must be a JSON object.",
                response.status,
                null
            );
        }

        if (
            response.status === 401 &&
            result.login_required
        ) {
            redirectToLogin();

            throw new SettingsRequestError(
                "Login session has expired.",
                401,
                result
            );
        }

        if (!response.ok) {
            throw new SettingsRequestError(
                result.message ||
                (
                    "Request failed with HTTP " +
                    response.status
                ),
                response.status,
                result
            );
        }

        return result;

    } catch (error) {
        if (
            error &&
            error.name === "AbortError"
        ) {
            throw new SettingsRequestError(
                "Request timed out. Please try again.",
                0,
                null
            );
        }

        throw error;

    } finally {
        window.clearTimeout(
            timeoutId
        );
    }
}


function wait(milliseconds) {
    return new Promise(function (resolve) {
        window.setTimeout(
            resolve,
            milliseconds
        );
    });
}


function appendCacheBuster(url) {
    const separator =
        String(url).includes("?")
            ? "&"
            : "?";

    return (
        String(url) +
        separator +
        "t=" +
        Date.now()
    );
}


function loadImageElement(
    image,
    imageUrl,
    errorMessage
) {
    return new Promise(function (
        resolve,
        reject
    ) {
        if (!image) {
            reject(
                new Error(
                    errorMessage ||
                    "Image element is missing."
                )
            );

            return;
        }

        let settled = false;

        const cleanup = function () {
            image.removeEventListener(
                "load",
                handleLoad
            );

            image.removeEventListener(
                "error",
                handleError
            );

            window.clearTimeout(
                timeoutId
            );
        };

        const handleLoad = function () {
            if (settled) {
                return;
            }

            settled = true;
            cleanup();
            resolve(true);
        };

        const handleError = function () {
            if (settled) {
                return;
            }

            settled = true;
            cleanup();

            reject(
                new Error(
                    errorMessage ||
                    "Cannot load image."
                )
            );
        };

        const timeoutId = window.setTimeout(
            handleError,
            IMAGE_LOAD_TIMEOUT_MS
        );

        image.addEventListener(
            "load",
            handleLoad,
            {
                once: true
            }
        );

        image.addEventListener(
            "error",
            handleError,
            {
                once: true
            }
        );

        image.src =
            appendCacheBuster(
                imageUrl
            );
    });
}


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

    /*
    Canvas ใช้สำหรับวาดภาพทับเท่านั้น
    ให้ Pointer Event ผ่านไปยังรูปด้านล่างเสมอ
    */
    canvas.style.pointerEvents = "none";

    image.style.userSelect = "none";
    image.draggable = false;

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
    if (
        !Array.isArray(points) ||
        points.length !== 4
    ) {
        return Array.isArray(points)
            ? [...points]
            : [];
    }

    const center = points.reduce(
        function (accumulator, point) {
            accumulator.x +=
                point.realX;

            accumulator.y +=
                point.realY;

            return accumulator;
        },
        {
            x: 0,
            y: 0
        }
    );

    center.x /= points.length;
    center.y /= points.length;

    let ordered = [...points].sort(
        function (a, b) {
            const angleA =
                Math.atan2(
                    a.realY - center.y,
                    a.realX - center.x
                );

            const angleB =
                Math.atan2(
                    b.realY - center.y,
                    b.realX - center.x
                );

            return angleA - angleB;
        }
    );

    let topLeftIndex = 0;
    let smallestSum = Infinity;

    ordered.forEach(
        function (point, index) {
            const coordinateSum =
                point.realX +
                point.realY;

            if (
                coordinateSum <
                smallestSum
            ) {
                smallestSum =
                    coordinateSum;

                topLeftIndex = index;
            }
        }
    );

    ordered = [
        ...ordered.slice(
            topLeftIndex
        ),
        ...ordered.slice(
            0,
            topLeftIndex
        )
    ];

    const signedArea =
        ordered.reduce(
            function (
                area,
                point,
                index
            ) {
                const next =
                    ordered[
                        (
                            index + 1
                        ) %
                        ordered.length
                    ];

                return (
                    area +
                    point.realX *
                        next.realY -
                    next.realX *
                        point.realY
                );
            },
            0
        );

    /*
    พิกัดภาพมีแกน Y ลงด้านล่าง
    ลำดับ TL → TR → BR → BL
    จะมี signed area เป็นบวก
    */
    if (signedArea < 0) {
        ordered = [
            ordered[0],
            ...ordered
                .slice(1)
                .reverse()
        ];
    }

    return ordered;
}


function validateCalibrationPoints(
    points,
    image
) {
    if (
        !Array.isArray(points) ||
        points.length !== 4
    ) {
        return (
            "กรุณาเลือกจุด Calibration " +
            "ให้ครบ 4 จุด"
        );
    }

    if (
        !image ||
        image.naturalWidth <= 0 ||
        image.naturalHeight <= 0
    ) {
        return (
            "ไม่สามารถตรวจสอบขนาดภาพ " +
            "Calibration ได้"
        );
    }

    for (const point of points) {
        if (
            !Number.isFinite(
                point.realX
            ) ||
            !Number.isFinite(
                point.realY
            ) ||
            point.realX < 0 ||
            point.realY < 0 ||
            point.realX >=
                image.naturalWidth ||
            point.realY >=
                image.naturalHeight
        ) {
            return (
                "พบพิกัด Calibration " +
                "ที่อยู่นอกขอบภาพ"
            );
        }
    }

    for (
        let firstIndex = 0;
        firstIndex < points.length;
        firstIndex++
    ) {
        for (
            let secondIndex =
                firstIndex + 1;
            secondIndex < points.length;
            secondIndex++
        ) {
            const deltaX =
                points[firstIndex].realX -
                points[secondIndex].realX;

            const deltaY =
                points[firstIndex].realY -
                points[secondIndex].realY;

            if (
                Math.hypot(
                    deltaX,
                    deltaY
                ) < 5
            ) {
                return (
                    "จุด Calibration " +
                    "อยู่ใกล้กันเกินไป"
                );
            }
        }
    }

    const doubledArea =
        points.reduce(
            function (
                area,
                point,
                index
            ) {
                const next =
                    points[
                        (
                            index + 1
                        ) %
                        points.length
                    ];

                return (
                    area +
                    point.realX *
                        next.realY -
                    next.realX *
                        point.realY
                );
            },
            0
        );

    if (
        Math.abs(
            doubledArea
        ) < 200
    ) {
        return (
            "พื้นที่ Calibration เล็กเกินไป " +
            "หรือจุดเกือบอยู่ในแนวเดียวกัน"
        );
    }

    return "";
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

/* =====================================================
   CLIENT BOX ID
===================================================== */

function createClientBoxId() {
    if (
        typeof crypto !== "undefined" &&
        typeof crypto.randomUUID ===
            "function"
    ) {
        return (
            "client_" +
            crypto.randomUUID()
        );
    }

    return (
        "client_" +
        Date.now() +
        "_" +
        Math.random()
            .toString(36)
            .slice(2)
    );
}


/* =====================================================
   RESET CALIBRATION POINTS
===================================================== */

const resetBtn =
    document.getElementById(
        "resetBtn"
    );


if (resetBtn) {
    resetBtn.addEventListener(
        "click",
        function () {
            rawPoints = [];
            sortedPoints = [];

            updatePointText();

            if (
                drawCtx &&
                drawCanvas
            ) {
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


/* =====================================================
   SAVE CALIBRATION
===================================================== */

const saveBtn =
    document.getElementById(
        "saveBtn"
    );


if (saveBtn) {
    saveBtn.addEventListener(
        "click",
        async function () {
            const validationMessage =
                validateCalibrationPoints(
                    sortedPoints,
                    hmiImage
                );

            if (validationMessage) {
                alert(
                    validationMessage
                );

                return;
            }

            if (!hmiImage) {
                alert(
                    "ไม่พบภาพสำหรับ Calibration"
                );

                return;
            }

            const imageName =
                String(
                    hmiImage.dataset
                        .currentImage ||
                    ""
                ).trim();

            if (!imageName) {
                alert(
                    "ไม่พบชื่อภาพสำหรับ Calibration"
                );

                return;
            }

            const originalText =
                saveBtn.innerText;

            saveBtn.disabled =
                true;

            saveBtn.innerText =
                "Saving...";

            const payload = {
                image_path: imageName,

                points:
                    sortedPoints.map(
                        function (point) {
                            return {
                                x:
                                    point.realX,

                                y:
                                    point.realY
                            };
                        }
                    )
            };

            try {
                const result =
                    await requestJson(
                        "/web_api/api/save_calibration",
                        {
                            method: "POST",

                            json: payload,

                            timeoutMs:
                                LONG_REQUEST_TIMEOUT_MS
                        }
                    );

                if (!result.ok) {
                    throw new Error(
                        result.message ||
                        "Save calibration failed."
                    );
                }

                saveBtn.innerText =
                    "Creating preview...";

                const previewResult =
                    await requestJson(
                        "/web_api/api/test_calibration",
                        {
                            method: "POST",

                            json: {},

                            timeoutMs:
                                LONG_REQUEST_TIMEOUT_MS
                        }
                    );

                if (!previewResult.ok) {
                    throw new Error(
                        previewResult.message ||
                        "Cannot create calibration preview."
                    );
                }

                saveBtn.innerText =
                    "Loading preview...";

                const refreshed =
                    await checkLatestCalibratedImage(
                        true
                    );

                if (!refreshed) {
                    throw new Error(
                        (
                            "Calibration was saved, " +
                            "but the calibrated image " +
                            "could not be loaded."
                        )
                    );
                }

                rawPoints = [];
                sortedPoints = [];

                updatePointText();
                drawCalibrationPoints();

                alert(
                    "Save Calibration สำเร็จ"
                );

            } catch (error) {
                console.error(
                    "Save calibration error:",
                    error
                );

                alert(
                    error.message ||
                    "Save calibration failed."
                );

            } finally {
                saveBtn.innerText =
                    originalText;

                saveBtn.disabled =
                    rawPoints.length !== 4;
            }
        }
    );
}


/* =====================================================
   CAPTURE IMAGE
===================================================== */

const captureImageBtn =
    document.getElementById(
        "captureImageBtn"
    );


async function loadRawImageImmediately(
    imageUrl,
    imageName
) {
    if (!hmiImage) {
        throw new Error(
            (
                "Calibration image " +
                "element is missing."
            )
        );
    }

    const normalizedImageUrl =
        String(
            imageUrl || ""
        ).trim();

    const normalizedImageName =
        String(
            imageName || ""
        ).trim();

    if (!normalizedImageUrl) {
        throw new Error(
            "Captured image URL is missing."
        );
    }

    if (!normalizedImageName) {
        throw new Error(
            "Captured image name is missing."
        );
    }

    await loadImageElement(
        hmiImage,
        normalizedImageUrl,
        "Cannot load captured image."
    );

    hmiImage.dataset.currentImage =
        normalizedImageName;

    const rawImageContainer =
        document.getElementById(
            "rawImageContainer"
        );

    const imagePathRow =
        document.getElementById(
            "imagePathRow"
        );

    const imagePathElement =
        document.getElementById(
            "imagePath"
        );

    if (rawImageContainer) {
        rawImageContainer.style.display =
            "";
    }

    if (imagePathRow) {
        imagePathRow.style.display =
            "";
    }

    if (imagePathElement) {
        imagePathElement.innerText =
            normalizedImageName;
    }

    hmiImage.style.display =
        "";

    drawCtx =
        setupCanvasForImage(
            hmiImage,
            drawCanvas
        );

    drawCalibrationPoints();

    return true;
}


async function refreshCapturedImage(
    expectedImage
) {
    const normalizedExpectedImage =
        String(
            expectedImage || ""
        ).trim();

    if (!normalizedExpectedImage) {
        return false;
    }

    const maximumAttempts = 20;
    let lastError = null;

    for (
        let attempt = 0;
        attempt < maximumAttempts;
        attempt++
    ) {
        try {
            const result =
                await requestJson(
                    (
                        "/web_api/api/latest_raw_image" +
                        "?t=" +
                        Date.now()
                    ),
                    {
                        timeoutMs:
                            POLL_REQUEST_TIMEOUT_MS
                    }
                );

            if (
                result.ok &&
                result.image &&
                result.image_url &&
                String(
                    result.image
                ) ===
                    normalizedExpectedImage
            ) {
                await loadRawImageImmediately(
                    result.image_url,
                    result.image
                );

                return true;
            }

        } catch (error) {
            lastError = error;
        }

        await wait(
            250
        );
    }

    if (lastError) {
        console.error(
            (
                "Cannot refresh the " +
                "captured image:"
            ),
            lastError
        );
    }

    return false;
}


if (captureImageBtn) {
    captureImageBtn.addEventListener(
        "click",
        async function () {
            const originalText =
                captureImageBtn.innerText;

            captureImageBtn.disabled =
                true;

            captureImageBtn.innerText =
                "Capturing...";

            try {
                const result =
                    await requestJson(
                        "/web_api/api/capture_image",
                        {
                            method: "POST",

                            json: {},

                            timeoutMs:
                                LONG_REQUEST_TIMEOUT_MS
                        }
                    );

                if (!result.ok) {
                    throw new Error(
                        result.message ||
                        "Capture failed."
                    );
                }

                if (
                    !result.image ||
                    !result.image_url
                ) {
                    throw new Error(
                        (
                            "Capture response does not " +
                            "contain image information."
                        )
                    );
                }

                /*
                ภาพใหม่ต้องไม่ใช้จุด
                Calibration ของภาพเดิม
                */
                rawPoints = [];
                sortedPoints = [];

                updatePointText();

                if (
                    drawCtx &&
                    drawCanvas
                ) {
                    drawCtx.clearRect(
                        0,
                        0,
                        drawCanvas.width,
                        drawCanvas.height
                    );
                }

                captureImageBtn.innerText =
                    "Loading image...";

                try {
                    await loadRawImageImmediately(
                        result.image_url,
                        result.image
                    );

                } catch (imageError) {
                    const refreshed =
                        await refreshCapturedImage(
                            result.image
                        );

                    if (!refreshed) {
                        throw imageError;
                    }
                }

                alert(
                    "Image captured successfully."
                );

            } catch (error) {
                console.error(
                    "Capture image error:",
                    error
                );

                alert(
                    error.message ||
                    (
                        "Cannot capture or " +
                        "load image."
                    )
                );

            } finally {
                captureImageBtn.disabled =
                    false;

                captureImageBtn.innerText =
                    originalText;
            }
        }
    );
}


/* =====================================================
   RESET CONFIGURATION
===================================================== */

const resetAllBtn =
    document.getElementById(
        "resetAllBtn"
    );


if (resetAllBtn) {
    resetAllBtn.addEventListener(
        "click",
        async function () {
            if (
                resetConfigurationInFlight
            ) {
                return;
            }

            const confirmed =
                window.confirm(
                    (
                        "ต้องการล้างค่ากล้อง " +
                        "ปิด Calibration และปิด " +
                        "User Tags ทั้งหมดใช่ไหม?\n\n" +
                        "ประวัติ OCR จะยังคงอยู่"
                    )
                );

            if (!confirmed) {
                return;
            }

            const originalText =
                resetAllBtn.innerText;

            resetConfigurationInFlight =
                true;

            resetAllBtn.disabled =
                true;

            resetAllBtn.innerText =
                "Resetting...";

            try {
                const result =
                    await requestJson(
                        "/web_api/api/reset_configuration",
                        {
                            method: "POST",

                            json: {},

                            timeoutMs:
                                LONG_REQUEST_TIMEOUT_MS
                        }
                    );

                if (!result.ok) {
                    throw new Error(
                        result.message ||
                        "Reset failed."
                    );
                }

                tagsDirty = false;
                tagsSaving = false;

                alert(
                    result.message ||
                    "Reset configuration complete."
                );

                window.location.reload();

            } catch (error) {
                console.error(
                    "Reset configuration error:",
                    error
                );

                alert(
                    error.message ||
                    "Reset failed."
                );

            } finally {
                resetConfigurationInFlight =
                    false;

                resetAllBtn.disabled =
                    false;

                resetAllBtn.innerText =
                    originalText;
            }
        }
    );
}


/* =====================================================
   OCR MODEL STATUS
===================================================== */

function disableRoiDrawing() {
    isOcrModelReady = false;
    drawMode = false;
    isDrawingBox = false;
    startPoint = null;
    currentPoint = null;

    const drawButton =
        document.getElementById(
            "drawRoiBtn"
        );

    const modeText =
        document.getElementById(
            "modeText"
        );

    if (drawButton) {
        drawButton.disabled =
            true;

        drawButton.classList.remove(
            "active"
        );

        drawButton.innerText =
            "Draw ROI";

        drawButton.title =
            "OCR model is preparing...";
    }

    if (modeText) {
        modeText.innerText =
            "Draw Mode OFF";
    }

    drawRoiCanvas();
}


function enableRoiDrawing() {
    isOcrModelReady = true;

    const drawButton =
        document.getElementById(
            "drawRoiBtn"
        );

    if (drawButton) {
        drawButton.disabled =
            false;

        drawButton.title =
            "";
    }
}


function updateOcrStatusCard(
    status,
    message
) {
    const card =
        document.getElementById(
            "ocrModelStatusCard"
        );

    const spinner =
        document.getElementById(
            "ocrStatusSpinner"
        );

    const readyIcon =
        document.getElementById(
            "ocrStatusReadyIcon"
        );

    const errorIcon =
        document.getElementById(
            "ocrStatusErrorIcon"
        );

    const title =
        document.getElementById(
            "ocrStatusTitle"
        );

    const description =
        document.getElementById(
            "ocrStatusDescription"
        );

    const statusMessage =
        document.getElementById(
            "ocrStatusMessage"
        );

    if (!card) {
        return;
    }

    const normalizedStatus =
        String(
            status || ""
        )
            .trim()
            .toUpperCase();

    const normalizedMessage =
        String(
            message || ""
        ).trim();

    card.classList.remove(
        "ocr-status-loading",
        "ocr-status-ready",
        "ocr-status-error"
    );

    if (spinner) {
        spinner.style.display =
            "none";
    }

    if (readyIcon) {
        readyIcon.style.display =
            "none";
    }

    if (errorIcon) {
        errorIcon.style.display =
            "none";
    }

    if (
        normalizedStatus ===
        "READY"
    ) {
        card.classList.add(
            "ocr-status-ready"
        );

        if (readyIcon) {
            readyIcon.style.display =
                "flex";
        }

        if (title) {
            title.innerText =
                "OCR Model Ready";
        }

        if (description) {
            description.innerText =
                (
                    "ระบบพร้อมใช้งานแล้ว " +
                    "สามารถเริ่มวาด Manual ROI ได้"
                );
        }

        if (statusMessage) {
            statusMessage.innerText =
                normalizedMessage ||
                "OCR model is ready.";
        }

        enableRoiDrawing();

        return;
    }

    if (
        normalizedStatus ===
        "ERROR"
    ) {
        card.classList.add(
            "ocr-status-error"
        );

        if (errorIcon) {
            errorIcon.style.display =
                "flex";
        }

        if (title) {
            title.innerText =
                "OCR Model Error";
        }

        if (description) {
            description.innerText =
                (
                    "ไม่สามารถเตรียมโมเดล OCR ได้ " +
                    "กรุณาตรวจสอบข้อความผิดพลาด"
                );
        }

        if (statusMessage) {
            statusMessage.innerText =
                normalizedMessage ||
                "Cannot prepare OCR model.";
        }

        disableRoiDrawing();

        return;
    }

    card.classList.add(
        "ocr-status-loading"
    );

    if (spinner) {
        spinner.style.display =
            "block";
    }

    if (title) {
        if (
            normalizedStatus ===
            "DOWNLOADING"
        ) {
            title.innerText =
                "Downloading OCR Model...";

        } else if (
            normalizedStatus ===
            "LOADING"
        ) {
            title.innerText =
                "Loading OCR Model...";

        } else {
            title.innerText =
                "Preparing OCR Model...";
        }
    }

    if (description) {
        description.innerText =
            (
                "กรุณารอจนกว่าโมเดล OCR " +
                "จะพร้อมใช้งาน ก่อนเริ่มวาด Manual ROI"
            );
    }

    if (statusMessage) {
        statusMessage.innerText =
            normalizedMessage ||
            "Checking OCR model status...";
    }

    disableRoiDrawing();
}


async function checkOcrModelStatus() {
    if (ocrStatusRequestInFlight) {
        return;
    }

    ocrStatusRequestInFlight =
        true;

    try {
        const result =
            await requestJson(
                (
                    "/web_api/api/ocr/status" +
                    "?t=" +
                    Date.now()
                ),
                {
                    timeoutMs:
                        POLL_REQUEST_TIMEOUT_MS
                }
            );

        const status =
            String(
                result.status || ""
            )
                .trim()
                .toUpperCase();

        updateOcrStatusCard(
            status,
            result.message
        );

        if (
            status === "READY" &&
            ocrStatusInterval
        ) {
            window.clearInterval(
                ocrStatusInterval
            );

            ocrStatusInterval =
                null;
        }

    } catch (error) {
        console.error(
            "OCR status error:",
            error
        );

        updateOcrStatusCard(
            "ERROR",
            (
                error.message ||
                "Cannot connect to OCR status service."
            )
        );

    } finally {
        ocrStatusRequestInFlight =
            false;
    }
}


function stopOcrStatusMonitoring() {
    if (ocrStatusInterval) {
        window.clearInterval(
            ocrStatusInterval
        );

        ocrStatusInterval =
            null;
    }
}


function startOcrStatusMonitoring() {
    stopOcrStatusMonitoring();

    disableRoiDrawing();

    checkOcrModelStatus();

    ocrStatusInterval =
        window.setInterval(
            function () {
                checkOcrModelStatus();
            },
            OCR_STATUS_CHECK_INTERVAL_MS
        );
}


/* =====================================================
   ROI DRAWING
===================================================== */

function configureRoiImageEvents() {
    if (!roiImage) {
        return;
    }

    roiImage.draggable =
        false;

    roiImage.style.userSelect =
        "none";

    roiImage.style.touchAction =
        "none";

    roiImage.addEventListener(
        "dragstart",
        function (event) {
            event.preventDefault();
        }
    );

    roiImage.addEventListener(
        "load",
        function () {
            roiCtx =
                setupCanvasForImage(
                    roiImage,
                    roiCanvas
                );

            drawRoiCanvas();
        }
    );

    if (
        roiImage.complete &&
        roiImage.naturalWidth > 0
    ) {
        roiCtx =
            setupCanvasForImage(
                roiImage,
                roiCanvas
            );

        drawRoiCanvas();
    }

    roiImage.addEventListener(
        "pointerdown",
        handleRoiPointerDown
    );

    roiImage.addEventListener(
        "pointermove",
        handleRoiPointerMove
    );

    roiImage.addEventListener(
        "pointerup",
        handleRoiPointerUp
    );

    roiImage.addEventListener(
        "pointercancel",
        handleRoiPointerCancel
    );

    roiImage.addEventListener(
        "lostpointercapture",
        handleRoiPointerCaptureLost
    );
}


function handleRoiPointerDown(
    event
) {
    if (
        !isOcrModelReady ||
        !drawMode ||
        isDrawingBox
    ) {
        return;
    }

    if (
        typeof event.button ===
            "number" &&
        event.button !== 0
    ) {
        return;
    }

    const point =
        getImagePoint(
            event,
            roiImage
        );

    if (!point) {
        return;
    }

    event.preventDefault();

    try {
        roiImage.setPointerCapture(
            event.pointerId
        );

    } catch (_error) {
        /*
        บาง Browser อาจไม่รองรับ
        Pointer Capture เต็มรูปแบบ
        */
    }

    isDrawingBox =
        true;

    startPoint =
        point;

    currentPoint =
        point;

    drawRoiCanvas();
    drawPreviewBox();
}


function handleRoiPointerMove(
    event
) {
    if (
        !drawMode ||
        !isDrawingBox
    ) {
        return;
    }

    const point =
        getImagePoint(
            event,
            roiImage
        );

    if (!point) {
        return;
    }

    event.preventDefault();

    currentPoint =
        point;

    drawRoiCanvas();
    drawPreviewBox();
}


function handleRoiPointerUp(
    event
) {
    if (
        !drawMode ||
        !isDrawingBox
    ) {
        return;
    }

    const point =
        getImagePoint(
            event,
            roiImage
        );

    if (!point) {
        cancelCurrentBox();
        return;
    }

    event.preventDefault();

    currentPoint =
        point;

    try {
        roiImage.releasePointerCapture(
            event.pointerId
        );

    } catch (_error) {
        /*
        ไม่มี Pointer Capture
        ให้ปล่อยผ่านได้
        */
    }

    finishBox();
}


function handleRoiPointerCancel() {
    if (!isDrawingBox) {
        return;
    }

    cancelCurrentBox();
}


function handleRoiPointerCaptureLost() {
    if (!isDrawingBox) {
        return;
    }

    /*
    หาก Pointer Capture หายก่อน Pointer Up
    ให้ยกเลิกกล่องชั่วคราว ป้องกัน ROI ค้าง
    */
    cancelCurrentBox();
}


function cancelCurrentBox() {
    isDrawingBox =
        false;

    startPoint =
        null;

    currentPoint =
        null;

    drawRoiCanvas();
}


const drawRoiBtn =
    document.getElementById(
        "drawRoiBtn"
    );


if (drawRoiBtn) {
    drawRoiBtn.disabled =
        true;

    drawRoiBtn.addEventListener(
        "click",
        function () {
            if (!isOcrModelReady) {
                alert(
                    (
                        "กรุณารอจนกว่าโมเดล OCR " +
                        "จะพร้อมใช้งาน"
                    )
                );

                return;
            }

            drawMode =
                !drawMode;

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


function drawRoiCanvas() {
    if (
        !roiCtx ||
        !roiCanvas ||
        !roiImage ||
        roiImage.naturalWidth <= 0 ||
        roiImage.naturalHeight <= 0
    ) {
        return;
    }

    roiCtx.clearRect(
        0,
        0,
        roiCanvas.width,
        roiCanvas.height
    );

    const scaleX =
        roiImage.clientWidth /
        roiImage.naturalWidth;

    const scaleY =
        roiImage.clientHeight /
        roiImage.naturalHeight;

    manualBoxes.forEach(
        function (
            box,
            index
        ) {
            const coordinates = [
                box.x1,
                box.y1,
                box.x2,
                box.y2
            ].map(Number);

            if (
                !coordinates.every(
                    Number.isFinite
                )
            ) {
                return;
            }

            const x =
                coordinates[0] *
                scaleX;

            const y =
                coordinates[1] *
                scaleY;

            const width =
                (
                    coordinates[2] -
                    coordinates[0]
                ) *
                scaleX;

            const height =
                (
                    coordinates[3] -
                    coordinates[1]
                ) *
                scaleY;

            if (
                width <= 0 ||
                height <= 0
            ) {
                return;
            }

            if (
                box.status ===
                    "pending" ||
                box.status ===
                    "waiting"
            ) {
                roiCtx.strokeStyle =
                    "#dc2626";

                roiCtx.fillStyle =
                    "#dc2626";

            } else if (
                box.status ===
                "done"
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

            roiCtx.lineWidth =
                3;

            roiCtx.strokeRect(
                x,
                y,
                width,
                height
            );

            roiCtx.font =
                "16px Arial";

            roiCtx.fillText(
                formatNo(index),
                x + 4,
                Math.max(
                    16,
                    y - 6
                )
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

    const x =
        Math.min(
            startPoint.displayX,
            currentPoint.displayX
        );

    const y =
        Math.min(
            startPoint.displayY,
            currentPoint.displayY
        );

    const width =
        Math.abs(
            currentPoint.displayX -
            startPoint.displayX
        );

    const height =
        Math.abs(
            currentPoint.displayY -
            startPoint.displayY
        );

    roiCtx.save();

    roiCtx.strokeStyle =
        "#7c3aed";

    roiCtx.lineWidth =
        3;

    roiCtx.setLineDash([
        8,
        5
    ]);

    roiCtx.strokeRect(
        x,
        y,
        width,
        height
    );

    roiCtx.restore();
}


function formatNo(index) {
    return (
        "No." +
        String(
            index + 1
        ).padStart(
            2,
            "0"
        )
    );
}


function finishBox() {
    isDrawingBox =
        false;

    if (
        !startPoint ||
        !currentPoint
    ) {
        startPoint =
            null;

        currentPoint =
            null;

        drawRoiCanvas();

        return;
    }

    const x1 =
        Math.min(
            startPoint.realX,
            currentPoint.realX
        );

    const y1 =
        Math.min(
            startPoint.realY,
            currentPoint.realY
        );

    const x2 =
        Math.max(
            startPoint.realX,
            currentPoint.realX
        );

    const y2 =
        Math.max(
            startPoint.realY,
            currentPoint.realY
        );

    const width =
        x2 - x1;

    const height =
        y2 - y1;

    startPoint =
        null;

    currentPoint =
        null;

    /*
    ป้องกัน ROI ที่เล็กเกินไป
    เพราะมักทำให้ OCR อ่านผิด
    */
    if (
        width < 5 ||
        height < 5
    ) {
        drawRoiCanvas();

        alert(
            (
                "ROI มีขนาดเล็กเกินไป " +
                "กรุณาวาดใหม่"
            )
        );

        return;
    }

    if (
        !roiImage ||
        roiImage.naturalWidth <= 0 ||
        roiImage.naturalHeight <= 0
    ) {
        drawRoiCanvas();

        return;
    }

    const normalizedX1 =
        Math.max(
            0,
            Math.min(
                Math.round(x1),
                roiImage.naturalWidth - 1
            )
        );

    const normalizedY1 =
        Math.max(
            0,
            Math.min(
                Math.round(y1),
                roiImage.naturalHeight - 1
            )
        );

    const normalizedX2 =
        Math.max(
            normalizedX1 + 1,
            Math.min(
                Math.round(x2),
                roiImage.naturalWidth
            )
        );

    const normalizedY2 =
        Math.max(
            normalizedY1 + 1,
            Math.min(
                Math.round(y2),
                roiImage.naturalHeight
            )
        );

    const box = {
        id:
            createClientBoxId(),

        x1:
            normalizedX1,

        y1:
            normalizedY1,

        x2:
            normalizedX2,

        y2:
            normalizedY2,

        value:
            "Reading...",

        tag_name:
            "",

        unit:
            "",

        sensor_api_key:
            "",

        status:
            "pending"
    };

    manualBoxes.push(
        box
    );

    markTagsDirty();

    drawRoiCanvas();
    updateRoiTable();

    readBoxWithOCR(
        box
    );
}


/* =====================================================
   OCR QUEUE
===================================================== */

async function readBoxWithOCR(box) {
    if (
        !box ||
        box.ocrInFlight
    ) {
        return;
    }

    box.ocrInFlight = true;

    let shouldRetry = false;

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
                result.text ??
                result.value ??
                result.raw_text ??
                "UNKNOWN";

            box.status =
                "done";

            box.ocrAttempts =
                0;

        } else if (
            String(
                result.status || ""
            )
                .trim()
                .toLowerCase() ===
                "loading"
        ) {
            const attempts =
                Number(
                    box.ocrAttempts || 0
                );

            box.value =
                result.message ||
                "Preparing OCR Model...";

            if (
                attempts <
                MANUAL_OCR_RETRY_LIMIT
            ) {
                box.status =
                    "waiting";

                box.ocrAttempts =
                    attempts + 1;

                shouldRetry =
                    true;

            } else {
                box.status =
                    "error";

                box.value =
                    (
                        "OCR model did not become " +
                        "ready in time."
                    );
            }

        } else {
            box.value =
                result.message ||
                "OCR ERROR";

            box.status =
                "error";
        }

    } catch (error) {
        console.error(
            "Manual OCR error:",
            error
        );

        box.value =
            error.message ||
            "Cannot connect to OCR service";

        box.status =
            "error";

    } finally {
        box.ocrInFlight =
            false;

        drawRoiCanvas();
        updateRoiTable();
    }

    if (shouldRetry) {
        window.setTimeout(
            function () {
                const stillExists =
                    manualBoxes.some(
                        function (item) {
                            return (
                                String(
                                    item.id
                                ) ===
                                String(
                                    box.id
                                )
                            );
                        }
                    );

                if (
                    stillExists &&
                    box.status ===
                        "waiting"
                ) {
                    readBoxWithOCR(
                        box
                    );
                }
            },
            MANUAL_OCR_RETRY_DELAY_MS
        );
    }
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

            message:
                (
                    "ROI image element " +
                    "is missing."
                )
        };
    }

    const imageName =
        String(
            roiImage.dataset
                .currentImage ||
            ""
        ).trim();

    if (!imageName) {
        return {
            ok: false,

            message:
                (
                    "Calibrated image name " +
                    "is missing."
                )
        };
    }

    try {
        return await requestJson(
            "/web_api/api/read_manual_roi",
            {
                method:
                    "POST",

                json: {
                    image:
                        imageName,

                    x1:
                        x1,

                    y1:
                        y1,

                    x2:
                        x2,

                    y2:
                        y2
                },

                timeoutMs:
                    LONG_REQUEST_TIMEOUT_MS
            }
        );

    } catch (error) {
        if (
            error instanceof
                SettingsRequestError &&
            error.payload
        ) {
            return {
                ...error.payload,

                ok:
                    false,

                message:
                    (
                        error.payload
                            .message ||
                        error.message ||
                        (
                            "Manual OCR " +
                            "request failed."
                        )
                    )
            };
        }

        throw error;
    }
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

    tbody.innerHTML =
        "";

    manualBoxes.forEach(
        function (
            box,
            index
        ) {
            const row =
                document.createElement(
                    "tr"
                );

            const safeBoxId =
                escapeHtml(
                    String(
                        box.id
                    )
                );

            let statusClass =
                "badge-pending";

            let statusText =
                "Reading";

            if (
                box.status ===
                "done"
            ) {
                statusClass =
                    "badge-done";

                statusText =
                    "Ready";

            } else if (
                box.status ===
                "waiting"
            ) {
                statusClass =
                    "badge-pending";

                statusText =
                    "Preparing";

            } else if (
                box.status ===
                "error"
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
                        data-box-id="${safeBoxId}"
                        data-field="tag_name"
                        maxlength="150"
                        placeholder="เช่น Current"
                    >
                </td>

                <td>
                    <input
                        type="text"
                        value="${escapeHtml(box.unit)}"
                        data-box-id="${safeBoxId}"
                        data-field="unit"
                        maxlength="100"
                        placeholder="เช่น A"
                    >
                </td>

                <td>
                    <input
                        type="password"
                        value="${escapeHtml(box.sensor_api_key)}"
                        data-box-id="${safeBoxId}"
                        data-field="sensor_api_key"
                        maxlength="4096"
                        placeholder="API Key"
                        autocomplete="off"
                    >
                </td>

                <td>
                    <button
                        type="button"
                        class="delete-btn"
                        title="Delete"
                        data-delete-box-id="${safeBoxId}"
                    >
                        ✕
                    </button>
                </td>
            `;

            tbody.appendChild(
                row
            );
        }
    );

    if (roiCount) {
        roiCount.innerText =
            manualBoxes.length;
    }

    bindTableInputs();
    bindDeleteButtons();
}


function bindTableInputs() {
    const inputs =
        document.querySelectorAll(
            "#roiTable input[data-box-id]"
        );

    inputs.forEach(
        function (input) {
            input.addEventListener(
                "input",
                function () {
                    const boxId =
                        input.dataset
                            .boxId;

                    const field =
                        input.dataset
                            .field;

                    if (
                        ![
                            "tag_name",
                            "unit",
                            "sensor_api_key"
                        ].includes(
                            field
                        )
                    ) {
                        return;
                    }

                    const box =
                        manualBoxes.find(
                            function (item) {
                                return (
                                    String(
                                        item.id
                                    ) ===
                                    String(
                                        boxId
                                    )
                                );
                            }
                        );

                    if (!box) {
                        return;
                    }

                    box[field] =
                        input.value;

                    markTagsDirty();

                    drawRoiCanvas();
                }
            );
        }
    );
}


function bindDeleteButtons() {
    const buttons =
        document.querySelectorAll(
            (
                "#roiTable button" +
                "[data-delete-box-id]"
            )
        );

    buttons.forEach(
        function (button) {
            button.addEventListener(
                "click",
                function () {
                    deleteBox(
                        button.dataset
                            .deleteBoxId
                    );
                }
            );
        }
    );
}


function deleteBox(boxId) {
    const previousCount =
        manualBoxes.length;

    manualBoxes =
        manualBoxes.filter(
            function (box) {
                return (
                    String(
                        box.id
                    ) !==
                    String(
                        boxId
                    )
                );
            }
        );

    if (
        manualBoxes.length ===
        previousCount
    ) {
        return;
    }

    markTagsDirty();

    drawRoiCanvas();
    updateRoiTable();
}


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
   SAVE TAGS
===================================================== */

const saveAllBtn =
    document.getElementById(
        "saveAllBtn"
    );


function updateSaveAllButton() {
    if (!saveAllBtn) {
        return;
    }

    if (tagsSaving) {
        saveAllBtn.disabled =
            true;

        saveAllBtn.innerText =
            "Saving...";

        saveAllBtn.classList.remove(
            "save-dirty"
        );

        return;
    }

    if (tagsDirty) {
        saveAllBtn.disabled =
            false;

        saveAllBtn.innerText =
            "Save Changes";

        saveAllBtn.classList.add(
            "save-dirty"
        );

        return;
    }

    saveAllBtn.disabled =
        true;

    saveAllBtn.innerText =
        "Saved";

    saveAllBtn.classList.remove(
        "save-dirty"
    );
}


function markTagsDirty() {
    tagsDirty =
        true;

    updateSaveAllButton();
}


function markTagsSaved() {
    tagsDirty =
        false;

    updateSaveAllButton();
}


function createSavedBox(
    tag,
    previousBoxes,
    index
) {
    const tagName =
        String(
            tag.tag_name ??
            tag.display_name ??
            ""
        ).trim();

    const x1 =
        Number(
            tag.x1 ??
            tag.roi_x1 ??
            0
        );

    const y1 =
        Number(
            tag.y1 ??
            tag.roi_y1 ??
            0
        );

    const x2 =
        Number(
            tag.x2 ??
            tag.roi_x2 ??
            0
        );

    const y2 =
        Number(
            tag.y2 ??
            tag.roi_y2 ??
            0
        );

    const matchingBox =
        previousBoxes.find(
            function (box) {
                return (
                    String(
                        box.tag_name ??
                        ""
                    ).trim() ===
                        tagName &&

                    Number(
                        box.x1
                    ) === x1 &&

                    Number(
                        box.y1
                    ) === y1 &&

                    Number(
                        box.x2
                    ) === x2 &&

                    Number(
                        box.y2
                    ) === y2
                );
            }
        ) ||
        previousBoxes[index] ||
        null;

    return {
        id:
            tag.id ??
            matchingBox?.id ??
            createClientBoxId(),

        x1:
            x1,

        y1:
            y1,

        x2:
            x2,

        y2:
            y2,

        value:
            matchingBox?.value ??
            "Saved",

        tag_name:
            tagName,

        unit:
            String(
                tag.unit ??
                ""
            ),

        sensor_api_key:
            String(
                tag.sensor_api_key ??
                ""
            ),

        status:
            "done",

        ocrAttempts:
            0,

        ocrInFlight:
            false
    };
}


function validateTagBoxesForSave() {
    const tagsToSave =
        [];

    const seenTagNames =
        new Set();

    const notReady =
        manualBoxes.some(
            function (box) {
                return (
                    box.status ===
                        "pending" ||

                    box.status ===
                        "waiting" ||

                    box.ocrInFlight ===
                        true
                );
            }
        );

    if (notReady) {
        return {
            ok:
                false,

            message:
                (
                    "ยังมี ROI ที่กำลังอ่าน OCR " +
                    "กรุณารอสักครู่"
                ),

            tags:
                []
        };
    }

    for (
        const box of manualBoxes
    ) {
        const tagName =
            String(
                box.tag_name ??
                ""
            ).trim();

        if (!tagName) {
            return {
                ok:
                    false,

                message:
                    (
                        "กรุณาใส่ Tag Name " +
                        "ให้ครบทุกช่อง"
                    ),

                tags:
                    []
            };
        }

        if (
            tagName.length >
            150
        ) {
            return {
                ok:
                    false,

                message:
                    (
                        "Tag Name ต้องไม่เกิน " +
                        "150 ตัวอักษร"
                    ),

                tags:
                    []
            };
        }

        if (
            tagName.includes(
                "\u0000"
            )
        ) {
            return {
                ok:
                    false,

                message:
                    (
                        "Tag Name มีอักขระ " +
                        "ที่ไม่ถูกต้อง"
                    ),

                tags:
                    []
            };
        }

        const normalizedTagName =
            tagName.toLocaleLowerCase();

        if (
            seenTagNames.has(
                normalizedTagName
            )
        ) {
            return {
                ok:
                    false,

                message:
                    (
                        "พบ Tag Name ซ้ำ: " +
                        tagName
                    ),

                tags:
                    []
            };
        }

        seenTagNames.add(
            normalizedTagName
        );

        const x1 =
            Number(
                box.x1
            );

        const y1 =
            Number(
                box.y1
            );

        const x2 =
            Number(
                box.x2
            );

        const y2 =
            Number(
                box.y2
            );

        if (
            ![
                x1,
                y1,
                x2,
                y2
            ].every(
                Number.isFinite
            ) ||
            x1 < 0 ||
            y1 < 0 ||
            x2 <= x1 ||
            y2 <= y1
        ) {
            return {
                ok:
                    false,

                message:
                    (
                        "พิกัด ROI ของ " +
                        tagName +
                        " ไม่ถูกต้อง"
                    ),

                tags:
                    []
            };
        }

        if (
            roiImage &&
            roiImage.naturalWidth > 0 &&
            roiImage.naturalHeight > 0
        ) {
            if (
                x1 >=
                    roiImage.naturalWidth ||

                y1 >=
                    roiImage.naturalHeight ||

                x2 >
                    roiImage.naturalWidth ||

                y2 >
                    roiImage.naturalHeight
            ) {
                return {
                    ok:
                        false,

                    message:
                        (
                            "พิกัด ROI ของ " +
                            tagName +
                            " อยู่นอกขอบภาพ"
                        ),

                    tags:
                        []
                };
            }
        }

        const unit =
            String(
                box.unit ??
                ""
            ).trim();

        const sensorApiKey =
            String(
                box.sensor_api_key ??
                ""
            ).trim();

        if (
            unit.length >
            100
        ) {
            return {
                ok:
                    false,

                message:
                    (
                        "Unit ของ " +
                        tagName +
                        " ยาวเกินไป"
                    ),

                tags:
                    []
            };
        }

        if (
            unit.includes(
                "\u0000"
            )
        ) {
            return {
                ok:
                    false,

                message:
                    (
                        "Unit ของ " +
                        tagName +
                        " มีอักขระที่ไม่ถูกต้อง"
                    ),

                tags:
                    []
            };
        }

        if (
            sensorApiKey.length >
            4096
        ) {
            return {
                ok:
                    false,

                message:
                    (
                        "Sensor API Key ของ " +
                        tagName +
                        " ยาวเกินไป"
                    ),

                tags:
                    []
            };
        }

        if (
            sensorApiKey.includes(
                "\u0000"
            )
        ) {
            return {
                ok:
                    false,

                message:
                    (
                        "Sensor API Key ของ " +
                        tagName +
                        " มีอักขระที่ไม่ถูกต้อง"
                    ),

                tags:
                    []
            };
        }

        const payload = {
            tag_name:
                tagName,

            unit:
                unit,

            sensor_api_key:
                sensorApiKey,

            x1:
                Math.round(
                    x1
                ),

            y1:
                Math.round(
                    y1
                ),

            x2:
                Math.round(
                    x2
                ),

            y2:
                Math.round(
                    y2
                )
        };

        const databaseId =
            Number(
                box.id
            );

        if (
            Number.isInteger(
                databaseId
            ) &&
            databaseId > 0
        ) {
            payload.id =
                databaseId;
        }

        tagsToSave.push(
            payload
        );
    }

    return {
        ok:
            true,

        message:
            "",

        tags:
            tagsToSave
    };
}


if (saveAllBtn) {
    saveAllBtn.addEventListener(
        "click",
        async function () {
            if (
                !tagsDirty ||
                tagsSaving
            ) {
                return;
            }

            const validation =
                validateTagBoxesForSave();

            if (!validation.ok) {
                alert(
                    validation.message
                );

                return;
            }

            tagsSaving =
                true;

            updateSaveAllButton();

            try {
                const result =
                    await requestJson(
                        "/web_api/api/save_user_tags",
                        {
                            method:
                                "POST",

                            json: {
                                tags:
                                    validation.tags
                            },

                            timeoutMs:
                                LONG_REQUEST_TIMEOUT_MS
                        }
                    );

                if (!result.ok) {
                    throw new Error(
                        result.message ||
                        "Save failed."
                    );
                }

                if (
                    !Array.isArray(
                        result.tags
                    )
                ) {
                    throw new Error(
                        (
                            "Saved tags were not " +
                            "returned by the server."
                        )
                    );
                }

                const previousBoxes =
                    [
                        ...manualBoxes
                    ];

                manualBoxes =
                    result.tags.map(
                        function (
                            tag,
                            index
                        ) {
                            return createSavedBox(
                                tag,
                                previousBoxes,
                                index
                            );
                        }
                    );

                markTagsSaved();

                drawRoiCanvas();
                updateRoiTable();

                alert(
                    "Save Tags สำเร็จ"
                );

            } catch (error) {
                console.error(
                    "Save tags error:",
                    error
                );

                alert(
                    error.message ||
                    "Save failed."
                );

            } finally {
                tagsSaving =
                    false;

                updateSaveAllButton();
            }
        }
    );
}


/* =====================================================
   AUTO REFRESH IMAGES
===================================================== */

async function checkLatestRawImage() {
    if (
        !hmiImage ||
        rawPoints.length > 0 ||
        rawImageRequestInFlight ||
        (
            captureImageBtn &&
            captureImageBtn.disabled
        )
    ) {
        return false;
    }

    rawImageRequestInFlight =
        true;

    try {
        const result =
            await requestJson(
                (
                    "/web_api/api/latest_raw_image" +
                    "?t=" +
                    Date.now()
                ),
                {
                    timeoutMs:
                        POLL_REQUEST_TIMEOUT_MS
                }
            );

        if (
            !result.ok ||
            !result.image ||
            !result.image_url
        ) {
            return false;
        }

        if (
            hmiImage.dataset
                .currentImage ===
            result.image
        ) {
            return true;
        }

        await loadRawImageImmediately(
            result.image_url,
            result.image
        );

        const imagePathElement =
            document.getElementById(
                "imagePath"
            );

        if (imagePathElement) {
            imagePathElement.innerText =
                result.image;
        }

        return true;

    } catch (error) {
        console.error(
            "Latest raw image error:",
            error
        );

        return false;

    } finally {
        rawImageRequestInFlight =
            false;
    }
}


async function checkLatestCalibratedImage(
    forceRefresh = false
) {
    if (
        calibratedImageRequestInFlight
    ) {
        if (!forceRefresh) {
            return false;
        }

        /*
        หากมีการโหลดภาพอยู่แล้วจาก Polling
        ให้รอจนคำขอเดิมจบก่อน

        รอได้สูงสุดประมาณ 12 วินาที
        */
        for (
            let attempt = 0;
            attempt < 120 &&
                calibratedImageRequestInFlight;
            attempt++
        ) {
            await wait(
                100
            );
        }

        if (
            calibratedImageRequestInFlight
        ) {
            return false;
        }
    }

    /*
    ห้ามเปลี่ยนภาพ Manual ROI อัตโนมัติ
    ระหว่างกำลังวาดหรือมีข้อมูลยังไม่บันทึก

    forceRefresh=true ใช้หลัง Save Calibration
    จึงอนุญาตให้อัปเดตภาพทันที
    */
    if (
        !forceRefresh &&
        (
            drawMode ||
            isDrawingBox ||
            tagsSaving ||
            tagsDirty
        )
    ) {
        return true;
    }

    const preview =
        document.getElementById(
            "calibratedPreview"
        );

    const roiSetupImage =
        document.getElementById(
            "roiImage"
        );

    const placeholder =
        document.getElementById(
            "calibratedPlaceholder"
        );

    const resultContainer =
        document.getElementById(
            "calibratedResultContainer"
        );

    const status =
        document.getElementById(
            "testStatus"
        );

    calibratedImageRequestInFlight =
        true;

    try {
        const result =
            await requestJson(
                (
                    "/web_api/api/latest_calibrated_image" +
                    "?t=" +
                    Date.now()
                ),
                {
                    timeoutMs:
                        POLL_REQUEST_TIMEOUT_MS
                }
            );

        if (
            !result.ok ||
            !result.image ||
            !result.image_url
        ) {
            return false;
        }

        const previewNeedsUpdate =
            Boolean(
                preview &&
                (
                    forceRefresh ||
                    preview.dataset
                        .currentImage !==
                        result.image
                )
            );

        const roiNeedsUpdate =
            Boolean(
                roiSetupImage &&
                (
                    forceRefresh ||
                    roiSetupImage.dataset
                        .currentImage !==
                        result.image
                )
            );

        if (
            !previewNeedsUpdate &&
            !roiNeedsUpdate
        ) {
            return true;
        }

        /*
        อัปเดตภาพส่วน Calibration Result
        */
        if (previewNeedsUpdate) {
            await loadImageElement(
                preview,
                result.image_url,
                (
                    "Cannot load Calibration " +
                    "Result image."
                )
            );

            preview.dataset.currentImage =
                result.image;

            preview.style.display =
                "";

            if (placeholder) {
                placeholder.style.display =
                    "none";
            }

            if (resultContainer) {
                resultContainer.style.display =
                    "";
            }

            if (status) {
                status.innerText =
                    "✅ Calibration Ready";

                status.classList.remove(
                    "calibration-not-ready"
                );

                status.classList.add(
                    "calibration-ready"
                );
            }
        }

        /*
        อัปเดตภาพส่วน Manual ROI Setup
        */
        if (roiNeedsUpdate) {
            const roiSetupContent =
                document.getElementById(
                    "roiSetupContent"
                );

            const roiNotReadyMessage =
                document.getElementById(
                    "roiNotReadyMessage"
                );

            const drawRoiButton =
                document.getElementById(
                    "drawRoiBtn"
                );

            await loadImageElement(
                roiSetupImage,
                result.image_url,
                (
                    "Cannot load Manual " +
                    "ROI image."
                )
            );

            /*
            เปลี่ยน currentImage หลังรูป
            โหลดสำเร็จแล้วเท่านั้น
            */
            roiSetupImage.dataset
                .currentImage =
                result.image;

            roiSetupImage.style.display =
                "";

            if (roiSetupContent) {
                roiSetupContent.style.display =
                    "";
            }

            if (roiNotReadyMessage) {
                roiNotReadyMessage.style.display =
                    "none";
            }

            if (drawRoiButton) {
                drawRoiButton.style.display =
                    "";
            }

            roiCtx =
                setupCanvasForImage(
                    roiSetupImage,
                    roiCanvas
                );

            drawRoiCanvas();
        }

        return true;

    } catch (error) {
        console.error(
            "Latest calibrated image error:",
            error
        );

        return false;

    } finally {
        calibratedImageRequestInFlight =
            false;
    }
}


/* =====================================================
   RESIZE HANDLING
===================================================== */

let resizeTimer =
    null;


window.addEventListener(
    "resize",
    function () {
        window.clearTimeout(
            resizeTimer
        );

        resizeTimer =
            window.setTimeout(
                function () {
                    resizeAllCanvases();
                },
                100
            );
    }
);


if (
    roiImage &&
    typeof ResizeObserver !==
        "undefined"
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
    typeof ResizeObserver !==
        "undefined"
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

const rawImageInterval =
    window.setInterval(
        function () {
            if (!document.hidden) {
                checkLatestRawImage();
            }
        },
        10000
    );


const calibratedImageInterval =
    window.setInterval(
        function () {
            if (!document.hidden) {
                checkLatestCalibratedImage();
            }
        },
        10000
    );


document.addEventListener(
    "visibilitychange",
    function () {
        if (!document.hidden) {
            checkLatestRawImage();

            checkLatestCalibratedImage();

            checkOcrModelStatus();
        }
    }
);


/*
เตือนก่อนปิดหรือออกจากหน้า
เมื่อ ROI มีการแก้ไขแต่ยังไม่ได้บันทึก
*/
window.addEventListener(
    "beforeunload",
    function (event) {
        if (
            tagsDirty &&
            !tagsSaving
        ) {
            event.preventDefault();

            event.returnValue =
                "";
        }
    }
);


/*
หยุด Interval เมื่อหน้าเว็บถูกนำออก
เพื่อไม่ให้มี Polling ค้าง
*/
window.addEventListener(
    "pagehide",
    function () {
        window.clearInterval(
            rawImageInterval
        );

        window.clearInterval(
            calibratedImageInterval
        );

        stopOcrStatusMonitoring();
    }
);


/* =====================================================
   CAMERA SETTINGS
===================================================== */

const saveCameraBtn =
    document.getElementById(
        "saveCameraBtn"
    );

const testCameraBtn =
    document.getElementById(
        "testCameraBtn"
    );


function getInputElement(
    elementId
) {
    const element =
        document.getElementById(
            elementId
        );

    if (!element) {
        throw new Error(
            (
                "Required form field is missing: " +
                elementId
            )
        );
    }

    return element;
}


function readInputValue(
    elementId,
    trim = true
) {
    const value =
        String(
            getInputElement(
                elementId
            ).value ?? ""
        );

    return trim
        ? value.trim()
        : value;
}


function parseCameraPort() {
    const rawValue =
        readInputValue(
            "cameraPort"
        );

    if (!rawValue) {
        return 554;
    }

    const port =
        Number(
            rawValue
        );

    if (
        !Number.isInteger(
            port
        ) ||
        port < 1 ||
        port > 65535
    ) {
        throw new Error(
            (
                "Camera Port ต้องเป็นตัวเลข " +
                "ระหว่าง 1 ถึง 65535"
            )
        );
    }

    return port;
}


function buildCameraPayload(
    includeName
) {
    const cameraIp =
        readInputValue(
            "cameraIp"
        );

    const rtspPath =
        readInputValue(
            "cameraRtspPath"
        );

    if (!cameraIp) {
        throw new Error(
            "กรุณากรอก Camera IP"
        );
    }

    if (!rtspPath) {
        throw new Error(
            "กรุณากรอก RTSP Path"
        );
    }

    const payload = {
        camera_ip:
            cameraIp,

        camera_port:
            parseCameraPort(),

        camera_username:
            readInputValue(
                "cameraUsername"
            ),

        camera_password:
            readInputValue(
                "cameraPassword",
                false
            ),

        rtsp_path:
            rtspPath
    };

    if (includeName) {
        payload.camera_name =
            readInputValue(
                "cameraName"
            );
    }

    return payload;
}


function setCameraControlsBusy(
    activeButton,
    busyText,
    isBusy,
    originalText
) {
    if (saveCameraBtn) {
        saveCameraBtn.disabled =
            isBusy;
    }

    if (testCameraBtn) {
        testCameraBtn.disabled =
            isBusy;
    }

    if (activeButton) {
        activeButton.innerText =
            isBusy
                ? busyText
                : originalText;
    }
}


if (saveCameraBtn) {
    saveCameraBtn.addEventListener(
        "click",
        async function () {
            if (
                cameraRequestInFlight
            ) {
                return;
            }

            cameraRequestInFlight =
                true;

            const originalText =
                saveCameraBtn.innerText;

            setCameraControlsBusy(
                saveCameraBtn,
                "Saving...",
                true,
                originalText
            );

            try {
                const payload =
                    buildCameraPayload(
                        true
                    );

                const result =
                    await requestJson(
                        "/web_api/api/camera/config",
                        {
                            method:
                                "POST",

                            json:
                                payload,

                            timeoutMs:
                                LONG_REQUEST_TIMEOUT_MS
                        }
                    );

                if (!result.ok) {
                    throw new Error(
                        result.message ||
                        "Save failed."
                    );
                }

                alert(
                    result.message ||
                    (
                        "Camera configuration " +
                        "saved."
                    )
                );

            } catch (error) {
                console.error(
                    (
                        "Cannot save camera " +
                        "configuration:"
                    ),
                    error
                );

                alert(
                    error.message ||
                    (
                        "Cannot save camera " +
                        "configuration."
                    )
                );

            } finally {
                cameraRequestInFlight =
                    false;

                setCameraControlsBusy(
                    saveCameraBtn,
                    "Saving...",
                    false,
                    originalText
                );
            }
        }
    );
}


/* =====================================================
   TEST CAMERA CONNECTION
===================================================== */

if (testCameraBtn) {
    testCameraBtn.addEventListener(
        "click",
        async function () {
            if (
                cameraRequestInFlight
            ) {
                return;
            }

            cameraRequestInFlight =
                true;

            const originalText =
                testCameraBtn.innerText;

            setCameraControlsBusy(
                testCameraBtn,
                "Testing...",
                true,
                originalText
            );

            try {
                const payload =
                    buildCameraPayload(
                        false
                    );

                const result =
                    await requestJson(
                        "/web_api/api/camera/test",
                        {
                            method:
                                "POST",

                            json:
                                payload,

                            timeoutMs:
                                LONG_REQUEST_TIMEOUT_MS
                        }
                    );

                if (!result.ok) {
                    throw new Error(
                        result.message ||
                        (
                            "Cannot connect " +
                            "camera."
                        )
                    );
                }

                alert(
                    result.message ||
                    (
                        "Camera connected " +
                        "successfully."
                    )
                );

            } catch (error) {
                console.error(
                    "Cannot test camera:",
                    error
                );

                alert(
                    error.message ||
                    "Cannot connect camera."
                );

            } finally {
                cameraRequestInFlight =
                    false;

                setCameraControlsBusy(
                    testCameraBtn,
                    "Testing...",
                    false,
                    originalText
                );
            }
        }
    );
}


/* =====================================================
   LOAD CAMERA CONFIGURATION
===================================================== */

function setInputValue(
    elementId,
    value
) {
    const element =
        document.getElementById(
            elementId
        );

    if (!element) {
        return;
    }

    element.value =
        value === null ||
        value === undefined
            ? ""
            : String(
                value
            );
}


async function loadCameraConfiguration() {
    try {
        const result =
            await requestJson(
                "/web_api/api/camera/config",
                {
                    timeoutMs:
                        POLL_REQUEST_TIMEOUT_MS
                }
            );

        /*
        กรณียังไม่เคยตั้งค่ากล้อง
        API จะคืน ok=false และ configured=false
        โดยไม่ถือเป็น Error ของหน้าเว็บ
        */
        if (
            !result.ok ||
            !result.camera ||
            typeof result.camera !==
                "object" ||
            Array.isArray(
                result.camera
            )
        ) {
            return;
        }

        const camera =
            result.camera;

        setInputValue(
            "cameraName",
            camera.camera_name
        );

        setInputValue(
            "cameraIp",
            camera.camera_ip
        );

        setInputValue(
            "cameraPort",
            camera.camera_port || 554
        );

        setInputValue(
            "cameraUsername",
            camera.camera_username
        );

        setInputValue(
            "cameraPassword",
            camera.camera_password
        );

        setInputValue(
            "cameraRtspPath",
            camera.rtsp_path
        );

    } catch (error) {
        if (
            error instanceof
                SettingsRequestError &&
            error.status === 404
        ) {
            return;
        }

        console.error(
            (
                "Cannot load camera " +
                "configuration:"
            ),
            error
        );
    }
}


/* =====================================================
   INITIALIZATION
===================================================== */

/*
ผูก Pointer Event สำหรับวาด ROI
หลังจากประกาศฟังก์ชันทั้งหมดแล้ว
*/
configureRoiImageEvents();


updateRoiTable();
updateSaveAllButton();


loadCameraConfiguration();


startOcrStatusMonitoring();


/*
ตรวจภาพล่าสุดทันทีเมื่อเปิดหน้า
โดยไม่ต้องรอ Polling รอบแรก 10 วินาที
*/
checkLatestRawImage();

checkLatestCalibratedImage();