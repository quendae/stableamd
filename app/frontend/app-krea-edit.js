(() => {
  const baseKreaEditApi = api;

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
        return baseKreaEditApi(path, { ...options, body: JSON.stringify(payload) });
      }
    }
    return baseKreaEditApi(path, options);
  };

  function syncKreaEditUi() {
    const mode = document.querySelector("#generation-mode");
    if (!mode) return false;
    const family = modelFamily();
    const krea = family === "krea2";
    const active = krea && mode.value === "img2img";
    const imageOption = Array.from(mode.options).find((option) => option.value === "img2img");
    if (imageOption && krea) {
      imageOption.textContent = imageOption.disabled
        ? "Image Edit · unavailable until the Krea edit integration is ready"
        : "Image Edit";
    }

    const promptLabel = document.querySelector("#prompt")?.closest(".field")?.querySelector(":scope > span");
    if (promptLabel) promptLabel.textContent = active ? "Edit instruction" : "Prompt";

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
      hint.textContent = file
        ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB · Krea 2 whole-image edit uses this source as its reference.`
        : "Choose a source image, then describe the requested whole-image change in Edit instruction. No mask or denoise slider is used.";
    }
    return true;
  }

  function bindKreaEditUi() {
    const mode = document.querySelector("#generation-mode");
    const model = document.querySelector("#model-select");
    if (!mode || !model) return false;
    if (mode.dataset.kreaEditBound !== "true") {
      mode.dataset.kreaEditBound = "true";
      mode.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      model.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
      document.querySelector("#input-image")?.addEventListener("change", () => queueMicrotask(syncKreaEditUi));
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
