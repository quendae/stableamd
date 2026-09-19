(() => {
  const bundleRoles = [
    { id: "diffusion_model", label: "Diffusion models", hint: "UNet / diffusion-model files used by Z-Image, Krea and other package families." },
    { id: "text_encoder", label: "Text encoders", hint: "CLIP, T5, Qwen and other text-encoder assets. A model package may use more than one." },
    { id: "vae", label: "VAE", hint: "VAE / autoencoder assets used to encode or decode images." },
  ];

  const packageState = { roots: {}, support: null, modelPatches: { root: "", models: [] } };
  const baseRenderModels = renderModels;

  function normalizeModels(payload) {
    if (!payload) return [];
    if (Array.isArray(payload)) return payload;
    const nested = getValue(payload, "models", "Models");
    if (!nested) return [];
    return Array.isArray(nested) ? nested : [nested];
  }

  function normalizeComponents(model) {
    const explicit = getValue(model, "components", "Components");
    if (explicit) return Array.isArray(explicit) ? explicit : [explicit];

    const path = String(getValue(model, "path", "Path") || "");
    const name = String(getValue(model, "name", "Name") || "Checkpoint");
    return [{ role: "checkpoint", label: "Checkpoint", expectedName: name, path, present: Boolean(path) }];
  }

  function isModelReady(model) {
    const value = getValue(model, "ready", "Ready");
    return value === undefined || value === null ? true : Boolean(value);
  }

  function ensureModelPackageUi() {
    const page = document.querySelector("#page-models");
    if (!page) return null;

    const toolbar = page.querySelector(":scope > .section-toolbar");
    if (toolbar && !toolbar.dataset.packageToolbar) {
      toolbar.dataset.packageToolbar = "true";
      const heading = toolbar.querySelector("h2");
      const copy = toolbar.querySelector("p");
      if (heading) heading.textContent = "Model packages";
      if (copy) copy.textContent = "StableAMD groups the files a model needs into one logical package. Ready packages can be selected directly in Generate.";
    }

    let list = page.querySelector("#model-package-list");
    if (!list) {
      list = document.createElement("div");
      list.id = "model-package-list";
      list.className = "model-install-grid model-package-list";
      if (toolbar) toolbar.after(list);
      else page.prepend(list);
    }

    let advanced = page.querySelector("#advanced-model-assets");
    if (!advanced) {
      advanced = document.createElement("details");
      advanced.id = "advanced-model-assets";
      advanced.className = "secondary-model-options model-assets-advanced";
      advanced.innerHTML = '<summary>Advanced model asset folders</summary><div id="advanced-model-assets-content"></div>';
      list.after(advanced);
    }

    const content = advanced.querySelector("#advanced-model-assets-content");
    if (content) {
      const moveIntoAdvanced = [
        page.querySelector(":scope > .model-root-card"),
        page.querySelector(":scope > .v02-lora-roots"),
        page.querySelector(":scope > .model-list-heading"),
        page.querySelector(":scope > #model-list"),
        page.querySelector(":scope > .secondary-model-options:not(#advanced-model-assets)"),
      ].filter(Boolean);
      for (const node of moveIntoAdvanced) content.append(node);
    }

    return { page, list, advanced, content };
  }

  function renderModelPackages(models) {
    const ui = ensureModelPackageUi();
    if (!ui) return;
    ui.list.replaceChildren();

    if (!models.length) {
      ui.list.innerHTML = '<div class="empty-state"><strong>No model packages found</strong><p>Add model files or folders, then scan again.</p></div>';
      return;
    }

    for (const model of models) {
      const name = String(getValue(model, "name", "Name") || "Unnamed model");
      const family = String(getValue(model, "family", "Family") || "unknown");
      const ready = isModelReady(model);
      const components = normalizeComponents(model);
      const missing = components.filter((component) => !Boolean(getValue(component, "present", "Present"))).length;

      const card = document.createElement("article");
      card.className = `install-card model-package-card ${ready ? "is-ready" : "is-incomplete"}`;
      card.dataset.modelPackage = String(getValue(model, "id", "Id") || name);

      const heading = document.createElement("div");
      heading.className = "install-card-heading";
      const title = document.createElement("strong");
      title.textContent = name;
      const subtitle = document.createElement("span");
      subtitle.textContent = family === "unknown" ? "Model package" : family;
      heading.append(title, subtitle);

      const status = document.createElement("span");
      status.className = `root-state ${ready ? "is-ready" : "is-missing"}`;
      status.textContent = ready ? "Ready" : `Incomplete · ${missing} missing`;
      heading.append(status);
      card.append(heading);

      const componentList = document.createElement("div");
      componentList.className = "model-root-list package-components";
      for (const component of components) {
        const present = Boolean(getValue(component, "present", "Present"));
        const label = String(getValue(component, "label", "Label") || getValue(component, "role", "Role") || "Component");
        const expected = String(getValue(component, "expectedName", "ExpectedName") || "");
        const path = String(getValue(component, "path", "Path") || "");

        const row = document.createElement("div");
        row.className = "model-root-row package-component";
        const main = document.createElement("div");
        main.className = "model-root-main";
        const componentTitle = document.createElement("strong");
        componentTitle.textContent = `${present ? "✓" : "✗"} ${label}`;
        const componentPath = document.createElement("code");
        componentPath.textContent = path || expected || "Missing";
        main.append(componentTitle, componentPath);

        const state = document.createElement("span");
        state.className = `root-state ${present ? "is-ready" : "is-missing"}`;
        state.textContent = present ? "Found" : "Missing";
        row.append(main, state);
        componentList.append(row);
      }
      card.append(componentList);
      ui.list.append(card);
    }
  }

  function supportedTxt2ImgIds() {
    const records = normalizeModels(packageState.support);
    const supported = new Set();
    for (const record of records) {
      if (getValue(record, "capabilities", "Capabilities")?.txt2img !== "supported") continue;
      const id = String(getValue(record, "id", "Id") || "");
      if (id) supported.add(id);
    }
    return supported;
  }

  function syncGenerateModelSelect(models) {
    const select = document.querySelector("#model-select");
    if (!select) return;
    const previous = select.value;
    const supportedIds = supportedTxt2ImgIds();

    const selectable = models.filter((model) => {
      if (!isModelReady(model)) return false;
      const id = String(getValue(model, "id", "Id") || "");
      if (supportedIds.size) return supportedIds.has(id);
      const family = String(getValue(model, "family", "Family") || "").toLowerCase();
      return family === "sdxl" || family === "z-image-turbo";
    });

    select.replaceChildren();
    if (!selectable.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No ready supported models found";
      select.append(option);
      return;
    }

    for (const model of selectable) {
      const option = document.createElement("option");
      option.value = String(getValue(model, "id", "Id") || "");
      option.textContent = String(getValue(model, "name", "Name") || "Unnamed model");
      select.append(option);
    }
    if (previous && selectable.some((model) => String(getValue(model, "id", "Id") || "") === previous)) {
      select.value = previous;
    }
  }

  window.renderModels = function renderModelsV03(models) {
    const normalized = Array.isArray(models) ? models : normalizeModels(models);
    baseRenderModels(normalized);
    renderModelPackages(normalized);
    syncGenerateModelSelect(normalized);
  };
  renderModels = window.renderModels;

  async function refreshExecutionSupport() {
    try {
      packageState.support = await api("/api/model-support");
      syncGenerateModelSelect(state.models || []);
    } catch (error) {
      showToast(`Model capability refresh failed: ${error.message}`, "error");
    }
  }

  async function refreshModelPackages() {
    try {
      const models = normalizeModels(await api("/api/models"));
      renderModels(models);
    } catch (error) {
      showToast(`Model package scan failed: ${error.message}`, "error");
    }
  }

  function formatModelPatchBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return "";
    return bytes >= 1024 * 1024 * 1024
      ? `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GiB`
      : `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  }

  function ensureModelPatchUi() {
    const ui = ensureModelPackageUi();
    if (!ui) return null;
    let section = ui.page.querySelector("#curated-model-patches");
    if (section) return section;

    section = document.createElement("section");
    section.id = "curated-model-patches";
    section.className = "v03-curated-model-patches";
    section.innerHTML = `
      <div class="section-toolbar">
        <div>
          <h3>Curated provider dependencies</h3>
          <p>Verified model patches required by provider features. StableAMD pins the official source, exact size and SHA-256 before installing.</p>
        </div>
      </div>
      <div id="model-patch-install-list" class="model-install-grid"><div class="history-model">Loading curated dependencies…</div></div>`;
    ui.list.after(section);
    return section;
  }

  function renderModelPatches() {
    ensureModelPatchUi();
    const root = document.querySelector("#model-patch-install-list");
    if (!root) return;
    root.replaceChildren();
    const models = Array.isArray(packageState.modelPatches?.models) ? packageState.modelPatches.models : [];
    if (!models.length) {
      root.innerHTML = '<div class="empty-state compact"><strong>No curated dependencies available</strong><p>The provider dependency catalog could not be loaded.</p></div>';
      return;
    }

    for (const model of models) {
      const integrity = String(model.integrity || "missing");
      const invalid = integrity === "size-mismatch";
      const card = document.createElement("article");
      card.className = `install-card model-patch-card ${model.ready ? "is-ready" : ""}`;

      const heading = document.createElement("div");
      heading.className = "install-card-heading";
      const info = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = String(model.name || model.id || "Model patch");
      const meta = document.createElement("span");
      meta.textContent = [model.family, formatModelPatchBytes(model.sizeBytes), model.license].filter(Boolean).join(" · ");
      info.append(title, meta);

      const status = document.createElement("span");
      status.className = `root-state ${model.ready ? "is-ready" : "is-missing"}`;
      status.textContent = model.ready ? "Ready" : (invalid ? "Invalid file" : (model.installedOnDisk ? "Restart required" : "Not installed"));
      heading.append(info, status);
      card.append(heading);

      const purpose = document.createElement("p");
      purpose.className = "history-model";
      purpose.textContent = String(model.purpose || "Provider dependency");
      card.append(purpose);

      if (invalid) {
        const warning = document.createElement("p");
        warning.className = "history-model";
        warning.textContent = `Existing file size ${formatModelPatchBytes(model.actualBytes)} does not match the pinned ${formatModelPatchBytes(model.sizeBytes)}. Remove or rename the bad file before installing.`;
        card.append(warning);
      }

      const actions = document.createElement("div");
      actions.className = "model-root-actions";
      if (model.homepage) {
        const source = document.createElement("a");
        source.href = model.homepage;
        source.target = "_blank";
        source.rel = "noreferrer noopener";
        source.textContent = "Source / license";
        actions.append(source);
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = model.ready ? "button button-quiet" : "button button-secondary";
      button.disabled = Boolean(model.ready || invalid);
      button.textContent = model.ready ? "Ready" : (model.installedOnDisk ? "Activate" : "Install & activate");
      button.addEventListener("click", () => void installAndActivateModelPatch(model, button));
      actions.append(button);
      card.append(actions);
      root.append(card);
    }
  }

  async function refreshModelPatches() {
    ensureModelPatchUi();
    try {
      packageState.modelPatches = await api("/api/model-patches/catalog");
      renderModelPatches();
    } catch (error) {
      const root = document.querySelector("#model-patch-install-list");
      if (root) root.innerHTML = `<div class="empty-state compact"><strong>Curated dependencies unavailable</strong><p>${error.message}</p></div>`;
    }
  }

  async function installAndActivateModelPatch(model, button) {
    const oldText = button.textContent;
    button.disabled = true;
    try {
      let result = { restartRequired: Boolean(model.installedOnDisk && !model.ready), ready: Boolean(model.ready) };
      if (!model.installedOnDisk) {
        button.textContent = "Downloading & verifying…";
        result = await api("/api/model-patches/install", {
          method: "POST",
          body: JSON.stringify({ id: model.id }),
        });
      }

      if (result?.restartRequired || !result?.ready) {
        button.textContent = "Activating…";
        showToast(`${model.name} installed. Restarting the compute backend to activate it…`, "success");
        const status = await api("/api/backend/restart", { method: "POST", body: "{}" });
        renderStatus(status);
      }

      button.textContent = "Checking…";
      await Promise.allSettled([refreshModelPatches(), refreshModelPackages(), refreshExecutionSupport()]);
      const refreshed = (packageState.modelPatches?.models || []).find((item) => item.id === model.id);
      if (refreshed?.ready) {
        showToast(`${model.name} is installed and ready.`, "success");
      } else {
        throw new Error(`${model.name} is installed, but ComfyUI has not registered it yet.`);
      }
    } catch (error) {
      showToast(`Provider dependency install failed: ${error.message}`, "error");
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  function ensureBundleRootUi() {
    const ui = ensureModelPackageUi();
    if (!ui?.content) return null;

    let section = document.querySelector("#bundle-root-section");
    if (section) return section;

    section = document.createElement("section");
    section.id = "bundle-root-section";
    section.className = "v03-bundle-roots";
    section.innerHTML = `
      <div class="section-toolbar">
        <div>
          <h3>Bundle asset folders</h3>
          <p>Advanced model asset folders map diffusion models, text encoders and VAE files into logical packages. Most users only need the package status above.</p>
        </div>
      </div>
      <div id="bundle-root-groups" class="model-install-grid"></div>`;

    const groups = section.querySelector("#bundle-root-groups");
    for (const role of bundleRoles) {
      const card = document.createElement("div");
      card.className = "install-card";
      card.dataset.bundleRole = role.id;
      card.innerHTML = `
        <div class="install-card-heading">
          <strong>${role.label}</strong>
          <span>${role.hint}</span>
        </div>
        <form data-bundle-root-form="${role.id}" class="model-root-form">
          <label class="field">
            <span>External folder</span>
            <div class="path-picker-row">
              <input data-bundle-root-path="${role.id}" type="text" required placeholder="D:\\AI\\${role.id}" autocomplete="off">
              <button class="button button-quiet" data-bundle-browse="${role.id}" type="button">Browse folder…</button>
              <button class="button button-secondary" type="submit">Add folder</button>
            </div>
          </label>
        </form>
        <div class="model-root-list" data-bundle-root-list="${role.id}"></div>`;
      groups.append(card);
    }

    const loraSection = ui.content.querySelector(".v02-lora-roots");
    if (loraSection) loraSection.before(section);
    else ui.content.prepend(section);
    section.addEventListener("submit", handleBundleRootSubmit);
    section.addEventListener("click", handleBundleRootClick);
    return section;
  }

  function normalizeRoots(payload, role) {
    const value = payload?.[role];
    if (!value) return [];
    return Array.isArray(value) ? value : [value];
  }

  function renderBundleRole(role, records) {
    const list = document.querySelector(`[data-bundle-root-list="${role}"]`);
    if (!list) return;
    list.replaceChildren();

    if (!records.length) {
      list.innerHTML = '<div class="empty-state compact"><strong>No folders configured</strong><p>The managed StableAMD folder will be created automatically after refresh.</p></div>';
      return;
    }

    for (const record of records) {
      const path = String(getValue(record, "path", "Path") || "");
      const managed = Boolean(getValue(record, "managed", "Managed"));
      const exists = Boolean(getValue(record, "exists", "Exists"));
      const row = document.createElement("div");
      row.className = "model-root-row";

      const main = document.createElement("div");
      main.className = "model-root-main";
      const title = document.createElement("strong");
      title.textContent = managed ? "StableAMD managed folder" : "External folder";
      const code = document.createElement("code");
      code.textContent = path;
      main.append(title, code);

      const actions = document.createElement("div");
      actions.className = "model-root-actions";
      const status = document.createElement("span");
      status.className = `root-state ${exists ? "is-ready" : "is-missing"}`;
      status.textContent = exists ? "Available" : "Missing";
      actions.append(status);

      if (!managed) {
        const remove = document.createElement("button");
        remove.className = "button button-quiet";
        remove.type = "button";
        remove.dataset.bundleRemoveRole = role;
        remove.dataset.bundleRemovePath = path;
        remove.textContent = "Remove";
        actions.append(remove);
      }

      row.append(main, actions);
      list.append(row);
    }
  }

  function renderBundleRoots(payload) {
    packageState.roots = payload || {};
    for (const role of bundleRoles) renderBundleRole(role.id, normalizeRoots(payload, role.id));
  }

  async function refreshBundleRoots() {
    ensureBundleRootUi();
    try {
      renderBundleRoots(await api("/api/bundle-roots"));
    } catch (error) {
      showToast(`Bundle asset folders failed: ${error.message}`, "error");
    }
  }

  async function browseBundleRoot(role, button) {
    const input = document.querySelector(`[data-bundle-root-path="${role}"]`);
    if (!input) return;
    const oldText = button.textContent;
    button.disabled = true;
    button.textContent = "Opening…";
    try {
      const result = await api("/api/bundle-roots/browse", {
        method: "POST",
        body: JSON.stringify({ role }),
      });
      if (!getValue(result, "cancelled", "Cancelled") && getValue(result, "path", "Path")) {
        input.value = String(getValue(result, "path", "Path"));
        input.focus();
      }
    } catch (error) {
      showToast(`Bundle folder picker failed: ${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  async function restartBackendForBundleFolders(message) {
    document.querySelector("#runtime-status").textContent = "Restarting backend…";
    document.querySelector("#runtime-dot").dataset.state = "starting";
    try {
      const status = await api("/api/backend/restart", { method: "POST", body: "{}" });
      renderStatus(status);
      await Promise.allSettled([refreshBundleRoots(), refreshModelPackages(), refreshExecutionSupport(), refreshModelPatches()]);
      showToast(message, "success");
    } catch (error) {
      showToast(`Bundle folder saved, but backend restart failed: ${error.message}`, "error");
      await refreshStatus();
    }
  }

  async function addBundleRoot(role, path, button) {
    const oldText = button.textContent;
    button.disabled = true;
    button.textContent = "Adding…";
    try {
      const result = await api("/api/bundle-roots", {
        method: "POST",
        body: JSON.stringify({ role, path }),
      });
      const input = document.querySelector(`[data-bundle-root-path="${role}"]`);
      if (input) input.value = "";
      await refreshBundleRoots();
      const added = Boolean(getValue(result, "added", "Added"));
      const restartRequired = Boolean(getValue(result, "restartRequired", "RestartRequired"));
      if (restartRequired) {
        void restartBackendForBundleFolders(`${role.replaceAll("_", " ")} folder added and backend refreshed.`);
      } else {
        await refreshModelPackages();
        showToast(added ? "Bundle asset folder added." : "Bundle asset folder is already configured.", "success");
      }
    } catch (error) {
      showToast(`Could not add bundle asset folder: ${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  async function removeBundleRoot(role, path, button) {
    button.disabled = true;
    try {
      const result = await api("/api/bundle-roots/remove", {
        method: "POST",
        body: JSON.stringify({ role, path }),
      });
      await refreshBundleRoots();
      const removed = Boolean(getValue(result, "removed", "Removed"));
      const restartRequired = Boolean(getValue(result, "restartRequired", "RestartRequired"));
      if (restartRequired) {
        void restartBackendForBundleFolders(`${role.replaceAll("_", " ")} folder removed and backend refreshed.`);
      } else {
        await refreshModelPackages();
        showToast(removed ? "Bundle asset folder removed." : "Bundle asset folder was not configured.", "success");
      }
    } catch (error) {
      showToast(`Could not remove bundle asset folder: ${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }

  function handleBundleRootSubmit(event) {
    const form = event.target.closest("[data-bundle-root-form]");
    if (!form) return;
    event.preventDefault();
    const role = form.dataset.bundleRootForm;
    const input = form.querySelector(`[data-bundle-root-path="${role}"]`);
    const path = input?.value.trim() || "";
    if (!path) {
      showToast("Choose a bundle asset folder first.", "error");
      return;
    }
    const button = form.querySelector('button[type="submit"]');
    void addBundleRoot(role, path, button);
  }

  function handleBundleRootClick(event) {
    const browse = event.target.closest("[data-bundle-browse]");
    if (browse) {
      void browseBundleRoot(browse.dataset.bundleBrowse, browse);
      return;
    }
    const remove = event.target.closest("[data-bundle-remove-role]");
    if (remove) void removeBundleRoot(remove.dataset.bundleRemoveRole, remove.dataset.bundleRemovePath, remove);
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensureModelPackageUi();
    ensureModelPatchUi();
    ensureBundleRootUi();
    document.querySelector('[data-page="models"]')?.addEventListener("click", () => {
      void Promise.allSettled([refreshBundleRoots(), refreshModelPackages(), refreshExecutionSupport(), refreshModelPatches()]);
    });
    document.querySelector("#refresh-button")?.addEventListener("click", () => {
      if (document.querySelector("#page-models")?.classList.contains("is-visible")) {
        void Promise.allSettled([refreshBundleRoots(), refreshModelPackages(), refreshExecutionSupport(), refreshModelPatches()]);
      }
    });

    const criticalStartup = Promise.allSettled([refreshModelPackages(), refreshExecutionSupport()]);
    void criticalStartup.finally(() => window.StableAmdStartup?.markCriticalReady?.());
    void Promise.allSettled([refreshBundleRoots(), refreshModelPatches()]);
  });
})();
