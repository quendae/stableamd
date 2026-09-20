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

  const CHARACTER_SHEET_DEFAULT_PROMPT = "Preserve the exact same person or character from Picture 1. Treat identity as fixed, not approximate: keep face shape, eyes, nose, mouth, age impression, hairstyle or fur, skin or fur tone, clothing, accessories, body proportions, colors, materials, and art style consistent across every view. Ignore background scenery, landmarks, furniture, statues, and other props from Picture 1. Use a clean neutral studio background with soft even lighting. Do not add text, labels, props, alternate outfits, extra characters, facial distortions, or identity drift.";
  const CHARACTER_SHEET_VIEWS = [
    { id: "face-close-up", label: "Face close-up" },
    { id: "front", label: "Front" },
    { id: "three-quarter", label: "3/4" },
    { id: "side", label: "Side" },
    { id: "back", label: "Back" },
  ];
  const CHARACTER_SHEET_IDENTITY_REFINE_VIEWS = new Set(["front", "three-quarter", "side"]);
  const CHARACTER_SHEET_JOB_POLL_MS = 1000;

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

  function selectedCharacterSheetFraming() {
    return String(document.querySelector("#krea-character-sheet-framing")?.value || "auto");
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

  function characterSheetSharedSeed(payload) {
    const explicit = Number(payload?.seed);
    if (Number.isSafeInteger(explicit) && explicit >= 0) return explicit;
    const values = new Uint32Array(1);
    if (globalThis.crypto?.getRandomValues) {
      globalThis.crypto.getRandomValues(values);
      return Number(values[0]);
    }
    return Math.floor(Math.random() * 0x100000000);
  }

  function updateCharacterSheetProgress(index, view, phase = "base") {
    const title = document.querySelector("#result-empty strong");
    const detail = document.querySelector("#result-empty p");
    if (title) title.textContent = `Character sheet · ${index + 1}/${CHARACTER_SHEET_VIEWS.length}`;
    if (detail) {
      detail.textContent = phase === "identity-refine"
        ? `Refining ${view.label} against the original face and FACE anchor.`
        : `Generating ${view.label}. Each view is rendered separately at full quality.`;
    }
  }

  function sleepCharacterSheet(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function waitForCharacterSheetGenerationJob(jobId) {
    const encoded = encodeURIComponent(jobId);
    for (;;) {
      const status = await baseKreaEditApi(`/api/generation-jobs/${encoded}`);
      const state = String(status?.status || "").toLowerCase();
      if (state === "completed") {
        return baseKreaEditApi(`/api/generation-jobs/${encoded}/result`);
      }
      if (state === "failed") {
        throw new Error(status?.error || "Character Sheet child generation failed.");
      }
      if (state !== "queued" && state !== "running") {
        throw new Error(`Character Sheet child generation entered an unknown state: ${state || "missing"}.`);
      }
      await sleepCharacterSheet(CHARACTER_SHEET_JOB_POLL_MS);
    }
  }

  async function submitCharacterSheetJob(path, options, payload) {
    const submitted = await baseKreaEditApi(path, { ...options, body: JSON.stringify(payload) });
    const jobId = String(submitted?.jobId || "");
    return jobId ? waitForCharacterSheetGenerationJob(jobId) : submitted;
  }

  function compactCharacterSheetItems(items) {
    return items.map((item, index) => ({
      CharacterSheetView: String(getValue(item, "CharacterSheetView", "characterSheetView") || CHARACTER_SHEET_VIEWS[index]?.id || ""),
      CharacterSheetLabel: String(getValue(item, "CharacterSheetLabel", "characterSheetLabel") || CHARACTER_SHEET_VIEWS[index]?.label || ""),
      CharacterSheetSourceFraming: String(getValue(item, "CharacterSheetSourceFraming", "characterSheetSourceFraming") || "source"),
      CharacterSheetWidth: Number(getValue(item, "CharacterSheetWidth", "characterSheetWidth") || getValue(item, "Width", "width") || 0),
      CharacterSheetHeight: Number(getValue(item, "CharacterSheetHeight", "characterSheetHeight") || getValue(item, "Height", "height") || 0),
      ModelId: String(getValue(item, "ModelId", "modelId") || ""),
      ModelName: String(getValue(item, "ModelName", "modelName") || "Krea 2 Turbo"),
      GenerationSeconds: Number(getValue(item, "GenerationSeconds", "generationSeconds") || 0),
      ImagePath: String(getValue(item, "ImagePath", "imagePath") || ""),
      HistoryPath: String(getValue(item, "HistoryPath", "historyPath") || ""),
    }));
  }

  function updateCharacterSheetComposeProgress() {
    const title = document.querySelector("#result-empty strong");
    const detail = document.querySelector("#result-empty p");
    if (title) title.textContent = "Character sheet · composing";
    if (detail) detail.textContent = "Combining the five identity-anchored views into one persisted character-sheet PNG.";
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
          const requestedFraming = selectedCharacterSheetFraming();
          const sharedSeed = characterSheetSharedSeed(payload);
          const items = [];
          let faceAnchorPath = "";

          for (const view of CHARACTER_SHEET_VIEWS) {
            updateCharacterSheetProgress(items.length, view, "base");
            const viewPayload = {
              ...payload,
              editTask: "character-sheet",
              characterSheetView: view.id,
              characterSheetFraming: requestedFraming,
              characterSheetPhase: "base",
              prompt: identityPrompt,
              seed: sharedSeed,
            };
            delete viewPayload.width;
            delete viewPayload.height;
            viewPayload.asyncJob = true;
            let result = await submitCharacterSheetJob(path, options, viewPayload);
            let imagePath = String(getValue(result, "ImagePath", "imagePath") || "");
            if (!imagePath) {
              throw new Error("Character Sheet child generation did not return an image path.");
            }

            if (view.id === "face-close-up") {
              faceAnchorPath = imagePath;
            } else if (faceAnchorPath && CHARACTER_SHEET_IDENTITY_REFINE_VIEWS.has(view.id)) {
              updateCharacterSheetProgress(items.length, view, "identity-refine");
              const baseHistoryPath = String(getValue(result, "HistoryPath", "historyPath") || "");
              const refinePayload = {
                ...payload,
                editTask: "character-sheet",
                characterSheetView: view.id,
                characterSheetFraming: requestedFraming,
                characterSheetPhase: "identity-refine",
                characterSheetAnchorImagePath: faceAnchorPath,
                characterSheetBaseImagePath: imagePath,
                characterSheetBaseHistoryPath: baseHistoryPath,
                prompt: identityPrompt,
                seed: sharedSeed,
              };
              delete refinePayload.width;
              delete refinePayload.height;
              refinePayload.asyncJob = true;
              result = await submitCharacterSheetJob(path, options, refinePayload);
              imagePath = String(getValue(result, "ImagePath", "imagePath") || "");
              if (!imagePath) {
                throw new Error(`Character Sheet identity refinement for ${view.label} did not return an image path.`);
              }
            }

            items.push({
              ...result,
              CharacterSheetView: view.id,
              CharacterSheetLabel: view.label,
            });
          }
          updateCharacterSheetComposeProgress();
          const compactItems = compactCharacterSheetItems(items);
          const sourceFraming = String(getValue(items[0], "CharacterSheetSourceFraming", "characterSheetSourceFraming") || "source");
          const composite = await baseKreaEditApi("/api/character-sheet/compose", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              items: compactItems,
              prompt: identityPrompt,
              sourceFraming,
              requestedFraming,
            }),
          });
          return {
            ...composite,
            CharacterSheetItems: items,
            CharacterSheetComposite: getValue(composite, "CharacterSheetComposite", "characterSheetComposite") || {
              ImagePath: getValue(composite, "ImagePath", "imagePath"),
              Width: getValue(composite, "Width", "width"),
              Height: getValue(composite, "Height", "height"),
            },
          };
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
      .character-sheet-composite { display:block; width:100%; max-height:72vh; object-fit:contain; border-radius:12px; background:rgba(255,255,255,.035); }
      .character-sheet-summary { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center; margin-top:12px; }
    `;
    document.head.append(style);
  }

  function renderCharacterSheetResult(result) {
    const composite = getValue(result, "CharacterSheetComposite", "characterSheetComposite") || result;
    const imagePath = getValue(composite, "ImagePath", "imagePath") || getValue(result, "ImagePath", "imagePath");
    if (!imagePath) {
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

    const image = document.createElement("img");
    image.className = "character-sheet-composite";
    image.src = imageUrl(String(imagePath));
    image.alt = "Completed five-view character sheet";

    const title = document.createElement("strong");
    title.className = "result-title";
    title.textContent = "Character sheet complete";
    const summary = document.createElement("div");
    summary.className = "character-sheet-summary";
    const model = document.createElement("span");
    model.textContent = String(getValue(result, "ModelName", "modelName") || "Krea 2");
    const size = document.createElement("span");
    const width = getValue(composite, "Width", "width") || getValue(result, "Width", "width") || "?";
    const height = getValue(composite, "Height", "height") || getValue(result, "Height", "height") || "?";
    size.textContent = `5 views · composite ${width} × ${height}`;
    const framing = document.createElement("span");
    framing.textContent = `framing: ${String(getValue(result, "CharacterSheetSourceFraming", "characterSheetSourceFraming") || "source")}`;
    const seconds = Number(getValue(result, "GenerationSeconds", "generationSeconds"));
    const time = document.createElement("span");
    time.textContent = Number.isFinite(seconds) && seconds > 0 ? `${seconds.toFixed(1)} s generation total` : "Sequential generation";
    summary.append(model, size, framing, time);
    target.append(image, title, summary);
  }

  renderGenerationResult = function kreaRenderGenerationResult(result) {
    const items = getValue(result, "CharacterSheetItems", "characterSheetItems");
    const composite = getValue(result, "CharacterSheetComposite", "characterSheetComposite");
    if (composite || (Array.isArray(items) && items.length)) {
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
          <label class="field">
            <span>Sheet framing</span>
            <select id="krea-character-sheet-framing">
              <option value="auto">Auto · detect portrait / full body</option>
              <option value="portrait">Portrait · head / shoulders / torso</option>
              <option value="full-body">Full body · head to toe</option>
            </select>
          </label>
          <p class="history-model">Strict identity mode first renders FACE as an anchor. Front, 3/4 and Side are then rendered normally and passed through a second identity-refinement edit using the original tight face crop plus the FACE anchor. Back stays a single rear-view pass so no extra face is introduced. Krea memory is released between jobs; the final 3 × 2 sheet is composed locally.</p>
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
          ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB · Strict identity Character Sheet uses the FACE result as an anchor and performs a second face-focused edit on Front / 3/4 / Side before composing the final PNG.`
          : "Choose one clear character image. FACE becomes the generated identity anchor; Front / 3/4 / Side then receive a second refinement pass against the original face crop and that anchor.";
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
      document.querySelector("#krea-character-sheet-framing")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
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