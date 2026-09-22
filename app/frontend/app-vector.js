(() => {
  const vectorState = {
    dependency: null,
    result: null,
  };

  pageMeta.vector = ["Vector", "Create clean editable SVG assets from text prompts."];

  const vectorQuery = (selector) => document.querySelector(selector);
  const vectorValue = (record, ...keys) => {
    for (const key of keys) {
      if (record && Object.prototype.hasOwnProperty.call(record, key)) return record[key];
    }
    return undefined;
  };

  function isVectorRecord(record) {
    return String(vectorValue(record, "assetType", "AssetType") || "").toLowerCase() === "svg";
  }

  function dependencyLabel(dependency) {
    const status = String(dependency?.status || "missing").toLowerCase();
    if (dependency?.ready) return "Vectorizer ready";
    if (status === "invalid") return "Vectorizer installation needs repair";
    return "Vectorizer is not installed";
  }

  function renderDependency(dependency) {
    vectorState.dependency = dependency || null;
    const panel = vectorQuery("#vector-dependency");
    const status = vectorQuery("#vector-dependency-status");
    const detail = vectorQuery("#vector-dependency-detail");
    const install = vectorQuery("#vector-install");
    const generate = vectorQuery("#vector-generate");
    if (!panel || !status || !detail || !install || !generate) return;

    const ready = Boolean(dependency?.ready);
    const current = String(dependency?.status || "missing").toLowerCase();
    panel.dataset.state = ready ? "ready" : current;
    status.textContent = dependencyLabel(dependency);
    const tracerVersion = dependency?.vtracer?.version || "1.0.0-alpha.4";
    const rendererVersion = dependency?.previewRenderer?.version || "0.5.0";
    detail.textContent = ready
      ? `VTracer ${tracerVersion} · SVG preview renderer ${rendererVersion}`
      : "StableAMD installs the pinned local vectorizer and preview renderer before the first SVG run.";
    install.hidden = ready;
    install.disabled = false;
    generate.disabled = !ready;
  }

  async function refreshDependency() {
    try {
      const dependency = await api("/api/vector/dependency");
      renderDependency(dependency);
      return dependency;
    } catch (error) {
      renderDependency({ ready: false, status: "missing" });
      showToast(`Vector dependency check failed: ${error.message}`, "error");
      return null;
    }
  }

  async function installDependency() {
    const button = vectorQuery("#vector-install");
    if (!button) return;
    button.disabled = true;
    const oldText = button.textContent;
    button.textContent = "Installing…";
    try {
      const dependency = await api("/api/vector/install", {
        method: "POST",
        body: JSON.stringify({ id: "text-to-svg-v1" }),
      });
      renderDependency(dependency);
      showToast("Vectorizer installed and ready.", "success");
    } catch (error) {
      showToast(`Vectorizer install failed: ${error.message}`, "error");
      await refreshDependency();
    } finally {
      button.disabled = false;
      if (!vectorState.dependency?.ready) button.textContent = oldText;
    }
  }

  function setVectorWorkflow(workflow) {
    vectorState.workflow = workflow === "image" ? "image" : "text";
    const textButton = vectorQuery("#vector-workflow-text");
    const imageButton = vectorQuery("#vector-workflow-image");
    const textControls = vectorQuery("#vector-text-controls");
    const imageControls = vectorQuery("#vector-image-controls");
    const generate = vectorQuery("#vector-generate");
    if (textButton) {
      textButton.classList.toggle("is-active", vectorState.workflow === "text");
      textButton.setAttribute("aria-selected", vectorState.workflow === "text" ? "true" : "false");
    }
    if (imageButton) {
      imageButton.classList.toggle("is-active", vectorState.workflow === "image");
      imageButton.setAttribute("aria-selected", vectorState.workflow === "image" ? "true" : "false");
    }
    if (textControls) textControls.hidden = vectorState.workflow !== "text";
    if (imageControls) imageControls.hidden = vectorState.workflow !== "image";
    if (generate) generate.textContent = vectorState.workflow === "image" ? "Convert to SVG" : "Generate SVG";
    if (vectorState.workflow === "image") syncImageVectorStylization();
  }

  function updateRangeOutput(id, valueId) {
    const input = vectorQuery(id);
    const output = vectorQuery(valueId);
    if (input && output) output.value = input.value;
  }

  function syncImageVectorStylization() {
    const mode = vectorQuery("#image-vector-mode")?.value || "artwork";
    const field = vectorQuery("#image-vector-stylization-field");
    if (field) field.hidden = mode !== "photo-stylized";
    const creative = mode === "photo-stylized" && vectorQuery("#image-vector-stylization")?.value === "creative";
    const sourceStatus = vectorQuery("#image-vector-source-status");
    if (creative && sourceStatus && !vectorState.imageSource) {
      sourceStatus.textContent = "Creative mode requires a source image.";
    }
  }

  function readImageVectorFile(file) {
    return new Promise((resolve, reject) => {
      if (!file) return reject(new Error("Choose an image."));
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
        return reject(new Error("Image-to-SVG supports PNG, JPEG, or WebP."));
      }
      if (file.size > 20 * 1024 * 1024) return reject(new Error("Image must be 20 MiB or smaller."));
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("Could not read the source image."));
      reader.onload = () => {
        const encoded = String(reader.result || "");
        const comma = encoded.indexOf(",");
        if (comma < 0) return reject(new Error("Could not encode the source image."));
        resolve({ name: file.name, mimeType: file.type, dataBase64: encoded.slice(comma + 1) });
      };
      reader.readAsDataURL(file);
    });
  }

  function imageVectorPreviewUrl(source) {
    if (!source) return "";
    if (source.kind === "upload") {
      return source.image ? `data:${source.image.mimeType};base64,${source.image.dataBase64}` : "";
    }
    const record = state.history?.find((item) => String(vectorValue(item, "promptId", "PromptId") || "") === String(source.id || ""));
    const path = vectorValue(record, "imagePath", "ImagePath");
    return path ? imageUrl(path) : "";
  }

  function renderImageVectorCropEditor() {
    const editor = vectorQuery("#image-vector-crop-editor");
    const cropMode = vectorQuery("#image-vector-crop")?.value || "preserve";
    if (!editor) return;
    if (cropMode !== "manual" || !vectorState.imageSource) {
      editor.hidden = true;
      editor.replaceChildren();
      return;
    }
    editor.hidden = false;
    editor.replaceChildren();
    const image = document.createElement("img");
    image.className = "image-vector-crop-preview";
    image.alt = "Image-to-SVG crop source";
    image.src = imageVectorPreviewUrl(vectorState.imageSource);
    const grid = document.createElement("div");
    grid.className = "vector-crop-fields";
    const values = vectorState.imageSource.crop || {x: 0, y: 0, width: 1, height: 1};
    for (const [key, label] of [["x", "X"], ["y", "Y"], ["width", "Width"], ["height", "Height"]]) {
      const wrapper = document.createElement("label");
      wrapper.className = "field";
      const span = document.createElement("span");
      span.textContent = label;
      const input = document.createElement("input");
      input.type = "number";
      input.min = key === "width" || key === "height" ? "1" : "0";
      input.value = String(values[key]);
      input.dataset.cropField = key;
      input.addEventListener("input", () => {
        vectorState.imageSource.crop = {
          ...(vectorState.imageSource.crop || values),
          [key]: Number(input.value),
        };
      });
      wrapper.append(span, input);
      grid.append(wrapper);
    }
    editor.append(image, grid);
  }

  function setImageVectorSource(source, label) {
    vectorState.imageSource = source;
    const status = vectorQuery("#image-vector-source-status");
    if (status) status.textContent = label || "Image source selected.";
    renderImageVectorCropEditor();
  }

  function useCurrentImageVector() {
    const result = window.StableAmdCurrentImage;
    const path = vectorValue(result, "ImagePath", "imagePath");
    const promptId = vectorValue(result, "PromptId", "promptId");
    if (!path || !promptId) {
      showToast("No current Generate/Image Edit result is available.", "error");
      return;
    }
    setImageVectorSource({ kind: "current", id: String(promptId) }, "Current image selected.");
    setPage("vector");
  }

  function chooseImageVectorGallery() {
    setPage("gallery");
    showToast("Choose a raster Gallery item and use Convert to SVG.", "info");
  }

  function imageVectorPayload() {
    if (!vectorState.imageSource) throw new Error("Select an image source first.");
    const mode = vectorQuery("#image-vector-mode")?.value || "artwork";
    const stylization = mode === "photo-stylized"
      ? (vectorQuery("#image-vector-stylization")?.value || "preserve")
      : undefined;
    const colorsRaw = vectorQuery("#image-vector-colors")?.value || "auto";
    const cropMode = vectorQuery("#image-vector-crop")?.value || "preserve";
    const payload = {
      source: vectorState.imageSource,
      mode,
      detail: vectorQuery("#image-vector-detail")?.value || "medium",
      colors: colorsRaw === "auto" ? "auto" : Number(colorsRaw),
      background: vectorQuery("#image-vector-background")?.value || "preserve",
      cropMode,
      advanced: {
        smoothing: Number(vectorQuery("#image-vector-smoothing")?.value || 0),
        edgeStrength: Number(vectorQuery("#image-vector-edge")?.value || 0),
        denoise: Number(vectorQuery("#image-vector-denoise")?.value || 0),
        posterize: Number(vectorQuery("#image-vector-posterize")?.value || 0),
        backgroundTolerance: Number(vectorQuery("#image-vector-tolerance")?.value || 18),
      },
    };
    if (stylization) payload.stylization = stylization;
    if (cropMode === "manual") {
      const crop = vectorState.imageSource?.crop;
      if (!crop) throw new Error("Define the manual crop rectangle first.");
      payload.crop = {
        x: Math.max(0, Math.trunc(Number(crop.x))),
        y: Math.max(0, Math.trunc(Number(crop.y))),
        width: Math.max(1, Math.trunc(Number(crop.width))),
        height: Math.max(1, Math.trunc(Number(crop.height))),
      };
    }
    return payload;
  }

  function applyImageVectorPreset() {
    const mode = vectorQuery("#image-vector-mode")?.value || "artwork";
    const stylization = mode === "photo-stylized" ? (vectorQuery("#image-vector-stylization")?.value || "preserve") : null;
    const preset = {
      artwork: {smoothing:20, edgeStrength:70, denoise:10, posterize:20},
      "photo-direct": {smoothing:35, edgeStrength:55, denoise:35, posterize:45},
      preserve: {smoothing:55, edgeStrength:65, denoise:50, posterize:70},
      creative: {smoothing:30, edgeStrength:60, denoise:20, posterize:35},
    }[mode === "photo-stylized" ? stylization : mode] || {smoothing:20, edgeStrength:70, denoise:10, posterize:20};
    for (const [id, value] of Object.entries(preset)) {
      const input = vectorQuery("#image-vector-" + id.replace("edgeStrength", "edge").replace("posterize", "posterize"));
      if (input) input.value = String(value);
    }
    updateRangeOutput("#image-vector-smoothing", "#image-vector-smoothing-value");
    updateRangeOutput("#image-vector-edge", "#image-vector-edge-value");
    updateRangeOutput("#image-vector-denoise", "#image-vector-denoise-value");
    updateRangeOutput("#image-vector-posterize", "#image-vector-posterize-value");
  }

  function toggleSolidColor() {
    const background = vectorQuery("#vector-background")?.value || "transparent";
    const field = vectorQuery("#vector-background-color-field");
    if (field) field.hidden = background !== "solid";
  }

  function vectorPayload() {
    const prompt = vectorQuery("#vector-prompt")?.value.trim() || "";
    if (!prompt) throw new Error("Enter a Vector prompt first.");
    const colorsRaw = vectorQuery("#vector-colors")?.value || "auto";
    const background = vectorQuery("#vector-background")?.value || "transparent";
    const payload = {
      prompt,
      style: vectorQuery("#vector-style")?.value || "icon",
      detail: vectorQuery("#vector-detail")?.value || "medium",
      colors: colorsRaw === "auto" ? "auto" : Number(colorsRaw),
      background,
    };
    if (background === "solid") {
      payload.backgroundColor = vectorQuery("#vector-background-color")?.value || "#ffffff";
    }
    const seedRaw = vectorQuery("#vector-seed")?.value.trim() || "";
    if (seedRaw) payload.seed = Number(seedRaw);
    return payload;
  }

  async function waitForJobsInterface(timeoutMs = 10000) {
    const deadline = performance.now() + timeoutMs;
    while (performance.now() < deadline) {
      if (window.StableAmdJobs?.waitForGenerationJob) return window.StableAmdJobs;
      await new Promise((resolve) => window.setTimeout(resolve, 25));
    }
    throw new Error("StableAMD job transport did not become ready.");
  }

  function appendMeta(meta, label, value) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value === undefined || value === null || value === "" ? "—" : String(value);
    meta.append(dt, dd);
  }

  function sourcePath(record) {
    return String(vectorValue(record, "svgPath", "SvgPath") || "");
  }

  function previewPath(record) {
    return String(vectorValue(record, "previewPath", "PreviewPath", "imagePath", "ImagePath") || "");
  }

  function renderVectorResult(result) {
    vectorState.result = result || null;
    const empty = vectorQuery("#vector-result-empty");
    const target = vectorQuery("#vector-result");
    if (!target || !empty) return;
    empty.hidden = true;
    target.hidden = false;
    target.replaceChildren();

    const preview = previewPath(result);
    if (preview) {
      const image = document.createElement("img");
      image.className = "vector-result-image";
      image.src = imageUrl(preview);
      image.alt = String(vectorValue(result, "prompt", "Prompt") || "Generated vector preview");
      target.append(image);
    }

    const heading = document.createElement("div");
    heading.className = "vector-result-heading";
    const title = document.createElement("strong");
    title.textContent = "SVG ready";
    const badge = document.createElement("span");
    badge.className = "vector-badge";
    badge.textContent = "SVG";
    heading.append(title, badge);

    const meta = document.createElement("dl");
    meta.className = "result-meta vector-result-meta";
    appendMeta(meta, "Style", vectorValue(result, "style", "Style"));
    appendMeta(meta, "Detail", vectorValue(result, "detail", "Detail"));
    appendMeta(meta, "Colors", vectorValue(result, "colors", "Colors"));
    appendMeta(meta, "Paths", vectorValue(result, "pathCount", "PathCount"));
    appendMeta(meta, "Nodes", vectorValue(result, "nodeCount", "NodeCount"));
    appendMeta(meta, "Seed", vectorValue(result, "seed", "Seed") ?? "random");
    appendMeta(meta, "Raster", `${vectorValue(result, "generationSeconds", "GenerationSeconds") ?? "?"} s`);
    appendMeta(meta, "Vectorize", `${vectorValue(result, "vectorizationSeconds", "VectorizationSeconds") ?? "?"} s`);

    const actions = document.createElement("div");
    actions.className = "vector-result-actions";
    const download = document.createElement("button");
    download.type = "button";
    download.className = "button button-secondary";
    download.textContent = "Download SVG";
    download.addEventListener("click", () => void downloadSvg(result).catch((error) => showToast(error.message, "error")));
    const view = document.createElement("button");
    view.type = "button";
    view.className = "button button-quiet";
    view.textContent = "View source";
    view.addEventListener("click", () => void openSource(result).catch((error) => showToast(error.message, "error")));
    actions.append(download, view);

    const path = document.createElement("code");
    path.className = "vector-path";
    path.textContent = sourcePath(result) || "SVG path unavailable";
    target.append(heading, meta, actions, path);
  }

  async function fetchSvgSource(record) {
    const path = sourcePath(record);
    if (!path) throw new Error("This Vector record has no SVG path.");
    return api(`/api/vector/source?path=${encodeURIComponent(path)}`);
  }

  function ensureSourcePanel() {
    let panel = vectorQuery("#vector-source-panel");
    if (panel) return panel;
    panel = document.createElement("section");
    panel.id = "vector-source-panel";
    panel.className = "vector-source-panel";
    panel.hidden = true;
    const heading = document.createElement("div");
    heading.className = "vector-source-heading";
    const title = document.createElement("strong");
    title.textContent = "Sanitized SVG source";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "button button-quiet";
    close.textContent = "Close";
    close.addEventListener("click", () => { panel.hidden = true; });
    heading.append(title, close);
    const source = document.createElement("pre");
    source.className = "vector-source-code";
    source.dataset.vectorSource = "";
    panel.append(heading, source);
    vectorQuery("#page-vector")?.append(panel);
    return panel;
  }

  async function openSource(record) {
    const payload = await fetchSvgSource(record);
    const panel = ensureSourcePanel();
    const source = panel.querySelector("[data-vector-source]");
    source.textContent = payload.svg;
    panel.hidden = false;
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function downloadSvg(record) {
    const payload = await fetchSvgSource(record);
    const blob = new Blob([payload.svg], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = payload.fileName || "stableamd-vector.svg";
      anchor.hidden = true;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    } finally {
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    }
  }

  async function submitImageVector() {
    const payload = imageVectorPayload();
    const submitted = await api("/api/vector/image-to-svg", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const jobId = String(submitted?.jobId || "");
    if (!jobId) return submitted;
    const jobs = await waitForJobsInterface();
    return jobs.waitForGenerationJob(jobId);
  }

  async function submitVector(event) {
    event.preventDefault();
    if (!vectorState.dependency?.ready) {
      showToast("Install the Vectorizer before generating SVG assets.", "error");
      return;
    }
    let payload;
    try {
      payload = vectorState.workflow === "image" ? imageVectorPayload() : vectorPayload();
    } catch (error) {
      showToast(error.message, "error");
      if (vectorState.workflow === "text") vectorQuery("#vector-prompt")?.focus();
      return;
    }

    const button = vectorQuery("#vector-generate");
    const empty = vectorQuery("#vector-result-empty");
    const resultPane = vectorQuery("#vector-result");
    button.disabled = true;
    button.textContent = "Generating SVG…";
    empty.hidden = false;
    empty.querySelector("strong").textContent = "Vector generation in progress";
    empty.querySelector("p").textContent = "StableAMD is generating a clean raster source, releasing GPU memory, then tracing and sanitizing the SVG.";
    resultPane.hidden = true;

    try {
      let result;
      if (vectorState.workflow === "image") {
        result = await submitImageVector();
      } else {
        const submitted = await api("/api/vector/text-to-svg", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        result = submitted;
        const jobId = String(submitted?.jobId || "");
        if (jobId) {
          const jobs = await waitForJobsInterface();
          result = await jobs.waitForGenerationJob(jobId);
        }
      }
      renderVectorResult(result);
      if (typeof refreshHistory === "function") await refreshHistory();
      showToast(vectorState.workflow === "image" ? "Image converted to SVG." : "SVG generated and sanitized.", "success");
    } catch (error) {
      empty.hidden = false;
      empty.querySelector("strong").textContent = "Vector generation failed";
      empty.querySelector("p").textContent = error.message;
      showToast(error.message, "error");
    } finally {
      button.disabled = !vectorState.dependency?.ready;
      button.textContent = "Generate SVG";
    }
  }

  function loadRecord(record) {
    if (!record) return;
    const set = (selector, value) => {
      const input = vectorQuery(selector);
      if (input && value !== undefined && value !== null) input.value = String(value);
    };
    set("#vector-prompt", vectorValue(record, "prompt", "Prompt") || "");
    set("#vector-style", vectorValue(record, "style", "Style") || "icon");
    set("#vector-detail", vectorValue(record, "detail", "Detail") || "medium");
    set("#vector-colors", vectorValue(record, "colors", "Colors") ?? "auto");
    set("#vector-background", vectorValue(record, "background", "Background") || "transparent");
    set("#vector-background-color", vectorValue(record, "backgroundColor", "BackgroundColor") || "#ffffff");
    set("#vector-seed", vectorValue(record, "seed", "Seed") ?? "");
    toggleSolidColor();
    if (sourcePath(record) || previewPath(record)) renderVectorResult(record);
    vectorQuery("#vector-prompt")?.focus();
  }

  function vectorActionButton(action, label, index) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `button button-quiet${action === "delete" ? " gallery-delete" : ""}`;
    button.dataset.vectorAction = action;
    button.dataset.vectorIndex = String(index);
    button.textContent = label;
    return button;
  }

  function decorateVectorGallery() {
    const cards = Array.from(document.querySelectorAll("#gallery-grid .history-card"));
    cards.forEach((card, index) => {
      const record = state.history?.[index];
      if (!isVectorRecord(record)) return;
      card.classList.add("history-card-vector");

      const visual = card.querySelector(".history-visual");
      const preview = previewPath(record);
      if (visual && preview) {
        let image = visual.querySelector("img");
        if (!image) {
          visual.replaceChildren();
          image = document.createElement("img");
          image.alt = String(vectorValue(record, "prompt", "Prompt") || "Vector preview");
          image.loading = "lazy";
          visual.append(image);
        }
        image.src = imageUrl(preview);
        if (!visual.querySelector(".vector-gallery-badge")) {
          const badge = document.createElement("span");
          badge.className = "vector-gallery-badge";
          badge.textContent = "SVG";
          visual.append(badge);
        }
      }

      const model = card.querySelector(".history-model");
      if (model) model.textContent = `Vector · ${vectorValue(record, "provider", "Provider") || "zimage-vtrace"}`;
      const meta = card.querySelector(".history-meta");
      if (meta && !meta.querySelector("[data-vector-meta]")) {
        const vectorMeta = document.createElement("span");
        vectorMeta.dataset.vectorMeta = "";
        const paths = vectorValue(record, "pathCount", "PathCount") ?? "?";
        const nodes = vectorValue(record, "nodeCount", "NodeCount") ?? "?";
        const colors = vectorValue(record, "colors", "Colors") ?? "auto";
        vectorMeta.textContent = `SVG · ${paths} paths · ${nodes} nodes · colors ${colors}`;
        meta.append(vectorMeta);
      }

      card.querySelector(".reuse-button")?.remove();
      card.querySelector(".history-actions")?.remove();
      if (card.querySelector(".vector-history-actions")) return;
      const body = card.querySelector(".history-body");
      if (!body) return;
      const actions = document.createElement("div");
      actions.className = "history-actions vector-history-actions";
      actions.append(
        vectorActionButton("vector-download", "Download SVG", index),
        vectorActionButton("vector-source", "View source", index),
        vectorActionButton("vector-reuse", "Reuse", index),
        vectorActionButton("delete", "Delete", index),
      );
      body.append(actions);
    });
  }

  async function deleteVectorRecord(record) {
    const promptId = String(vectorValue(record, "promptId", "PromptId") || "").trim();
    if (!promptId) throw new Error("This Vector item has no deletable history identifier.");
    if (!window.confirm("Delete this SVG, its preview, and its owned local intermediates?")) return;
    const result = await api("/api/history/delete", {
      method: "POST",
      body: JSON.stringify({ promptId }),
    });
    if (!result?.deleted) throw new Error("Vector Gallery item was not found on disk.");
    await refreshHistory();
    showToast("Vector Gallery item deleted.", "success");
  }

  async function handleVectorGalleryAction(button) {
    const index = Number(button.dataset.vectorIndex);
    const record = state.history?.[index];
    if (!record || !isVectorRecord(record)) throw new Error("Vector Gallery record is no longer available.");
    const action = button.dataset.vectorAction;
    if (action === "vector-download") return downloadSvg(record);
    if (action === "vector-convert") {
      vectorState.workflow = "image";
      setVectorWorkflow("image");
      setImageVectorSource({ kind: "gallery", id: String(vectorValue(record, "promptId", "PromptId") || "") }, "Gallery image selected.");
      setPage("vector");
      return;
    }
    if (action === "vector-source") {
      setPage("vector");
      loadRecord(record);
      return openSource(record);
    }
    if (action === "vector-reuse") {
      window.StableAmdVector.loadRecord(record);
      setPage("vector");
      showToast("Vector settings restored.", "success");
      return;
    }
    if (action === "delete") return deleteVectorRecord(record);
  }

  document.addEventListener("DOMContentLoaded", () => {
    vectorQuery("#vector-form")?.addEventListener("submit", submitVector);
    vectorQuery("#vector-workflow-text")?.addEventListener("click", () => setVectorWorkflow("text"));
    vectorQuery("#vector-workflow-image")?.addEventListener("click", () => setVectorWorkflow("image"));
    vectorQuery("#image-vector-upload")?.addEventListener("change", async (event) => {
      try {
        const file = event.target.files?.[0];
        const image = await readImageVectorFile(file);
        setImageVectorSource({ kind: "upload", image }, file.name);
      } catch (error) {
        showToast(error.message, "error");
        event.target.value = "";
      }
    });
    vectorQuery("#image-vector-use-current")?.addEventListener("click", useCurrentImageVector);
    vectorQuery("#image-vector-from-gallery")?.addEventListener("click", chooseImageVectorGallery);
    vectorQuery("#image-vector-mode")?.addEventListener("change", () => { syncImageVectorStylization(); applyImageVectorPreset(); });
    vectorQuery("#image-vector-stylization")?.addEventListener("change", applyImageVectorPreset);\n    vectorQuery("#image-vector-crop")?.addEventListener("change", renderImageVectorCropEditor);
    for (const [id, output] of [
      ["#image-vector-smoothing", "#image-vector-smoothing-value"],
      ["#image-vector-edge", "#image-vector-edge-value"],
      ["#image-vector-denoise", "#image-vector-denoise-value"],
      ["#image-vector-posterize", "#image-vector-posterize-value"],
      ["#image-vector-tolerance", "#image-vector-tolerance-value"],
    ]) vectorQuery(id)?.addEventListener("input", () => updateRangeOutput(id, output));
    vectorQuery("#vector-background")?.addEventListener("change", toggleSolidColor);
    vectorQuery("#vector-install")?.addEventListener("click", () => void installDependency());
    document.querySelector('[data-page="vector"]')?.addEventListener("click", () => void refreshDependency());

    const grid = vectorQuery("#gallery-grid");
    if (grid) {
      grid.addEventListener("click", (event) => {
        const button = event.target.closest("[data-vector-action]");
        if (!button) return;
        event.preventDefault();
        event.stopPropagation();
        button.disabled = true;
        Promise.resolve(handleVectorGalleryAction(button))
          .catch((error) => showToast(error.message, "error"))
          .finally(() => { button.disabled = false; });
      });
      new MutationObserver(() => window.queueMicrotask(decorateVectorGallery)).observe(grid, { childList: true });
    }

    toggleSolidColor();
    void refreshDependency();
    window.queueMicrotask(decorateVectorGallery);
  });

  window.StableAmdVector = {
    loadRecord,
    refreshDependency,
    openSource,
    downloadSvg,
  };
})();
