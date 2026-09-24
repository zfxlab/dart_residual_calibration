"use strict";
let fitDatasetId = null, parameterRequest = 0, featureBusy = false;
function downsample(rows, field, budget = 2000) {
  if (rows.length <= budget) return rows;
  const selected = new Set([0, rows.length - 1]), buckets = Math.floor((budget - 2) / 2);
  for (let b = 0; b < buckets; b++) {
    const start = Math.floor(b * rows.length / buckets), end = Math.floor((b + 1) * rows.length / buckets);
    let low = start, high = start;
    for (let i = start + 1; i < end; i++) {
      if (Number(rows[i].row[field]) < Number(rows[low].row[field])) low = i;
      if (Number(rows[i].row[field]) > Number(rows[high].row[field])) high = i;
    }
    selected.add(low); selected.add(high);
  }
  return [...selected].sort((a, b) => a - b).map(i => rows[i]);
}
async function updateDataset(d, rows = d.rows, definitions = d.derived || [], columns = d.columns) {
  if (featureBusy) throw Error("正在更新数据，请稍后重试。");
  featureBusy = true;
  const token = revision;
  try {
    const result = definitions.length ? await api("/api/derive", { rows, columns, derived: definitions }) : { rows, columns, derived: definitions };
    if (token !== revision) throw Error("数据或选区已变化，本次修改未写入，请重试。");
    Object.assign(d, result); invalidate(); persist();
    if (current() === d) render(true);
  } finally { featureBusy = false; renderDerived(); syncFitFields(); }
}
function renderDerived() {
  const d = current();
  $("save-derived").disabled = !d || featureBusy;
  $("derived-list").innerHTML = (d?.derived || []).map(item =>
    '<button class="derived-item" data-name="' + esc(item.name) + '"><b>' + esc(item.name) +
    '</b><code>' + esc(item.expression) + '</code><small>' + esc(item.unit || "未标注单位") +
    (d.diagnostics?.[item.name] ? " · 空值 " + d.diagnostics[item.name].invalid : "") + "</small></button>").join("");
}
async function saveDerived(name, expression, unit = "") {
  const d = current();
  if (!d) throw Error("请先选择数据集。");
  if (!name.trim()) throw Error("请填写派生列名称。");
  const definitions = structuredClone(d.derived || []), index = definitions.findIndex(item => item.name === name);
  if (index < 0 && d.columns.includes(name)) throw Error("不能覆盖原始字段，请使用新列名。");
  const definition = { name, expression, unit, on_error: "null" };
  if (index < 0) definitions.push(definition); else definitions[index] = definition;
  await updateDataset(d, d.rows, definitions);
  notify("已保存派生列 " + name + "；无效数值显示为空值。");
}
function readParameters() {
  const parameters = {};
  $("parameter-editor").querySelectorAll("[data-parameter]").forEach(row => {
    const c = {};
    for (const key of ["initial", "lower", "upper"]) {
      const value = row.querySelector('[data-value="' + key + '"]').value;
      if (value !== "") c[key] = Number(value);
    }
    c.fixed = row.querySelector('[data-value="fixed"]').checked;
    if (Object.keys(c).length > 1 || c.fixed) parameters[row.dataset.parameter] = c;
  });
  return parameters;
}
function fitSettings() {
  return {
    x: $("fit-x").value, y: $("fit-y").value,
    model: $("model").value, formula: $("custom-formula").value,
    validation: Number($("validation").value), group: $("fit-group").value,
    weight: $("fit-weight").value, loss: $("fit-loss").value,
    f_scale: Number($("fit-scale").value), source: $("fit-source").value, parameters: readParameters(),
  };
}
function rememberFit() { const d = current(); if (d) { d.fit = fitSettings(); persist(); } }
async function identifyParameters(config = {}) {
  const request = ++parameterRequest, dataset = current();
  const model = $("model").value, formula = $("custom-formula").value;
  $("custom-formula").disabled = model !== "custom";
  $("parameter-editor").textContent = "正在识别参数…";
  try {
    const result = await api("/api/model", { model, formula });
    if (request !== parameterRequest || current() !== dataset) return;
    if (model !== "custom") $("custom-formula").value = result.formula;
    $("parameter-editor").innerHTML = '<table class="parameter-table"><thead><tr><th>参数</th><th>初值</th><th>下限</th><th>上限</th><th>固定</th></tr></thead><tbody>' +
      result.parameters.map(name => {
        const c = config[name] || {};
        return '<tr data-parameter="' + esc(name) + '"><td>' + esc(name) + "</td>" +
          ["initial", "lower", "upper"].map(key => '<td><input aria-label="' + esc(name + " " + key) + '" data-value="' + key + '" type="number" step="any" placeholder="' + (key === "initial" ? "自动" : "不限") + '" value="' + esc(c[key] ?? "") + '"></td>').join("") +
          '<td><input aria-label="' + esc(name) + ' 固定" data-value="fixed" type="checkbox"' + (c.fixed ? " checked" : "") + "></td></tr>";
      }).join("") + "</tbody></table>";
    rememberFit();
  } catch (error) {
    if (request === parameterRequest) { $("parameter-editor").textContent = error.message; notify(error.message, true); }
  }
}
function syncFitFields(reset = false) {
  const d = current(), fields = numberFields(d);
  $("fit-dataset-label").textContent = d?.name || "请先选择数据集";
  const switched = d?.id !== fitDatasetId, config = d?.fit || {};
  for (const axis of ["x", "y"]) {
    const oldExpression = config[axis + "_expression"];
    const legacyColumn = d?.columns.find(c => "[" + c + "]" === oldExpression);
    const chosen = switched ? (config[axis] || legacyColumn || d?.[axis]) : $("fit-" + axis).value;
    const columns = d?.columns || [];
    setOptions("fit-" + axis, columns, columns.includes(chosen) ? chosen : (fields[axis === "x" ? 0 : 1] || fields[0] || columns[0]));
    $("fit-" + axis).disabled = !columns.length;
  }
  $("fit").disabled = !d || featureBusy;
  $("compare-models").disabled = !d;
  if (d?.id !== fitDatasetId) {
    fitDatasetId = d?.id;
    const config = d?.fit || {};
    $("model").value = config.model || "linear"; $("custom-formula").value = config.formula || "a+b*x";
    $("validation").value = String(config.validation ?? .2); $("fit-source").value = config.source || "all";
    $("fit-loss").value = config.loss || "linear"; $("fit-scale").value = config.f_scale ?? 1;
    setOptions("fit-group", d?.columns || [], config.group || "", true);
    setOptions("fit-weight", fields, config.weight || "", true);
    identifyParameters(config.parameters || {});
  } else if (reset) {
    setOptions("fit-group", d?.columns || [], $("fit-group").value, true);
    setOptions("fit-weight", fields, $("fit-weight").value, true);
  }
}
function fitPayload() {
  const d = current(); if (!d) throw Error("请选择数据集。");
  const config = fitSettings();
  if (!d.columns.includes(config.x) || !d.columns.includes(config.y)) throw Error("请选择 X 和 Y 数据列。");
  return { ...config, rows: config.source === "selection" ? selectedRows().map(item => item.row) : d.rows, columns: d.columns, derived: d.derived || [] };
}
function svgPoints(x, y, mask = null) {
  const rows = x.map((value, i) => ({ row: { x: value, y: y[i] }, index: i })).filter(item => !mask || mask[item.index]);
  const points = downsample(rows, "y");
  return { x: points.map(p => p.row.x), y: points.map(p => p.row.y), type: "scatter", mode: "markers" };
}
function drawFitResult() {
  const result = fitResult; if (!result || view !== "fit") return;
  $("fit-placeholder").hidden = true; $("fit-result").hidden = false; $("formula").textContent = result.formula;
  $("fit-note").textContent = "训练 " + result.train.count + " 点 · 验证 " + (result.validation?.count || 0) + " 点 · 跳过 " + result.skipped + " 行";
  $("fit-metrics").innerHTML = [["训练 RMSE", result.train.rmse], ["验证 RMSE", result.validation?.rmse], ["验证 R²", result.validation?.r2]].map(([k, v]) => "<div><span>" + k + "</span><strong>" + fmt(v) + "</strong></div>").join("");
  $("fit-warnings").textContent = (result.warnings || []).join(" ");
  $("parameter-results").innerHTML = '<table><thead><tr><th>参数</th><th>估计值</th><th>95% 近似置信区间</th></tr></thead><tbody>' + result.parameters.map(p => "<tr><td>" + esc(p.name) + (p.fixed ? "（固定）" : "") + "</td><td>" + fmt(p.value) + "</td><td>" + (p.ci95 ? p.ci95.map(fmt).join(" ~ ") : "不提供") + "</td></tr>").join("") + "</tbody></table>";
  const obs = result.observations;
  const traces = [
    { ...svgPoints(obs.x, obs.y, obs.validation.map(v => !v)), name: "训练", marker: { color: "#26988e", size: 5 } },
    { ...svgPoints(obs.x, obs.y, obs.validation), name: "验证", marker: { color: "#b878b0", symbol: "diamond", size: 6 } },
    { ...result.curve, type: "scatter", mode: "lines", name: "模型（训练范围）", line: { color: "#e39a4c", width: 2.5 } },
  ];
  const layout = { ...chartLayout, dragmode: "zoom", showlegend: true, legend: { orientation: "h" }, xaxis: { title: { text: result.x } }, yaxis: { title: { text: result.y } } };
  Plotly.react("fit-chart", traces, layout, { responsive: true, displaylogo: false });
  Plotly.react("residual-chart", [{ ...svgPoints(result.residuals.x, result.residuals.y), marker: { color: "#26988e", size: 5 } }], { ...layout, showlegend: false, yaxis: { title: { text: "预测 − 实测" }, zerolinecolor: "#bbb" } }, { responsive: true, displaylogo: false });
}
async function runFit() {
  if (featureBusy) { notify("数据更新尚未完成，请稍后拟合。", true); return; }
  const token = revision;
  $("fit").disabled = true; $("fit").textContent = "正在拟合…";
  try {
    const payload = fitPayload(); rememberFit();
    const result = await api("/api/fit", payload);
    if (token !== revision) throw Error("数据或设置已变化，请重新拟合。");
    fitResult = result; setView("fit"); drawFitResult(); notify("拟合完成。置信区间为模型局部线性近似，请结合残差与验证指标判断。");
  } catch (error) { notify(error.message, true); }
  finally { $("fit").disabled = !current(); $("fit").textContent = "执行拟合 ↗"; }
}
function renderTemplates() {
  $("template-choice").innerHTML = '<option value="">选择模板</option>' + (state.templates || []).map((item, i) => '<option value="' + i + '">' + esc(item.name) + "</option>").join("");
}
function setupFeatures() {
  $("fit-inspector").prepend($("model-panel"));
  $("fit-main").insertBefore($("fit-result"), $("comparison-panel"));
  $("fit-result").insertAdjacentHTML("beforeend", '<p id="fit-warnings" class="hint"></p><div id="parameter-results" class="table-scroll"></div><p class="hint">95% 区间采用局部线性近似；稳健拟合、参数触及边界或不可识别时不提供。</p>');
  $("formula").insertAdjacentHTML("afterend", '<div id="fit-chart" style="height:360px"></div>');
  window.addEventListener("hashchange", () => setView(location.hash.slice(2)));
  $("go-fit").onclick = () => { $("fit-source").value = "selection"; invalidate(); rememberFit(); setView("fit"); };
  $("back-data").onclick = () => setView("explore");
  $("save-derived").onclick = async () => {
    try { await saveDerived($("derived-name").value.trim(), $("derived-expression").value.trim(), $("derived-unit").value.trim()); }
    catch (error) { notify(error.message, true); }
  };
  $("derived-list").onclick = event => {
    const button = event.target.closest("[data-name]");
    const item = current()?.derived?.find(d => d.name === button?.dataset.name);
    if (item) { $("derived-name").value = item.name; $("derived-expression").value = item.expression; $("derived-unit").value = item.unit || ""; }
  };
  $("model").onchange = () => { invalidate(); identifyParameters(); };
  $("identify-parameters").onclick = () => { invalidate(); identifyParameters(readParameters()); };
  $("parameter-editor").onchange = () => { invalidate(); rememberFit(); };
  for (const id of ["fit-x", "fit-y", "fit-source", "validation", "custom-formula", "fit-group", "fit-weight", "fit-loss", "fit-scale"]) {
    $(id).onchange = () => { invalidate(); rememberFit(); };
  }
  $("custom-formula").onchange = () => { invalidate(); identifyParameters(readParameters()); };
  $("save-template").onclick = async () => {
    const name = await ask("模板名称"); if (!name) return; const c = fitSettings();
    state.templates = state.templates || [];
    state.templates.push({ name, model: c.model, formula: c.formula, parameters: c.parameters, loss: c.loss, f_scale: c.f_scale });
    persist(); renderTemplates(); notify("已保存函数模板，项目 JSON 也包含这些模板。");
  };
  $("load-template").onclick = async () => {
    const choice = $("template-choice").value; if (choice === "") return;
    const template = state.templates[Number(choice)];
    $("model").value = template.model; $("custom-formula").value = template.formula;
    $("fit-loss").value = template.loss; $("fit-scale").value = template.f_scale;
    invalidate(); await identifyParameters(template.parameters);
  };
  $("compare-models").onclick = async () => {
    const token = revision; $("compare-models").disabled = true; $("comparison-table").textContent = "正在比较…";
    try {
      const payload = fitPayload(), comparisons = [];
      for (const model of ["constant", "linear", "quadratic", "cubic", "exponential", "logarithmic", "power"]) {
        if (token !== revision) throw Error("配置已变化，比较已取消。");
        try {
          const result = await api("/api/fit", { ...payload, model, parameters: {} });
          comparisons.push({ model, train: result.train.rmse, validation: result.validation?.rmse, error: "" });
        } catch (error) { comparisons.push({ model, error: error.message }); }
      }
      if (token !== revision) throw Error("配置已变化，比较已取消。");
      $("comparison-table").innerHTML = "<table><thead><tr><th>模型</th><th>训练 RMSE</th><th>验证 RMSE</th><th>说明</th></tr></thead><tbody>" + comparisons.map(r => "<tr><td>" + esc(r.model) + "</td><td>" + fmt(r.train) + "</td><td>" + fmt(r.validation) + "</td><td>" + esc(r.error) + "</td></tr>").join("") + "</tbody></table>";
    } catch (error) { $("comparison-table").textContent = error.message; }
    finally { $("compare-models").disabled = !current(); }
  };
}

