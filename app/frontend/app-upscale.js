(() => {
  const upscaleState = {
    record: null,
    data: { root: "", models: [], diskModels: [], restartRecommended: false, recommendations: [] },
    catalog: { root: "", models: [] },
    plan: null,
  };

  function installUpscaleStyles() {
    if (document.querySelector("#upscale-styles")) return;
    const style = document.createElement("style");
    style.id = "upscale-styles";
    style.textContent = `
      .upscale-overlay { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: rgba(4, 8, 12, .72); backdrop-filter: blur(6px); }
      .upscale-overlay[hidden] { display: none; }
      .upscale-card { width: min(700px, 100%); max-height: min(820px, calc(100vh - 40px)); overflow: auto; border: 1px solid var(--border, #303844); border-radius: 18px; background: var(--panel, #151b22); box-shadow: 0 24px 80px rgba(0,0,0,.45); padding: 20px; display: grid; gap: 16px; }
      .upscale-heading { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
      .upscale-heading h2 { margin: 0; }
      .upscale-choice-row { display:grid; grid-template-columns:110px minmax(0,1fr); gap:10px; }
      .upscale-choice-row .field { margin:0; }
      .upscale-note { padding: 12px; border-radius: 12px; background: rgba(255,255,255,.035); }
      .upscale-note code { word-break: break-all; }
      .upscale-note ul { margin: 8px 0; padding-left: 22px; }
      .upscale-note.is-error { color: var(--danger, #ef6f79); }
      .upscale-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
      .upscale-catalog { display:grid; gap:10px; padding-top:4px; }
      .upscale-catalog-heading { display:flex; justify-content:space-between; gap:12px; align-items:end; }
      .upscale-catalog-heading strong { font-size:14px; }
      .upscale-catalog-heading small { color:#9da9b7; }
      .upscale-install-list { display:grid; gap:8px; }
      .upscale-install-card { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px; align-items:center; border:1px solid var(--border, #303844); border-radius:12px; padding:11px 12px; background:rgba(255,255,255,.025); }
      .upscale-install-name { display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-weight:650; }
      .upscale-install-meta { margin-top:3px; font-size:12px; color:#9da9b7; line-height:1.4; }
      .upscale-license-warning { color:var(--warning, #e6b85c); font-weight:650; }
      .upscale-ready { color:var(--success, #74c991); font-weight:650; }
      .upscale-catalog-error { color:var(--danger, #ef6f79); }
      @media (max-width:560px) { .upscale-choice-row { grid-template-columns:1fr; } .upscale-install-card { grid-template-columns:1fr; } }
    `;
    document.head.append(style);
  }

  function ensureUpscaleUi() {
    let overlay = document.querySelector("#upscale-overlay");
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.id = "upscale-overlay";
    overlay.className = "upscale-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `
      <section class="upscale-card" role="dialog" aria-modal="true" aria-labelledby="upscale-title">
        <div class="upscale-heading">
          <div>
            <h2 id="upscale-title">Upscale image</h2>
            <p class="history-model">Classic local upscaling. StableAMD can chain small models to reach an exact target.</p>
          </div>
          <button class="button button-quiet" id="upscale-close" type="button" aria-label="Close upscale dialog">Close</button>
        </div>
        <div class="upscale-choice-row">
          <label class="field">
            <span>Target</span>
            <select id="upscale-factor">
              <option value="2">2x</option>
              <option value="4">4x</option>
              <option value="8">8x</option>
            </select>
          </label>
          <label class="field">
            <span>Upscale model</span>
            <select id="upscale-model"><option value="">Auto</option></select>
          </label>
        </div>
        <div class="upscale-note" id="upscale-model-note"></div>
        <div class="upscale-catalog">
          <div class="upscale-catalog-heading">
            <div><strong>Curated models</strong><br><small>Verified download + checksum, installed into StableAMD's managed folder.</small></div>
          </div>
          <div class="upscale-install-list" id="upscale-install-list"><div class="history-model">Loading curated models…</div></div>
        </div>
        <div class="upscale-actions">
          <button class="button button-quiet" id="upscale-refresh-models" type="button">Check again</button>
          <button class="button button-quiet" id="upscale-cancel" type="button">Cancel</button>
          <button class="button button-primary" id="upscale-run" type="button">Upscale</button>
        </div>
      </section>`;
    document.body.append(overlay);
    overlay.querySelector("#upscale-close").addEventListener("click", closeUpscale);
    overlay.querySelector("#upscale-cancel").addEventListener("click", closeUpscale);
    overlay.querySelector("#upscale-refresh-models").addEventListener("click", () => void refreshUpscaleModelsWithFeedback());
    overlay.querySelector("#upscale-factor").addEventListener("change", () => void refreshUpscalePlan());
    overlay.querySelector("#upscale-model").addEventListener("change", () => void refreshUpscalePlan());
    overlay.addEventListener("click", (event) => { if (event.target === overlay) closeUpscale(); });
    overlay.querySelector("#upscale-run").addEventListener("click", () => void runUpscale());
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !overlay.hidden) closeUpscale(); });
    return overlay;
  }

  function closeUpscale() {
    const overlay = document.querySelector("#upscale-overlay");
    if (overlay) overlay.hidden = true;
    upscaleState.record = null;
    upscaleState.plan = null;
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return "";
    return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  }

  async function refreshUpscalePlan() {
    const note = document.querySelector("#upscale-model-note");
    const run = document.querySelector("#upscale-run");
    const models = Array.isArray(upscaleState.data?.models) ? upscaleState.data.models : [];
    if (!note || !run || !models.length) return;
    const factor = Number(document.querySelector("#upscale-factor")?.value || 2);
    const modelName = document.querySelector("#upscale-model")?.value || "";
    const payload = { factor };
    if (modelName) payload.modelName = modelName;
    note.classList.remove("is-error");
    note.textContent = "Planning exact upscale chain…";
    run.disabled = true;
    try {
      const plan = await api("/api/upscale/plan", { method: "POST", body: JSON.stringify(payload) });
      upscaleState.plan = plan;
      const chain = Array.isArray(plan?.chain) ? plan.chain : [];
      const passes = Number(plan?.passes || chain.length || 0);
      note.innerHTML = `<strong>${factor}x ready · ${passes} pass${passes === 1 ? "" : "es"}</strong><p></p>`;
      note.querySelector("p").textContent = chain.join(" → ");
      run.disabled = false;
    } catch (error) {
      upscaleState.plan = null;
      note.classList.add("is-error");
      note.textContent = error.message;
      run.disabled = true;
    }
  }

  function renderUpscaleModels() {
    const select = document.querySelector("#upscale-model");
    const note = document.querySelector("#upscale-model-note");
    if (!select || !note) return;
    select.replaceChildren();
    const models = Array.isArray(upscaleState.data?.models) ? upscaleState.data.models : [];
    const diskModels = Array.isArray(upscaleState.data?.diskModels) ? upscaleState.data.diskModels : [];
    const restartRecommended = upscaleState.data?.restartRecommended === true;
    if (!models.length) {
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = diskModels.length ? "Model file found, waiting for ComfyUI" : "No upscale models installed";
      select.append(empty);
      select.disabled = true;
      document.querySelector("#upscale-factor").disabled = true;
      document.querySelector("#upscale-run").disabled = true;
      const root = String(upscaleState.data?.root || "");

      if (diskModels.length) {
        note.innerHTML = `<strong>Model file found on disk, but ComfyUI has not registered it yet.</strong><p>The file is in the correct StableAMD folder.</p><ul></ul><p class="upscale-registration-hint"></p><code></code>`;
        const list = note.querySelector("ul");
        for (const model of diskModels) {
          const item = document.createElement("li");
          item.textContent = String(model);
          list.append(item);
        }
        note.querySelector(".upscale-registration-hint").textContent = restartRecommended
          ? "Use Activate below or restart the compute backend so ComfyUI reloads the upscale_models search path."
          : "Use Check again after ComfyUI refreshes its model list.";
        note.querySelector("code").textContent = root || ".runtime/stableamd/models/upscale_models";
        return;
      }

      note.innerHTML = `<strong>No classic upscale model is ready.</strong><p>Install a verified model below. StableAMD will place it in the managed folder and can restart the compute backend to activate it.</p><code></code>`;
      note.querySelector("code").textContent = root || ".runtime/stableamd/models/upscale_models";
      return;
    }

    select.disabled = false;
    document.querySelector("#upscale-factor").disabled = false;
    const auto = document.createElement("option");
    auto.value = "";
    auto.textContent = "Auto";
    select.append(auto);
    for (const model of models) {
      const option = document.createElement("option");
      option.value = String(model);
      option.textContent = String(model);
      select.append(option);
    }
    void refreshUpscalePlan();
  }

  function renderCuratedCatalog() {
    const root = document.querySelector("#upscale-install-list");
    if (!root) return;
    root.replaceChildren();
    const models = Array.isArray(upscaleState.catalog?.models) ? upscaleState.catalog.models : [];
    if (!models.length) {
      const empty = document.createElement("div");
      empty.className = "upscale-catalog-error";
      empty.textContent = "Curated model catalog is unavailable.";
      root.append(empty);
      return;
    }

    for (const model of models) {
      const card = document.createElement("div");
      card.className = "upscale-install-card";
      const info = document.createElement("div");
      const name = document.createElement("div");
      name.className = "upscale-install-name";
      name.textContent = `${model.name} · native ${model.nativeScale}x`;
      if (model.ready) {
        const ready = document.createElement("span");
        ready.className = "upscale-ready";
        ready.textContent = "Ready";
        name.append(" ", ready);
      }
      const meta = document.createElement("div");
      meta.className = "upscale-install-meta";
      const details = [model.purpose, formatBytes(model.sizeBytes), model.license].filter(Boolean).join(" · ");
      meta.textContent = details;
      if (model.nonCommercial) {
        const warning = document.createElement("div");
        warning.className = "upscale-license-warning";
        warning.textContent = "Non-commercial license — CC BY-NC-SA 4.0.";
        meta.append(document.createElement("br"), warning);
      }
      if (model.homepage) {
        const link = document.createElement("a");
        link.href = model.homepage;
        link.target = "_blank";
        link.rel = "noreferrer noopener";
        link.textContent = "Source / license";
        meta.append(document.createTextNode(" · "), link);
      }
      info.append(name, meta);

      const button = document.createElement("button");
      button.type = "button";
      button.className = model.ready ? "button button-quiet" : "button button-secondary";
      button.disabled = Boolean(model.ready);
      button.textContent = model.ready ? "Ready" : (model.installedOnDisk ? "Activate" : "Install & activate");
      button.addEventListener("click", () => void installAndActivateCurated(model, button));
      card.append(info, button);
      root.append(card);
    }
  }

  async function refreshCuratedCatalog() {
    upscaleState.catalog = await api("/api/upscale-models/catalog");
    renderCuratedCatalog();
  }

  async function refreshUpscaleModels() {
    upscaleState.data = await api("/api/upscale-models");
    renderUpscaleModels();
  }

  async function refreshEverything() {
    await refreshUpscaleModels();
    try {
      await refreshCuratedCatalog();
    } catch (error) {
      const root = document.querySelector("#upscale-install-list");
      if (root) {
        root.innerHTML = "";
        const message = document.createElement("div");
        message.className = "upscale-catalog-error";
        message.textContent = `Curated model catalog unavailable: ${error.message}`;
        root.append(message);
      }
    }
  }

  async function refreshUpscaleModelsWithFeedback() {
    const button = document.querySelector("#upscale-refresh-models");
    const oldText = button?.textContent || "Check again";
    if (button) {
      button.disabled = true;
      button.textContent = "Checking…";
    }
    try {
      await refreshEverything();
      const ready = Array.isArray(upscaleState.data?.models) ? upscaleState.data.models.length : 0;
      if (ready) showToast(`${ready} upscale model${ready === 1 ? "" : "s"} ready.`, "success");
    } catch (error) {
      showToast(`Upscale models unavailable: ${error.message}`, "error");
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = oldText;
      }
    }
  }

  async function installAndActivateCurated(model, button) {
    const oldText = button.textContent;
    button.disabled = true;
    try {
      let result = { restartRequired: Boolean(model.installedOnDisk && !model.ready), filename: model.filename };
      if (!model.installedOnDisk) {
        button.textContent = "Downloading…";
        result = await api("/api/upscale-models/install", {
          method: "POST",
          body: JSON.stringify({ id: model.id }),
        });
      }

      if (result?.restartRequired || !result?.ready) {
        button.textContent = "Activating…";
        showToast(`${model.name} installed. Restarting the compute backend to activate it…`, "success");
        await api("/api/backend/restart", { method: "POST", body: "{}" });
      }

      button.textContent = "Checking…";
      await refreshEverything();
      const refreshed = (upscaleState.catalog?.models || []).find((item) => item.id === model.id);
      if (refreshed?.ready) {
        const select = document.querySelector("#upscale-model");
        if (select && Array.from(select.options).some((option) => option.value === refreshed.filename)) {
          select.value = refreshed.filename;
          await refreshUpscalePlan();
        }
        showToast(`${model.name} is ready.`, "success");
      } else {
        showToast(`${model.name} is installed, but ComfyUI has not registered it yet.`, "error");
      }
    } catch (error) {
      showToast(`Upscaler install failed: ${error.message}`, "error");
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  async function openStableAmdUpscale(record) {
    installUpscaleStyles();
    const overlay = ensureUpscaleUi();
    upscaleState.record = record;
    upscaleState.plan = null;
    overlay.hidden = false;
    overlay.querySelector("#upscale-factor").value = "2";
    const select = overlay.querySelector("#upscale-model");
    select.disabled = true;
    select.replaceChildren(new Option("Loading models…", ""));
    overlay.querySelector("#upscale-run").disabled = true;
    overlay.querySelector("#upscale-model-note").textContent = "Querying the managed ComfyUI backend…";
    overlay.querySelector("#upscale-install-list").innerHTML = '<div class="history-model">Loading curated models…</div>';
    try {
      await refreshEverything();
    } catch (error) {
      overlay.querySelector("#upscale-model-note").textContent = `Upscale models unavailable: ${error.message}`;
      showToast(`Upscale models unavailable: ${error.message}`, "error");
    }
  }

  async function runUpscale() {
    const record = upscaleState.record;
    const imagePath = String(getValue(record, "imagePath", "ImagePath") || "");
    const factor = Number(document.querySelector("#upscale-factor")?.value || 2);
    const modelName = document.querySelector("#upscale-model")?.value || "";
    if (!imagePath || ![2, 4, 8].includes(factor)) {
      showToast("Choose a valid upscale target first.", "error");
      return;
    }
    const button = document.querySelector("#upscale-run");
    const oldText = button.textContent;
    button.disabled = true;
    button.textContent = `Upscaling ${factor}x…`;
    try {
      const payload = { imagePath, factor };
      if (modelName) payload.modelName = modelName;
      const result = await api("/api/upscale", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      closeUpscale();
      const passes = Number(getValue(result, "UpscalePasses", "upscalePasses") || 1);
      showToast(`Upscale ${factor}x complete · ${passes} pass${passes === 1 ? "" : "es"}.`, "success");
      if (typeof refreshHistory === "function") await refreshHistory();
      if (typeof setPage === "function") setPage("gallery");
    } catch (error) {
      showToast(`Upscale failed: ${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    installUpscaleStyles();
    ensureUpscaleUi();
  });

  window.openStableAmdUpscale = openStableAmdUpscale;
})();
