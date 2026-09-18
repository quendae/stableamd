(() => {
  const STARTUP_TIMEOUT_MS = 15000;
  const MIN_GATE_MS = 450;
  const POLL_INTERVAL_MS = 75;

  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  let criticalReady = false;
  let resolveCriticalReady = null;
  const criticalReadyPromise = new Promise((resolve) => {
    resolveCriticalReady = resolve;
  });

  window.StableAmdStartup = {
    markCriticalReady() {
      if (criticalReady) return;
      criticalReady = true;
      resolveCriticalReady?.();
    },
    get criticalReady() {
      return criticalReady;
    },
  };

  async function fetchJson(path) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`${path}: ${response.status} ${response.statusText}`);
    const text = await response.text();
    return text ? JSON.parse(text) : null;
  }

  function normalizeRecords(payload) {
    if (!payload) return [];
    if (Array.isArray(payload)) return payload;
    const nested = payload.models ?? payload.Models;
    if (nested === undefined || nested === null) return [];
    return Array.isArray(nested) ? nested : [nested];
  }

  function modelUiReady(modelSupport) {
    const select = document.querySelector("#model-select");
    if (!select) return false;

    const labels = Array.from(select.options).map((option) => String(option.textContent || "").toLowerCase());
    if (labels.some((label) => label.includes("loading models"))) return false;
    if (typeof state === "undefined" || !Array.isArray(state.models)) return false;

    const supportEntries = normalizeRecords(modelSupport);
    if (!supportEntries.length) return false;
    const supportById = new Map(
      supportEntries.map((entry) => [String(entry?.id ?? entry?.Id ?? ""), entry]),
    );
    const expectedIds = state.models
      .filter((model) => {
        const ready = model?.ready ?? model?.Ready;
        if (ready === false) return false;
        const id = String(model?.id ?? model?.Id ?? "");
        const support = supportById.get(id);
        const capabilities = support?.capabilities ?? support?.Capabilities ?? {};
        return String(capabilities?.txt2img || "").toLowerCase() === "supported";
      })
      .map((model) => String(model?.id ?? model?.Id ?? ""))
      .filter(Boolean);

    if (!expectedIds.length) return false;
    const values = new Set(Array.from(select.options).map((option) => String(option.value || "")));
    return expectedIds.every((id) => values.has(id));
  }

  async function waitForModelUiReady(modelSupport, timeoutMs) {
    const deadline = performance.now() + Math.max(0, timeoutMs);
    while (performance.now() < deadline) {
      if (modelUiReady(modelSupport)) return true;
      await delay(POLL_INTERVAL_MS);
    }
    return modelUiReady(modelSupport);
  }

  async function waitForCriticalStartup(timeoutMs) {
    if (criticalReady) return true;
    if (timeoutMs <= 0) return false;
    return Promise.race([
      criticalReadyPromise.then(() => true),
      delay(timeoutMs).then(() => false),
    ]);
  }

  async function waitForMinimumGate(startedAt) {
    const remaining = MIN_GATE_MS - (performance.now() - startedAt);
    if (remaining > 0) await delay(remaining);
  }

  function revealGui(timedOut) {
    const gate = document.querySelector("#startup-gate");
    const shell = document.querySelector(".app-shell");
    if (shell) shell.hidden = false;
    if (gate) gate.hidden = true;
    document.body.removeAttribute("aria-busy");

    if (timedOut) {
      setTimeout(() => {
        if (typeof showToast === "function") {
          showToast("Model discovery is still finishing. Use Refresh if a model is missing.", "error");
        }
      }, 0);
    }
  }

  async function initializeStartupGate() {
    document.body.setAttribute("aria-busy", "true");
    const startedAt = performance.now();
    const gateMessage = document.querySelector("#startup-gate-message");
    if (gateMessage) gateMessage.textContent = "Preparing models and capabilities…";

    const modelSupportPromise = fetchJson("/api/model-support").catch(() => null);
    const criticalReadyResult = await waitForCriticalStartup(STARTUP_TIMEOUT_MS);
    let remainingMs = STARTUP_TIMEOUT_MS - (performance.now() - startedAt);

    let modelSupport = null;
    if (remainingMs > 0) {
      modelSupport = await Promise.race([
        modelSupportPromise,
        delay(remainingMs).then(() => null),
      ]);
    }

    remainingMs = STARTUP_TIMEOUT_MS - (performance.now() - startedAt);
    let modelReady = false;
    if (criticalReadyResult && modelSupport && remainingMs > 0) {
      if (gateMessage) gateMessage.textContent = "Finalizing Generate workspace…";
      modelReady = await waitForModelUiReady(modelSupport, remainingMs);
    }

    await waitForMinimumGate(startedAt);
    revealGui(!(criticalReadyResult && modelReady));
  }

  document.addEventListener("DOMContentLoaded", () => {
    void initializeStartupGate();
  });
})();
