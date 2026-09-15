(() => {
  const controlState = {
    support: { models: [] },
    dependencies: [],
  };

  function installStyles() {
    if (document.querySelector('#controlnet-styles')) return;
    const style = document.createElement('style');
    style.id = 'controlnet-styles';
    style.textContent = `
      .controlnet-panel { border: 1px solid var(--border, #303642); border-radius: 12px; padding: 12px; display: grid; gap: 10px; }
      .controlnet-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; }
      .controlnet-heading strong { font-size: 14px; }
      .controlnet-grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:10px; }
      .controlnet-help { margin:0; opacity:.72; font-size:12px; line-height:1.45; }
      .controlnet-install { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:9px 10px; border-radius:9px; background:rgba(127,127,127,.09); }
      .controlnet-file-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:100%; }
      @media (max-width: 720px) { .controlnet-grid { grid-template-columns: 1fr; } }
    `;
    document.head.append(style);
  }

  function selectedModelSupport() {
    const select = document.querySelector('#model-select');
    if (!select) return null;
    return (controlState.support.models || []).find((item) => String(item.id || '') === String(select.value || '')) || null;
  }

  function supportedControls(modelSupport) {
    return ((modelSupport?.controlPolicy?.controls) || []).filter((item) => item?.status === 'supported');
  }

  function plannedInstallableControls(modelSupport) {
    return ((modelSupport?.controlPolicy?.controls) || []).filter((item) => item?.status !== 'supported' && item?.installable && item?.dependencyId);
  }

  function createPanel() {
    if (document.querySelector('#controlnet-panel')) return document.querySelector('#controlnet-panel');
    const form = document.querySelector('#generate-form');
    const button = document.querySelector('#generate-button');
    if (!form || !button) return null;

    const panel = document.createElement('section');
    panel.id = 'controlnet-panel';
    panel.className = 'controlnet-panel';
    panel.innerHTML = `
      <div class="controlnet-heading">
        <strong>Control guidance</strong>
        <label class="checkbox-field"><input id="controlnet-enabled" type="checkbox" disabled> <span>Enable</span></label>
      </div>
      <p id="controlnet-help" class="controlnet-help">Select Z-Image Turbo or Krea 2 Turbo to see provider-specific controls.</p>
      <div id="controlnet-install" class="controlnet-install" hidden></div>
      <div id="controlnet-fields" hidden>
        <div class="controlnet-grid">
          <label class="field"><span>Control type</span><select id="controlnet-type"></select></label>
          <label class="field"><span>Strength</span><input id="controlnet-strength" type="number" min="0" max="2" step="0.05" value="1"></label>
        </div>
        <label class="field">
          <span id="controlnet-image-label">Control image</span>
          <input id="controlnet-image" type="file" accept="image/png,image/jpeg,image/webp">
          <small id="controlnet-image-hint" class="controlnet-help"></small>
        </label>
        <div id="controlnet-canny-fields" class="controlnet-grid" hidden>
          <label class="field"><span>Canny low</span><input id="controlnet-canny-low" type="number" min="0.01" max="0.99" step="0.01" value="0.4"></label>
          <label class="field"><span>Canny high</span><input id="controlnet-canny-high" type="number" min="0.01" max="0.99" step="0.01" value="0.8"></label>
        </div>
      </div>
    `;
    form.insertBefore(panel, button);

    panel.querySelector('#controlnet-enabled')?.addEventListener('change', updateFieldVisibility);
    panel.querySelector('#controlnet-type')?.addEventListener('change', updateFieldVisibility);
    return panel;
  }

  function dependencyById(id) {
    return controlState.dependencies.find((item) => String(item.id || '') === String(id || '')) || null;
  }

  function updateFieldVisibility() {
    const enabled = document.querySelector('#controlnet-enabled');
    const fields = document.querySelector('#controlnet-fields');
    const type = document.querySelector('#controlnet-type');
    const canny = document.querySelector('#controlnet-canny-fields');
    const label = document.querySelector('#controlnet-image-label');
    const hint = document.querySelector('#controlnet-image-hint');
    if (!enabled || !fields || !type || !canny) return;

    fields.hidden = !enabled.checked;
    canny.hidden = !enabled.checked || type.value !== 'canny';
    if (type.value === 'openpose') {
      if (label) label.textContent = 'OpenPose / DWPose map';
      if (hint) hint.textContent = 'First Krea 2 gate expects an already prepared skeleton map. Automatic DWPose extraction is the next sub-phase.';
    } else {
      if (label) label.textContent = 'Source image';
      if (hint) hint.textContent = 'StableAMD runs Canny locally inside the Z-Image graph.';
    }
  }

  async function installDependency(id, button) {
    button.disabled = true;
    const old = button.textContent;
    button.textContent = 'Installing…';
    try {
      const result = await api('/api/controlnet/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      });
      if (result?.restartRequired) {
        button.textContent = 'Restarting backend…';
        await api('/api/backend/restart', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
        });
      }
      await refreshControlSupport();
      if (typeof showToast === 'function') showToast('Control dependency installed.');
    } catch (error) {
      if (typeof showToast === 'function') showToast(error?.message || String(error));
    } finally {
      button.disabled = false;
      button.textContent = old;
    }
  }

  function renderPanel() {
    const panel = createPanel();
    if (!panel) return;
    const model = selectedModelSupport();
    const enable = panel.querySelector('#controlnet-enabled');
    const type = panel.querySelector('#controlnet-type');
    const strength = panel.querySelector('#controlnet-strength');
    const help = panel.querySelector('#controlnet-help');
    const install = panel.querySelector('#controlnet-install');
    const available = supportedControls(model);
    const installable = plannedInstallableControls(model);

    type.replaceChildren();
    available.forEach((item) => {
      const option = document.createElement('option');
      option.value = String(item.id || '');
      option.textContent = String(item.label || item.id || 'Control');
      option.dataset.strength = String(item.strengthDefault ?? 1);
      type.append(option);
    });

    enable.disabled = !available.length;
    if (!available.length) enable.checked = false;
    install.hidden = true;
    install.replaceChildren();

    if (!model) {
      help.textContent = 'Select Z-Image Turbo or Krea 2 Turbo to see provider-specific controls.';
    } else if (available.length) {
      help.textContent = model.controlPolicy?.note || 'Provider-specific control is ready.';
      const chosen = available.find((item) => String(item.id) === type.value) || available[0];
      strength.value = String(chosen?.strengthDefault ?? 1);
      if (chosen?.id === 'canny') {
        const low = panel.querySelector('#controlnet-canny-low');
        const high = panel.querySelector('#controlnet-canny-high');
        if (low) low.value = String(chosen.cannyLowDefault ?? 0.4);
        if (high) high.value = String(chosen.cannyHighDefault ?? 0.8);
      }
    } else if (installable.length) {
      const item = installable[0];
      const dep = dependencyById(item.dependencyId);
      help.textContent = model.controlPolicy?.note || 'A pinned dependency is required before this control route can be enabled.';
      install.hidden = false;
      const text = document.createElement('span');
      text.textContent = dep?.note || `${item.label || item.id} requires its curated dependency.`;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'button button-secondary';
      button.textContent = 'Install dependency';
      button.addEventListener('click', () => installDependency(item.dependencyId, button));
      install.append(text, button);
    } else {
      help.textContent = model.controlPolicy?.note || 'Control guidance is not enabled for this model yet.';
    }
    updateFieldVisibility();
  }

  async function refreshControlSupport() {
    try {
      const [support, deps] = await Promise.all([
        api('/api/model-support'),
        api('/api/controlnet/dependencies'),
      ]);
      controlState.support = support || { models: [] };
      controlState.dependencies = Array.isArray(deps?.dependencies) ? deps.dependencies : [];
      renderPanel();
    } catch (error) {
      const help = document.querySelector('#controlnet-help');
      if (help) help.textContent = `Control capability refresh failed: ${error?.message || error}`;
    }
  }

  function readFilePayload(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Could not read the control image.'));
      reader.onload = () => {
        const value = String(reader.result || '');
        const comma = value.indexOf(',');
        if (comma < 0) return reject(new Error('Control image encoding failed.'));
        resolve({
          name: file.name,
          mimeType: file.type || 'application/octet-stream',
          dataBase64: value.slice(comma + 1),
        });
      };
      reader.readAsDataURL(file);
    });
  }

  function installApiWrapper() {
    if (window.__stableAmdControlApiWrapped) return;
    window.__stableAmdControlApiWrapped = true;
    const previousApi = api;
    api = async function controlAwareApi(path, options = {}) {
      if (path === '/api/generate' && String(options.method || 'GET').toUpperCase() === 'POST') {
        const enabled = document.querySelector('#controlnet-enabled');
        if (enabled?.checked) {
          const request = JSON.parse(options.body || '{}');
          const file = document.querySelector('#controlnet-image')?.files?.[0];
          if (!file) throw new Error('Choose a control image first.');
          const type = document.querySelector('#controlnet-type')?.value || '';
          const control = {
            enabled: true,
            type,
            image: await readFilePayload(file),
            strength: Number(document.querySelector('#controlnet-strength')?.value || 1),
          };
          if (type === 'canny') {
            control.cannyLow = Number(document.querySelector('#controlnet-canny-low')?.value || 0.4);
            control.cannyHigh = Number(document.querySelector('#controlnet-canny-high')?.value || 0.8);
          }
          request.control = control;
          options = { ...options, body: JSON.stringify(request) };
        }
      }
      return previousApi(path, options);
    };
  }

  function boot() {
    installStyles();
    createPanel();
    installApiWrapper();
    document.querySelector('#model-select')?.addEventListener('change', renderPanel);
    refreshControlSupport();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
