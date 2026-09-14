(() => {
  const previousApi = api;
  let outpaintRecord = null;

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
      margins: {
        left: readMargin("outpaint-left"),
        right: readMargin("outpaint-right"),
        top: readMargin("outpaint-top"),
        bottom: readMargin("outpaint-bottom"),
      },
    };
  }

  document.addEventListener("stableamd:load-generated-image", (event) => {
    const detail = event.detail || {};
    if (detail.action === "outpaint") outpaintRecord = detail.record || null;
    else if (detail.action === "inpaint" || detail.action === "img2img") outpaintRecord = null;
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelector("#generation-mode")?.addEventListener("change", (event) => {
      if (event.target.value !== "inpaint") outpaintRecord = null;
    });
  });

  api = async function outpaintContextApi(path, options = {}) {
    const method = String(options?.method || "GET").toUpperCase();
    if (path === "/api/generate" && method === "POST" && outpaintPrepared()) {
      let payload = {};
      try { payload = options.body ? JSON.parse(options.body) : {}; }
      catch { payload = {}; }
      const editContext = buildEditContext();
      const total = Object.values(editContext.margins).reduce((sum, value) => sum + value, 0);
      if (total <= 0) throw new Error("Outpaint requires at least one non-zero expansion margin.");
      payload.editContext = editContext;
      return previousApi(path, { ...options, body: JSON.stringify(payload) });
    }
    return previousApi(path, options);
  };
})();