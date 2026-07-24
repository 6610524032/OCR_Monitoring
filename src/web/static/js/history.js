let historyPoints=[];let selectedVariable=null;let selectedUnit="";const variableSelect=document.getElementById("variableSelect");const chart=document.getElementById("historyChart");const chartStatus=document.getElementById("chartStatus");
async function loadVariables(){const response=await fetch("/web_api/api/history/variables");const result=await response.json();variableSelect.innerHTML="";if(!result.ok||result.variables.length===0){chartStatus.innerText="No variables found. Please save tags first.";return;}result.variables.forEach(function(item){const option=document.createElement("option");option.value=item.tag_name;option.textContent=item.unit?item.tag_name+" ("+item.unit+")":item.tag_name;option.dataset.unit=item.unit||"";variableSelect.appendChild(option);});selectedVariable=variableSelect.value;selectedUnit=variableSelect.options[variableSelect.selectedIndex].dataset.unit||"";await loadHistoryData();}
variableSelect.addEventListener("change",async function(){selectedVariable=variableSelect.value;selectedUnit=variableSelect.options[variableSelect.selectedIndex].dataset.unit||"";await loadHistoryData();});
async function loadHistoryData(){if(!selectedVariable)return;chart.style.display="none";chartStatus.style.display="block";chartStatus.innerText="Loading history data...";const url="/web_api/api/history/data?tag_name="+encodeURIComponent(selectedVariable);const response=await fetch(url);const result=await response.json();if(!result.ok){chartStatus.innerText=result.message||"Cannot load history data";return;}historyPoints=result.points||[];drawChart();}
function drawChart(){chart.innerHTML="";const numericPoints=historyPoints.filter(function(point){return point.value!==null&&!Number.isNaN(point.value);});if(numericPoints.length===0){chart.style.display="none";chartStatus.style.display="block";chartStatus.innerText="No numeric data found for "+selectedVariable;return;}chartStatus.style.display="none";chart.style.display="block";const width=1000;const height=460;const margin={left:70,right:30,top:35,bottom:65};const plotWidth=width-margin.left-margin.right;const plotHeight=height-margin.top-margin.bottom;let minValue=Math.min(...numericPoints.map(point=>point.value));let maxValue=Math.max(...numericPoints.map(point=>point.value));if(minValue===maxValue){minValue-=1;maxValue+=1;}const paddingValue=(maxValue-minValue)*0.12;minValue-=paddingValue;maxValue+=paddingValue;function xScale(index){if(numericPoints.length===1)return margin.left+plotWidth/2;return margin.left+(index/(numericPoints.length-1))*plotWidth;}function yScale(value){return margin.top+((maxValue-value)/(maxValue-minValue))*plotHeight;}drawGrid(margin,plotWidth,plotHeight,minValue,maxValue);drawLine(numericPoints,xScale,yScale);drawPoints(numericPoints,xScale,yScale);drawXAxisLabels(numericPoints,xScale,height);}
function createSvgElement(tagName){return document.createElementNS("http://www.w3.org/2000/svg",tagName);}
function drawGrid(margin,plotWidth,plotHeight,minValue,maxValue){for(let i=0;i<=5;i++){const y=margin.top+(i/5)*plotHeight;const value=maxValue-(i/5)*(maxValue-minValue);const line=createSvgElement("line");line.setAttribute("x1",margin.left);line.setAttribute("x2",margin.left+plotWidth);line.setAttribute("y1",y);line.setAttribute("y2",y);line.setAttribute("class","grid-line");chart.appendChild(line);const label=createSvgElement("text");label.setAttribute("x",margin.left-12);label.setAttribute("y",y+4);label.setAttribute("text-anchor","end");label.setAttribute("class","axis-text");label.textContent=formatNumber(value);chart.appendChild(label);}const yAxis=createSvgElement("line");yAxis.setAttribute("x1",margin.left);yAxis.setAttribute("x2",margin.left);yAxis.setAttribute("y1",margin.top);yAxis.setAttribute("y2",margin.top+plotHeight);yAxis.setAttribute("class","axis-line");chart.appendChild(yAxis);const xAxis=createSvgElement("line");xAxis.setAttribute("x1",margin.left);xAxis.setAttribute("x2",margin.left+plotWidth);xAxis.setAttribute("y1",margin.top+plotHeight);xAxis.setAttribute("y2",margin.top+plotHeight);xAxis.setAttribute("class","axis-line");chart.appendChild(xAxis);const title=createSvgElement("text");title.setAttribute("x",margin.left);title.setAttribute("y",22);title.setAttribute("class","axis-text");title.textContent=selectedVariable+(selectedUnit?" ("+selectedUnit+")":"")+" vs Time";chart.appendChild(title);}
function drawLine(points,xScale,yScale){const path=createSvgElement("path");let d="";points.forEach(function(point,index){const x=xScale(index);const y=yScale(point.value);if(index===0)d+="M "+x+" "+y;else d+=" L "+x+" "+y;});path.setAttribute("d",d);path.setAttribute("class","chart-line");chart.appendChild(path);}
function drawPoints(points,xScale,yScale){points.forEach(function(point,index){const x=xScale(index);const y=yScale(point.value);const circle=createSvgElement("circle");circle.setAttribute("cx",x);circle.setAttribute("cy",y);circle.setAttribute("r",6);circle.setAttribute("class","point");circle.setAttribute("fill",point.is_normal?"#2563eb":"#dc2626");circle.addEventListener("click",function(){openRunDetail(point.run_id);});const title=createSvgElement("title");title.textContent=point.ocr_time+" | "+selectedVariable+" = "+point.value+(selectedUnit?" "+selectedUnit:"")+" | Status: "+point.status;circle.appendChild(title);chart.appendChild(circle);});}
function drawXAxisLabels(points,xScale,height){const maxLabels=8;const step=Math.max(1,Math.ceil(points.length/maxLabels));points.forEach(function(point,index){if(index%step!==0&&index!==points.length-1)return;const x=xScale(index);const label=createSvgElement("text");label.setAttribute("x",x);label.setAttribute("y",height-32);label.setAttribute("text-anchor","middle");label.setAttribute("class","axis-text");label.textContent=point.time_label;chart.appendChild(label);});}
function formatNumber(value){if(Math.abs(value)>=100)return value.toFixed(0);if(Math.abs(value)>=10)return value.toFixed(1);return value.toFixed(3);}
async function openRunDetail(runId){

    const response = await fetch("/web_api/api/history/run/" + runId)
    const result = await response.json();

    if(!result.ok){
        alert(result.message || "Cannot load OCR detail");
        return;
    }

    const run = result.run;
    const values = result.values || [];

    document.getElementById("modalTitle").innerText =
        "OCR Detail - Run #" + run.id;

    document.getElementById("modalSubtitle").innerText =
        run.ocr_time;

    const statusEl = document.getElementById("modalStatus");

    statusEl.innerHTML =
        "<p>Status: <span class='" +
        (run.is_normal ? "status-normal" : "status-warning") +
        "'>" +
        run.status +
        "</span></p>" +
        (run.missing_tags ? "<p>Missing Tags: " + run.missing_tags + "</p>" : "");

    const modalImage = document.getElementById("modalImage");
    const modalNoImage = document.getElementById("modalNoImage");

    if(run.calibrated_image_url){
        modalImage.src =
            run.calibrated_image_url + "?t=" + new Date().getTime();

        modalImage.style.display = "block";
        modalNoImage.style.display = "none";

    }else if(run.raw_image_url){
        modalImage.src =
            run.raw_image_url + "?t=" + new Date().getTime();

        modalImage.style.display = "block";
        modalNoImage.style.display = "none";

    }else{
        modalImage.style.display = "none";
        modalNoImage.style.display = "block";
    }

    const tbody = document.getElementById("modalValues");
    tbody.innerHTML = "";

    values.forEach(function(item){

        const row = document.createElement("tr");

        row.innerHTML = `
            <td>${escapeHtml(item.tag_name)}</td>
            <td>${escapeHtml(item.value)}</td>
            <td>${escapeHtml(item.unit)}</td>
            <td>
                <input
                    class="fix-input modal-edit-input"
                    data-tag="${escapeHtml(item.tag_name)}"
                    value="${escapeHtml(item.value)}"
                >
            </td>
        `;

        tbody.appendChild(row);
    });

    if(!document.getElementById("saveModalEditBtn")){

        const saveBtn = document.createElement("button");
        saveBtn.id = "saveModalEditBtn";
        saveBtn.innerText = "Save";
        saveBtn.style.marginTop = "16px";
        saveBtn.style.background = "#16a34a";
        saveBtn.style.color = "white";
        saveBtn.style.border = "none";
        saveBtn.style.padding = "12px 20px";
        saveBtn.style.borderRadius = "8px";
        saveBtn.style.cursor = "pointer";

        document.querySelector("#detailModalBg .modal").appendChild(saveBtn);
    }

    document.getElementById("saveModalEditBtn").onclick = async function(){

        const inputs = document.querySelectorAll(".modal-edit-input");
        const editedValues = [];

        inputs.forEach(function(input){
            editedValues.push({
                tag_name: input.dataset.tag,
                value: input.value.trim()
            });
        });

        const saveResponse = await fetch("/web_api/api/review/save_values/" + runId, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                values: editedValues
            })
        });

        const saveResult = await saveResponse.json();

        if(saveResult.ok){

            if(saveResult.invalid_tags && saveResult.invalid_tags.length > 0){
                alert(
                    "ยังมีค่าที่ไม่ถูกต้อง: " +
                    saveResult.invalid_tags.join(", ")
                );
            }else{
                alert("Saved");
                document.getElementById("detailModalBg").style.display = "none";
            }

            await loadReviewCount();
            await loadReviewList();
            await loadHistoryData();

        }else{
            alert(saveResult.message || "Save failed");
        }
    };

    document.getElementById("detailModalBg").style.display = "block";
}
function closeModal(){document.getElementById("detailModalBg").style.display="none";}
function escapeHtml(text){return String(text||"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");}