function editCell(cell) {
  if (cell.querySelector("input") || featureBusy) return;
  const d = current(), index = Number(cell.dataset.row), col = d.columns[Number(cell.dataset.col)];
  const original = String(d.rows[index][col] ?? "");
  const input = document.createElement("input");
  input.className = "cell-input"; input.value = original; input.setAttribute("aria-label", "编辑 " + col);
  cell.replaceChildren(input); input.focus(); input.select();
  let finished = false;
  const finish = async cancel => {
    if (finished) return;
    finished = true;
    const value = input.value.trim();
    if (cancel || value === original) { cell.textContent = original; return; }
    const rows = d.rows.map(row => ({ ...row }));
    rows[index][col] = value === "" ? null : numeric(value) ? Number(value) : value;
    input.disabled = true;
    try { await updateDataset(d, rows); }
    catch (error) { cell.textContent = original; notify(error.message, true); }
  };
  input.onblur = () => finish(false);
  input.onkeydown = event => {
    if (event.key === "Enter" || event.key === "Escape") {
      event.preventDefault(); event.stopPropagation(); finish(event.key === "Escape");
    }
  };
}

async function deleteTableItem(kind, index) {
  if (featureBusy) { notify("数据正在更新，请稍后删除。", true); return; }
  const d = current(); if (!d) return;
  const token = revision, column = d.columns[index];
  if (kind === "column") {
    if (d.columns.length <= 1) { notify("数据集至少保留一个字段。", true); return; }
    const dependents = (d.derived || []).filter(item => item.name !== column &&
      [...item.expression.matchAll(/\[([^\[\]]+)\]/g)].some(match => match[1] === column));
    if (dependents.length) {
      notify("字段被派生列依赖：" + dependents.map(item => item.name).join("、") + "。请先修改或删除这些派生列。", true);
      return;
    }
  }
  const dialog = $("table-delete-dialog");
  if (dialog.open) return;
  $("table-delete-description").textContent = kind === "row" ? "删除第 " + (index + 1) + " 条记录？" : "删除字段「" + column + "」及其所有值？";
  dialog.returnValue = "cancel"; dialog.showModal();
  const confirmed = await new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "delete"), { once: true }));
  if (!confirmed) return;
  if (revision !== token || current() !== d) { notify("数据已变化，请重新选择删除项。", true); return; }
  try {
    const rows = kind === "row" ? d.rows.filter((_, i) => i !== index) :
      d.rows.map(row => Object.fromEntries(Object.entries(row).filter(([key]) => key !== column)));
    const columns = kind === "column" ? d.columns.filter(c => c !== column) : d.columns;
    const definitions = kind === "column" ? (d.derived || []).filter(item => item.name !== column) : d.derived || [];
    await updateDataset(d, rows, definitions, columns);
    selection = null; render(true);
    rememberFit();
    notify(kind === "row" ? "已删除记录。" : "已删除字段「" + column + "」。");
  } catch (error) { notify(error.message, true); }
}
