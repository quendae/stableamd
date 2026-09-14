(() => {
  function finitePositive(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : null;
  }

  function median(values) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function estimateGenerationSeconds(records, payload) {
    const rows = Array.isArray(records) ? records : [];
    const usable = rows
      .map((record) => ({
        record,
        seconds: finitePositive(getValue(record, "generationSeconds", "GenerationSeconds")),
      }))
      .filter((item) => item.seconds !== null);

    const exact = usable.filter(({ record }) =>
      String(getValue(record, "modelId", "ModelId") || "") === String(payload.modelId || "") &&
      Number(getValue(record, "width", "Width")) === Number(payload.width) &&
      Number(getValue(record, "height", "Height")) === Number(payload.height) &&
      Number(getValue(record, "steps", "Steps")) === Number(payload.steps) &&
      String(getValue(record, "sampler", "Sampler") || "") === String(payload.samplerName || "") &&
      String(getValue(record, "scheduler", "Scheduler") || "") === String(payload.scheduler || "") &&
      String(getValue(record, "loraName", "LoraName") || "") === String(payload.loraName || "")
    );

    const similar = usable.filter(({ record }) =>
      String(getValue(record, "modelId", "ModelId") || "") === String(payload.modelId || "") &&
      Number(getValue(record, "width", "Width")) === Number(payload.width) &&
      Number(getValue(record, "height", "Height")) === Number(payload.height) &&
      Number(getValue(record, "steps", "Steps")) === Number(payload.steps)
    );

    const pool = exact.length ? exact : similar;
    if (!pool.length) return null;
    return median(pool.slice(0, 5).map((item) => item.seconds));
  }

  function createProgressUi(estimateSeconds) {
    const empty = qs("#result-empty");
    empty.querySelector(".generation-progress")?.remove();

    const root = document.createElement("div");
    root.className = `generation-progress${estimateSeconds ? "" : " is-indeterminate"}`;
    root.innerHTML = `
      <div class="generation-progress-track" role="progressbar" aria-label="Generation progress" aria-valuemin="0" aria-valuemax="100">
        <div class="generation-progress-fill"></div>
      </div>
      <div class="generation-progress-copy">
        <strong>Preparing generation…</strong>
        <span></span>
      </div>`;
    empty.append(root);

    const track = root.querySelector(".generation-progress-track");
    const fill = root.querySelector(".generation-progress-fill");
    const label = root.querySelector(".generation-progress-copy strong");
    const meta = root.querySelector(".generation-progress-copy span");
    const started = performance.now();

    function render(done = false) {
      const elapsed = Math.max(0, (performance.now() - started) / 1000);
      if (done) {
        root.classList.remove("is-indeterminate");
        fill.style.width = "100%";
        track.setAttribute("aria-valuenow", "100");
        label.textContent = "Generation complete";
        meta.textContent = `${elapsed.toFixed(1)} s elapsed`;
        return;
      }

      if (estimateSeconds) {
        const percent = Math.min(95, Math.max(1, (elapsed / estimateSeconds) * 100));
        fill.style.width = `${percent.toFixed(1)}%`;
        track.setAttribute("aria-valuenow", String(Math.round(percent)));
        const remaining = Math.max(0, estimateSeconds - elapsed);
        label.textContent = "Generating…";
        meta.textContent = elapsed <= estimateSeconds
          ? `${elapsed.toFixed(0)} s elapsed · ETA ~${Math.ceil(remaining)} s`
          : `${elapsed.toFixed(0)} s elapsed · recent estimate ~${Math.ceil(estimateSeconds)} s`;
      } else {
        track.removeAttribute("aria-valuenow");
        label.textContent = "Generating…";
        meta.textContent = `${elapsed.toFixed(0)} s elapsed · ETA learning from history`;
      }
    }

    render(false);
    const timer = window.setInterval(() => render(false), 250);
    return {
      complete() {
        window.clearInterval(timer);
        render(true);
      },
      remove() {
        window.clearInterval(timer);
        root.remove();
      },
    };
  }

  submitGeneration = async function enhancedSubmitGeneration(event) {
    event.preventDefault();
    const button = qs("#generate-button");
    const prompt = qs("#prompt").value.trim();
    const modelId = qs("#model-select").value;
    if (!prompt) { showToast("Enter a prompt first.", "error"); qs("#prompt").focus(); return; }
    if (!modelId) { showToast("Select a model first.", "error"); return; }

    const payload = {
      prompt,
      negativePrompt: qs("#negative-prompt").value,
      modelId,
      width: readNumber("#width", 1024),
      height: readNumber("#height", 1024),
      steps: readNumber("#steps", 20),
      cfg: readNumber("#cfg", 7),
      samplerName: qs("#sampler").value.trim() || "euler",
      scheduler: qs("#scheduler").value.trim() || "normal",
      startBackendIfNeeded: true,
    };
    const seed = readNumber("#seed");
    if (seed !== undefined) payload.seed = seed;

    const loraName = qs("#lora-select")?.value?.trim() || "";
    if (loraName) {
      payload.loraName = loraName;
      payload.loraModelStrength = readNumber("#lora-model-strength", 1);
      payload.loraClipStrength = readNumber("#lora-clip-strength", 1);
    }

    button.disabled = true;
    button.textContent = "Generating…";
    const resultEmpty = qs("#result-empty");
    const resultCopy = resultEmpty.querySelector("p");
    resultEmpty.hidden = false;
    resultEmpty.querySelector("strong").textContent = "Generation in progress";
    resultCopy.textContent = "";
    resultCopy.hidden = true;
    qs("#result-details").hidden = true;

    let progress = null;
    try {
      const recent = await api("/api/history?limit=20").catch(() => []);
      const estimate = estimateGenerationSeconds(recent, payload);
      progress = createProgressUi(estimate);

      const result = await api("/api/generate", { method: "POST", body: JSON.stringify(payload) });
      progress.complete();
      renderGenerationResult(result);
      await Promise.allSettled([refreshHistory(), refreshStatus()]);
      showToast("Generation completed.", "success");
    } catch (error) {
      progress?.remove();
      resultEmpty.querySelector("strong").textContent = "Generation failed";
      resultCopy.hidden = false;
      resultCopy.textContent = error.message;
      showToast(error.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Generate image";
    }
  };
})();
