"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const numeric = value => value !== null && value !== undefined && value !== "" && typeof value !== "boolean" && Number.isFinite(Number(value));
const fmt = value => value == null || !Number.isFinite(value) ? "—" : Number(value.toPrecision(6)).toLocaleString("en-US", { maximumFractionDigits: 6 });
const KEY = "data-workbench-v1";
let state = { version: 1, name: "未命名项目", datasets: [], active: null };
let selection = null, fitResult = null, page = 0, revision = 0, captureData = null, capturing = false, view = "explore", pollBusy = false;
const current = () => state.datasets.find(d => d.id === state.active);
const numberFields = d => d ? d.columns.filter(c => d.rows.some(r => numeric(r[c]))) : [];
function notify(text, error = false) { $("notice").textContent = text; $("notice").className = error ? "error" : ""; $("notice").hidden = false; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const result = await response.json(); if (!response.ok) throw Error(result.error || "请求失败"); return result;
}
function persist() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); $("save-status").textContent = "已自动保存"; $("storage-state").textContent = "浏览器自动保存 · 可下载项目备份"; }
  catch { $("save-status").textContent = "尚未保存"; $("storage-state").textContent = "浏览器空间不足，请下载项目 JSON"; notify("浏览器存储空间不足，请保存项目 JSON，避免刷新后丢失修改。", true); }
}
function invalidate() { revision++; fitResult = null; $("fit-result").hidden = true; $("fit-placeholder").hidden = false; $("comparison-table").innerHTML = ""; }
function addDataset(name, columns, rows, source) {
  const d = { id: crypto.randomUUID(), name, columns, rows, source }; state.datasets.push(d); state.active = d.id;
  selection = null; page = 0; invalidate(); persist(); render(true); return d;
}
function download(name, content, type) { const url = URL.createObjectURL(new Blob([content], { type })); const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
async function ask(title, value = "", required = true) {
  $("dialog-input").required = required;
  $("dialog-title").textContent = title; $("dialog-input").value = value; $("text-dialog").returnValue = "cancel"; $("text-dialog").showModal(); $("dialog-input").focus();
  return new Promise(resolve => $("text-dialog").addEventListener("close", () => resolve($("text-dialog").returnValue === "ok" ? $("dialog-input").value.trim() : null), { once: true }));
}
function setOptions(id, items, chosen, blank = false) {
  $(id).innerHTML = (blank ? '<option value="">不筛选</option>' : "") + items.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  if (items.includes(chosen)) $(id).value = chosen;
}
function selectedRows() {
  const d = current(); if (!d) return [];
  const x = $("x-field").value, lo = $("x-min").value, hi = $("x-max").value, f = $("filter-field").value, value = $("filter-value").value;
  return d.rows.map((row, index) => ({ row, index })).filter(({ row, index }) =>
    (!selection || selection.has(index)) && (!f || String(row[f] ?? "") === value) &&
    (lo === "" || numeric(row[x]) && Number(row[x]) >= Number(lo)) && (hi === "" || numeric(row[x]) && Number(row[x]) <= Number(hi)));
}
function render(reset = false) {
  const d = current(), fields = numberFields(d);
  $("datasets").innerHTML = state.datasets.map(item => `<div class="dataset-row"><button class="dataset ${item.id === state.active ? "active" : ""}" data-id="${esc(item.id)}">▤ &nbsp;${esc(item.name)}<small>${item.rows.length.toLocaleString()} 条记录 · ${item.columns.length} 字段</small></button><button class="dataset-delete" data-delete-id="${esc(item.id)}" title="删除 ${esc(item.name)}" aria-label="删除 ${esc(item.name)}">×</button></div>`).join("");
  renderProject();
  $("dataset-count").textContent = state.datasets.length;
  if (reset) {
    setOptions("x-field", fields, d?.x || fields[0]); setOptions("y-field", fields, d?.y || fields[1] || fields[0]); setOptions("filter-field", d?.columns || [], "", true);
    $("x-min").value = ""; $("x-max").value = ""; $("filter-value").value = "";
  }
  $("stat-name").textContent = d?.name || "暂无数据"; $("stat-source").textContent = d?.source || "CSV / 手工 / ROS 2";
  $("stat-rows").textContent = d?.rows.length.toLocaleString() || "0"; $("stat-fields").textContent = fields.length;
  $("empty").hidden = !!d; $("chart").hidden = !d;
  for (const id of ["export-csv", "rename", "add-column", "add-row", "summarize", "fit"]) $(id).disabled = !d;
  renderSelection(); draw(); renderDerived(); syncFitFields(reset);
}
function renderSelection() {
  const rows = selectedRows(), y = $("y-field").value, values = rows.map(({ row }) => row[y]).filter(numeric).map(Number);
  $("stat-selected").textContent = rows.length.toLocaleString(); $("table-count").textContent = rows.length.toLocaleString();
  $("stat-selection-note").textContent = selection ? "图表选区 + 条件筛选" : "符合筛选条件的记录";
  $("summary-field").textContent = y || "Y";
  const n = values.length, mean = n ? values.reduce((a, b) => a + b, 0) / n : null;
  const sd = n > 1 ? Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : null;
  const min = n ? values.reduce((a, b) => Math.min(a, b), Infinity) : null, max = n ? values.reduce((a, b) => Math.max(a, b), -Infinity) : null;
  $("summary").innerHTML = [["有效数值", n], ["均值", fmt(mean)], ["样本标准差", fmt(sd)], ["最小值", fmt(min)], ["最大值", fmt(max)]].map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  renderTable(rows);
}
function renderTable(rows) {
  const d = current(); if (!d) { $("table").innerHTML = ""; $("pagination").textContent = "暂无记录"; return; }
  const pages = Math.max(1, Math.ceil(rows.length / 40)); page = Math.min(page, pages - 1);
  const derived = new Set((d.derived || []).map(item => item.name));
  $("table").innerHTML = `<table><thead><tr><th>#</th>${d.columns.map((c, col) => `<th>${esc(c)} <button class="table-delete" data-delete-column="${col}" aria-label="删除字段 ${esc(c)}" title="删除字段">×</button></th>`).join("")}<th>操作</th></tr></thead><tbody>${rows.slice(page * 40, page * 40 + 40).map(({ row, index }) => `<tr><td>${index + 1}</td>${d.columns.map((c, col) => `<td class="${derived.has(c) ? "computed" : "editable"}" data-row="${index}" data-col="${col}" ${derived.has(c) ? "" : 'tabindex="0"'} title="${derived.has(c) ? "派生列，由公式计算" : "单击编辑，Enter 保存，Esc 取消"}">${esc(typeof row[c] === "number" ? fmt(row[c]) : row[c])}</td>`).join("")}<td><button class="table-delete" data-delete-row="${index}" aria-label="删除第 ${index + 1} 条记录">删除</button></td></tr>`).join("")}</tbody></table>`;
  $("pagination").textContent = `第 ${page + 1} / ${pages} 页 · 每页 40 条`; $("prev").disabled = page === 0; $("next").disabled = page >= pages - 1;
}
const chartLayout = { paper_bgcolor: "#fff", plot_bgcolor: "#fff", font: { family: 'Inter, "Microsoft YaHei", sans-serif', color: "#83919b", size: 11 }, margin: { l: 65, r: 25, t: 25, b: 55 }, hovermode: "closest", dragmode: "select", showlegend: false };
function draw() {
  const d = current(); if (!d || view !== "explore") return;
  const x = $("x-field").value, y = $("y-field").value, type = $("chart-type").value;
  // Draw the range-filtered context; a box selection remains visible as highlighted points.
  const saved = selection; selection = null; const rows = selectedRows(); selection = saved;
  const valid = rows.filter(({ row }) => numeric(row[y]) && (["histogram", "box"].includes(type) || numeric(row[x])));
  if (type === "line") valid.sort((a, b) => Number(a.row[x]) - Number(b.row[x]) || a.index - b.index);
  const plotted = downsample(valid, y, 2000), stride = valid.length / Math.max(1, plotted.length);
  const trace = { x: plotted.map(({ row }) => Number(row[x])), y: plotted.map(({ row }) => Number(row[y])), customdata: plotted.map(r => r.index), type: "scatter", mode: type === "line" ? "lines+markers" : "markers", marker: { color: "#26988e", size: 5, opacity: .7 }, line: { color: "#26988e", width: 1.5 }, name: d.name };
  if (type === "histogram") { trace.type = "histogram"; trace.x = valid.map(({ row }) => Number(row[y])); delete trace.y; }
  if (type === "box") { trace.type = "box"; trace.y = valid.map(({ row }) => Number(row[y])); delete trace.x; }
  if (saved && ["scatter", "line"].includes(type)) trace.selectedpoints = plotted.flatMap((r, i) => saved.has(r.index) ? [i] : []);
  const traces = [trace];

  $("chart-label").textContent = "原始数据";
  $("chart-title").textContent = type === "histogram" ? `${y} · 数值分布` : type === "box" ? `${y} · 箱线图` : `${y || "Y"} 与 ${x || "X"}`;
  $("chart-points").textContent = `原始 ${valid.length.toLocaleString()} 点 · 绘制 ${["box", "histogram"].includes(type) ? valid.length : plotted.length} 点`;
  $("chart-footnote").textContent = stride > 1 ? "显示已降采样；矩形框选按完整数据计算。" : "拖动框选数据，选区会同步到统计、记录和拟合。";
  if (type === "line") $("chart-footnote").textContent += " 折线按 X 升序连接，相同 X 保持记录顺序。";
  Plotly.react("chart", traces, { ...chartLayout, xaxis: { title: { text: type === "histogram" ? y : x }, gridcolor: "#eff2f4", zeroline: false }, yaxis: { title: { text: type === "histogram" ? "频数" : y }, gridcolor: "#eff2f4", zeroline: false }, uirevision: `${d.id}-${x}-${y}-${type}` }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d"] }).then(() => {
    $("chart").removeAllListeners("plotly_selected");
    $("chart").on("plotly_selected", event => {
      if (!event || !["scatter", "line"].includes(type)) return;
      if (event.range) { const xr = event.range.x, yr = event.range.y; selection = new Set(valid.filter(({ row }) => Number(row[x]) >= xr[0] && Number(row[x]) <= xr[1] && Number(row[y]) >= yr[0] && Number(row[y]) <= yr[1]).map(r => r.index)); }
      else selection = new Set(event.points.filter(p => p.curveNumber === 0).map(p => p.customdata));
      page = 0; invalidate(); renderSelection(); draw();
    });
  });
}
function demo() {
  const rows = Array.from({ length: 240 }, (_, i) => { const x = 1 + i * .04; return { time_s: Number((i * .1).toFixed(2)), input: Number(x.toFixed(3)), response: Number((1.2 + 1.85 * x + .075 * x * x + Math.sin(i * 1.7) * .35 + Math.cos(i * .6) * .18).toFixed(5)), temperature_c: Number((24 + Math.sin(i / 30) * 1.2).toFixed(2)), batch: i < 192 ? "A" : "B" }; });
  const d = addDataset("传感器响应实验", Object.keys(rows[0]), rows, "合成示例 · 非实测数据"); d.x = "input"; d.y = "response"; persist(); render(true);
}
function setView(name) {
  if (!["explore", "fit", "capture"].includes(name)) name = "explore";
  view = name; if (location.hash !== `#/${name}`) history.replaceState(null, "", `#/${name}`);
  document.querySelectorAll(".nav").forEach(b => b.classList.toggle("active", b.dataset.view === name));
  $("view-name").textContent = { explore: "数据探索", fit: "函数拟合", capture: "实时采集" }[name];
  $("title").textContent = { explore: "让数据呈现规律。", fit: "从观测，到可解释的模型。", capture: "记录每一次变化。" }[name];
  $("subtitle").textContent = { explore: "导入、观察、选取与拟合，在同一个工作空间完成。", fit: "自由选择变量与函数，以残差和独立验证评估拟合效果。", capture: "连接 ROS 2 话题，采集完成后保存为可分析的数据集。" }[name];
  $("capture-panel").hidden = name !== "capture";
  $("live-panel").hidden = name !== "capture";
  $("data-page").hidden = name !== "explore"; $("fit-page").hidden = name !== "fit";
  document.querySelector(".stats").hidden = name === "capture";
  $("rename").hidden = name === "capture"; $("export-csv").hidden = name === "capture";
  if (name === "explore") draw();
  if (name === "fit") { syncFitFields(); if (fitResult) drawFitResult(); }
  if (name === "capture") { drawLive(); pollCapture(); }
}
function drawLive() {
  if (view !== "capture" || !captureData?.samples.length) return;
  const rows = captureData.samples.slice(-2000), fields = numberFields({ columns: Object.keys(rows.at(-1)), rows });
  setOptions("live-field", fields, $("live-field").value || fields.find(c => c !== "elapsed_s") || fields[0]);
  const field = $("live-field").value;
  Plotly.react("live-chart", [{ x: rows.map(r => r.elapsed_s), y: rows.map(r => numeric(r[field]) ? Number(r[field]) : null), type: "scatter", mode: "lines", connectgaps: false, line: { color: "#26988e", width: 1.5 } }], { ...chartLayout, dragmode: "zoom", uirevision: field, xaxis: { title: { text: "接收时间 / s" } }, yaxis: { title: { text: field } } }, { responsive: true, displaylogo: false });
}
$("live-field").onchange = drawLive;
async function pollCapture() {
  if (pollBusy) return; pollBusy = true;
  try {
    captureData = await api("/api/capture"); capturing = captureData.running; $("capture-state").textContent = capturing ? "正在记录" : captureData.samples.length ? "已停止" : "未连接";
    $("capture-count").textContent = `${captureData.samples.length.toLocaleString()} 条消息`; $("start-capture").disabled = capturing; $("stop-capture").disabled = !capturing; $("keep-capture").disabled = capturing || !captureData.samples.length;
    $("capture-dot").className = capturing ? "live" : ""; $("capture-log").textContent = captureData.logs.join("\n");
    if (capturing && !captureData.samples.length && !captureData.logs.length) $("capture-log").textContent = "等待消息，请确认发布节点、ROS_DOMAIN_ID 与话题类型。";
    drawLive();
  } catch (error) { if (view === "capture") notify(error.message, true); } finally { pollBusy = false; }
}
document.querySelectorAll(".nav").forEach(b => b.onclick = () => setView(b.dataset.view));
$("datasets").onclick = event => { const remove = event.target.closest("[data-delete-id]"); if (remove) { deleteDataset(remove.dataset.deleteId); return; } const b = event.target.closest("[data-id]"); if (!b) return; state.active = b.dataset.id; selection = null; page = 0; invalidate(); persist(); render(true); };
$("demo").onclick = demo; $("empty-demo").onclick = demo; $("import").onclick = () => $("file").click();
$("file").onchange = async () => {
  const file = $("file").files[0]; if (!file) return; try {
    if (file.size > 32 * 1024 * 1024) throw Error("文件超过 32 MB。"); const text = await file.text();
    if (file.name.toLowerCase().endsWith(".json")) {
      const incoming = JSON.parse(text);
      await importProject(incoming, file.name);
    } else { const data = await api("/api/import", { csv: text }); addDataset(file.name.replace(/\.csv$/i, ""), data.columns, data.rows, "CSV 文件"); }
    notify(`已导入 ${file.name}`);
  } catch (error) { notify(error.message, true); } finally { $("file").value = ""; }
};
$("new-data").onclick = async () => { const name = await ask("新建数据表", "未命名实验"); if (name) addDataset(name, ["x", "y"], [], "手工记录"); };
$("rename").onclick = async () => { const d = current(); if (!d) return; const name = await ask("重命名数据集", d.name); if (name) { d.name = name; persist(); render(); } };
$("export-csv").onclick = () => { const d = current(); if (!d) return; const cell = v => '"' + String(v ?? "").replaceAll('"', '""') + '"'; download(`${d.name}.csv`, "\uFEFF" + [d.columns.map(cell).join(","), ...selectedRows().map(({ row }) => d.columns.map(c => cell(row[c])).join(","))].join("\r\n"), "text/csv;charset=utf-8"); };
for (const id of ["x-field", "y-field", "chart-type", "x-min", "x-max", "filter-field", "filter-value"]) $(id).onchange = () => { selection = null; page = 0; invalidate(); const d = current(); if (d) { d.x = $("x-field").value; d.y = $("y-field").value; persist(); } render(); };
$("reset-selection").onclick = () => { selection = null; $("x-min").value = ""; $("x-max").value = ""; $("filter-field").value = ""; page = 0; invalidate(); render(); };
$("prev").onclick = () => { page--; renderSelection(); }; $("next").onclick = () => { page++; renderSelection(); };
$("add-column").onclick = async () => { const d = current(); if (!d || featureBusy) return; const name = await ask("新字段名称"); if (!name) return; if (d.columns.includes(name)) { notify("字段名已存在。", true); return; } d.columns.push(name); d.rows.forEach(r => Object.defineProperty(r, name, { value: null, writable: true, enumerable: true, configurable: true })); invalidate(); persist(); render(true); };
$("add-row").onclick = async () => {
  const d = current(); if (!d) return;
  if (d.rows.length >= 100000) { notify("最多支持 100000 行。", true); return; }
  try { selection = null; $("x-min").value = ""; $("x-max").value = ""; $("filter-field").value = ""; await updateDataset(d, [...d.rows, Object.fromEntries(d.columns.map(c => [c, null]))]); page = Math.floor((d.rows.length - 1) / 40); renderSelection(); } catch (error) { notify(error.message, true); }
};
$("table").onclick = event => {
  const rowButton = event.target.closest("[data-delete-row]");
  const columnButton = event.target.closest("[data-delete-column]");
  if (rowButton) { deleteTableItem("row", Number(rowButton.dataset.deleteRow)); return; }
  if (columnButton) { deleteTableItem("column", Number(columnButton.dataset.deleteColumn)); return; }
  const cell = event.target.closest("td.editable");
  if (cell) editCell(cell);
};
$("table").onkeydown = event => {
  if (event.target.matches("td.editable") && ["Enter", " "].includes(event.key)) {
    event.preventDefault(); editCell(event.target);
  }
};
$("summarize").onclick = async () => {
  const d = current(), rows = selectedRows(); if (!d || !rows.length) { notify("当前选区为空。", true); return; } const name = await ask("汇总记录名称", `${d.name} · 选区均值`); if (!name) return;
  const result = { record_name: name, source_dataset: d.name, sample_count: rows.length }; for (const field of numberFields(d)) { const vals = rows.map(({ row }) => row[field]).filter(numeric).map(Number); if (!vals.length) continue; const mean = vals.reduce((a, b) => a + b, 0) / vals.length; result[`${field}_mean`] = mean; result[`${field}_n`] = vals.length; result[`${field}_std`] = vals.length > 1 ? Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / (vals.length - 1)) : null; }
  let target = state.datasets.find(item => item.source === "选区汇总记录"); if (!target) { target = { id: crypto.randomUUID(), name: "实验汇总记录", columns: [], rows: [], source: "选区汇总记录" }; state.datasets.push(target); } target.columns = [...new Set([...target.columns, ...Object.keys(result)])]; target.rows.push(result); persist(); render(); notify(`已追加到「${target.name}」，可切换数据集继续填写参考值。`);
};
$("fit").onclick = runFit;
$("export-model").onclick = () => { if (fitResult) download("fitted-model.json", JSON.stringify({ ...fitResult, dataset: current().name, created_at: new Date().toISOString() }, null, 2), "application/json"); };
$("start-capture").onclick = async () => { try { if (captureData?.samples.length && !confirm("开始新采集将替换服务中的上次采集缓存。已保存的数据集会保留。继续？")) return; await api("/api/capture/start", { topic: $("topic").value, message_type: $("message-type").value, duration: Number($("duration").value), limit: Number($("limit").value) }); await pollCapture(); } catch (error) { notify(error.message, true); } };
$("stop-capture").onclick = async () => { try { await api("/api/capture/stop", {}); await pollCapture(); } catch (error) { notify(error.message, true); } };
$("keep-capture").onclick = () => { if (!captureData?.samples.length || capturing) return; const rows = structuredClone(captureData.samples); addDataset(`采集 ${new Date().toLocaleTimeString()}`, [...new Set(rows.flatMap(Object.keys))], rows, `ROS · ${captureData.topic}`); notify("采集已保存为数据集。可按 status、frame_id 或 segment 筛选后分析。"); setView("explore"); };
try { const cached = localStorage.getItem(KEY); if (cached) { const parsed = JSON.parse(cached); if (parsed.version === 1 && Array.isArray(parsed.datasets)) state = parsed; } } catch { notify("无法恢复浏览器缓存，可导入已保存的项目。", true); }
setupProject(); setupFeatures(); renderTemplates(); render(true); setView(location.hash.slice(2) || "explore"); pollCapture(); setInterval(() => { if (capturing || view === "capture") pollCapture(); }, 1500);
