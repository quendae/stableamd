const pageMeta = {
  generate: ["Generate", "Create an SDXL image on your Radeon GPU."],
  models: ["Models", "Install and manage checkpoints available to StableAMD."],
  gallery: ["Gallery", "Browse recent generations and reuse their settings."],
  settings: ["Settings", "StableAMD v0.1 runtime and generation defaults."],
  diagnostics: ["Diagnostics", "Inspect backend health and runtime logs."],
};

const state = { models: [], history: [], status: null };
const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => Array.from(document.querySelectorAll(selector));

function getValue(obj, ...keys) {
  for (const key of keys) {
    if (obj && Object.prototype.hasOwnProperty.call(obj, key)) return obj[key];
  }
  return undefined;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); }
    catch { payload = { error: text }; }
  }
  if (!response.ok) throw new Error(payload?.error || `${response.status} ${response.statusText}`);
  return payload;
}

function imageUrl(path) {
  return `/api/image?path=${encodeURIComponent(path)}`;
}

function showToast(message, kind = "info") {
  const toast = qs("#toast");
  toast.textContent = message;
  toast.dataset.kind = kind;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 5000);
}

function setPage(name) {
  qsa(".page").forEach((page) => page.classList.toggle("is-visible", page.dataset.page === name));
  qsa(".nav-item").forEach((item) => {
    const active = item.dataset.page === name;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
  });
  const [title, subtitle] = pageMeta[name] || pageMeta.generate;
  qs("#page-title").textContent = title;
  qs("#page-subtitle").textContent = subtitle;
  if (name === "gallery") refreshHistory();
  if (name === "diagnostics") refreshDiagnostics();
}

function renderStatus(status) {
  state.status = status;
  const statusName = String(getValue(status, "Status", "status") || "unknown").toLowerCase();
  const healthy = Boolean(getValue(status, "Healthy", "healthy"));
  qs("#runtime-status").textContent = healthy ? "Backend ready" : statusName === "stopped" ? "Backend stopped" : `Backend ${statusName}`;
  qs("#runtime-dot").dataset.state = healthy ? "ready" : statusName;
}

async function refreshStatus() {
  try { renderStatus(await api("/api/status")); }
  catch (error) {
    qs("#runtime-status").textContent = "Backend unavailable";
    qs("#runtime-dot").dataset.state = "error";
    showToast(error.message, "error");
  }
}

function normalizeModels(payload) {
  if (!payload) return [];
  return Array.isArray(payload) ? payload : [payload];
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "size unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function renderModels(models) {
  state.models = models;
  const select = qs("#model-select");
  const previous = select.value;
  select.replaceChildren();
  const sdxl = models.filter((model) => String(getValue(model, "family", "Family") || "").toLowerCase() === "sdxl");
  if (!sdxl.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No SDXL checkpoints found";
    select.append(option);
  } else {
    for (const model of sdxl) {
      const option = document.createElement("option");
      option.value = String(getValue(model, "id", "Id") || "");
      option.textContent = String(getValue(model, "name", "Name") || option.value);
      select.append(option);
    }
    if (previous && sdxl.some((model) => String(getValue(model, "id", "Id")) === previous)) select.value = previous;
  }

  const list = qs("#model-list");
  list.replaceChildren();
  if (!models.length) {
    list.innerHTML = '<div class="empty-state"><strong>No checkpoints found</strong><p>Import a local .safetensors checkpoint or download one from Hugging Face.</p></div>';
    return;
  }
  for (const model of models) {
    const row = document.createElement("article");
    row.className = "model-row";
    row.innerHTML = '<div class="model-main"><strong></strong><span></span></div><div class="model-meta"><span></span><span></span></div>';
    row.querySelector("strong").textContent = String(getValue(model, "name", "Name") || "Unnamed model");
    row.querySelector(".model-main span").textContent = String(getValue(model, "path", "Path") || "");
    row.querySelectorAll(".model-meta span")[0].textContent = String(getValue(model, "family", "Family") || "unknown").toUpperCase();
    row.querySelectorAll(".model-meta span")[1].textContent = `${getValue(model, "source", "Source") || "discovered"} · ${formatBytes(Number(getValue(model, "sizeBytes", "SizeBytes") || 0))}`;
    list.append(row);
  }
}

async function refreshModels() {
  try { renderModels(normalizeModels(await api("/api/models"))); }
  catch (error) { showToast(`Model scan failed: ${error.message}`, "error"); }
}

async function installModel(form, payload) {
  const button = form.querySelector('button[type="submit"]');
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = payload.source === "local" ? "Importing…" : "Downloading…";
  try {
    const result = await api("/api/models/install", { method: "POST", body: JSON.stringify(payload) });
    await refreshModels();
    showToast(`Model ready: ${getValue(result, "name", "Name") || "checkpoint"}`, "success");
    if (payload.source === "local") {
      qs("#local-model-path").value = "";
      qs("#local-model-sha").value = "";
      qs("#local-model-move").checked = false;
    }
  } catch (error) {
    showToast(`Model install failed: ${error.message}`, "error");
  } finally {
    button.disabled = false;
    button.textContent = oldText;
  }
}

