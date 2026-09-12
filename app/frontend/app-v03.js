(() => {
  const bundleRoles = [
    { id: "diffusion_model", label: "Diffusion models", hint: "UNet / diffusion-model files used by FLUX, Krea and other bundle families." },
    { id: "text_encoder", label: "Text encoders", hint: "CLIP, T5, Qwen and other text-encoder assets. A logical model may use more than one." },
    { id: "vae", label: "VAE", hint: "VAE / autoencoder assets used to encode or decode images." },
  ];

  const bundleState = { roots: {} };

  function ensureBundleRootUi() {
    let section = document.querySelector("#bundle-root-section");
    if (section) return section;

    const page = document.querySelector("#page-models");
    if (!page) return null;
    const anchor = page.querySelector(".v02-lora-roots") || page.querySelector(".model-list-heading");
    if (!anchor) return null;

    section = document.createElement("section");
    section.id = "bundle-root-section";
    section.className = "v03-bundle-roots";
    section.innerHTML = `
      <div class="section-toolbar">
        <div>
          <h2>Bundle asset folders</h2>
          <p>Modern model families can use separate diffusion model, text encoder and VAE files. StableAMD keeps these as asset roles and later combines them into one logical model.</p>
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

    anchor.before(section);
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
    bundleState.roots = payload || {};
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
      await refreshBundleRoots();
      document.querySelector("#refresh-button")?.click();
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
    ensureBundleRootUi();
    document.querySelector('[data-page="models"]')?.addEventListener("click", () => void refreshBundleRoots());
    document.querySelector("#refresh-button")?.addEventListener("click", () => {
      if (document.querySelector("#page-models")?.classList.contains("is-visible")) void refreshBundleRoots();
    });
    void refreshBundleRoots();
  });
})();
