(() => {
  const upscaleState = {
    record: null,
    data: { root: "", models: [], diskModels: [], restartRecommended: false, recommendations: [] },
    plan: null,
  };

  function installUpscaleStyles() {
    if (document.querySelector("#upscale-styles")) return;
    const style = document.createElement("style");
    style.id = "upscale-styles";
    style.textContent = `
      .upscale-overlay { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: rgba(4, 8, 12, .72); backdrop-filter: blur(6px); }
      .upscale-overlay[hidden] { display: none; }
      .upscale-card { width: min(620px, 100%); max-height: min(760px, calc(100vh - 40px)); overflow: auto; border: 1px solid var(--border, #303844); border-radius: 18px; background: var(--panel, #151b22); box-shadow: 0 24px 80px rgba(0,0,0,.45); padding: 20px; display: grid; gap: 16px; }
      .upscale-heading { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
      .upscale-heading h2 { margin: 0; }
      .upscale-choice-row { display:grid; grid-template-columns:110px minmax(0,1fr); gap:10px; }
      .upscale-choice-row .field { margin:0; }
      .upscale-note { padding: 12px; border-radius: 12px; background: rgba(255,255,255,.035); }
      .upscale-note code { word-break: break-all; }
      .upscale-note ul { margin: 8px 0; padding-left: 22px; }
      .upscale-note.is-error { color: var(--danger, #ef6f79); }
      .upscale-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
      @media (max-width:560px) { .upscale-choice-row { grid-template-columns:1fr; } }
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
        note.innerHTML = `<strong>Model file found on disk, but ComfyUI has not registered it yet.</strong><p>The file is in the correct StableAMD folder, so do not download or move it again.</p><ul></ul><p class="upscale-registration-hint"></p><code></code>`;
        const list = note.querySelector("ul");
        for (const model of diskModels) {
          const item = document.createElement("li");
          item.textContent = String(model);
          list.append(item);
        }
        note.querySelector(".upscale-registration-hint").textContent = restartRecommended
          ? "A full compute-backend restart is recommended so ComfyUI reloads the upscale_models search path. After restart, use Check again."
          : "Use Check again after ComfyUI refreshes its model list.";
        note.querySelector("code").textContent = root || ".runtime/stableamd/models/upscale_models";
        return;
      }

      note.innerHTML = `<strong>No stock upscale model detected.</strong><p>Place a compatible model such as <b>4x-UltraSharp</b>, <b>RealESRGAN x4plus</b> or <b>RealESRGAN x2plus</b> in:</p><code></code><p>Then use Check again. SeedVR2 remains a separate optional provider.</p>`;
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

  async function refreshUpscaleModels() {
    upscaleState.data = await api("/api/upscale-models");
    renderUpscaleModels();
  }

  async function refreshUpscaleModelsWithFeedback() {
    const button = document.querySelector("#upscale-refresh-models");
    const oldText = button?.textContent || "Check again";
    if (button) {
      button.disabled = true;
      button.textContent = "Checking…";
    }
    try {
      await refreshUpscaleModels();
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
    try {
      await refreshUpscaleModels();
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
