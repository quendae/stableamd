(() => {
  function fillSelect(select, values, preferred, emptyLabel = null) {
    const available = Array.isArray(values) ? values.map(String).filter(Boolean) : [];
    const previous = select.value;
    select.replaceChildren();

    if (emptyLabel !== null) {
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = emptyLabel;
      select.append(empty);
    }

    for (const value of available) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.append(option);
    }

    const target = [previous, preferred].find((candidate) =>
      candidate !== undefined && Array.from(select.options).some((option) => option.value === String(candidate))
    );
    if (target !== undefined) select.value = String(target);
  }

  function syncLoraStrengthState() {
    const enabled = Boolean(document.querySelector("#lora-select")?.value);
    for (const id of ["#lora-model-strength", "#lora-clip-strength"]) {
      const input = document.querySelector(id);
      if (input) input.disabled = !enabled;
    }
  }

  async function refreshGenerationOptions() {
    try {
      const options = await api("/api/generation-options");
      fillSelect(document.querySelector("#sampler"), options?.samplers, "euler");
      fillSelect(document.querySelector("#scheduler"), options?.schedulers, "normal");
      fillSelect(document.querySelector("#lora-select"), options?.loras, "", "None");
      syncLoraStrengthState();
    } catch (error) {
      syncLoraStrengthState();
      showToast(`Generation options unavailable: ${error.message}`, "error");
    }
  }

  function restoreLoraSettings(index) {
    const record = state.history[index];
    if (!record) return;

    const loraName = String(getValue(record, "loraName", "LoraName") || "");
    const select = document.querySelector("#lora-select");
    if (select && Array.from(select.options).some((option) => option.value === loraName)) {
      select.value = loraName;
    } else if (select) {
      select.value = "";
    }

    const modelStrength = getValue(record, "loraModelStrength", "LoraModelStrength");
    const clipStrength = getValue(record, "loraClipStrength", "LoraClipStrength");
    document.querySelector("#lora-model-strength").value = modelStrength ?? 1;
    document.querySelector("#lora-clip-strength").value = clipStrength ?? 1;
    syncLoraStrengthState();
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelector("#lora-select")?.addEventListener("change", syncLoraStrengthState);
    document.querySelector("#gallery-grid")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-history-index]");
      if (button) restoreLoraSettings(Number(button.dataset.historyIndex));
    });
    void refreshGenerationOptions();
  });
})();
