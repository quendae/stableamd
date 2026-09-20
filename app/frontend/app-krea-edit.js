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

  function isTurnaroundTask() {
    return document.querySelector("#krea-edit-task")?.value === "character-turnaround";
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

  function buildCharacterTurnaroundInstruction() {
    const additional = String(document.querySelector("#prompt")?.value || "").trim();
    const base = "Create a single character turnaround sheet using Picture 1 as the identity reference. Show the same character four times from left to right: front view, three-quarter view, side profile, and back view. Keep the character identity, face, hairstyle, clothing, accessories, body proportions, colors, and materials consistent in every view. Show the full body from head to toe at equal scale, aligned to a common ground line, with a neutral relaxed pose and consistent camera height. Use a clean neutral studio background with even lighting. Do not add text, labels, borders, extra characters, props, cropped body parts, or alternate outfits.";
    return additional ? `${base} Additional character notes: ${additional}` : base;
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

  function reference2Enabled() {
    return document.querySelector("#krea-reference-2-enabled")?.checked === true;
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
        const turnaround = isTurnaroundTask();
        if (turnaround) {
          payload.editTask = "character-turnaround";
          payload.prompt = buildCharacterTurnaroundInstruction();
          payload.width = 1536;
          payload.height = 768;
          delete payload.references;
        } else {
          delete payload.editTask;
          if (isMaterialTask()) {
            const materialInstruction = buildMaterialInstruction();
            payload.prompt = materialInstruction;
          }
          if (referenceEnabled()) {
            const references = [];
            const role = String(document.querySelector("#krea-reference-role")?.value || "style");
            const file = document.querySelector("#krea-reference-image")?.files?.[0];
            references.push({ role, image: await readReferenceImage(file) });

            if (reference2Enabled()) {
              const role2 = String(document.querySelector("#krea-reference-role-2")?.value || "material");
              const file2 = document.querySelector("#krea-reference-image-2")?.files?.[0];
              references.push({ role: role2, image: await readReferenceImage(file2) });
            }
            payload.references = references;
          } else {
            delete payload.references;
          }
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
            <option value="character-turnaround">Character turnaround</option>
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
        <div id="krea-turnaround-controls" class="model-root-card" hidden>
          <strong>Four-view character sheet</strong>
          <p class="history-model">Fixed output: 1536 × 768 · front / 3/4 / side / back. The source image is the only identity reference; extra reference images are intentionally disabled for this task.</p>
        </div>
        <div id="krea-reference-section" class="field">
          <label class="checkbox-field">
            <input id="krea-reference-enabled" type="checkbox">
            <span>Use reference images</span>
          </label>
          <div id="krea-reference-controls" hidden>
            <div class="model-root-card">
              <strong>Reference 1</strong>
              <label class="field">
                <span>Reference 1 role</span>
                <select id="krea-reference-role">
                  <option value="style">Style</option>
                  <option value="material">Material</option>
                  <option value="content">Content</option>
                </select>
              </label>
              <label class="field">
                <span>Reference 1 image · PNG, JPEG or WebP · max 20 MiB</span>
                <input id="krea-reference-image" type="file" accept="image/png,image/jpeg,image/webp">
              </label>
              <p id="krea-reference-hint" class="history-model">Picture 1 remains the source image. Picture 2 is used according to the selected reference role.</p>
            </div>

            <label class="checkbox-field">
              <input id="krea-reference-2-enabled" type="checkbox">
              <span>Use Reference 2</span>
            </label>
            <div id="krea-reference-2-controls" class="model-root-card" hidden>
              <strong>Reference 2</strong>
              <label class="field">
                <span>Reference 2 role</span>
                <select id="krea-reference-role-2">
                  <option value="material">Material</option>
                  <option value="style">Style</option>
                  <option value="content">Content</option>
                </select>
              </label>
              <label class="field">
                <span>Reference 2 image · PNG, JPEG or WebP · max 20 MiB</span>
                <input id="krea-reference-image-2" type="file" accept="image/png,image/jpeg,image/webp">
              </label>
              <p id="krea-reference-hint-2" class="history-model">Picture 3 is used according to the selected second reference role.</p>
            </div>
          </div>
        </div>
      </div>`;

    if (hint) hint.before(panel);
    else controls.append(panel);
    return panel;
  }

  function syncReferenceHint({ inputId, roleId, hintId, pictureNumber }) {
    const input = document.querySelector(inputId);
    const role = String(document.querySelector(roleId)?.value || "style");
    const hint = document.querySelector(hintId);
    if (!hint) return;
    const file = input?.files?.[0];
    hint.textContent = file
      ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB · Picture ${pictureNumber} will be used as the ${role} reference.`
      : `Choose Picture ${pictureNumber} to use as the ${role} reference.`;
  }

  function syncKreaEditUi() {
    const mode = document.querySelector("#generation-mode");
    if (!mode) return false;
    const taskPanel = ensureKreaEditTaskUi();
    const family = modelFamily();
    const krea = family === "krea2";
    const active = krea && mode.value === "img2img";
    const material = active && isMaterialTask();
    const turnaround = active && isTurnaroundTask();
    const imageOption = Array.from(mode.options).find((option) => option.value === "img2img");
    if (imageOption && krea) {
      imageOption.textContent = imageOption.disabled
        ? "Image Edit · unavailable until the Krea edit integration is ready"
        : "Image Edit";
    }

    if (taskPanel) taskPanel.hidden = !active;
    const materialControls = document.querySelector("#krea-material-controls");
    if (materialControls) materialControls.hidden = !material;
    const turnaroundControls = document.querySelector("#krea-turnaround-controls");
    if (turnaroundControls) turnaroundControls.hidden = !turnaround;

    const preset = document.querySelector("#krea-material-preset");
    const customField = document.querySelector("#krea-material-custom-field");
    const custom = document.querySelector("#krea-material-custom");
    const customActive = material && preset?.value === "custom";
    if (customField) customField.hidden = !customActive;
    if (custom) custom.required = Boolean(customActive);

    const target = document.querySelector("#krea-material-target");
    if (target) target.required = Boolean(material);

    const referenceSection = document.querySelector("#krea-reference-section");
    if (referenceSection) referenceSection.hidden = turnaround;
    const referenceOn = active && !turnaround && referenceEnabled();
    const referenceControls = document.querySelector("#krea-reference-controls");
    const referenceInput = document.querySelector("#krea-reference-image");
    if (referenceControls) referenceControls.hidden = !referenceOn;
    if (referenceInput) referenceInput.required = referenceOn;
    if (referenceOn) {
      syncReferenceHint({
        inputId: "#krea-reference-image",
        roleId: "#krea-reference-role",
        hintId: "#krea-reference-hint",
        pictureNumber: 2,
      });
    }

    const reference2On = referenceOn && reference2Enabled();
    const reference2Controls = document.querySelector("#krea-reference-2-controls");
    const reference2Input = document.querySelector("#krea-reference-image-2");
    if (reference2Controls) reference2Controls.hidden = !reference2On;
    if (reference2Input) reference2Input.required = reference2On;
    if (reference2On) {
      syncReferenceHint({
        inputId: "#krea-reference-image-2",
        roleId: "#krea-reference-role-2",
        hintId: "#krea-reference-hint-2",
        pictureNumber: 3,
      });
    }

    const prompt = document.querySelector("#prompt");
    const promptLabel = prompt?.closest(".field")?.querySelector(":scope > span");
    if (promptLabel) {
      promptLabel.textContent = turnaround
        ? "Additional character notes (optional)"
        : (material ? "Additional instruction (optional)" : (active ? "Edit instruction" : "Prompt"));
    }
    if (prompt) {
      prompt.required = !(material || turnaround);
      prompt.placeholder = turnaround
        ? "Optional: preserve a signature accessory, expression, age, costume detail or other identity cue…"
        : (material
          ? "Optional: add color, finish, grain, wear, reflectivity or other details…"
          : "Describe the image you want to create…");
    }

    const input = document.querySelector("#input-image");
    const inputLabel = input?.closest(".field")?.querySelector(":scope > span");
    if (inputLabel && active) {
      inputLabel.textContent = turnaround
        ? "Character reference image · PNG, JPEG or WebP · max 20 MiB"
        : "Source image · PNG, JPEG or WebP · max 20 MiB";
    }

    const denoise = document.querySelector("#img2img-denoise");
    const denoiseField = denoise?.closest(".field");
    if (denoiseField) denoiseField.hidden = active;
    if (denoise) denoise.disabled = active || mode.value !== "img2img";

    const hint = document.querySelector("#img2img-source-hint");
    if (hint && active) {
      const file = input?.files?.[0];
      if (turnaround) {
        hint.textContent = file
          ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB · Character turnaround will use this image as the identity reference for all four views.`
          : "Choose one clear character image. StableAMD will create one 1536 × 768 sheet with front / 3/4 / side / back views and consistent framing.";
      } else if (material) {
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
      document.querySelector("#krea-reference-2-enabled")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      document.querySelector("#krea-reference-role-2")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      document.querySelector("#krea-reference-image-2")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
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
