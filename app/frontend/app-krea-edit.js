(() => {
  const baseKreaEditApi = api;

  const MATERIAL_PRESETS = {
    leather: 'leather',
    wood: 'wood',
    marble: 'marble',
    metal: 'metal',
    concrete: 'concrete',
    fabric: 'fabric',
    glass: 'glass',
  };

  function modelFamily(modelId = "") {
    const id = String(modelId || document.querySelector("#model-select")?.value || "");
    const model = Array.isArray(state?.models)
      ? state.models.find((entry) => String(getValue(entry, "id", "Id") || "") === id)
      : null;
    const family = String(getValue(model, "family", "Family") || "").toLowerCase();
    if (family) return family;
    const label = String(document.querySelector("#model-select")?.selectedOptions?.[0]?.textContent || "").toLowerCase();
    return label.includes("krea") ? "krea2" : "";
  }

  function isKreaEditRequest(payload) {
    const family = modelFamily(payload?.modelId);
    const mode = String(payload?.mode || document.querySelector("#generation-mode")?.value || "txt2img").toLowerCase();
    return family === "krea2" && mode === "img2img";
  }

  function isMaterialTask() {
    return document.querySelector("#krea-edit-task")?.value === "material-replace";
  }

  function selectedMaterialDescriptor() {
    const preset = String(document.querySelector("#krea-material-preset")?.value || "leather");
    if (preset === "custom") {
      return String(document.querySelector("#krea-material-custom")?.value || "").trim();
    }
    return MATERIAL_PRESETS[preset] || preset;
  }

  function buildMaterialInstruction() {
    const target = String(document.querySelector("#krea-material-target")?.value || "").trim();
    const material = selectedMaterialDescriptor();
    const additional = String(document.querySelector("#prompt")?.value || "").trim();
    if (!target) throw new Error("Describe the object or area whose material should be replaced.");
    if (!material) throw new Error("Describe the replacement material or texture.");

    const base = `Replace the material or texture of ${target} with ${material}. Preserve the object's shape, geometry, position, lighting, scene composition, and all unrelated areas.`;
    return additional ? `${base} ${additional}` : base;
  }

  function readReferenceImage(file) {
    return new Promise((resolve, reject) => {
      if (!file) {
        reject(new Error("Choose a reference image."));
        return;
      }
      if (![/^image\/png$/i, /^image\/jpeg$/i, /^image\/webp$/i].some((pattern) => pattern.test(file.type || ""))) {
        reject(new Error("Reference image must be PNG, JPEG, or WebP."));
        return;
      }
      if (file.size > 20 * 1024 * 1024) {
        reject(new Error("Reference image must be 20 MiB or smaller."));
        return;
      }
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("Could not read the reference image."));
      reader.onload = () => {
        const encoded = String(reader.result || "");
        const comma = encoded.indexOf(",");
        if (comma < 0 || !encoded.slice(comma + 1)) {
          reject(new Error("Could not encode the reference image."));
          return;
        }
        resolve({
          name: file.name,
          mimeType: file.type,
          dataBase64: encoded.slice(comma + 1),
        });
      };
      reader.readAsDataURL(file);
    });
  }

  function referenceEnabled() {
    return document.querySelector("#krea-reference-enabled")?.checked === true;
  }

  // app-v02 owns the generic img2img transport. Load this adapter before it so
  // v02 captures this API wrapper as its base transport: v02 can collect the
  // source image normally, then this layer removes classic denoise semantics
  // before the request reaches the async generation transport.
  api = async function kreaImageEditApi(path, options = {}) {
    if (path === "/api/generate" && String(options?.method || "GET").toUpperCase() === "POST") {
      let payload = {};
      try { payload = options.body ? JSON.parse(options.body) : {}; }
      catch { payload = {}; }
      if (isKreaEditRequest(payload)) {
        delete payload.denoise;
        if (isMaterialTask()) {
          const materialInstruction = buildMaterialInstruction();
          payload.prompt = materialInstruction;
        }
        if (referenceEnabled()) {
          const role = String(document.querySelector("#krea-reference-role")?.value || "style");
          const file = document.querySelector("#krea-reference-image")?.files?.[0];
          payload.references = [{ role, image: await readReferenceImage(file) }];
        } else {
          delete payload.references;
        }
        return baseKreaEditApi(path, { ...options, body: JSON.stringify(payload) });
      }
    }
    return baseKreaEditApi(path, options);
  };

  function ensureKreaEditTaskUi() {
    if (document.querySelector("#krea-edit-task-panel")) return document.querySelector("#krea-edit-task-panel");
    const controls = document.querySelector("#img2img-controls");
    const hint = document.querySelector("#img2img-source-hint");
    if (!controls) return null;

    const panel = document.createElement("div");
    panel.id = "krea-edit-task-panel";
    panel.className = "model-root-card";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="field-grid field-grid-2">
        <label class="field">
          <span>Edit task</span>
          <select id="krea-edit-task">
            <option value="general">General edit</option>
            <option value="material-replace">Material / texture</option>
          </select>
        </label>
        <div id="krea-material-controls" hidden>
          <label class="field">
            <span>Target object / area</span>
            <input id="krea-material-target" type="text" placeholder="e.g. the sofa upholstery, the floor, the car body">
          </label>
          <label class="field">
            <span>Replacement material</span>
            <select id="krea-material-preset">
              <option value="leather">Leather</option>
              <option value="wood">Wood</option>
              <option value="marble">Marble</option>
              <option value="metal">Metal</option>
              <option value="concrete">Concrete</option>
              <option value="fabric">Fabric</option>
              <option value="glass">Glass</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          <label class="field" id="krea-material-custom-field" hidden>
            <span>Custom material / texture</span>
            <input id="krea-material-custom" type="text" placeholder="e.g. dark green velvet, brushed copper, white terrazzo">
          </label>
          <p class="history-model">StableAMD builds a focused replacement instruction and asks Krea to preserve geometry, lighting, composition and unrelated areas.</p>
        </div>
        <div class="field">
          <label class="checkbox-field">
            <input id="krea-reference-enabled" type="checkbox">
            <span>Use one reference image</span>
          </label>
          <div id="krea-reference-controls" hidden>
            <label class="field">
              <span>Reference role</span>
              <select id="krea-reference-role">
                <option value="style">Style</option>
                <option value="material">Material</option>
                <option value="content">Content</option>
              </select>
            </label>
            <label class="field">
              <span>Reference image · PNG, JPEG or WebP · max 20 MiB</span>
              <input id="krea-reference-image" type="file" accept="image/png,image/jpeg,image/webp">
            </label>
            <p id="krea-reference-hint" class="history-model">Picture 1 remains the source image. Picture 2 is used according to the selected reference role.</p>
          </div>
        </div>
      </div>`;

    if (hint) hint.before(panel);
    else controls.append(panel);
    return panel;
  }

  function syncKreaEditUi() {
    const mode = document.querySelector("#generation-mode");
    if (!mode) return false;
    const taskPanel = ensureKreaEditTaskUi();
    const family = modelFamily();
    const krea = family === "krea2";
    const active = krea && mode.value === "img2img";
    const material = active && isMaterialTask();
    const imageOption = Array.from(mode.options).find((option) => option.value === "img2img");
    if (imageOption && krea) {
      imageOption.textContent = imageOption.disabled
        ? "Image Edit · unavailable until the Krea edit integration is ready"
        : "Image Edit";
    }

    if (taskPanel) taskPanel.hidden = !active;
    const materialControls = document.querySelector("#krea-material-controls");
    if (materialControls) materialControls.hidden = !material;

    const preset = document.querySelector("#krea-material-preset");
    const customField = document.querySelector("#krea-material-custom-field");
    const custom = document.querySelector("#krea-material-custom");
    const customActive = material && preset?.value === "custom";
    if (customField) customField.hidden = !customActive;
    if (custom) custom.required = Boolean(customActive);

    const target = document.querySelector("#krea-material-target");
    if (target) target.required = Boolean(material);

    const referenceOn = active && referenceEnabled();
    const referenceControls = document.querySelector("#krea-reference-controls");
    const referenceInput = document.querySelector("#krea-reference-image");
    if (referenceControls) referenceControls.hidden = !referenceOn;
    if (referenceInput) referenceInput.required = referenceOn;
    const referenceHint = document.querySelector("#krea-reference-hint");
    if (referenceHint && referenceOn) {
      const role = String(document.querySelector("#krea-reference-role")?.value || "style");
      const file = referenceInput?.files?.[0];
      referenceHint.textContent = file
        ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB · Picture 2 will be used as the ${role} reference.`
        : `Choose Picture 2 to use as the ${role} reference.`;
    }

    const prompt = document.querySelector("#prompt");
    const promptLabel = prompt?.closest(".field")?.querySelector(":scope > span");
    if (promptLabel) {
      promptLabel.textContent = material
        ? "Additional instruction (optional)"
        : (active ? "Edit instruction" : "Prompt");
    }
    if (prompt) {
      prompt.required = !material;
      prompt.placeholder = material
        ? "Optional: add color, finish, grain, wear, reflectivity or other details…"
        : "Describe the image you want to create…";
    }

    const input = document.querySelector("#input-image");
    const inputLabel = input?.closest(".field")?.querySelector(":scope > span");
    if (inputLabel && active) inputLabel.textContent = "Source image · PNG, JPEG or WebP · max 20 MiB";

    const denoise = document.querySelector("#img2img-denoise");
    const denoiseField = denoise?.closest(".field");
    if (denoiseField) denoiseField.hidden = active;
    if (denoise) denoise.disabled = active || mode.value !== "img2img";

    const hint = document.querySelector("#img2img-source-hint");
    if (hint && active) {
      const file = input?.files?.[0];
      if (material) {
        hint.textContent = file
          ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB · Material / texture replacement uses the source as the preserved scene reference.`
          : "Choose a source image, identify the target object/area and select the replacement material. Additional instruction is optional.";
      } else {
        hint.textContent = file
          ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB · Krea 2 whole-image edit uses this source as Picture 1.`
          : "Choose a source image, then describe the requested whole-image change in Edit instruction. No mask or denoise slider is used.";
      }
    }
    return true;
  }

  function bindKreaEditUi() {
    const mode = document.querySelector("#generation-mode");
    const model = document.querySelector("#model-select");
    if (!mode || !model) return false;
    ensureKreaEditTaskUi();
    if (mode.dataset.kreaEditBound !== "true") {
      mode.dataset.kreaEditBound = "true";
      mode.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      model.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      document.querySelector("#input-image")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      document.querySelector("#krea-edit-task")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      document.querySelector("#krea-material-preset")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      document.querySelector("#krea-reference-enabled")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      document.querySelector("#krea-reference-role")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      document.querySelector("#krea-reference-image")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      new MutationObserver(() => queueMicrotask(syncKreaEditUi)).observe(model, { childList: true });
    }
    syncKreaEditUi();
    return true;
  }

  document.addEventListener("DOMContentLoaded", () => {
    let attempts = 0;
    const bind = () => {
      if (bindKreaEditUi() || attempts++ >= 40) return;
      setTimeout(bind, 50);
    };
    setTimeout(bind, 0);
  });
})();
