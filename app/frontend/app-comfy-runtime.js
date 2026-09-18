(() => {
  let openComfyLink = null;

  function detachExternalNavLink() {
    const original = document.querySelector("#open-comfyui");
    if (!original) return null;
    // app.js binds SPA navigation to .nav-item. Replacing this external item
    // drops that listener while preserving the shared navigation styling.
    const replacement = original.cloneNode(true);
    original.replaceWith(replacement);
    return replacement;
  }

  function ensureRuntimeCard() {
    const page = document.querySelector("#page-diagnostics");
    if (!page) return null;
    let card = page.querySelector("#comfyui-runtime-card");
    if (card) return card;

    card = document.createElement("article");
    card.id = "comfyui-runtime-card";
    card.className = "install-card comfyui-runtime-card";
    card.innerHTML = `
      <div class="install-card-heading">
        <div>
          <strong>ComfyUI runtime</strong>
          <span>StableAMD pins a tested ComfyUI checkout. Update checks are informational only.</span>
        </div>
        <span class="root-state" data-comfy-runtime-state>Checking…</span>
      </div>
      <div class="model-root-list" data-comfy-runtime-details></div>`;

    const grid = page.querySelector(".diagnostics-grid");
    if (grid) grid.before(card);
    else page.append(card);
    return card;
  }

  function addDetail(root, label, value, detail = "") {
    const row = document.createElement("div");
    row.className = "model-root-row";
    const main = document.createElement("div");
    main.className = "model-root-main";
    const title = document.createElement("strong");
    title.textContent = label;
    const code = document.createElement("code");
    code.textContent = value || "Unknown";
    main.append(title, code);
    row.append(main);
    if (detail) {
      const meta = document.createElement("span");
      meta.className = "history-model";
      meta.textContent = detail;
      row.append(meta);
    }
    root.append(row);
  }

  function shortCommit(value) {
    const text = String(value || "");
    return text ? text.slice(0, 12) : "unknown";
  }

  function renderRuntime(data) {
    const card = ensureRuntimeCard();
    if (!card) return;

    const backendUrl = String(data?.backendUrl || "http://127.0.0.1:8190/");
    if (openComfyLink) {
      openComfyLink.href = backendUrl;
      openComfyLink.title = `Open managed ComfyUI at ${backendUrl}`;
    }

    const details = card.querySelector("[data-comfy-runtime-details]");
    const state = card.querySelector("[data-comfy-runtime-state]");
    if (details) details.replaceChildren();

    const installedVersion = data?.installed?.version || "unknown";
    const pinnedVersion = data?.pinned?.version || "unknown";
    const latestVersion = data?.latest?.version || null;
    const updateAvailable = data?.updateAvailable;
    const pinMatchesCheckout = data?.pinMatchesCheckout;

    if (state) {
      if (pinMatchesCheckout === false) {
        state.className = "root-state is-missing";
        state.textContent = "Checkout differs from pin";
      } else if (updateAvailable === true) {
        state.className = "root-state is-missing";
        state.textContent = "Update available";
      } else if (pinMatchesCheckout === true) {
        state.className = "root-state is-ready";
        state.textContent = "Pinned runtime";
      } else {
        state.className = "root-state";
        state.textContent = "Runtime detected";
      }
    }

    if (!details) return;
    addDetail(
      details,
      "Installed",
      `ComfyUI ${installedVersion}`,
      `commit ${shortCommit(data?.installed?.commit)}`,
    );
    addDetail(
      details,
      "StableAMD pin",
      `ComfyUI ${pinnedVersion}`,
      `commit ${shortCommit(data?.pinned?.commit)}`,
    );
    addDetail(
      details,
      "Latest stable",
      latestVersion ? `ComfyUI ${latestVersion}` : "Check unavailable",
      data?.latestCheck === "ok" ? "GitHub release check succeeded" : "StableAMD keeps using the pinned runtime",
    );

    if (data?.latest?.url) {
      const row = document.createElement("div");
      row.className = "model-root-row";
      const note = document.createElement("div");
      note.className = "model-root-main";
      const title = document.createElement("strong");
      title.textContent = updateAvailable === true ? "Newer ComfyUI exists" : "Release status";
      const copy = document.createElement("span");
      copy.textContent = updateAvailable === true
        ? "Updates are not installed automatically; promote them only after StableAMD compatibility tests."
        : "The managed runtime is current according to the latest successful release check.";
      note.append(title, copy);
      const link = document.createElement("a");
      link.href = data.latest.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View release ↗";
      row.append(note, link);
      details.append(row);
    }
  }

  function renderFailure(message) {
    const card = ensureRuntimeCard();
    if (!card) return;
    const state = card.querySelector("[data-comfy-runtime-state]");
    const details = card.querySelector("[data-comfy-runtime-details]");
    if (state) {
      state.className = "root-state is-missing";
      state.textContent = "Unavailable";
    }
    if (details) {
      details.replaceChildren();
      addDetail(details, "Runtime check", "Unavailable", message || "Could not inspect ComfyUI runtime.");
    }
  }

  async function refreshComfyRuntime() {
    try {
      const response = await fetch("/api/comfyui-runtime", { cache: "no-store" });
      const text = await response.text();
      const payload = text ? JSON.parse(text) : {};
      if (!response.ok) throw new Error(payload?.error || `${response.status} ${response.statusText}`);
      renderRuntime(payload);
      return payload;
    } catch (error) {
      renderFailure(error.message);
      return null;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    openComfyLink = detachExternalNavLink();
    ensureRuntimeCard();

    document.querySelector('[data-page="diagnostics"]')?.addEventListener("click", () => {
      void refreshComfyRuntime();
    });
    document.querySelector("#diagnostics-refresh")?.addEventListener("click", () => {
      void refreshComfyRuntime();
    });

    void refreshComfyRuntime();
  });

  window.refreshComfyRuntime = refreshComfyRuntime;
})();