async function loadReviewList(){

    const response = await fetch("/web_api/api/review/list");
    const result = await response.json();

    const card = document.getElementById("reviewListCard");
    const list = document.getElementById("reviewList");

    list.innerHTML = "";

    if(!result.ok || result.items.length === 0){
        card.style.display = "none";
        return;
    }
    if(reviewExpanded){
        card.style.display = "block";
    }else{
        card.style.display = "none";
    }

    document
        .getElementById("reviewToggle")
        .onclick = toggleReviewList;

    result.items.forEach(function(item){

        const imageUrl =
            item.calibrated_image_url ||
            item.raw_image_url ||
            "";

        const div = document.createElement("div");
        div.className = "review-item";

        div.innerHTML = `
            <h3>Run #${item.id}</h3>
            <p><b>OCR Time:</b> ${escapeHtml(item.ocr_time)}</p>
            <p><b>Status:</b> ${escapeHtml(item.status)}</p>
            <p><b>Missing Tags:</b> ${escapeHtml(item.missing_tags)}</p>
            <p><b>Message:</b> ${escapeHtml(item.alert_message)}</p>

            ${
                imageUrl
                ? `<img class="review-image" src="${imageUrl}?t=${new Date().getTime()}">`
                : `<div class="empty-box">No image found</div>`
            }

            <div class="review-actions">
                <button class="accept-btn" onclick="acceptRun(${item.id})">
                    Accept As Is
                </button>

                <button class="accept-btn" onclick="manualFixRun(${item.id}, '${escapeHtml(item.missing_tags)}')">
                    Manual Fix
                </button>

                <button class="delete-run-btn" onclick="deleteRun(${item.id})">
                    Delete Run
                </button>
            </div>
        `;

        list.appendChild(div);
    });
}


