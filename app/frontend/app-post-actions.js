(() => {
  const postState = {
    outpaintRecord: null,
  };

  function loadCompactGenerateUi() {
    if (document.querySelector('script[data-stableamd-compact-generate]')) return;
    const script = document.createElement('script');
    script.src = '/app-generate-compact.js';
    script.dataset.stableamdCompactGenerate = '';
    document.body.append(script);
  }

  function iconSvg(name) {
    const common = 'viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
    const paths = {
      upscale: '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/><path d="M3 8l6-6M21 8l-6-6M3 16l6 6M21 16l-6 6"/>',
      img2img: '<rect x="3" y="5" width="14" height="14" rx="2"/><path d="m3 15 4-4 4 4 2-2 4 4"/><path d="M18 8h3m-1.5-1.5L21 8l-1.5 1.5"/>',
      inpaint: '<path d="m14 4 6 6-8.5 8.5a3 3 0 0 1-4.2 0l-1.8-1.8a3 3 0 0 1 0-4.2L14 4Z"/><path d="m11 7 6 6"/>',
      outpaint: '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/><rect x="7" y="7" width="10" height="10" rx="1"/>',
      delete: '<path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/>',
    };
    return `<svg ${common}>${paths[name] || ''}</svg>`;
  }

  function installPostActionStyles() {
    if (document.querySelector("#post-action-styles")) return;
    const style = document.createElement("style");
    style.id = "post-action-styles";
    style.textContent = `
      .history-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
      .history-actions .button { min-width: 0; min-height: 32px; padding: 0 9px; display: inline-flex; align-items: center; gap: 6px; }
      .history-actions .button svg { flex: 0 0 auto; }
      .history-actions .gallery-delete { margin-left: auto; color: var(--danger, #ef6f79); }
      .history-card-upscale .history-model { color: var(--accent, #ef6c45); }
      .outpaint-controls { display: grid; gap: 10px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border, #303844); }
      .outpaint-margin-grid { display: grid; grid-template-columns: repeat(4, minmax(90px, 1fr)); gap: 8px; }
      .outpaint-blend-field { max-width: 240px; }
      @media (max-width: 760px) { .outpaint-margin-grid { grid-template-columns: repeat(2, minmax(90px, 1fr)); } }
    `;
    document.head.append(style);
  }

  function recordImagePath(record) {
    return String(getValue(record, "imagePath", "ImagePath") || "");
  }

  function recordMode(record) {
    return String(getValue(record, "mode", "Mode") || "").toLowerCase();
  }

  function postActionEvent(action, record) {
    document.dispatchEvent(new CustomEvent("stableamd:load-generated-image", {
      detail: { imagePath: recordImagePath(record), action, record },
    }));
  }

  async function fetchGeneratedFile(record, namePrefix = "stableamd-source") {
    const path = recordImagePath(record);
    if (!path) throw new Error("This gallery record has no generated image.");
    const response = await fetch(`/api/image?path=${encodeURIComponent(path)}`, { cache: "no-store" });
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try { message = (await response.json())?.error || message; } catch { }
      throw new Error(message);
    }
    const blob = await response.blob();
    const extension = blob.type === "image/jpeg" ? ".jpg" : blob.type === "image/webp" ? ".webp" : ".png";
    return new File([blob], `${namePrefix}${extension}`, { type: blob.type || "image/png" });
  }

  function assignFileInput(input, file) {
    if (!input) throw new Error("The target image editor is not available.");
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function modelFamily(model) {
    return String(getValue(model, "family", "Family") || "").toLowerCase();
  }

  function modelId(model) {
    return String(getValue(model, "id", "Id") || "");
  }

  async function selectEditingModel(record, capability) {
    const modelSelect = document.querySelector("#model-select");
    if (!modelSelect || !Array.isArray(state.models)) throw new Error("Model selection is not available.");

    let supportModels = [];
    try {
      const support = await api("/api/model-support");
      supportModels = Array.isArray(support?.models) ? support.models : [];
    } catch { }
    const capabilitySupported = (id) => supportModels.some((item) => String(item?.id || "") === id && item?.capabilities?.[capability] === "supported");

    const recordId = String(getValue(record, "modelId", "ModelId") || "");
    const sourceModel = state.models.find((item) => modelId(item) === recordId) || null;
    let model = sourceModel && capabilitySupported(recordId) ? sourceModel : null;

    if (!model) {
      const supported = state.models.filter((item) => capabilitySupported(modelId(item)));
      model = supported.find((item) => modelFamily(item).includes("sdxl")) || supported[0] || null;
    }
    if (!model && sourceModel && modelFamily(sourceModel).includes("sdxl")) model = sourceModel;
    if (!model) model = state.models.find((item) => modelFamily(item).includes("sdxl")) || null;
    if (!model) throw new Error(`No installed model currently supports ${capability}.`);

    const id = modelId(model);
    if (!Array.from(modelSelect.options).some((option) => option.value === id)) throw new Error("The editing model is not currently selectable.");
    modelSelect.value = id;
    modelSelect.dispatchEvent(new Event("change", { bubbles: true }));
    return { model, usedSourceModel: Boolean(sourceModel && id === recordId) };
  }

  function restoreSourcePrompt(record) {
    const prompt = document.querySelector("#prompt");
    if (prompt) prompt.value = String(getValue(record, "prompt", "Prompt") || prompt.value || "");
  }

  async function handoffToImg2Img(record) {
    postActionEvent("img2img", record);
    const selection = await selectEditingModel(record, "img2img");
    restoreSourcePrompt(record);
    setPage("generate");
    await new Promise((resolve) => setTimeout(resolve, 0));
    const mode = document.querySelector("#generation-mode");
    if (!mode) throw new Error("Generation mode control is unavailable.");
    mode.value = "img2img";
    mode.dispatchEvent(new Event("change", { bubbles: true }));
    const file = await fetchGeneratedFile(record, "stableamd-img2img");
    assignFileInput(document.querySelector("#input-image"), file);
    document.querySelector("#prompt")?.focus();
    showToast(selection.usedSourceModel ? "Image sent to Img2Img with its source model." : "Image sent to Img2Img using a compatible editing model.", "success");
  }

  async function handoffToInpaint(record, action = "inpaint") {
    postActionEvent(action, record);
    const selection = await selectEditingModel(record, "inpaint");
    restoreSourcePrompt(record);
    setPage("generate");
    await new Promise((resolve) => setTimeout(resolve, 0));
    const mode = document.querySelector("#generation-mode");
    if (!mode) throw new Error("Generation mode control is unavailable.");
    mode.value = "inpaint";
    mode.dispatchEvent(new Event("change", { bubbles: true }));
    const file = await fetchGeneratedFile(record, action === "outpaint" ? "stableamd-outpaint-original" : "stableamd-inpaint");
    assignFileInput(document.querySelector("#inpaint-source-image"), file);
    if (action !== "outpaint") {
      postState.outpaintRecord = null;
      const controls = document.querySelector("#outpaint-controls");
      if (controls) controls.hidden = true;
      showToast(selection.usedSourceModel ? "Image sent to Inpaint with its source model." : "Image sent to Inpaint using a compatible editing model.", "success");
    }
    return selection;
  }

  function ensureOutpaintControls() {
    let controls = document.querySelector("#outpaint-controls");
    if (controls) return controls;
    const inpaint = document.querySelector("#inpaint-controls .inpaint-editor");
    if (!inpaint) return null;
    controls = document.createElement("div");
    controls.id = "outpaint-controls";
    controls.className = "outpaint-controls";
    controls.hidden = true;
    controls.innerHTML = `
      <div>
        <strong>Outpaint expansion</strong>
        <p class="history-model">The source prompt is restored automatically. Expand the canvas and StableAMD blends the new area into the original image instead of using a hard border.</p>
      </div>
      <div class="outpaint-margin-grid">
        <label class="field"><span>Left</span><input id="outpaint-left" type="number" min="0" max="1024" step="64" value="256"></label>
        <label class="field"><span>Right</span><input id="outpaint-right" type="number" min="0" max="1024" step="64" value="256"></label>
        <label class="field"><span>Top</span><input id="outpaint-top" type="number" min="0" max="1024" step="64" value="0"></label>
        <label class="field"><span>Bottom</span><input id="outpaint-bottom" type="number" min="0" max="1024" step="64" value="0"></label>
      </div>
      <label class="field outpaint-blend-field">
        <span>Blend overlap <small>soft transition into source</small></span>
        <input id="outpaint-blend" type="number" min="0" max="256" step="8" value="64">
      </label>
      <button class="button button-secondary" id="outpaint-prepare" type="button">Prepare expanded canvas</button>`;
    inpaint.append(controls);
    controls.querySelector("#outpaint-prepare").addEventListener("click", () => {
      if (!postState.outpaintRecord) return;
      void prepareOutpaintSource(postState.outpaintRecord).catch((error) => showToast(error.message, "error"));
    });
    return controls;
  }

  async function imageFromFile(file) {
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error("Could not decode the gallery image for outpainting."));
        image.src = url;
      });
      return image;
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }
  }

  function outpaintMargin(id) {
    const value = Number(document.querySelector(`#${id}`)?.value || 0);
    if (!Number.isFinite(value) || value < 0 || value > 1024) throw new Error("Outpaint margins must be between 0 and 1024 pixels.");
    return Math.round(value / 8) * 8;
  }

  function outpaintBlend() {
    const value = Number(document.querySelector("#outpaint-blend")?.value ?? 64);
    if (!Number.isFinite(value) || value < 0 || value > 256) throw new Error("Outpaint blend overlap must be between 0 and 256 pixels.");
    return Math.round(value / 8) * 8;
  }

  function paintOutpaintMask(mask, left, right, top, bottom, imageWidth, imageHeight, blend) {
    const ctx = mask.getContext("2d");
    const width = mask.width;
    const height = mask.height;
    const x0 = left;
    const y0 = top;
    const x1 = left + imageWidth;
    const y1 = top + imageHeight;
    const feather = Math.min(blend, Math.floor(imageWidth / 2), Math.floor(imageHeight / 2));
    const pixels = ctx.createImageData(width, height);
    const data = pixels.data;

    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const offset = (y * width + x) * 4;
        const outside = x < x0 || x >= x1 || y < y0 || y >= y1;
        let alpha = outside ? 255 : 0;
        if (!outside && feather > 0) {
          if (left > 0 && x < x0 + feather) alpha = Math.max(alpha, 255 * (1 - (x - x0 + 0.5) / feather));
          if (right > 0 && x >= x1 - feather) alpha = Math.max(alpha, 255 * (1 - (x1 - x - 0.5) / feather));
          if (top > 0 && y < y0 + feather) alpha = Math.max(alpha, 255 * (1 - (y - y0 + 0.5) / feather));
          if (bottom > 0 && y >= y1 - feather) alpha = Math.max(alpha, 255 * (1 - (y1 - y - 0.5) / feather));
        }
        data[offset] = 255;
        data[offset + 1] = 55;
        data[offset + 2] = 55;
        data[offset + 3] = Math.max(0, Math.min(255, Math.round(alpha)));
      }
    }
    ctx.putImageData(pixels, 0, 0);
  }

  async function waitForInpaintCanvas(width, height) {
    const deadline = performance.now() + 5000;
    while (performance.now() < deadline) {
      const source = document.querySelector("#inpaint-source-canvas");
      const mask = document.querySelector("#inpaint-mask-canvas");
      if (source?.width === width && source?.height === height && mask?.width === width && mask?.height === height) return mask;
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    throw new Error("The inpaint editor did not finish loading the expanded outpaint canvas.");
  }

  async function prepareOutpaintSource(record) {
    const sourceFile = await fetchGeneratedFile(record, "stableamd-outpaint-original");
    const image = await imageFromFile(sourceFile);
    const left = outpaintMargin("outpaint-left");
    const right = outpaintMargin("outpaint-right");
    const top = outpaintMargin("outpaint-top");
    const bottom = outpaintMargin("outpaint-bottom");
    const blend = outpaintBlend();
    if (left + right + top + bottom <= 0) throw new Error("Set at least one outpaint margin above zero.");

    const width = image.naturalWidth + left + right;
    const height = image.naturalHeight + top + bottom;
    if (width > 2048 || height > 2048) throw new Error(`Expanded outpaint canvas ${width} × ${height} exceeds the current 2048 px editor limit.`);

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(image, left, top);
    const blob = await new Promise((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error("Could not create the outpaint PNG.")), "image/png"));
    const expanded = new File([blob], "stableamd-outpaint.png", { type: "image/png" });
    assignFileInput(document.querySelector("#inpaint-source-image"), expanded);

    const mask = await waitForInpaintCanvas(width, height);
    paintOutpaintMask(mask, left, right, top, bottom, image.naturalWidth, image.naturalHeight, blend);

    const widthInput = document.querySelector("#width");
    const heightInput = document.querySelector("#height");
    if (widthInput) widthInput.value = width;
    if (heightInput) heightInput.value = height;
    const hint = document.querySelector("#inpaint-hint");
    if (hint) hint.textContent = `Outpaint ${width} × ${height} · ${blend}px blend overlap softens the transition into the source; adjust with Brush/Eraser if needed.`;
    showToast("Outpaint canvas prepared with a feathered blend zone.", "success");
  }

  async function handoffToOutpaint(record) {
    const selection = await handoffToInpaint(record, "outpaint");
    postState.outpaintRecord = record;
    const controls = ensureOutpaintControls();
    if (controls) controls.hidden = false;
    showToast(selection.usedSourceModel ? "Outpaint ready with the source model and prompt." : "Outpaint ready with the source prompt and a compatible editing model.", "success");
  }

  function handoffToUpscale(record) {
    postActionEvent("upscale", record);
    if (typeof window.openStableAmdUpscale === "function") {
      window.openStableAmdUpscale(record);
      return;
    }
    showToast("Upscale provider is not loaded yet.", "error");
  }

  async function deleteGalleryRecord(record) {
    const promptId = String(getValue(record, "promptId", "PromptId") || "").trim();
    if (!promptId) throw new Error("This Gallery item has no deletable history identifier.");
    if (!window.confirm("Delete this Gallery item and its local output image?")) return;

    const result = await api("/api/history/delete", {
      method: "POST",
      body: JSON.stringify({ promptId }),
    });
    if (!result?.deleted) throw new Error("Gallery item was not found on disk.");
    await refreshHistory();
    showToast(result.imageDeleted ? "Gallery item and image deleted." : "Gallery history item deleted.", "success");
  }

  function labelUpscaleCard(card, record) {
    if (recordMode(record) !== "upscale") return;
    card.classList.add("history-card-upscale");
    const modelName = String(getValue(record, "upscaleModel", "UpscaleModel") || getValue(record, "modelName", "ModelName") || "Upscaler");
    const scale = Number(getValue(record, "upscaleScale", "UpscaleScale"));
    const prompt = card.querySelector(".history-prompt");
    const model = card.querySelector(".history-model");
    if (prompt) prompt.textContent = Number.isFinite(scale) && scale > 0 ? `Upscaled image · ${scale}×` : "Upscaled image";
    if (model) model.textContent = `Upscale · ${modelName.replace(/^Upscale\s*·\s*/i, "")}`;
    card.querySelector(".reuse-button")?.remove();
  }

  function actionButton(action, label, index) {
    const button = document.createElement("button");
    button.className = `button button-quiet${action === "delete" ? " gallery-delete" : ""}`;
    button.type = "button";
    button.dataset.postAction = action;
    button.dataset.postIndex = String(index);
    button.setAttribute("aria-label", label);
    button.title = label;
    button.innerHTML = `${iconSvg(action)}<span>${label}</span>`;
    return button;
  }

  function addGalleryActions() {
    const cards = Array.from(document.querySelectorAll("#gallery-grid .history-card"));
    cards.forEach((card, index) => {
      const record = state.history?.[index];
      if (!record) return;
      labelUpscaleCard(card, record);
      if (card.querySelector(".history-actions")) return;
      const body = card.querySelector(".history-body");
      if (!body) return;
      const actions = document.createElement("div");
      actions.className = "history-actions";

      if (recordImagePath(record)) {
        for (const [action, label] of [["upscale", "Upscale"], ["img2img", "Img2Img"], ["inpaint", "Inpaint"], ["outpaint", "Outpaint"]]) {
          actions.append(actionButton(action, label, index));
        }
      }
      actions.append(actionButton("delete", "Delete", index));
      body.append(actions);
    });
  }

  async function handleGalleryPostAction(button) {
    const index = Number(button.dataset.postIndex);
    const record = state.history?.[index];
    if (!record) throw new Error("Gallery record is no longer available.");
    const action = button.dataset.postAction;
    if (action === "upscale") return handoffToUpscale(record);
    if (action === "img2img") return handoffToImg2Img(record);
    if (action === "inpaint") return handoffToInpaint(record);
    if (action === "outpaint") return handoffToOutpaint(record);
    if (action === "delete") return deleteGalleryRecord(record);
  }

  document.addEventListener("DOMContentLoaded", () => {
    installPostActionStyles();
    ensureOutpaintControls();
    loadCompactGenerateUi();
    const grid = document.querySelector("#gallery-grid");
    if (grid) {
      grid.addEventListener("click", (event) => {
        const button = event.target.closest("[data-post-action]");
        if (!button) return;
        button.disabled = true;
        Promise.resolve(handleGalleryPostAction(button))
          .catch((error) => showToast(error.message, "error"))
          .finally(() => { button.disabled = false; });
      });
      new MutationObserver(addGalleryActions).observe(grid, { childList: true });
    }
    addGalleryActions();
  });

  window.prepareOutpaintSource = prepareOutpaintSource;
})();