(() => {
  const compatibilityState = {
    catalog: [],
    loras: [],
    showIncompatibleLoras: false,
    refreshing: false,
  };

  function normalizeName(value) {
    return String(value || "").replaceAll("\\", "/").toLowerCase();
  }

  function normalizeFamily(value) {
    const raw = String(value || "").toLowerCase().replaceAll("_", "-");
    if (!raw) return "unknown";
    if (raw.includes("z-image") || raw.includes("zimage")) return "z-image";
    if (raw.includes("krea")) return "krea";
    if (raw.includes("flux")) return "flux";
    if (raw.startsWith("sdxl") || raw.includes("sd-xl")) return "sdxl";
    if (raw.startsWith("sd3")) return "sd3";
    if (raw === "sd15" || raw.startsWith("sd1")) return "sd15";
    return raw;
  }

  function selectedModelFamily() {
    const id = document.querySelector("#model-select")?.value || "";
    const model = Array.isArray(state.models)
      ? state.models.find((entry) => String(getValue(entry, "id", "Id") || "") === String(id))
      : null;
    return normalizeFamily(getValue(model, "family", "Family") || "unknown");
  }

  function catalogEntryForName(name) {
    const normalized = normalizeName(name);
    const exact = compatibilityState.catalog.find((entry) => normalizeName(entry?.name) === normalized);
    if (exact) return exact;
    const leaf = normalized.split("/").pop();
    const matches = compatibilityState.catalog.filter((entry) => normalizeName(entry?.name).split("/").pop() === leaf);
    return matches.length === 1 ? matches[0] : null;
  }

  function compatibilityForName(name) {
    const modelFamily = selectedModelFamily();
    const entry = catalogEntryForName(name);
    const loraFamily = normalizeFamily(entry?.family || "unknown");
    let status = "unknown";
    if (loraFamily === "shared" || loraFamily === "unknown" || modelFamily === "unknown") status = "unknown";
    else if (loraFamily === modelFamily) status = "compatible";
    else status = "incompatible";
    return { status, modelFamily, loraFamily, entry };
  }

  function labelForLora(name) {
    const compatibility = compatibilityForName(name);
    if (compatibility.status === "compatible") return `${name} · ${compatibility.loraFamily.toUpperCase()}`;
    if (compatibility.status === "incompatible") return `${name} · incompatible (${compatibility.loraFamily})`;
    return `${name} · compatibility unknown`;
  }

  function ensureCompatibilityUi() {
    const panel = document.querySelector("#lora-stack-panel");
    if (!panel || panel.querySelector("#show-incompatible-loras")) return;
    const toolbar = panel.querySelector(".section-toolbar");
    if (!toolbar) return;

    const control = document.createElement("label");
    control.className = "checkbox-field";
    control.innerHTML = '<input id="show-incompatible-loras" type="checkbox"> <span>Show incompatible</span>';
    toolbar.append(control);
    control.querySelector("input").addEventListener("change", (event) => {
      compatibilityState.showIncompatibleLoras = Boolean(event.target.checked);
      refreshLoraStackCompatibility();
    });

    const hint = document.createElement("p");
    hint.id = "lora-compatibility-hint";
    hint.className = "history-model";
    hint.textContent = "LoRA compatibility: metadata and family folders are checked before generation.";
    panel.append(hint);
  }

  function repopulateSelect(select) {
    const previous = select.value;
    const previousCompatibility = previous ? compatibilityForName(previous) : null;
    select.replaceChildren();

    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "Choose LoRA…";
    select.append(empty);

    for (const name of compatibilityState.loras) {
      const compatibility = compatibilityForName(name);
      if (compatibility.status === "incompatible" && !compatibilityState.showIncompatibleLoras) continue;
      const option = document.createElement("option");
      option.value = name;
      option.textContent = labelForLora(name);
      if (compatibility.status === "incompatible") option.disabled = true;
      select.append(option);
    }

    const row = select.closest("[data-lora-stack-row]");
    if (!previous) return;
    const existing = Array.from(select.options).find((option) => option.value === previous);
    if (existing && !existing.disabled) {
      select.value = previous;
      if (row) row.dataset.loraCompatibility = compatibilityForName(previous).status;
      return;
    }

    if (previousCompatibility?.status === "incompatible") {
      const blocked = document.createElement("option");
      blocked.value = previous;
      blocked.textContent = `${previous} · incompatible with ${previousCompatibility.modelFamily}`;
      blocked.disabled = true;
      blocked.selected = true;
      select.append(blocked);
      if (row) {
        row.dataset.loraCompatibility = "incompatible";
        const enabled = row.querySelector("[data-lora-enabled]");
        if (enabled) enabled.checked = false;
      }
    }
  }

  function refreshLoraStackCompatibility() {
    if (compatibilityState.refreshing) return;
    compatibilityState.refreshing = true;
    try {
      ensureCompatibilityUi();
      for (const select of document.querySelectorAll("[data-lora-name]")) repopulateSelect(select);

      const family = selectedModelFamily();
      const hint = document.querySelector("#lora-compatibility-hint");
      if (hint) {
        const unknownCount = compatibilityState.loras.filter((name) => compatibilityForName(name).status === "unknown").length;
        hint.textContent = `LoRA compatibility · selected family ${family || "unknown"} · ${unknownCount} adapter${unknownCount === 1 ? "" : "s"} could not be classified and remain available with a warning.`;
      }
    } finally {
      compatibilityState.refreshing = false;
    }
  }

  async function refreshLoraCompatibilityCatalog() {
    try {
      const [catalog, options] = await Promise.all([
        api("/api/lora-catalog"),
        api("/api/generation-options"),
      ]);
      compatibilityState.catalog = Array.isArray(catalog) ? catalog : [];
      compatibilityState.loras = Array.isArray(options?.loras) ? options.loras.map(String).filter(Boolean) : [];
      refreshLoraStackCompatibility();
    } catch (error) {
      showToast(`LoRA compatibility scan unavailable: ${error.message}`, "error");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensureCompatibilityUi();
    document.querySelector("#model-select")?.addEventListener("change", () => {
      queueMicrotask(refreshLoraStackCompatibility);
    });
    document.querySelector("#refresh-button")?.addEventListener("click", () => {
      setTimeout(() => void refreshLoraCompatibilityCatalog(), 0);
    });
    document.addEventListener("click", (event) => {
      if (event.target.closest("#lora-stack-add")) setTimeout(refreshLoraStackCompatibility, 0);
    });
    const list = document.querySelector("#lora-stack-list");
    if (list) new MutationObserver(() => refreshLoraStackCompatibility()).observe(list, { childList: true });
    void refreshLoraCompatibilityCatalog();
  });

  window.refreshLoraStackCompatibility = refreshLoraStackCompatibility;
})();
