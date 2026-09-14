(() => {
  const previousApi = api;
  const DEFAULT_OUTPAINT_MARGIN = 256;
  let outpaintRecord = null;
  let autoPreparing = false;

  function getValue(record, camel, pascal) {
    if (!record || typeof record !== "object") return undefined;
    if (Object.prototype.hasOwnProperty.call(record, camel)) return record[camel];
    return record[pascal];
  }

  function readMargin(id) {
    const value = Number(document.querySelector(`#${id}`)?.value || 0);
    if (!Number.isFinite(value)) return 0;
    return Math.max(0, Math.min(1024, Math.round(value / 8) * 8));
  }

  function readBlendOverlap() {
    const value = Number(document.querySelector("#outpaint-blend")?.value ?? 64);
    if (!Number.isFinite(value)) return 64;
    return Math.max(0, Math.min(256, Math.round(value / 8) * 8));
  }

  function outpaintPrepared() {
    if (!outpaintRecord) return false;
    const controls = document.querySelector("#outpaint-controls");
    const input = document.querySelector("#inpaint-source-image");
    const file = input?.files?.[0];
    return controls && !controls.hidden && file && /^stableamd-outpaint\.png$/i.test(file.name || "");
  }

  function buildEditContext() {
    return {
      kind: "outpaint",
      sourcePromptId: String(getValue(outpaintRecord, "promptId", "PromptId") || ""),
      sourceImagePath: String(getValue(outpaintRecord, "imagePath", "ImagePath") || ""),
      blendOverlap: readBlendOverlap(),
      margins: {
        left: readMargin("outpaint-left"),
        right: readMargin("outpaint-right"),
        top: readMargin("outpaint-top"),
        bottom: readMargin("outpaint-bottom"),
      },
    };
  }

  function useOutpaintDenoiseDefault() {
    const denoise = document.querySelector("#inpaint-denoise");
    if (denoise) denoise.value = "1";
  }

  function useOutpaintMarginDefaults() {
    for (const side of ["left", "right", "top", "bottom"]) {
      const input = document.querySelector(`#outpaint-${side}`);
      if (input) input.value = String(DEFAULT_OUTPAINT_MARGIN);
    }
  }

  function syncPreparedDimensions() {
    const source = document.querySelector("#inpaint-source-canvas");
    if (!source?.width || !source?.height) return;

    const tier = document.querySelector("#resolution-tier");
    if (tier && Array.from(tier.options).some((option) => option.value === "custom")) {
      tier.value = "custom";
      tier.dispatchEvent(new Event("change", { bubbles: true }));
    }

    const width = document.querySelector("#width");
    const height = document.querySelector("#height");
    if (width) {
      width.value = String(source.width);
      width.dispatchEvent(new Event("input", { bubbles: true }));
      width.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (height) {
      height.value = String(source.height);
      height.dispatchEvent(new Event("input", { bubbles: true }));
      height.dispatchEvent(new Event("change", { bubbles: true }));
    }

    document.dispatchEvent(new CustomEvent("stableamd:outpaint-prepared", {
      detail: {
        width: source.width,
        height: source.height,
        margins: buildEditContext().margins,
      },
    }));
  }

  async function waitForPreparedSourceCanvas(file) {
    const url = URL.createObjectURL(file);
    let width = 0;
    let height = 0;
    try {
      const image = new Image();
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error("Could not decode the prepared outpaint canvas."));
        image.src = url;
      });
      width = image.naturalWidth;
      height = image.naturalHeight;
    } finally {
      URL.revokeObjectURL(url);
    }

    const deadline = performance.now() + 5000;
    while (performance.now() < deadline) {
      const canvas = document.querySelector("#inpaint-source-canvas");
      if (canvas?.width === width && canvas?.height === height) {
        const left = readMargin("outpaint-left");
        const right = readMargin("outpaint-right");
        const top = readMargin("outpaint-top");
        const bottom = readMargin("outpaint-bottom");
        const sourceWidth = width - left - right;
        const sourceHeight = height - top - bottom;
        if (sourceWidth > 0 && sourceHeight > 0) {
          const probeX = Math.min(width - 1, Math.max(0, left + Math.floor(sourceWidth / 2)));
          const probeY = Math.min(height - 1, Math.max(0, top + Math.floor(sourceHeight / 2)));
          const alpha = canvas.getContext("2d", { willReadFrequently: true }).getImageData(probeX, probeY, 1, 1).data[3];
          if (alpha > 0) return canvas;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    throw new Error("The prepared outpaint source did not finish loading in the editor.");
  }

  async function seedOutpaintCanvas(file) {
    const canvas = await waitForPreparedSourceCanvas(file);
    const left = readMargin("outpaint-left");
    const right = readMargin("outpaint-right");
    const top = readMargin("outpaint-top");
    const bottom = readMargin("outpaint-bottom");
    const sourceWidth = canvas.width - left - right;
    const sourceHeight = canvas.height - top - bottom;
    if (sourceWidth <= 0 || sourceHeight <= 0) return;

    const source = document.createElement("canvas");
    source.width = sourceWidth;
    source.height = sourceHeight;
    source.getContext("2d").drawImage(canvas, left, top, sourceWidth, sourceHeight, 0, 0, sourceWidth, sourceHeight);

    const ctx = canvas.getContext("2d");
    const blur = Math.max(24, Math.min(96, readBlendOverlap() || 64));
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.filter = `blur(${blur}px)`;
    ctx.drawImage(source, -blur * 2, -blur * 2, canvas.width + blur * 4, canvas.height + blur * 4);
    ctx.restore();
    ctx.drawImage(source, left, top);
    canvas.dataset.outpaintLatentSeed = "blurred-edge";
  }

  async function autoPrepareOutpaint() {
    if (!outpaintRecord || autoPreparing) return;
    if (typeof window.prepareOutpaintSource !== "function") return;

    autoPreparing = true;
    const prepareButton = document.querySelector("#outpaint-prepare");
    const hint = document.querySelector("#inpaint-hint");
    if (prepareButton) prepareButton.disabled = true;
    if (hint) hint.textContent = "Preparing 256 px outpaint expansion on every side…";
    showToast("Preparing 256 px outpaint expansion on every side…", "success");
    try {
      await window.prepareOutpaintSource(outpaintRecord);
      syncPreparedDimensions();
    } finally {
      autoPreparing = false;
      if (prepareButton) prepareButton.disabled = false;
    }
  }

  document.addEventListener("stableamd:load-generated-image", (event) => {
    const detail = event.detail || {};
    if (detail.action === "outpaint") {
      outpaintRecord = detail.record || null;
      useOutpaintMarginDefaults();
      useOutpaintDenoiseDefault();
    } else if (detail.action === "img2img" || detail.action === "inpaint") {
      outpaintRecord = null;
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelector("#generation-mode")?.addEventListener("change", (event) => {
      if (event.target.value !== "inpaint") outpaintRecord = null;
    });
    document.querySelector("#inpaint-source-image")?.addEventListener("change", (event) => {
      const file = event.target.files?.[0];
      if (!outpaintRecord || !file) return;

      useOutpaintDenoiseDefault();
      if (/^stableamd-outpaint-original\.(png|jpe?g|webp)$/i.test(file.name || "")) {
        void autoPrepareOutpaint().catch((error) => showToast(`Outpaint preparation failed: ${error.message}`, "error"));
        return;
      }
      if (!/^stableamd-outpaint\.png$/i.test(file.name || "")) return;
      void seedOutpaintCanvas(file)
        .then(syncPreparedDimensions)
        .catch((error) => showToast(`Outpaint preparation warning: ${error.message}`, "error"));
    });
  });

  api = async function outpaintContextApi(path, options = {}) {
    const method = String(options?.method || "GET").toUpperCase();
    if (path === "/api/generate" && method === "POST" && outpaintPrepared()) {
      let payload = {};
      try { payload = options.body ? JSON.parse(options.body) : {};
      } catch { payload = {}; }
      const editContext = buildEditContext();
      const total = Object.values(editContext.margins).reduce((sum, value) => sum + value, 0);
      if (total <= 0) throw new Error("Outpaint requires at least one non-zero expansion margin.");
      payload.editContext = editContext;
      return previousApi(path, { ...options, body: JSON.stringify(payload) });
    }
    return previousApi(path, options);
  };
})();