"use strict";
let deletedDatasets = [];

function normalizeProject(project, fallbackName = "未命名项目") {
  const datasets = Array.isArray(project.datasets) ? project.datasets : [];
  for (const d of datasets) d.excluded = [...excludedRows(d)];
  const { templates, ...metadata } = project;
  const name = typeof project.name === "string" && project.name.trim() ? project.name.trim() : fallbackName;
  return {
    ...metadata, version: 1, name, datasets,
    active: datasets.some(d => d.id === project.active) ? project.active : (datasets[0]?.id || null)
  };
}

function exportFilename(name, extension) {
  let stem = String(name || "未命名项目").trim().replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_")
    .replace(/[. ]+$/g, "").slice(0, 120);
  if (!stem) stem = "未命名项目";
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(stem)) stem = "_" + stem;
  return stem + "." + extension;
}

function renderProject() {
  $("rename-project").textContent = state.name;
  $("rename-project").title = "项目：" + state.name + " · 点击重命名";
  $("undo-delete").hidden = !deletedDatasets.length;
  document.title = state.name + " · Data Workbench";
}

async function deleteDataset(id) {
  if (featureBusy) { notify("数据正在更新，请稍后删除。", true); return; }
  const dataset = state.datasets.find(d => d.id === id);
  if (!dataset) return;
  const dialog = $("delete-dialog");
  if (dialog.open) return;
  $("delete-description").textContent = "确定删除「" + dataset.name + "」及其 " + dataset.rows.length + " 条记录、派生列和拟合设置？";
  dialog.returnValue = "cancel";
  dialog.showModal();
  const confirmed = await new Promise(resolve =>
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "delete"), { once: true }));
  if (!confirmed) return;
  if (featureBusy) { notify("数据正在更新，删除未执行，请稍后重试。", true); return; }
  const index = state.datasets.findIndex(d => d === dataset);
  if (index < 0) return;
  deletedDatasets.push({ dataset, index });
  if (deletedDatasets.length > 10) deletedDatasets.shift();
  state.datasets.splice(index, 1);
  if (state.active === id) state.active = state.datasets[Math.min(index, state.datasets.length - 1)]?.id || null;
  activePoint = null; page = 0; invalidate(); persist(); render(true);
  notify("已删除「" + dataset.name + "」。本次会话可通过侧栏撤销，已下载的文件不受影响。");
}

function undoDelete() {
  if (featureBusy) { notify("数据正在更新，请稍后撤销。", true); return; }
  const entry = deletedDatasets.pop();
  if (!entry) return;
  state.datasets.splice(Math.min(entry.index, state.datasets.length), 0, entry.dataset);
  state.active = entry.dataset.id;
  activePoint = null; page = 0; invalidate(); persist(); render(true);
  notify("已恢复数据集「" + entry.dataset.name + "」。");
}

async function importProject(project, filename) {
  if (!project || project.version !== 1 || !Array.isArray(project.datasets)) throw Error("请选择工作台项目 JSON。");
  for (const d of project.datasets) {
    if (!d || !Array.isArray(d.columns) || !d.columns.length || !d.columns.every(c => typeof c === "string") ||
      !Array.isArray(d.rows) || d.rows.length > 100000 || !d.rows.every(r => r && typeof r === "object" && !Array.isArray(r))) {
      throw Error("项目数据结构无效。");
    }
  }
  const token = revision;
  const datasets = [];
  // Prepare the entire import before changing the current project.
  for (const original of project.datasets) {
    const d = structuredClone(original);
    d.excluded = [...excludedRows(d)];
    if (d.derived?.length) Object.assign(d, await api("/api/derive", d));
    datasets.push({ ...d, id: crypto.randomUUID() });
  }
  if (token !== revision) throw Error("当前项目已变化，导入未写入，请重试。");
  const wasEmpty = state.datasets.length === 0;
  if (wasEmpty) state.name = normalizeProject(project, filename.replace(/\.json$/i, "") || "未命名项目").name;
  state.datasets.push(...datasets);
  if (datasets.length) {
    const originalActive = project.datasets.findIndex(d => d.id === project.active);
    state.active = datasets[originalActive >= 0 ? originalActive : 0].id;
  }
  activePoint = null; page = 0; invalidate(); persist(); render(true);
}

function setupProject() {
  state = normalizeProject(state);
  $("rename-project").onclick = async () => {
    const name = await ask("项目名称", state.name);
    if (!name) return;
    state.name = name; persist(); renderProject();
  };
  $("undo-delete").onclick = undoDelete;
  $("save-project").onclick = () => download(exportFilename(state.name, "json"), JSON.stringify(state, null, 2), "application/json");
}