async function acceptRun(runId){

    const ok = confirm("ยืนยันว่าจะเก็บข้อมูลรอบนี้ไว้ทั้งแบบนี้ใช่ไหม?");

    if(!ok){
        return;
    }

    const response = await fetch("/web_api/api/review/accept/" + runId, {
        method: "POST"
    });

    const result = await response.json();

    if(result.ok){
        alert("Accepted");
        await loadReviewCount();
        await loadReviewList();
        await loadHistoryData();
    }else{
        alert(result.message || "Accept failed");
    }
}


async function deleteRun(runId){

    const ok = confirm("ต้องการลบข้อมูลรอบนี้และไฟล์รูปภาพจริงใช่ไหม?");

    if(!ok){
        return;
    }

    const response = await fetch("/web_api/api/review/delete/" + runId, {
        method: "POST"
    });

    const result = await response.json();

    if(result.ok){
        alert("Deleted");
        await loadReviewCount();
        await loadReviewList();
        await loadHistoryData();
    }else{
        alert(result.message || "Delete failed");
    }
}

async function manualFixRun(runId, missingTagsText){

    const response = await fetch("/web_api/api/history/run/" + runId)
    const result = await response.json();

    if(!result.ok){
        alert(result.message || "Cannot load run data");
        return;
    }

    const run = result.run;
    const values = result.values || [];

    const imageUrl =
        run.calibrated_image_url ||
        run.raw_image_url ||
        "";

    if(imageUrl){
        document.getElementById("fixImage").src =
            imageUrl + "?t=" + new Date().getTime();
    }

    const tbody = document.querySelector("#fixTable tbody");
    tbody.innerHTML = "";

    values.forEach(function(item){

        const row = document.createElement("tr");

        row.innerHTML = `
            <td>${escapeHtml(item.tag_name)}</td>
            <td>${escapeHtml(item.value)}</td>
            <td>${escapeHtml(item.unit)}</td>
            <td>
                <input
                    class="fix-input"
                    data-tag="${escapeHtml(item.tag_name)}"
                    value="${escapeHtml(item.value)}"
                >
            </td>
        `;

        tbody.appendChild(row);
    });

    document.getElementById("saveFixBtn").onclick = async function(){

        const inputs = document.querySelectorAll(".fix-input");
        const fixedValues = [];

        inputs.forEach(function(input){
            fixedValues.push({
                tag_name: input.dataset.tag,
                value: input.value.trim()
            });
        });

        const saveResponse = await fetch("/web_api/api/review/save_values/" + runId, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                values: fixedValues
            })
        });

        const saveResult = await saveResponse.json();

        if(saveResult.ok){
            alert("Saved");
            document.getElementById("fixModal").style.display = "none";

            await loadReviewCount();
            await loadReviewList();
            await loadHistoryData();
        }else{
            alert(saveResult.message || "Save failed");
        }
    };

    document.getElementById("fixModal").style.display = "block";
}

