"use strict";
let captureSummary = null, summaryCaptureId = null, summaryFieldsKey = "", summaryRevision = 0;
let summaryBusy = false, summarySaving = false;

function clearCaptureSummary() {
  summaryRevision++; captureSummary = null;
  $("capture-summary-result").hidden = true;
  $("save-capture-summary").disabled = true;
}
function summaryConfig() {
  return {capture_id: captureData?.capture_id, fields: Array.from($("capture-summary-fields").selectedOptions, o => o.value).sort(),
    sample_mode: $("capture-summary-mode").value, valid_field: $("capture-summary-valid").value,
    valid_value: $("capture-summary-value").value.trim()};
}
function syncCaptureSummary() {
  const id = captureData?.capture_id || null, samples = captureData?.samples || [];
  if (id !== summaryCaptureId) {
    summaryCaptureId = id; summaryFieldsKey = ""; clearCaptureSummary();
    $("capture-summary-name").value = ""; $("capture-summary-reference").value = "";
  }
  const fields = [...new Set(samples.flatMap(Object.keys))];
  const key = JSON.stringify(fields);
  if (key !== summaryFieldsKey) {
    summaryFieldsKey = key;
    const select = $("capture-summary-fields"), previousFields = new Set(Array.from(select.selectedOptions, o => o.value));
    select.innerHTML = fields.map(f => '<option value="' + esc(f) + '"' + (previousFields.has(f) ? ' selected' : '') + '>' + esc(f) + '</option>').join("");
    const valid = $("capture-summary-valid"), previous = valid.value;
    valid.innerHTML = '<option value="">不限制（全部记录）</option>' + fields.map(f => '<option value="' + esc(f) + '">' + esc(f) + '</option>').join("");
    valid.value = fields.includes(previous) ? previous : "";
  }
  if (captureData?.running && captureSummary) clearCaptureSummary();
  $("capture-summary-value").disabled = !$("capture-summary-valid").value;
  $("calculate-capture-summary").disabled = summaryBusy || summarySaving || !id || !samples.length || !!captureData?.running;
  $("save-capture-summary").disabled = !captureSummary || summaryBusy || summarySaving || !!captureData?.running || captureSummary.capture_id !== id;
  if (!captureSummary) $("capture-summary-status").textContent = summaryBusy ? "正在计算…" : captureData?.running ? "采集中，请停止后计算" : samples.length ? "选择字段后计算本次汇总" : "等待采集数据";
}
async function calculateCaptureSummary() {
  if (summaryBusy || summarySaving || !captureData?.capture_id || captureData.running) return;
  clearCaptureSummary();
  const token = summaryRevision, config = summaryConfig();
  summaryBusy = true; syncCaptureSummary();
  try {
    const result = await api("/api/capture/summary", config);
    if (token !== summaryRevision || captureData.running || result.capture_id !== captureData.capture_id) return;
    captureSummary = result;
    $("capture-summary-status").textContent = "总数 " + result.total_count + " · 满足条件 " + result.matched_count + " · 条件排除 " + result.rejected_count;
    $("capture-summary-result").innerHTML = '<table><thead><tr><th>字段</th><th>有效数</th><th>未参与数</th><th>均值</th><th>样本标准差</th><th>最小值</th><th>最大值</th></tr></thead><tbody>' +
      result.statistics.map(item => '<tr><td>' + esc(item.field) + '</td>' + [item.count,item.missing_count,fmt(item.mean),fmt(item.std),fmt(item.min),fmt(item.max)].map(v=>'<td>'+esc(v)+'</td>').join('') + '</tr>').join('') + '</tbody></table>';
    $("capture-summary-result").hidden = false;
  } catch (error) { notify(error.message, true); }
  finally { summaryBusy = false; syncCaptureSummary(); }
}
async function saveCaptureSummary() {
  if (!captureSummary || summaryBusy || summarySaving || featureBusy || captureData?.running || captureSummary.capture_id !== captureData?.capture_id) return;
  const name = $("capture-summary-name").value.trim();
  if (!name) { notify("请填写工况 / 记录名称。", true); return; }
  const input = $("capture-summary-reference"), text = input.value.trim();
  if (input.validity.badInput || (text && !numeric(text))) { notify("参考值必须为有限数值。", true); return; }
  const s = captureSummary;
  const record = {record_name:name, total_count:s.total_count, matched_count:s.matched_count,
    rejected_count:s.rejected_count, sample_mode:s.sample_mode, valid_field:s.valid_field, valid_value:s.valid_value,
    capture_id:s.capture_id, topic:s.topic, created_at:new Date().toISOString()};
  for (const item of s.statistics) for (const metric of ["count","missing_count","mean","std","min","max"]) {
    if (Object.hasOwn(record, item.field + "_" + metric)) {
      notify("统计列命名冲突，请分开汇总这些字段。", true); return;
    }
    Object.defineProperty(record, item.field + "_" + metric, {value:item[metric], enumerable:true, writable:true, configurable:true});
  }
  const referenceField = $("capture-summary-reference-name").value.trim();
  if (referenceField) {
    if (Object.hasOwn(record, referenceField) || referenceField === "summary_key") {
      notify("参考字段名与统计列或记录信息重名，请修改。", true); return;
    }
    Object.defineProperty(record, referenceField, {value:text ? Number(text) : null, enumerable:true, writable:true, configurable:true});
  } else if (text) { notify("填写参考值时也需要指定参考字段名。", true); return; }
  const key = JSON.stringify([s.capture_id,[...s.fields].sort(),s.sample_mode,s.valid_field,s.valid_value]);
  record.summary_key = key;
  let target = state.datasets.find(d => d.kind === "capture_statistics_summary");
  if (target?.rows.some(r => r.summary_key === key)) { notify("本次采集的相同配置已保存，可在数据表中编辑工况和参考值。", true); return; }
  summarySaving = true; syncCaptureSummary();
  try {
    if (!target) {
      target = addDataset("采集汇总记录", Object.keys(record), [record], "采集字段统计汇总");
      target.kind = "capture_statistics_summary"; target.x = s.fields[0] + "_mean"; target.y = referenceField || target.x;
      persist(); render(true);
    } else {
      if (target.rows.length >= 100000) throw Error("汇总记录已达到 100000 行上限。");
      await updateDataset(target, [...target.rows,record], target.derived || [], [...new Set([...target.columns,...Object.keys(record)])]);
    }
    notify("已追加到「" + target.name + "」。可继续采集下一个工况，或在数据探索页查看、拟合。");
    render();
  } catch (error) { notify(error.message, true); }
  finally { summarySaving = false; syncCaptureSummary(); }
}
function setupCaptureSummary() {
  for (const id of ["capture-summary-fields", "capture-summary-mode", "capture-summary-valid", "capture-summary-value"]) {
    $(id).onchange = () => { clearCaptureSummary(); syncCaptureSummary(); };
  }
  $("calculate-capture-summary").onclick = calculateCaptureSummary;
  $("save-capture-summary").onclick = saveCaptureSummary;
  syncCaptureSummary();
}
