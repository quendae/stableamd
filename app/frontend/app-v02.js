(() => {
  pageMeta.settings = ["Settings", "StableAMD v0.3 runtime, model capabilities and generation defaults."];

  const v02State = {
    generationOptions: { samplers: [], schedulers: [], loras: [] },
    profileCatalog: { profiles: [] },
    modelSupport: { models: [] },
    loraRoots: [],
  };

  const baseApi = api;

  function fillSelect(select, values, preferred, emptyLabel = null) {
    if (!select) return;
    const available = Array.isArray(values) ? values.map(String).filter(Boolean) : [];
    const previous = select.value;
    select.replaceChildren();

    if (emptyLabel !== null) {
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = emptyLabel;
      select.append(empty);
    } else if (!available.length && preferred) {
      available.push(String(preferred));
    }

    for (const value of available) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.append(option);
    }

    const target = [previous, preferred].find((candidate) =>
      candidate !== undefined && Array.from(select.options).some((option) => option.value === String(candidate))
    );
    if (target !== undefined) select.value = String(target);
  }

  function supportForCurrentModel() {
    const modelId = document.querySelector("#model-select")?.value || "";
    const entries = Array.isArray(v02State.modelSupport?.models) ? v02State.modelSupport.models : [];
    return entries.find((entry) => String(entry?.id || "") === String(modelId)) || null;
  }

  function maxLoraStack() {
    const support = supportForCurrentModel();
    const value = Number(support?.loraPolicy?.maxStack ?? 0);
    if (Number.isInteger(value) && value > 0) return Math.min(8, value);
    return support?.capabilities?.lora === "supported" ? 1 : 0;
  }

  function ensureModelSupportHint() {
    let hint = document.querySelector("#model-support-hint");
    if (hint) return hint;
    const modelField = document.querySelector("#model-select")?.closest(".field");
    if (!modelField) return null;
    hint = document.createElement("p");
    hint.id = "model-support-hint";
    hint.className = "history-model";
    hint.setAttribute("aria-live", "polite");
    modelField.append(hint);
    return hint;
  }

  function renderModelSupportHint() {
    const hint = ensureModelSupportHint();
    if (!hint) return;
    const support = supportForCurrentModel();
    if (!support) {
      hint.textContent = "Model capabilities will appear after model discovery.";
      return;
    }
    const caps = support.capabilities || {};
    const family = support.label || support.family || "Unknown model";
    const parts = [
      `txt2img ${caps.txt2img || "unsupported"}`,
      `img2img ${caps.img2img || "unsupported"}`,
      `inpaint ${caps.inpaint || "unsupported"}`,
      `ControlNet ${caps.controlnet || "unsupported"}`,
    ];
    const maxStack = Number(support?.loraPolicy?.maxStack || 0);
    if (caps.lora === "supported") parts.push(maxStack > 1 ? `LoRA stack up to ${maxStack}` : "LoRA supported");
    hint.textContent = `${family} · ${parts.join(" · ")}`;
    syncLoraStackAvailability();
  }

  function syncLegacyLoraStrengthState() {
    const enabled = Boolean(document.querySelector("#lora-select")?.value);
    for (const id of ["#lora-model-strength", "#lora-clip-strength"]) {
      const input = document.querySelector(id);
      if (input) input.disabled = !enabled;
    }
  }

  function ensureProfileControl() {
    if (document.querySelector("#generation-profile")) return document.querySelector("#generation-profile");
    const modelSelect = document.querySelector("#model-select");
    const modelField = modelSelect?.closest(".field");
    if (!modelField) return null;

    const field = document.createElement("label");
    field.className = "field";
    field.innerHTML = `
      <span>Generation preset <small>matched to the selected model</small></span>
      <select id="generation-profile" name="generationProfile"><option value="">Custom</option></select>`;
    modelField.after(field);
    const select = field.querySelector("select");
    select.addEventListener("change", applySelectedProfile);
    return select;
  }

  function currentModel() {
    const modelId = document.querySelector("#model-select")?.value;
    return state.models.find((model) => String(getValue(model, "id", "Id") || "") === String(modelId || "")) || null;
  }

  function profileMatchesModel(profile, model) {
    if (!profile || !model) return false;
    const name = String(getValue(model, "name", "Name") || "");
    const family = String(getValue(model, "family", "Family") || "").toLowerCase();
    const patterns = Array.isArray(profile?.match?.namePatterns) ? profile.match.namePatterns : [];
    for (const pattern of patterns) {
      try {
        if (new RegExp(pattern, "i").test(name)) return true;
      } catch { }
    }
    return family && family === String(profile.family || "").toLowerCase();
  }

  function matchedProfile() {
    const model = currentModel();
    const profiles = Array.isArray(v02State.profileCatalog?.profiles) ? v02State.profileCatalog.profiles : [];
    return profiles.find((profile) => profileMatchesModel(profile, model)) || null;
  }

  function populateProfileControl(applyDefault = false) {
    const select = ensureProfileControl();
    if (!select) return;
    const previous = select.value;
    select.replaceChildren();

    const custom = document.createElement("option");
    custom.value = "";
    custom.textContent = "Custom";
    select.append(custom);

    const profile = matchedProfile();
    const combinations = Array.isArray(profile?.combinations) ? profile.combinations : [];
    for (const combination of combinations) {
      const option = document.createElement("option");
      option.value = `${profile.id}::${combination.id}`;
      option.textContent = `${profile.label} · ${combination.label}`;
      select.append(option);
    }

    if (previous && Array.from(select.options).some((option) => option.value === previous)) {
      select.value = previous;
      return;
    }

    if (applyDefault && combinations.length) {
      select.value = `${profile.id}::${combinations[0].id}`;
      applySelectedProfile();
    }
  }

  function setIfOptionExists(selector, value) {
    const select = document.querySelector(selector);
    if (!select || !value) return;
    if (Array.from(select.options).some((option) => option.value === String(value))) select.value = String(value);
  }

  function applySelectedProfile() {
    const select = document.querySelector("#generation-profile");
    if (!select?.value) return;
    const [profileId, combinationId] = select.value.split("::");
    const profiles = Array.isArray(v02State.profileCatalog?.profiles) ? v02State.profileCatalog.profiles : [];
    const profile = profiles.find((item) => String(item.id) === profileId);
    const combination = profile?.combinations?.find((item) => String(item.id) === combinationId);
    if (!profile || !combination) return;

    const defaults = profile.defaults || {};
    if (defaults.width) document.querySelector("#width").value = defaults.width;
    if (defaults.height) document.querySelector("#height").value = defaults.height;
    if (combination.steps) document.querySelector("#steps").value = combination.steps;
    if (combination.cfg !== undefined) document.querySelector("#cfg").value = combination.cfg;
    setIfOptionExists("#sampler", combination.sampler || defaults.sampler);
    setIfOptionExists("#scheduler", combination.scheduler || defaults.scheduler);
  }

  function loraChoices() {
    return Array.isArray(v02State.generationOptions?.loras) ? v02State.generationOptions.loras.map(String).filter(Boolean) : [];
  }

  function populateLoraRowSelect(select, preferred = "") {
    if (!select) return;
    const previous = preferred || select.value;
    select.replaceChildren();
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "Choose LoRA…";
    select.append(empty);
    for (const value of loraChoices()) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.append(option);
    }
    if (previous && Array.from(select.options).some((option) => option.value === String(previous))) select.value = String(previous);
  }

  function ensureLoraStackUi() {
    let panel = document.querySelector("#lora-stack-panel");
    if (panel) return panel;

    const legacySelect = document.querySelector("#lora-select");
    const legacyField = legacySelect?.closest(".field");
    const legacyStrengthGrid = document.querySelector("#lora-model-strength")?.closest(".field-grid");
    if (!legacyField || !legacyStrengthGrid) return null;

    legacyField.hidden = true;
    legacyStrengthGrid.hidden = true;

    panel = document.createElement("div");
    panel.id = "lora-stack-panel";
    panel.className = "model-root-card";
    panel.innerHTML = `
      <div class="section-toolbar">
        <div>
          <strong>LoRA stack</strong>
          <p>LoRAs are applied from top to bottom. Each entry has independent model and CLIP strength.</p>
        </div>
        <button class="button button-secondary" id="lora-stack-add" type="button">Add LoRA</button>
      </div>
      <div id="lora-stack-list"></div>
      <p id="lora-stack-limit" class="history-model"></p>`;
    legacyStrengthGrid.after(panel);
    panel.querySelector("#lora-stack-add").addEventListener("click", () => addLoraStackRow());
    panel.querySelector("#lora-stack-list").addEventListener("click", handleLoraStackAction);
    panel.querySelector("#lora-stack-list").addEventListener("change", (event) => {
      if (event.target.matches('[data-lora-name], [data-lora-enabled]')) syncLoraStackRow(event.target.closest("[data-lora-stack-row]"));
    });
    syncLoraStackAvailability();
    return panel;
  }

  function makeLoraStackRow(entry = {}) {
    const row = document.createElement("div");
    row.className = "model-root-row";
    row.dataset.loraStackRow = "";
    row.innerHTML = `
      <div class="model-root-main">
        <label class="checkbox-field"><input type="checkbox" data-lora-enabled checked> <span>Enabled</span></label>
        <label class="field"><span>LoRA</span><select data-lora-name></select></label>
        <div class="field-grid field-grid-2">
          <label class="field"><span>Model strength</span><input data-lora-model-strength type="number" min="-4" max="4" step="0.05" value="1"></label>
          <label class="field"><span>CLIP strength</span><input data-lora-clip-strength type="number" min="-4" max="4" step="0.05" value="1"></label>
        </div>
      </div>
      <div class="model-root-actions">
        <button class="button button-quiet" type="button" data-lora-action="up" aria-label="Move LoRA up">↑</button>
        <button class="button button-quiet" type="button" data-lora-action="down" aria-label="Move LoRA down">↓</button>
        <button class="button button-quiet" type="button" data-lora-action="remove">Remove</button>
      </div>`;

    populateLoraRowSelect(row.querySelector("[data-lora-name]"), String(entry?.name || ""));
    row.querySelector("[data-lora-enabled]").checked = entry?.enabled !== false;
    row.querySelector("[data-lora-model-strength]").value = entry?.modelStrength ?? 1;
    row.querySelector("[data-lora-clip-strength]").value = entry?.clipStrength ?? 1;
    syncLoraStackRow(row);
    return row;
  }

  function loraStackRows() {
    return Array.from(document.querySelectorAll("[data-lora-stack-row]"));
  }

  function addLoraStackRow(entry = {}) {
    const panel = ensureLoraStackUi();
    if (!panel) return;
    const max = maxLoraStack();
    const rows = loraStackRows();
    if (max <= 0) {
      showToast("The selected model does not currently support LoRA in StableAMD.", "error");
      return;
    }
    if (rows.length >= max) {
      showToast(`This model supports at most ${max} LoRA${max === 1 ? "" : "s"} in the current StableAMD profile.`, "error");
      return;
    }
    panel.querySelector("#lora-stack-list").append(makeLoraStackRow(entry));
    syncLoraStackAvailability();
  }

  function syncLoraStackRow(row) {
    if (!row) return;
    const enabled = row.querySelector("[data-lora-enabled]")?.checked !== false;
    const hasName = Boolean(row.querySelector("[data-lora-name]")?.value);
    for (const input of row.querySelectorAll("[data-lora-model-strength], [data-lora-clip-strength]")) input.disabled = !enabled || !hasName;
  }

  function syncLoraStackAvailability() {
    const panel = document.querySelector("#lora-stack-panel");
    if (!panel) return;
    const max = maxLoraStack();
    const count = loraStackRows().length;
    const button = panel.querySelector("#lora-stack-add");
    if (button) button.disabled = max <= 0 || count >= max;
    const limit = panel.querySelector("#lora-stack-limit");
    if (limit) limit.textContent = max > 0 ? `${count}/${max} LoRA slots used` : "LoRA is not enabled for this model family yet.";
    for (const row of loraStackRows()) syncLoraStackRow(row);
  }

  function handleLoraStackAction(event) {
    const button = event.target.closest("[data-lora-action]");
    const row = button?.closest("[data-lora-stack-row]");
    if (!button || !row) return;
    const action = button.dataset.loraAction;
    if (action === "remove") row.remove();
    if (action === "up" && row.previousElementSibling) row.parentElement.insertBefore(row, row.previousElementSibling);
    if (action === "down" && row.nextElementSibling) row.parentElement.insertBefore(row.nextElementSibling, row);
    syncLoraStackAvailability();
  }

  function collectLoraStack() {
    const stack = [];
    for (const row of loraStackRows()) {
      const name = row.querySelector("[data-lora-name]")?.value || "";
      if (!name) continue;
      const modelStrength = Number(row.querySelector("[data-lora-model-strength]")?.value ?? 1);
      const clipStrength = Number(row.querySelector("[data-lora-clip-strength]")?.value ?? 1);
      stack.push({
        name,
        modelStrength: Number.isFinite(modelStrength) ? modelStrength : 1,
        clipStrength: Number.isFinite(clipStrength) ? clipStrength : 1,
        enabled: row.querySelector("[data-lora-enabled]")?.checked !== false,
      });
    }
    return stack;
  }

  function renderLoraStack(entries) {
    ensureLoraStackUi();
    const list = document.querySelector("#lora-stack-list");
    if (!list) return;
    list.replaceChildren();
    const stack = Array.isArray(entries) ? entries : [];
    for (const entry of stack.slice(0, Math.max(0, maxLoraStack()))) list.append(makeLoraStackRow(entry));
    syncLoraStackAvailability();
  }

  api = async function v03Api(path, options = {}) {
    if (path === "/api/generate" && String(options?.method || "GET").toUpperCase() === "POST") {
      let payload = {};
      try { payload = options.body ? JSON.parse(options.body) : {}; }
      catch { payload = {}; }
      const loraStack = collectLoraStack();
      delete payload.loraName;
      delete payload.loraModelStrength;
      delete payload.loraClipStrength;
      if (loraStack.length) payload.loraStack = loraStack;
      else delete payload.loraStack;
      return baseApi(path, { ...options, body: JSON.stringify(payload) });
    }
    return baseApi(path, options);
  };

  async function refreshGenerationOptions() {
    try {
      const [options, catalog, modelSupport] = await Promise.all([
        api("/api/generation-options"),
        api("/api/generation-profiles"),
        api("/api/model-support"),
      ]);
      v02State.generationOptions = options || { samplers: [], schedulers: [], loras: [] };
      v02State.profileCatalog = catalog || { profiles: [] };
      v02State.modelSupport = modelSupport || { models: [] };
      fillSelect(document.querySelector("#sampler"), options?.samplers, "euler");
      fillSelect(document.querySelector("#scheduler"), options?.schedulers, "normal");
      fillSelect(document.querySelector("#lora-select"), options?.loras, "", "None");
      syncLegacyLoraStrengthState();
      for (const select of document.querySelectorAll("[data-lora-name]")) populateLoraRowSelect(select, select.value);
      populateProfileControl(false);
      renderModelSupportHint();
      syncLoraStackAvailability();
    } catch (error) {
      syncLegacyLoraStrengthState();
      showToast(`Generation options unavailable: ${error.message}`, "error");
    }
  }

  function restoreLoraSettings(index) {
    const record = state.history[index];
    if (!record) return;

    const historyStack = getValue(record, "loraStack", "LoraStack");
    if (Array.isArray(historyStack)) {
      renderLoraStack(historyStack);
    } else {
      const loraName = String(getValue(record, "loraName", "LoraName") || "");
      const modelStrength = getValue(record, "loraModelStrength", "LoraModelStrength");
      const clipStrength = getValue(record, "loraClipStrength", "LoraClipStrength");
      renderLoraStack(loraName ? [{ name: loraName, modelStrength: modelStrength ?? 1, clipStrength: clipStrength ?? 1, enabled: true }] : []);
    }

    const legacyName = String(getValue(record, "loraName", "LoraName") || "");
    const legacySelect = document.querySelector("#lora-select");
    if (legacySelect && Array.from(legacySelect.options).some((option) => option.value === legacyName)) legacySelect.value = legacyName;
    else if (legacySelect) legacySelect.value = "";
    const legacyModelStrength = getValue(record, "loraModelStrength", "LoraModelStrength");
    const legacyClipStrength = getValue(record, "loraClipStrength", "LoraClipStrength");
    document.querySelector("#lora-model-strength").value = legacyModelStrength ?? 1;
    document.querySelector("#lora-clip-strength").value = legacyClipStrength ?? 1;
    syncLegacyLoraStrengthState();
    if (document.querySelector("#generation-profile")) document.querySelector("#generation-profile").value = "";
  }

  function ensureLoraRootUi() {
    if (document.querySelector("#lora-root-form")) return;
    const page = document.querySelector("#page-models");
    const checkpointHeading = page?.querySelector(".model-list-heading");
    if (!page || !checkpointHeading) return;

    const section = document.createElement("div");
    section.className = "v02-lora-roots";
    section.innerHTML = `
      <div class="section-toolbar">
        <div>
          <h2>LoRA folders</h2>
          <p>Add existing LoRA libraries without copying files. Changes refresh the managed backend.</p>
        </div>
      </div>
      <div class="model-root-card">
        <form id="lora-root-form" class="model-root-form">
          <label class="field model-root-field">
            <span>Folder containing LoRA files</span>
            <div class="path-picker-row">
              <input id="lora-root-path" type="text" required placeholder="D:\\AI\\LoRA" autocomplete="off">
              <button class="button button-quiet" id="lora-root-browse" type="button">Browse folder…</button>
              <button class="button button-secondary" type="submit">Add folder</button>
            </div>
          </label>
        </form>
        <div class="model-root-list" id="lora-root-list"></div>
      </div>`;
    checkpointHeading.before(section);

    section.querySelector("#lora-root-form").addEventListener("submit", submitLoraRoot);
    section.querySelector("#lora-root-browse").addEventListener("click", browseLoraRoot);
    section.querySelector("#lora-root-list").addEventListener("click", (event) => {
      const button = event.target.closest("[data-lora-root-remove]");
      if (button) void removeLoraRoot(button.dataset.loraRootRemove, button);
    });
  }

  function renderLoraRoots(roots) {
    v02State.loraRoots = Array.isArray(roots) ? roots : roots ? [roots] : [];
    const list = document.querySelector("#lora-root-list");
    if (!list) return;
    list.replaceChildren();
    if (!v02State.loraRoots.length) {
      list.innerHTML = '<div class="empty-state compact"><strong>No LoRA folders configured</strong><p>Add a folder containing .safetensors LoRA files.</p></div>';
      return;
    }

    for (const root of v02State.loraRoots) {
      const path = String(getValue(root, "path", "Path") || "");
      const managed = Boolean(getValue(root, "managed", "Managed"));
      const exists = Boolean(getValue(root, "exists", "Exists"));
      const row = document.createElement("div");
      row.className = "model-root-row";
      row.innerHTML = '<div class="model-root-main"><strong></strong><code></code></div><div class="model-root-actions"><span></span></div>';
      row.querySelector("strong").textContent = managed ? "StableAMD managed LoRA" : "External LoRA folder";
      row.querySelector("code").textContent = path;
      const status = row.querySelector(".model-root-actions span");
      status.className = `root-state ${exists ? "is-ready" : "is-missing"}`;
      status.textContent = exists ? "Available" : "Missing";
      if (!managed) {
        const remove = document.createElement("button");
        remove.className = "button button-quiet";
        remove.type = "button";
        remove.dataset.loraRootRemove = path;
        remove.textContent = "Remove";
        row.querySelector(".model-root-actions").append(remove);
      }
      list.append(row);
    }
  }

  async function refreshLoraRoots() {
    ensureLoraRootUi();
    try { renderLoraRoots(await api("/api/lora-roots")); }
    catch (error) { showToast(`LoRA folders failed: ${error.message}`, "error"); }
  }

  async function browseLoraRoot() {
    const button = document.querySelector("#lora-root-browse");
    button.disabled = true;
    const oldText = button.textContent;
    button.textContent = "Opening…";
    try {
      const result = await api("/api/lora-roots/browse", { method: "POST", body: "{}" });
      if (!getValue(result, "cancelled", "Cancelled") && getValue(result, "path", "Path")) {
        document.querySelector("#lora-root-path").value = String(getValue(result, "path", "Path"));
        document.querySelector("#lora-root-path").focus();
      }
    } catch (error) {
      showToast(`LoRA folder picker failed: ${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  async function refreshBackendForLoraFolders(message) {
    document.querySelector("#runtime-status").textContent = "Restarting backend…";
    document.querySelector("#runtime-dot").dataset.state = "starting";
    try {
      const status = await api("/api/backend/restart", { method: "POST", body: "{}" });
      renderStatus(status);
      await Promise.all([refreshGenerationOptions(), refreshLoraRoots()]);
      showToast(message, "success");
    } catch (error) {
      showToast(`LoRA folder saved, but backend restart failed: ${error.message}`, "error");
      await refreshStatus();
    }
  }

  async function submitLoraRoot(event) {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const path = document.querySelector("#lora-root-path").value.trim();
    if (!path) { showToast("Choose a LoRA folder first.", "error"); return; }
    const oldText = button.textContent;
    button.disabled = true;
    button.textContent = "Adding…";
    try {
      const result = await api("/api/lora-roots", { method: "POST", body: JSON.stringify({ path }) });
      document.querySelector("#lora-root-path").value = "";
      await refreshLoraRoots();
      const added = Boolean(getValue(result, "added", "Added"));
      const restartRequired = Boolean(getValue(result, "restartRequired", "RestartRequired"));
      if (restartRequired) void refreshBackendForLoraFolders("LoRA folder added and backend refreshed.");
      else showToast(added ? "LoRA folder added." : "LoRA folder is already configured.", "success");
    } catch (error) {
      showToast(`Could not add LoRA folder: ${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  async function removeLoraRoot(path, button) {
    button.disabled = true;
    try {
      const result = await api("/api/lora-roots/remove", { method: "POST", body: JSON.stringify({ path }) });
      await refreshLoraRoots();
      const removed = Boolean(getValue(result, "removed", "Removed"));
      const restartRequired = Boolean(getValue(result, "restartRequired", "RestartRequired"));
      if (restartRequired) void refreshBackendForLoraFolders("LoRA folder removed and backend refreshed.");
      else showToast(removed ? "LoRA folder removed." : "LoRA folder was not configured.", "success");
    } catch (error) {
      showToast(`Could not remove LoRA folder: ${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensureProfileControl();
    ensureModelSupportHint();
    ensureLoraStackUi();
    ensureLoraRootUi();
    document.querySelector("#model-select")?.addEventListener("change", () => {
      populateProfileControl(true);
      renderModelSupportHint();
      syncLoraStackAvailability();
    });
    document.querySelector("#refresh-button")?.addEventListener("click", () => { void refreshGenerationOptions(); });
    document.querySelector('[data-page="models"]')?.addEventListener("click", () => void refreshLoraRoots());
    document.querySelector("#gallery-grid")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-history-index]");
      if (button) restoreLoraSettings(Number(button.dataset.historyIndex));
    });

    const modelSelect = document.querySelector("#model-select");
    if (modelSelect) new MutationObserver(() => {
      populateProfileControl(false);
      renderModelSupportHint();
    }).observe(modelSelect, { childList: true });

    void Promise.all([refreshGenerationOptions(), refreshLoraRoots()]);
  });
})();
