(() => {
  const STARTUP_TIMEOUT_MS = 30000;
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

  function settledValue(result) {
    return result?.status === "fulfilled" ? result.value : null;
  }

  function normalizeRecords(payload) {
    if (!payload) return [];
    if (Array.isArray(payload)) return payload;
    const nested = payload.models ?? payload.Models;
    if (nested === undefined || nested === null) return [];
    return Array.isArray(nested) ? nested : [nested];
  }

  function optionValues(selector) {
    const select = document.querySelector(selector);
    if (!select) return null;
    return new Set(Array.from(select.options).map((option) => String(option.value || "")));
  }

  function allExpectedOptionsPresent(selector, expected) {
    if (!Array.isArray(expected) || !expected.length) return true;
    const available = optionValues(selector);
    return Boolean(available && expected.every((value) => available.has(String(value))));
  }

  function modelUiReady(modelSupport) {
    const select = document.querySelector("#model-select");
    if (!select) return false;
    const labels = Array.from(select.options).map((option) => String(option.textContent || "").toLowerCase());
    if (labels.some((label) => label.includes("loading models"))) return false;

    if (typeof state === "undefined" || !Array.isArray(state.models)) return false;
    const supportEntries = normalizeRecords(modelSupport);
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

    const values = new Set(Array.from(select.options).map((option) => String(option.value || "")));
    if (!expectedIds.every((id) => values.has(id))) return false;

    const packageList = document.querySelector("#model-package-list");
    if (!packageList) return false;
    if (/loading/i.test(String(packageList.textContent || ""))) return false;

    if (state.models.length) {
      const supportHint = document.querySelector("#model-support-hint");
      if (!supportHint || /will appear after model discovery/i.test(String(supportHint.textContent || ""))) return false;
    }
    return true;
  }

  function generationOptionsUiReady(options) {
    if (!document.querySelector("#generation-profile")) return false;
    const samplers = Array.isArray(options?.samplers) ? options.samplers.map(String).filter(Boolean) : [];
    const schedulers = Array.isArray(options?.schedulers) ? options.schedulers.map(String).filter(Boolean) : [];
    const loras = Array.isArray(options?.loras) ? options.loras.map(String).filter(Boolean) : [];
    if (!allExpectedOptionsPresent("#sampler", samplers)) return false;
    if (!allExpectedOptionsPresent("#scheduler", schedulers)) return false;
    if (!allExpectedOptionsPresent("#lora-select", loras)) return false;
    return true;
  }

  function loraUiReady() {
    const hint = document.querySelector("#lora-compatibility-hint");
    return Boolean(hint && /selected family/i.test(String(hint.textContent || "")));
  }

  async function waitForUiReady(metadata, timeoutMs) {
    const deadline = performance.now() + timeoutMs;
    while (performance.now() < deadline) {
      if (
        modelUiReady(metadata.modelSupport)
        && generationOptionsUiReady(metadata.generationOptions)
        && loraUiReady()
      ) {
        return true;
      }
      await delay(POLL_INTERVAL_MS);
    }
    return false;
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
          showToast("Startup model scan is still finishing. Use Refresh if a model is missing.", "error");
        }
      }, 0);
    }
  }

  async function initializeStartupGate() {
    document.body.setAttribute("aria-busy", "true");
    const gateMessage = document.querySelector("#startup-gate-message");

    const metadataPromise = Promise.allSettled([
      fetch("/api/model-support", { headers: { "Content-Type": "application/json" }, cache: "no-store" }).then(async (response) => {
        if (!response.ok) throw new Error(`model support ${response.status}`);
        return response.json();
      }),
      fetch("/api/generation-options", { headers: { "Content-Type": "application/json" }, cache: "no-store" }).then(async (response) => {
        if (!response.ok) throw new Error(`generation options ${response.status}`);
        return response.json();
      }),
      fetch("/api/lora-catalog", { headers: { "Content-Type": "application/json" }, cache: "no-store" }).then(async (response) => {
        if (!response.ok) throw new Error(`LoRA catalog ${response.status}`);
        return response.json();
      }),
    ]);

    const metadataResults = await Promise.race([
      metadataPromise,
      delay(STARTUP_TIMEOUT_MS).then(() => null),
    ]);

    if (!metadataResults) {
      revealGui(true);
      return;
    }

    const metadata = {
      modelSupport: settledValue(metadataResults[0]),
      generationOptions: settledValue(metadataResults[1]),
      loraCatalog: settledValue(metadataResults[2]),
    };

    if (gateMessage) gateMessage.textContent = "Preparing model lists and generation options…";
    const ready = await waitForUiReady(metadata, STARTUP_TIMEOUT_MS);
    revealGui(!ready);
  }

  document.addEventListener("DOMContentLoaded", () => {
    void initializeStartupGate();
  });
})();
