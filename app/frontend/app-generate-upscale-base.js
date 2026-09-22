(() => {
  const upscaleAfterState = {
    models: [],
    planTimer: null,
    planningToken: 0,
  };

  function installStyles() {
    if (document.querySelector('#upscale-after-styles')) return;
    const style = document.createElement('style');
    style.id = 'upscale-after-styles';
    style.textContent = `
      .upscale-after-generation { display:flex; flex-wrap:wrap; align-items:end; gap:8px; margin:4px 0 12px; padding:9px 10px; border:1px solid var(--border); border-radius:9px; background:rgba(255,255,255,.018); }
      .upscale-after-generation .field { margin:0; }
      .upscale-after-factor-field { flex:0 0 105px; }
      .upscale-after-model-field { flex:0 1 250px; min-width:180px; }
      .upscale-after-generation select { height:36px; }
      .upscale-output-hint { flex:1 1 220px; align-self:center; margin:0; color:var(--muted); font-size:10px; line-height:1.45; }
      .upscale-output-hint.large-output { color:var(--warning); }
      .upscale-output-hint.is-error { color:var(--danger); }
      @media (max-width:560px) { .upscale-after-factor-field, .upscale-after-model-field { flex:1 1 130px; min-width:0; } .upscale-output-hint { flex-basis:100%; } }
    `;
    document.head.append(style);
  }

  function ensureUi() {
    let panel = document.querySelector('#upscale-after-generation');
    if (panel) return panel;
    const form = document.querySelector('#generate-form');
    if (!form) return null;

    panel = document.createElement('div');
    panel.id = 'upscale-after-generation';
    panel.className = 'upscale-after-generation';
    panel.innerHTML = `
      <label class="field upscale-after-factor-field">
        <span>Upscale after</span>
        <select id="upscale-after-factor">
          <option value="1">Off</option>
          <option value="2">2x</option>
          <option value="4">4x</option>
          <option value="8">8x</option>
        </select>
      </label>
      <label class="field upscale-after-model-field">
        <span>Upscale model</span>
        <select id="upscale-after-model" disabled><option value="">Auto</option></select>
      </label>
      <p id="upscale-output-hint" class="upscale-output-hint">Off · keep the original generated image.</p>`;

    const stack = document.querySelector('#lora-stack-panel');
    const parameters = document.querySelector('#generate-parameter-row');
    const modeWorkspace = document.querySelector('#generate-mode-workspace');
    const anchor = modeWorkspace || stack || parameters;
    if (anchor) anchor.after(panel);
    else form.insertBefore(panel, document.querySelector('#generate-button'));

    panel.querySelector('#upscale-after-factor').addEventListener('change', syncUi);
    panel.querySelector('#upscale-after-model').addEventListener('change', schedulePlanRefresh);
    for (const selector of ['#width', '#height', '#resolution-tier', '#aspect-ratio']) {
      document.querySelector(selector)?.addEventListener('change', schedulePlanRefresh);
      document.querySelector(selector)?.addEventListener('input', schedulePlanRefresh);
    }
    syncUi();
    return panel;
  }

  function fillModels() {
    const select = document.querySelector('#upscale-after-model');
    if (!select) return;
    const previous = select.value;
    select.replaceChildren(new Option('Auto', ''));
    for (const model of upscaleAfterState.models) {
      const option = document.createElement('option');
      option.value = String(model);
      option.textContent = String(model);
      select.append(option);
    }
    if (previous && Array.from(select.options).some((option) => option.value === previous)) select.value = previous;
  }

  async function refreshModels() {
    try {
      const data = await api('/api/upscale-models');
      upscaleAfterState.models = Array.isArray(data?.models) ? data.models.map(String).filter(Boolean) : [];
      fillModels();
      syncUi();
    } catch (error) {
      upscaleAfterState.models = [];
      fillModels();
      const hint = document.querySelector('#upscale-output-hint');
      if (hint) {
        hint.classList.add('is-error');
        hint.textContent = `Upscale models unavailable: ${error.message}`;
      }
    }
  }

  function selectedFactor() {
    const value = Number(document.querySelector('#upscale-after-factor')?.value || 1);
    return [2, 4, 8].includes(value) ? value : 1;
  }

  function targetDimensions(factor) {
    const width = Number(document.querySelector('#width')?.value || 0);
    const height = Number(document.querySelector('#height')?.value || 0);
    const targetWidth = Number.isFinite(width) && width > 0 ? Math.round(width * factor) : 0;
    const targetHeight = Number.isFinite(height) && height > 0 ? Math.round(height * factor) : 0;
    return { targetWidth, targetHeight };
  }

  function withUpscaledDimensions(upscaled, source, factor) {
    const existingWidth = Number(getValue(upscaled, 'Width', 'width'));
    const existingHeight = Number(getValue(upscaled, 'Height', 'height'));
    if (Number.isFinite(existingWidth) && existingWidth > 0 && Number.isFinite(existingHeight) && existingHeight > 0) {
      return upscaled;
    }

    const sourceWidth = Number(getValue(source, 'Width', 'width'));
    const sourceHeight = Number(getValue(source, 'Height', 'height'));
    let width = Number.isFinite(sourceWidth) && sourceWidth > 0 ? Math.round(sourceWidth * factor) : 0;
    let height = Number.isFinite(sourceHeight) && sourceHeight > 0 ? Math.round(sourceHeight * factor) : 0;
    if (!width || !height) {
      const configured = targetDimensions(factor);
      width = configured.targetWidth;
      height = configured.targetHeight;
    }
    if (!width || !height) return upscaled;

    return {
      ...upscaled,
      width,
      height,
      Width: width,
      Height: height,
    };
  }

  function syncUi() {
    ensureUi();
    const factor = selectedFactor();
    const model = document.querySelector('#upscale-after-model');
    if (model) model.disabled = factor === 1 || upscaleAfterState.models.length === 0;
    schedulePlanRefresh();
  }

  function schedulePlanRefresh() {
    clearTimeout(upscaleAfterState.planTimer);
    upscaleAfterState.planTimer = setTimeout(() => void refreshPlanHint(), 80);
  }

  async function refreshPlanHint() {
    const hint = document.querySelector('#upscale-output-hint');
    if (!hint) return;
    const factor = selectedFactor();
    hint.classList.remove('is-error', 'large-output');
    if (factor === 1) {
      hint.textContent = 'Off · keep the original generated image.';
      return;
    }

    const { targetWidth, targetHeight } = targetDimensions(factor);
    const pixels = targetWidth * targetHeight;
    const large = targetWidth > 4096 || targetHeight > 4096 || pixels > 16_800_000;
    hint.classList.toggle('large-output', large);
    const sizeText = targetWidth && targetHeight ? `${targetWidth} × ${targetHeight}` : `${factor}× output`;
    if (!upscaleAfterState.models.length) {
      hint.classList.add('is-error');
      hint.textContent = `${sizeText} · no registered classic upscale model is available.`;
      return;
    }

    const token = ++upscaleAfterState.planningToken;
    const modelName = document.querySelector('#upscale-after-model')?.value || '';
    try {
      const payload = { factor };
      if (modelName) payload.modelName = modelName;
      const plan = await api('/api/upscale/plan', { method: 'POST', body: JSON.stringify(payload) });
      if (token !== upscaleAfterState.planningToken) return;
      const chain = Array.isArray(plan?.chain) ? plan.chain : [];
      const passes = Number(plan?.passes || chain.length || 0);
      const chainText = chain.length ? chain.join(' → ') : 'Auto';
      hint.textContent = `${sizeText} · ${passes} pass${passes === 1 ? '' : 'es'} · ${chainText}${large ? ' · large output' : ''}`;
    } catch (error) {
      if (token !== upscaleAfterState.planningToken) return;
      hint.classList.add('is-error');
      hint.textContent = `${sizeText} · ${error.message}`;
    }
  }

  function installGenerationCompleteHook() {
    if (window.__stableAmdUpscaleAfterHookInstalled) return;
    if (typeof renderGenerationResult !== 'function') return;
    window.__stableAmdUpscaleAfterHookInstalled = true;
    const previousRender = renderGenerationResult;
    renderGenerationResult = function stableAmdRenderWithPostProcess(result) {
      previousRender(result);
      const mode = String(getValue(result, 'Mode', 'mode') || '').toLowerCase();
      if (mode === 'upscale') return;
      document.dispatchEvent(new CustomEvent('stableamd:generation-complete', { detail: { result } }));
    };
  }

  async function runUpscaleAfterGeneration(result) {
    const factor = selectedFactor();
    if (factor === 1) return;
    const imagePath = String(getValue(result, 'ImagePath', 'imagePath') || '');
    if (!imagePath) return;

    const modelName = document.querySelector('#upscale-after-model')?.value || '';
    const planPayload = { factor };
    if (modelName) planPayload.modelName = modelName;
    const plan = await api('/api/upscale/plan', { method: 'POST', body: JSON.stringify(planPayload) });
    const passes = Number(plan?.passes || 0);
    showToast(`Generation complete · upscaling ${factor}×${passes ? ` in ${passes} pass${passes === 1 ? '' : 'es'}` : ''}…`);

    const request = { imagePath, factor };
    if (modelName) request.modelName = modelName;
    const upscaled = await api('/api/upscale', { method: 'POST', body: JSON.stringify(request) });
    renderGenerationResult(withUpscaledDimensions(upscaled, result, factor));
    await refreshHistory();
    showToast(`Upscale ${factor}× completed.`, 'success');
  }

  function boot() {
    installStyles();
    ensureUi();
    installGenerationCompleteHook();
    document.addEventListener('stableamd:generation-complete', (event) => {
      void runUpscaleAfterGeneration(event.detail?.result || {}).catch((error) => {
        showToast(`Post-generation upscale failed: ${error.message}`, 'error');
      });
    });
    document.querySelector('#refresh-button')?.addEventListener('click', () => setTimeout(() => void refreshModels(), 0));
    void refreshModels();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
