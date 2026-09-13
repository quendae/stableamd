(() => {
  const postState = {
    outpaintRecord: null,
  };

  function installPostActionStyles() {
    if (document.querySelector("#post-action-styles")) return;
    const style = document.createElement("style");
    style.id = "post-action-styles";
    style.textContent = `
      .history-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin-top: 10px; }
      .history-actions .button { min-width: 0; padding-inline: 8px; }
      .outpaint-controls { display: grid; gap: 10px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border, #303844); }
      .outpaint-margin-grid { display: grid; grid-template-columns: repeat(4, minmax(90px, 1fr)); gap: 8px; }
      @media (max-width: 760px) { .outpaint-margin-grid { grid-template-columns: repeat(2, minmax(90px, 1fr)); } }
    `;
    document.head.append(style);
  }

  function recordImagePath(record) {
    return String(getValue(record, "imagePath", "ImagePath") || "");
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

  function selectEditingModel(record) {
    const modelSelect = document.querySelector("#model-select");
    if (!modelSelect || !Array.isArray(state.models)) throw new Error("Model selection is not available.");
    const recordId = String(getValue(record, "modelId", "ModelId") || "");
    let model = state.models.find((item) => String(getValue(item, "id", "Id") || "") === recordId && modelFamily(item).includes("sdxl"));
    if (!model) model = state.models.find((item) => modelFamily(item).includes("sdxl"));
    if (!model) throw new Error("Img2Img, inpaint and outpaint currently require an installed SDXL model.");
    const id = String(getValue(model, "id", "Id") || "");
    if (!Array.from(modelSelect.options).some((option) => option.value === id)) throw new Error("The SDXL editing model is not currently selectable.");
    modelSelect.value = id;
    modelSelect.dispatchEvent(new Event("change", { bubbles: true }));
    return model;
  }

  function restoreSourcePrompt(record) {
    const prompt = document.querySelector("#prompt");
    if (prompt) prompt.value = String(getValue(record, "prompt", "Prompt") || prompt.value || "");
  }

  async function handoffToImg2Img(record) {
    postActionEvent("img2img", record);
    selectEditingModel(record);
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
    showToast("Image sent to Img2Img.", "success");
  }

  async function handoffToInpaint(record) {
    postActionEvent("inpaint", record);
    selectEditingModel(record);
    restoreSourcePrompt(record);
    setPage("generate");
    await new Promise((resolve) => setTimeout(resolve, 0));
    const mode = document.querySelector("#generation-mode");
    if (!mode) throw new Error("Generation mode control is unavailable.");
    mode.value = "inpaint";
    mode.dispatchEvent(new Event("change", { bubbles: true }));
    const file = await fetchGeneratedFile(record, "stableamd-inpaint");
    assignFileInput(document.querySelector("#inpaint-source-image"), file);
    showToast("Image sent to Inpaint. Paint the region to replace.", "success");
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
        <p class="history-model">Expand the canvas, then use the normal inpaint prompt to generate the new border areas.</p>
      </div>
      <div class="outpaint-margin-grid">
        <label class="field"><span>Left</span><input id="outpaint-left" type="number" min="0" max="1024" step="64" value="256"></label>
        <label class="field"><span>Right</span><input id="outpaint-right" type="number" min="0" max="1024" step="64" value="256"></label>
        <label class="field"><span>Top</span><input id="outpaint-top" type="number" min="0" max="1024" step="64" value="0"></label>
        <label class="field"><span>Bottom</span><input id="outpaint-bottom" type="number" min="0" max="1024" step="64" value="0"></label>
      </div>
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
      // Caller draws synchronously after this promise resolves, so keep image data
      // decoded while releasing the backing object URL immediately afterwards.
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }
  }

  function outpaintMargin(id) {
    const value = Number(document.querySelector(`#${id}`)?.value || 0);
    if (!Number.isFinite(value) || value < 0 || value > 1024) throw new Error("Outpaint margins must be between 0 and 1024 pixels.");
    return Math.round(value / 8) * 8;
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
    const maskCtx = mask.getContext("2d");
    maskCtx.clearRect(0, 0, width, height);
    maskCtx.fillStyle = "rgba(255, 55, 55, 0.88)";
    maskCtx.fillRect(0, 0, width, height);
    maskCtx.clearRect(left, top, image.naturalWidth, image.naturalHeight);

    const widthInput = document.querySelector("#width");
    const heightInput = document.querySelector("#height");
    if (widthInput) widthInput.value = width;
    if (heightInput) heightInput.value = height;
    const hint = document.querySelector("#inpaint-hint");
    if (hint) hint.textContent = `Outpaint ${width} × ${height} · border areas are pre-masked; adjust with Brush/Eraser if needed.`;
    showToast("Outpaint canvas prepared. Adjust the mask or generate when ready.", "success");
  }

  async function handoffToOutpaint(record) {
    postActionEvent("outpaint", record);
    await handoffToInpaint(record);
    postState.outpaintRecord = record;
    const controls = ensureOutpaintControls();
    if (controls) controls.hidden = false;
    showToast("Outpaint ready. Choose expansion margins and prepare the canvas.", "success");
  }

  function handoffToUpscale(record) {
    postActionEvent("upscale", record);
    if (typeof window.openStableAmdUpscale === "function") {
      window.openStableAmdUpscale(record);
      return;
    }
    showToast("Upscale provider is not loaded yet.", "error");
  }

  function addGalleryActions() {
    const cards = Array.from(document.querySelectorAll("#gallery-grid .history-card"));
    cards.forEach((card, index) => {
      if (card.querySelector(".history-actions")) return;
      const record = state.history?.[index];
      if (!record || !recordImagePath(record)) return;
      const body = card.querySelector(".history-body");
      if (!body) return;
      const actions = document.createElement("div");
      actions.className = "history-actions";
      for (const [action, label] of [["upscale", "Upscale"], ["img2img", "Img2Img"], ["inpaint", "Inpaint"], ["outpaint", "Outpaint"]]) {
        const button = document.createElement("button");
        button.className = "button button-quiet";
        button.type = "button";
        button.dataset.postAction = action;
        button.dataset.postIndex = String(index);
        button.textContent = label;
        actions.append(button);
      }
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
  }

  document.addEventListener("DOMContentLoaded", () => {
    installPostActionStyles();
    ensureOutpaintControls();
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
