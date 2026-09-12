(() => {
  pageMeta.settings = ["Settings", "StableAMD v0.2 runtime and generation defaults."];

  const v02State = {
    generationOptions: { samplers: [], schedulers: [], loras: [] },
    profileCatalog: { profiles: [] },
    loraRoots: [],
  };

  function fillSelect(select, values, preferred, emptyLabel = null) {
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

  function syncLoraStrengthState() {
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

  async function refreshGenerationOptions() {
    try {
      const [options, catalog] = await Promise.all([
        api("/api/generation-options"),
        api("/api/generation-profiles"),
      ]);
      v02State.generationOptions = options || { samplers: [], schedulers: [], loras: [] };
      v02State.profileCatalog = catalog || { profiles: [] };
      fillSelect(document.querySelector("#sampler"), options?.samplers, "euler");
      fillSelect(document.querySelector("#scheduler"), options?.schedulers, "normal");
      fillSelect(document.querySelector("#lora-select"), options?.loras, "", "None");
      syncLoraStrengthState();
      populateProfileControl(false);
    } catch (error) {
      syncLoraStrengthState();
      showToast(`Generation options unavailable: ${error.message}`, "error");
    }
  }

  function restoreLoraSettings(index) {
    const record = state.history[index];
    if (!record) return;

    const loraName = String(getValue(record, "loraName", "LoraName") || "");
    const select = document.querySelector("#lora-select");
    if (select && Array.from(select.options).some((option) => option.value === loraName)) {
      select.value = loraName;
    } else if (select) {
      select.value = "";
    }

    const modelStrength = getValue(record, "loraModelStrength", "LoraModelStrength");
    const clipStrength = getValue(record, "loraClipStrength", "LoraClipStrength");
    document.querySelector("#lora-model-strength").value = modelStrength ?? 1;
    document.querySelector("#lora-clip-strength").value = clipStrength ?? 1;
    syncLoraStrengthState();
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
    ensureLoraRootUi();
    document.querySelector("#lora-select")?.addEventListener("change", syncLoraStrengthState);
    document.querySelector("#model-select")?.addEventListener("change", () => populateProfileControl(true));
    document.querySelector("#refresh-button")?.addEventListener("click", () => { void refreshGenerationOptions(); });
    document.querySelector('[data-page="models"]')?.addEventListener("click", () => void refreshLoraRoots());
    document.querySelector("#gallery-grid")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-history-index]");
      if (button) restoreLoraSettings(Number(button.dataset.historyIndex));
    });

    const modelSelect = document.querySelector("#model-select");
    if (modelSelect) new MutationObserver(() => populateProfileControl(false)).observe(modelSelect, { childList: true });

    void Promise.all([refreshGenerationOptions(), refreshLoraRoots()]);
  });
})();