window.addEventListener("load", function(){

    document.getElementById("fixModal").addEventListener("click", function(event){

        if(event.target.id === "fixModal"){
            document.getElementById("fixModal").style.display = "none";
        }

    });

});

async function loadReviewCount(){

    try{

        const response = await fetch("/web_api/api/review/count");
        const result = await response.json();

        if(!result.ok){
            return;
        }

        const count = result.count || 0;

        const banner =
            document.getElementById("reviewBanner");

        const countText =
            document.getElementById("reviewCount");

        if(count > 0){

            countText.innerText = count;
            banner.style.display = "block";

        }else{

            banner.style.display = "none";

        }

    }catch(e){

        console.log(e);

    }
}


let reviewExpanded = false;

loadReviewCount();
loadReviewList();
loadVariables();

function toggleReviewList(){

    reviewExpanded = !reviewExpanded;

    const card =
        document.getElementById("reviewListCard");

    const list =
        document.getElementById("reviewList");

    const title =
        document.getElementById("reviewToggle");

    if(reviewExpanded){

        card.style.display = "block";
        list.style.display = "block";
        title.innerText = "▲ ซ่อนรายการ";

    }else{

        card.style.display = "none";
        list.style.display = "none";
        title.innerText = "▼ ดูรายการ";

    }
}

