(() => {
  const previousApi = api;
  let supportCatalog = { models: [] };
  let sourceFile = null;
  let paintTool = "brush";
  let drawing = false;
  let lastPoint = null;

  async function directApi(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const text = await response.text();
    let payload = null;
    if (text) {
      try { payload = JSON.parse(text); }
      catch { payload = { error: text }; }
    }
    if (!response.ok) throw new Error(payload?.error || `${response.status} ${response.statusText}`);
    return payload;
  }

  function collectLoraStackFromDom() {
    const stack = [];
    for (const row of document.querySelectorAll("[data-lora-stack-row]")) {
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

  function currentSupport() {
    const modelId = document.querySelector("#model-select")?.value || "";
    const models = Array.isArray(supportCatalog?.models) ? supportCatalog.models : [];
    return models.find((item) => String(item?.id || "") === String(modelId)) || null;
  }

  async function refreshInpaintSupport() {
    try {
      supportCatalog = await previousApi("/api/model-support") || { models: [] };
    } catch {
      supportCatalog = { models: [] };
    }
    syncInpaintUi();
  }

  function installStyles() {
    if (document.querySelector("#inpaint-styles")) return;
    const style = document.createElement("style");
    style.id = "inpaint-styles";
    style.textContent = `
      .inpaint-editor { display: grid; gap: 12px; }
      .inpaint-canvas-stage { position: relative; overflow: hidden; border: 1px solid var(--border, #303844); border-radius: 10px; background: #090b0e; max-width: 720px; }
      .inpaint-canvas-stage canvas { display: block; width: 100%; height: auto; }
      #inpaint-mask-canvas { position: absolute; inset: 0; touch-action: none; cursor: crosshair; }
      .inpaint-toolbar { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; }
      .inpaint-toolbar .field { min-width: 150px; flex: 1 1 150px; }
      .inpaint-tool-active { outline: 2px solid currentColor; }
      #inpaint-empty { padding: 34px 18px; text-align: center; color: #9da9b7; }
    `;
    document.head.append(style);
  }

  function ensureInpaintUi() {
    installStyles();
    const modeSelect = document.querySelector("#generation-mode");
    const modePanel = document.querySelector("#generation-mode-panel");
    if (!modeSelect || !modePanel) return null;

    if (!Array.from(modeSelect.options).some((option) => option.value === "inpaint")) {
      const option = document.createElement("option");
      option.value = "inpaint";
      option.textContent = "Inpainting";
      modeSelect.append(option);
    }

    let panel = document.querySelector("#inpaint-controls");
    if (panel) return panel;

    panel = document.createElement("div");
    panel.id = "inpaint-controls";
    panel.className = "model-root-card";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="inpaint-editor">
        <label class="field">
          <span>Source image <small>PNG, JPEG or WebP · max 20 MiB</small></span>
          <input id="inpaint-source-image" type="file" accept="image/png,image/jpeg,image/webp">
        </label>
        <div class="inpaint-canvas-stage" id="inpaint-canvas-stage">
          <div id="inpaint-empty">Choose an image, then paint the area StableAMD may replace.</div>
          <canvas id="inpaint-source-canvas" hidden></canvas>
          <canvas id="inpaint-mask-canvas" hidden aria-label="Inpainting mask canvas"></canvas>
        </div>
        <div class="inpaint-toolbar">
          <button class="button button-secondary inpaint-tool-active" id="inpaint-brush" type="button">Brush</button>
          <button class="button button-quiet" id="inpaint-eraser" type="button">Eraser</button>
          <button class="button button-quiet" id="inpaint-clear" type="button">Clear mask</button>
          <label class="field">
            <span>Brush size</span>
            <input id="inpaint-brush-size" type="range" min="4" max="256" step="2" value="64">
          </label>
          <label class="field">
            <span>Denoise strength <small>higher values allow larger changes</small></span>
            <input id="inpaint-denoise" type="number" min="0" max="1" step="0.05" value="0.8">
          </label>
        </div>
        <p id="inpaint-hint" class="history-model">Painted red areas are encoded into the managed PNG alpha mask. Source and mask stay local.</p>
      </div>`;
    modePanel.after(panel);

    modeSelect.addEventListener("change", syncInpaintUi);
    panel.querySelector("#inpaint-source-image").addEventListener("change", loadInpaintSource);
    panel.querySelector("#inpaint-brush").addEventListener("click", () => setPaintTool("brush"));
    panel.querySelector("#inpaint-eraser").addEventListener("click", () => setPaintTool("eraser"));
    panel.querySelector("#inpaint-clear").addEventListener("click", clearMask);

    const mask = panel.querySelector("#inpaint-mask-canvas");
    mask.addEventListener("pointerdown", beginStroke);
    mask.addEventListener("pointermove", continueStroke);
    mask.addEventListener("pointerup", endStroke);
    mask.addEventListener("pointercancel", endStroke);
    mask.addEventListener("pointerleave", (event) => { if (drawing && event.buttons === 0) endStroke(event); });
    syncInpaintUi();
    return panel;
  }

  function setPaintTool(tool) {
    paintTool = tool;
    document.querySelector("#inpaint-brush")?.classList.toggle("inpaint-tool-active", tool === "brush");
    document.querySelector("#inpaint-eraser")?.classList.toggle("inpaint-tool-active", tool === "eraser");
  }

  function canvasPoint(event) {
    const canvas = document.querySelector("#inpaint-mask-canvas");
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) * (canvas.width / rect.width),
      y: (event.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function drawStroke(from, to) {
    const canvas = document.querySelector("#inpaint-mask-canvas");
    const ctx = canvas.getContext("2d");
    const size = Number(document.querySelector("#inpaint-brush-size")?.value || 64);
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = size;
    ctx.globalCompositeOperation = paintTool === "eraser" ? "destination-out" : "source-over";
    ctx.strokeStyle = "rgba(255, 55, 55, 0.88)";
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
    ctx.restore();
  }

  function beginStroke(event) {
    const canvas = event.currentTarget;
    if (!sourceFile || canvas.hidden) return;
    drawing = true;
    canvas.setPointerCapture?.(event.pointerId);
    lastPoint = canvasPoint(event);
    drawStroke(lastPoint, lastPoint);
    event.preventDefault();
  }

  function continueStroke(event) {
    if (!drawing || !lastPoint) return;
    const point = canvasPoint(event);
    drawStroke(lastPoint, point);
    lastPoint = point;
    event.preventDefault();
  }

  function endStroke(event) {
    if (!drawing) return;
    drawing = false;
    lastPoint = null;
    try { event.currentTarget.releasePointerCapture?.(event.pointerId); } catch { }
  }

  function clearMask() {
    const canvas = document.querySelector("#inpaint-mask-canvas");
    if (!canvas) return;
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  }

  async function loadInpaintSource(event) {
    const file = event.target.files?.[0] || null;
    sourceFile = null;
    const sourceCanvas = document.querySelector("#inpaint-source-canvas");
    const maskCanvas = document.querySelector("#inpaint-mask-canvas");
    const empty = document.querySelector("#inpaint-empty");
    if (!file) {
      sourceCanvas.hidden = true;
      maskCanvas.hidden = true;
      empty.hidden = false;
      return;
    }
    if (!/^image\/(png|jpeg|webp)$/i.test(file.type || "")) {
      showToast("Inpainting accepts PNG, JPEG, or WebP source images.", "error");
      event.target.value = "";
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      showToast("Inpainting source image must be 20 MiB or smaller.", "error");
      event.target.value = "";
      return;
    }

    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error("Could not decode the inpainting source image."));
        image.src = url;
      });
      sourceCanvas.width = image.naturalWidth;
      sourceCanvas.height = image.naturalHeight;
      maskCanvas.width = image.naturalWidth;
      maskCanvas.height = image.naturalHeight;
      const ctx = sourceCanvas.getContext("2d", { willReadFrequently: true });
      ctx.clearRect(0, 0, sourceCanvas.width, sourceCanvas.height);
      ctx.drawImage(image, 0, 0);
      clearMask();
      sourceCanvas.hidden = false;
      maskCanvas.hidden = false;
      empty.hidden = true;
      sourceFile = file;
      document.querySelector("#inpaint-hint").textContent = `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB · paint the region to replace.`;
    } catch (error) {
      showToast(error.message, "error");
      event.target.value = "";
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function maskCoverage() {
    const canvas = document.querySelector("#inpaint-mask-canvas");
    if (!canvas || !canvas.width || !canvas.height) return 0;
    const data = canvas.getContext("2d", { willReadFrequently: true }).getImageData(0, 0, canvas.width, canvas.height).data;
    let painted = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] > 8) painted += 1;
    return painted / Math.max(1, data.length / 4);
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("Could not encode the inpainting input."));
      reader.onload = () => {
        const value = String(reader.result || "");
        const comma = value.indexOf(",");
        if (comma < 0) reject(new Error("Could not encode the inpainting input."));
        else resolve(value.slice(comma + 1));
      };
      reader.readAsDataURL(blob);
    });
  }

  async function buildInpaintInputImage() {
    if (!sourceFile) throw new Error("Choose a source image for inpainting.");
    const coverage = maskCoverage();
    if (coverage <= 0) throw new Error("Paint at least one area of the inpainting mask.");

    const sourceCanvas = document.querySelector("#inpaint-source-canvas");
    const maskCanvas = document.querySelector("#inpaint-mask-canvas");
    const composite = document.createElement("canvas");
    composite.width = sourceCanvas.width;
    composite.height = sourceCanvas.height;
    const ctx = composite.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(sourceCanvas, 0, 0);

    const pixels = ctx.getImageData(0, 0, composite.width, composite.height);
    const mask = maskCanvas.getContext("2d", { willReadFrequently: true }).getImageData(0, 0, maskCanvas.width, maskCanvas.height);
    for (let i = 0; i < pixels.data.length; i += 4) {
      // ComfyUI LoadImage exposes MASK as 1 - alpha. The visible red overlay
      // therefore becomes transparent alpha in the managed PNG.
      pixels.data[i + 3] = 255 - mask.data[i + 3];
    }
    ctx.putImageData(pixels, 0, 0);

    const blob = await new Promise((resolve, reject) => composite.toBlob((value) => value ? resolve(value) : reject(new Error("Could not create the inpainting PNG.")), "image/png"));
    const stem = sourceFile.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9._-]+/g, "_") || "input";
    return {
      name: `${stem}-StableAMD-inpaint.png`,
      mimeType: "image/png",
      dataBase64: await blobToBase64(blob),
    };
  }

  function syncInpaintUi() {
    const select = document.querySelector("#generation-mode");
    const panel = document.querySelector("#inpaint-controls");
    if (!select || !panel) return;
    const option = Array.from(select.options).find((item) => item.value === "inpaint");
    const supported = currentSupport()?.capabilities?.inpaint === "supported";
    if (option) {
      option.disabled = !supported;
      option.textContent = supported ? "Inpainting" : "Inpainting · unavailable for this model";
    }
    if (select.value === "inpaint" && !supported) select.value = "txt2img";
    panel.hidden = select.value !== "inpaint";
  }

  api = async function inpaintApi(path, options = {}) {
    const method = String(options?.method || "GET").toUpperCase();
    if (path === "/api/generate" && method === "POST" && document.querySelector("#generation-mode")?.value === "inpaint") {
      if (currentSupport()?.capabilities?.inpaint !== "supported") {
        throw new Error("Inpainting is not supported for the selected model.");
      }
      let payload = {};
      try { payload = options.body ? JSON.parse(options.body) : {}; }
      catch { payload = {}; }
      const denoise = Number(document.querySelector("#inpaint-denoise")?.value ?? 0.8);
      if (!Number.isFinite(denoise) || denoise < 0 || denoise > 1) throw new Error("Denoise strength must be between 0 and 1.");

      payload.mode = "inpaint";
      payload.denoise = denoise;
      payload.inputImage = await buildInpaintInputImage();
      delete payload.loraName;
      delete payload.loraModelStrength;
      delete payload.loraClipStrength;
      const stack = collectLoraStackFromDom();
      if (stack.length) payload.loraStack = stack;
      else delete payload.loraStack;
      return directApi(path, { ...options, body: JSON.stringify(payload) });
    }
    return previousApi(path, options);
  };

  document.addEventListener("DOMContentLoaded", () => {
    ensureInpaintUi();
    document.querySelector("#model-select")?.addEventListener("change", syncInpaintUi);
    document.querySelector("#generation-mode")?.addEventListener("change", syncInpaintUi);
    document.querySelector("#refresh-button")?.addEventListener("click", () => void refreshInpaintSupport());
    document.querySelector("#gallery-grid")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-history-index]");
      if (!button) return;
      const record = state.history[Number(button.dataset.historyIndex)];
      if (String(getValue(record, "mode", "Mode") || "").toLowerCase() !== "inpaint") return;
      const select = document.querySelector("#generation-mode");
      if (select && Array.from(select.options).some((option) => option.value === "inpaint" && !option.disabled)) select.value = "inpaint";
      const denoise = getValue(record, "denoise", "Denoise");
      if (denoise !== undefined && denoise !== null) document.querySelector("#inpaint-denoise").value = denoise;
      const input = document.querySelector("#inpaint-source-image");
      if (input) input.value = "";
      sourceFile = null;
      clearMask();
      document.querySelector("#inpaint-source-canvas").hidden = true;
      document.querySelector("#inpaint-mask-canvas").hidden = true;
      document.querySelector("#inpaint-empty").hidden = false;
      document.querySelector("#inpaint-hint").textContent = "Settings restored. Reselect the local source image and paint the mask again.";
      syncInpaintUi();
    });
    void refreshInpaintSupport();
  });
})();
