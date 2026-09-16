(() => {
  const STARTUP_TIMEOUT_MS = 10000;
  const POLL_INTERVAL_MS = 75;

  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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
    if (gateMessage) gateMessage.textContent = "Loading models…";

    let modelSupport = null;
    try {
      modelSupport = await Promise.race([
        fetchJson("/api/model-support"),
        delay(STARTUP_TIMEOUT_MS).then(() => null),
      ]);
    } catch {
      modelSupport = null;
    }

    const remainingMs = STARTUP_TIMEOUT_MS - (performance.now() - startedAt);
    if (!modelSupport || remainingMs <= 0) {
      revealGui(true);
      return;
    }

    const ready = await waitForModelUiReady(modelSupport, remainingMs);
    revealGui(!ready);
  }

  document.addEventListener("DOMContentLoaded", () => {
    void initializeStartupGate();
  });
})();
