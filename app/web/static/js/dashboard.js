function escapeHtml(text){
    return String(text ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

async function loadDashboard(){
    const content = document.getElementById("dashboard-content");

    try{
        const response = await fetch("/web_api/api/latest");
        const result = await response.json();

        if(!result.has_data){
            content.innerHTML =
                '<div class="card empty">' +
                '<h2>No OCR Data Yet</h2>' +
                '<p>ยังไม่มีข้อมูล OCR ในฐานข้อมูล</p>' +
                '<p>ให้ตั้งค่า ROI ใน Settings แล้วนำรูปใหม่ใส่ใน <b>server/data/incoming</b></p>' +
                '</div>';
            return;
        }

        const data = result.data;
        const values = data.values || [];

        let valueCards = "";

        values.forEach(function(item){
            valueCards +=
                '<div class="value-card">' +
                '<div class="label">' + escapeHtml(item.tag_name) + '</div>' +
                '<div class="value">' +
                escapeHtml(item.value || "-") +
                (item.unit ? '<span style="font-size:16px;"> ' + escapeHtml(item.unit) + '</span>' : '') +
                '</div>' +
                (item.raw_text ? '<div class="raw">Raw: ' + escapeHtml(item.raw_text) + '</div>' : '') +
                '</div>';
        });

        const imageUrl = data.calibrated_image_path
            ? "/calibrated_images/" + data.calibrated_image_path + "?t=" + data.id
            : "";

        content.innerHTML =
            '<div class="main-layout">' +

            '<div>' +
            '<div class="card">' +
            '<h2>Status</h2>' +
            '<p><b>OCR Time:</b> ' + escapeHtml(data.ocr_time) + '</p>' +
            '<div class="' + (data.status === "NORMAL" ? "status-normal" : "status-alert") + '">' +
            (data.status === "NORMAL" ? "🟢 NORMAL" : "🔴 ALERT") +
            '</div>' +
            (data.alert_message ? '<p>' + escapeHtml(data.alert_message) + '</p>' : '') +
            (data.missing_tags ? '<p><b>Missing:</b> ' + escapeHtml(data.missing_tags) + '</p>' : '') +
            '</div>' +

            '<div class="card">' +
            '<h2>Latest OCR Values</h2>' +
            (values.length > 0
                ? '<div class="grid">' + valueCards + '</div>'
                : '<div class="empty">ยังไม่มีค่าที่อ่านได้ในรอบล่าสุด</div>'
            ) +
            '</div>' +
            '</div>' +

            '<div class="card image-card">' +
            '<h2>Latest Calibrated Image</h2>' +
            (imageUrl
                ? '<img src="' + imageUrl + '" alt="Latest calibrated image">' +
                  '<p style="font-size:13px;color:#6b7280;">' + escapeHtml(data.calibrated_image_path) + '</p>'
                : '<div class="empty">ไม่มีรูป calibrated image</div>'
            ) +
            '</div>' +

            '</div>';

    }catch(error){
        content.innerHTML =
            '<div class="card empty">' +
            '<h2>Cannot load API data</h2>' +
            '<p>' + escapeHtml(error.message) + '</p>' +
            '</div>';
    }
}

loadDashboard();
setInterval(loadDashboard, 30000);