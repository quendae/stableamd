(() => {
  const baseKreaEditApi = api;
  const baseRenderGenerationResult = renderGenerationResult;

  const MATERIAL_PRESETS = {
    leather: 'leather',
    wood: 'wood',
    marble: 'marble',
    metal: 'metal',
    concrete: 'concrete',
    fabric: 'fabric',
    glass: 'glass',
  };

  const CHARACTER_SHEET_DEFAULT_PROMPT = "Preserve the exact same character from Picture 1: identity, facial features, hairstyle or fur, clothing, accessories, body proportions, colors, materials, and art style. Keep the design consistent across every generated view. Use a clean neutral studio background with soft even lighting. Do not add text, labels, props, alternate outfits, or extra characters.";
  const CHARACTER_SHEET_VIEWS = [
    { id: "face-close-up", label: "Face close-up" },
    { id: "front", label: "Front" },
    { id: "three-quarter", label: "3/4" },
    { id: "side", label: "Side" },
    { id: "back", label: "Back" },
  ];

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

  function isCharacterSheetTask() {
    return document.querySelector("#krea-edit-task")?.value === "character-sheet";
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

  function reference2Enabled() {
    return document.querySelector("#krea-reference-2-enabled")?.checked === true;
  }

  function updateCharacterSheetProgress(index, view) {
    const title = document.querySelector("#result-empty strong");
    const detail = document.querySelector("#result-empty p");
    if (title) title.textContent = `Character sheet · ${index + 1}/${CHARACTER_SHEET_VIEWS.length}`;
    if (detail) detail.textContent = `Generating ${view.label}. Each view is rendered separately at full quality.`;
  }

  function aggregateCharacterSheetResults(items) {
    const first = items[0] || {};
    const seconds = items.reduce((total, item) => {
      const value = Number(getValue(item, "GenerationSeconds", "generationSeconds"));
      return total + (Number.isFinite(value) ? value : 0);
    }, 0);
    return {
      ...first,
      EditOperation: "character-sheet",
      CharacterSheetItems: items,
      CharacterSheetViews: CHARACTER_SHEET_VIEWS.map((view) => view.id),
      Width: 1024,
      Height: 1024,
      GenerationSeconds: seconds || getValue(first, "GenerationSeconds", "generationSeconds"),
    };
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
        const characterSheet = isCharacterSheetTask();
        if (characterSheet) {
          delete payload.references;
          const identityPrompt = String(payload.prompt || "").trim() || CHARACTER_SHEET_DEFAULT_PROMPT;
          const items = [];
          for (const view of CHARACTER_SHEET_VIEWS) {
            updateCharacterSheetProgress(items.length, view);
            const viewPayload = {
              ...payload,
              editTask: "character-sheet",
              characterSheetView: view.id,
              prompt: identityPrompt,
              width: 1024,
              height: 1024,
            };
            const result = await baseKreaEditApi(path, { ...options, body: JSON.stringify(viewPayload) });
            items.push({
              ...result,
              CharacterSheetView: view.id,
              CharacterSheetLabel: view.label,
            });
          }
          return aggregateCharacterSheetResults(items);
        }

        delete payload.editTask;
        delete payload.characterSheetView;
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
        return baseKreaEditApi(path, { ...options, body: JSON.stringify(payload) });
      }
    }
    return baseKreaEditApi(path, options);
  };

  function ensureCharacterSheetStyles() {
    if (document.querySelector("#character-sheet-styles")) return;
    const style = document.createElement("style");
    style.id = "character-sheet-styles";
    style.textContent = `
      .character-sheet-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; width:100%; }
      .character-sheet-item { margin:0; display:grid; gap:7px; min-width:0; }
      .character-sheet-item img { display:block; width:100%; aspect-ratio:1 / 1; object-fit:contain; border-radius:12px; background:rgba(255,255,255,.035); }
      .character-sheet-item figcaption { font-size:.82rem; font-weight:650; text-align:center; opacity:.82; }
      .character-sheet-summary { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center; margin-top:12px; }
    `;
    document.head.append(style);
  }

  function renderCharacterSheetResult(result) {
    const items = getValue(result, "CharacterSheetItems", "characterSheetItems");
    if (!Array.isArray(items) || !items.length) {
      baseRenderGenerationResult(result);
      return;
    }

    ensureCharacterSheetStyles();
    const empty = document.querySelector("#result-empty");
    if (empty) empty.hidden = true;
    const target = document.querySelector("#result-details");
    if (!target) {
      baseRenderGenerationResult(result);
      return;
    }
    target.hidden = false;
    target.replaceChildren();

    const grid = document.createElement("div");
    grid.className = "character-sheet-grid";
    items.forEach((item, index) => {
      const frame = document.createElement("figure");
      frame.className = "character-sheet-item";
      const imagePath = getValue(item, "ImagePath", "imagePath");
      if (imagePath) {
        const image = document.createElement("img");
        image.src = imageUrl(String(imagePath));
        image.alt = String(getValue(item, "CharacterSheetLabel", "characterSheetLabel") || CHARACTER_SHEET_VIEWS[index]?.label || "Character sheet view");
        frame.append(image);
      }
      const caption = document.createElement("figcaption");
      caption.textContent = String(getValue(item, "CharacterSheetLabel", "characterSheetLabel") || CHARACTER_SHEET_VIEWS[index]?.label || `View ${index + 1}`);
      frame.append(caption);
      grid.append(frame);
    });

    const title = document.createElement("strong");
    title.className = "result-title";
    title.textContent = "Character sheet complete";
    const summary = document.createElement("div");
    summary.className = "character-sheet-summary";
    const model = document.createElement("span");
    model.textContent = String(getValue(result, "ModelName", "modelName") || "Krea 2");
    const size = document.createElement("span");
    size.textContent = `${items.length} views · 1024 × 1024 each`;
    const seconds = Number(getValue(result, "GenerationSeconds", "generationSeconds"));
    const time = document.createElement("span");
    time.textContent = Number.isFinite(seconds) && seconds > 0 ? `${seconds.toFixed(1)} s total` : "Sequential generation";
    summary.append(model, size, time);
    target.append(grid, title, summary);
  }

  renderGenerationResult = function kreaRenderGenerationResult(result) {
    const items = getValue(result, "CharacterSheetItems", "characterSheetItems");
    if (Array.isArray(items) && items.length) {
      renderCharacterSheetResult(result);
      return;
    }
    baseRenderGenerationResult(result);
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
            <option value="character-sheet">Character sheet</option>
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
        <div id="krea-character-sheet-controls" class="model-root-card" hidden>
          <strong>Five-view character sheet</strong>
          <p class="history-model">5 sequential 1024 × 1024 generations · Face / Front / 3/4 / Side / Back. One view is rendered per generation, then StableAMD shows the results together as a grid.</p>
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
    const characterSheet = active && isCharacterSheetTask();
    const imageOption = Array.from(mode.options).find((option) => option.value === "img2img");
    if (imageOption && krea) {
      imageOption.textContent = imageOption.disabled
        ? "Image Edit · unavailable until the Krea edit integration is ready"
        : "Image Edit";
    }

    if (taskPanel) taskPanel.hidden = !active;
    const materialControls = document.querySelector("#krea-material-controls");
    if (materialControls) materialControls.hidden = !material;
    const characterSheetControls = document.querySelector("#krea-character-sheet-controls");
    if (characterSheetControls) characterSheetControls.hidden = !characterSheet;

    const preset = document.querySelector("#krea-material-preset");
    const customField = document.querySelector("#krea-material-custom-field");
    const custom = document.querySelector("#krea-material-custom");
    const customActive = material && preset?.value === "custom";
    if (customField) customField.hidden = !customActive;
    if (custom) custom.required = Boolean(customActive);

    const target = document.querySelector("#krea-material-target");
    if (target) target.required = Boolean(material);

    const referenceSection = document.querySelector("#krea-reference-section");
    if (referenceSection) referenceSection.hidden = characterSheet;
    const referenceOn = active && !characterSheet && referenceEnabled();
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
      promptLabel.textContent = characterSheet
        ? "Character identity prompt"
        : (material ? "Additional instruction (optional)" : (active ? "Edit instruction" : "Prompt"));
    }
    if (prompt) {
      if (characterSheet) {
        if (!prompt.value.trim() || prompt.dataset.characterSheetDefault === "true") {
          prompt.value = CHARACTER_SHEET_DEFAULT_PROMPT;
          prompt.dataset.characterSheetDefault = "true";
        }
      } else if (prompt.dataset.characterSheetDefault === "true" && prompt.value === CHARACTER_SHEET_DEFAULT_PROMPT) {
        prompt.value = "";
        delete prompt.dataset.characterSheetDefault;
      }
      prompt.required = !material;
      prompt.placeholder = characterSheet
        ? "Describe identity details that must remain consistent across Face / Front / 3/4 / Side / Back…"
        : (material
          ? "Optional: add color, finish, grain, wear, reflectivity or other details…"
          : "Describe the image you want to create…");
    }

    const input = document.querySelector("#input-image");
    const inputLabel = input?.closest(".field")?.querySelector(":scope > span");
    if (inputLabel && active) {
      inputLabel.textContent = characterSheet
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
      if (characterSheet) {
        hint.textContent = file
          ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB · This identity reference will be reused for five separate high-quality generations.`
          : "Choose one clear character image. StableAMD will render Face / Front / 3/4 / Side / Back separately at 1024 × 1024, then show them together as a grid.";
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
    ensureCharacterSheetStyles();
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
      document.querySelector("#prompt")?.addEventListener("input", (event) => {
        if (event.target.dataset.characterSheetDefault === "true" && event.target.value !== CHARACTER_SHEET_DEFAULT_PROMPT) {
          delete event.target.dataset.characterSheetDefault;
        }
      });
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