function submitLocalModel(event) {
  event.preventDefault();
  installModel(event.currentTarget, {
    source: "local",
    localPath: qs("#local-model-path").value.trim(),
    moveLocal: qs("#local-model-move").checked,
    expectedSha256: qs("#local-model-sha").value.trim(),
  });
}

function submitHuggingFaceModel(event) {
  event.preventDefault();
  installModel(event.currentTarget, {
    source: "huggingface",
    repository: qs("#hf-repository").value.trim(),
    filename: qs("#hf-filename").value.trim(),
    revision: qs("#hf-revision").value.trim() || "main",
    token: qs("#hf-token").value,
    expectedSha256: qs("#hf-sha").value.trim(),
  });
}

function formatDate(value) {
  if (!value) return "Unknown time";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function makeHistoryVisual(record) {
  const visual = document.createElement("div");
  visual.className = "history-visual";
  const imagePath = getValue(record, "imagePath", "ImagePath");
  if (imagePath) {
    const image = document.createElement("img");
    image.src = imageUrl(String(imagePath));
    image.alt = String(getValue(record, "prompt", "Prompt") || "Generated StableAMD image");
    image.loading = "lazy";
    image.addEventListener("error", () => {
      image.remove();
      const fallback = document.createElement("span");
      fallback.textContent = "Image unavailable";
      visual.append(fallback);
    }, { once: true });
    visual.append(image);
  } else {
    const fallback = document.createElement("span");
    fallback.textContent = "SDXL";
    visual.append(fallback);
  }
  return visual;
}

function renderHistory(records) {
  state.history = Array.isArray(records) ? records : [];
  const grid = qs("#gallery-grid");
  grid.replaceChildren();
  if (!state.history.length) {
    grid.innerHTML = '<div class="empty-state"><strong>No generations yet</strong><p>Your successful StableAMD generations will appear here.</p></div>';
    return;
  }
  state.history.forEach((record, index) => {
    const card = document.createElement("article");
    card.className = "history-card";
    card.append(makeHistoryVisual(record));

    const body = document.createElement("div");
    body.className = "history-body";
    const prompt = document.createElement("strong");
    prompt.className = "history-prompt";
    prompt.textContent = String(getValue(record, "prompt", "Prompt") || "Untitled generation");
    const model = document.createElement("p");
    model.className = "history-model";
    model.textContent = String(getValue(record, "modelName", "ModelName") || "Unknown model");
    const meta = document.createElement("div");
    meta.className = "history-meta";
    const size = document.createElement("span");
    size.textContent = `${getValue(record, "width", "Width") || "?"} × ${getValue(record, "height", "Height") || "?"} · seed ${getValue(record, "seed", "Seed") ?? "random"}`;
    const created = document.createElement("span");
    created.textContent = formatDate(getValue(record, "createdAtUtc", "CreatedAtUtc"));
    meta.append(size, created);
    const reuse = document.createElement("button");
    reuse.className = "button button-quiet reuse-button";
    reuse.type = "button";
    reuse.dataset.historyIndex = String(index);
    reuse.textContent = "Reuse settings";
    body.append(prompt, model, meta, reuse);
    card.append(body);
    grid.append(card);
  });
}

async function refreshHistory() {
  try { renderHistory(await api("/api/history?limit=60")); }
  catch (error) { showToast(`Gallery refresh failed: ${error.message}`, "error"); }
}

function reuseHistory(index) {
  const record = state.history[index];
  if (!record) return;
  qs("#prompt").value = getValue(record, "prompt", "Prompt") || "";
  qs("#negative-prompt").value = getValue(record, "negativePrompt", "NegativePrompt") || "";
  qs("#width").value = getValue(record, "width", "Width") || 1024;
  qs("#height").value = getValue(record, "height", "Height") || 1024;
  qs("#steps").value = getValue(record, "steps", "Steps") || 20;
  qs("#cfg").value = getValue(record, "cfg", "Cfg") || 7;
  qs("#seed").value = getValue(record, "seed", "Seed") ?? "";
  qs("#sampler").value = getValue(record, "sampler", "Sampler") || "euler";
  qs("#scheduler").value = getValue(record, "scheduler", "Scheduler") || "normal";
  const modelId = getValue(record, "modelId", "ModelId");
  if (modelId && qsa("#model-select option").some((option) => option.value === String(modelId))) qs("#model-select").value = String(modelId);
  setPage("generate");
  qs("#prompt").focus();
  showToast("Generation settings restored.");
}

async function refreshDiagnostics() {
  try {
    const data = await api("/api/diagnostics");
    qs("#diagnostics-runtime").textContent = JSON.stringify(data?.runtime || {}, null, 2);
    const list = qs("#diagnostics-logs");
    list.replaceChildren();
    const logs = Array.isArray(data?.logs) ? data.logs : [];
    if (!logs.length) {
      list.innerHTML = '<div class="empty-state"><strong>No runtime logs found</strong><p>Logs appear after managed backend sessions.</p></div>';
      return;
    }
    for (const log of logs) {
      const row = document.createElement("div");
      row.className = "log-row";
      const name = document.createElement("strong");
      name.textContent = log.name || "log";
      const path = document.createElement("span");
      path.textContent = log.path || "";
      row.append(name, path);
      list.append(row);
    }
  } catch (error) { showToast(`Diagnostics failed: ${error.message}`, "error"); }
}

function readNumber(id, fallback = undefined) {
  const value = qs(id).value.trim();
  if (value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

async function submitGeneration(event) {
  event.preventDefault();
  const button = qs("#generate-button");
  const prompt = qs("#prompt").value.trim();
  const modelId = qs("#model-select").value;
  if (!prompt) { showToast("Enter a prompt first.", "error"); qs("#prompt").focus(); return; }
  if (!modelId) { showToast("Select an SDXL checkpoint first.", "error"); return; }

  const payload = {
    prompt,
    negativePrompt: qs("#negative-prompt").value,
    modelId,
    width: readNumber("#width", 1024),
    height: readNumber("#height", 1024),
    steps: readNumber("#steps", 20),
    cfg: readNumber("#cfg", 7),
    samplerName: qs("#sampler").value.trim() || "euler",
    scheduler: qs("#scheduler").value.trim() || "normal",
    startBackendIfNeeded: true,
  };
  const seed = readNumber("#seed");
  if (seed !== undefined) payload.seed = seed;

  button.disabled = true;
  button.textContent = "Generating…";
  qs("#result-empty").hidden = false;
  qs("#result-empty strong").textContent = "Generation in progress";
  qs("#result-empty p").textContent = "StableAMD is running the SDXL workflow. This can take a while on the first run.";
  qs("#result-details").hidden = true;
  try {
    const result = await api("/api/generate", { method: "POST", body: JSON.stringify(payload) });
    renderGenerationResult(result);
    await Promise.allSettled([refreshHistory(), refreshStatus()]);
    showToast("Generation completed.", "success");
  } catch (error) {
    qs("#result-empty strong").textContent = "Generation failed";
    qs("#result-empty p").textContent = error.message;
    showToast(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Generate image";
  }
}

function renderGenerationResult(result) {
  qs("#result-empty").hidden = true;
  const target = qs("#result-details");
  target.hidden = false;
  target.replaceChildren();
  const imagePath = getValue(result, "ImagePath", "imagePath");
  if (imagePath) {
    const image = document.createElement("img");
    image.className = "result-image";
    image.src = imageUrl(String(imagePath));
    image.alt = String(getValue(result, "Prompt", "prompt") || "Generated StableAMD image");
    target.append(image);
  }
  const title = document.createElement("strong");
  title.className = "result-title";
  title.textContent = "Generation complete";
  const path = document.createElement("code");
  path.textContent = imagePath || "Image path unavailable";
  const meta = document.createElement("dl");
  meta.className = "result-meta";
  const items = [
    ["Model", getValue(result, "ModelName", "modelName")],
    ["Size", `${getValue(result, "Width", "width")} × ${getValue(result, "Height", "height")}`],
    ["Seed", getValue(result, "Seed", "seed")],
    ["Time", `${getValue(result, "GenerationSeconds", "generationSeconds") ?? "?"} s`],
  ];
  for (const [label, value] of items) {
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = value ?? "—";
    meta.append(dt, dd);
  }
  target.append(title, path, meta);
}

async function backendAction(action) {
  const button = qs(`#backend-${action}`);
  button.disabled = true;
  try {
    const status = await api(`/api/backend/${action}`, { method: "POST", body: "{}" });
    renderStatus(status);
    showToast(action === "start" ? "Backend started." : "Backend stopped.", "success");
  } catch (error) { showToast(error.message, "error"); }
  finally { button.disabled = false; await refreshStatus(); }
}

async function refreshCurrentPage() {
  await Promise.allSettled([refreshStatus(), refreshModels()]);
  const visible = qs(".page.is-visible")?.dataset.page;
  if (visible === "gallery") await refreshHistory();
  if (visible === "diagnostics") await refreshDiagnostics();
}

function bindEvents() {
  qsa(".nav-item").forEach((item) => item.addEventListener("click", () => setPage(item.dataset.page)));
  qs("#generate-form").addEventListener("submit", submitGeneration);
  qs("#local-model-form").addEventListener("submit", submitLocalModel);
  qs("#hf-model-form").addEventListener("submit", submitHuggingFaceModel);
  qs("#backend-start").addEventListener("click", () => backendAction("start"));
  qs("#backend-stop").addEventListener("click", () => backendAction("stop"));
  qs("#refresh-button").addEventListener("click", refreshCurrentPage);
  qs("#models-refresh").addEventListener("click", refreshModels);
  qs("#gallery-refresh").addEventListener("click", refreshHistory);
  qs("#diagnostics-refresh").addEventListener("click", refreshDiagnostics);
  qs("#gallery-grid").addEventListener("click", (event) => {
    const button = event.target.closest("[data-history-index]");
    if (button) reuseHistory(Number(button.dataset.historyIndex));
  });
}

async function boot() {
  bindEvents();
  await Promise.allSettled([refreshStatus(), refreshModels()]);
}

document.addEventListener("DOMContentLoaded", boot);
