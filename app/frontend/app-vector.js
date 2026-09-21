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

  async function submitVector(event) {
    event.preventDefault();
    if (!vectorState.dependency?.ready) {
      showToast("Install the Vectorizer before generating SVG assets.", "error");
      return;
    }
    let payload;
    try {
      payload = vectorPayload();
    } catch (error) {
      showToast(error.message, "error");
      vectorQuery("#vector-prompt")?.focus();
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
      const submitted = await api("/api/vector/text-to-svg", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      let result = submitted;
      const jobId = String(submitted?.jobId || "");
      if (jobId) {
        const jobs = await waitForJobsInterface();
        result = await jobs.waitForGenerationJob(jobId);
      }
      renderVectorResult(result);
      if (typeof refreshHistory === "function") await refreshHistory();
      showToast("SVG generated and sanitized.", "success");
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
