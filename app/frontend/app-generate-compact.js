(() => {
  function ensureCompactStylesheet() {
    if (document.querySelector('link[data-stableamd-compact-generate]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/compact-generate.css';
    link.dataset.stableamdCompactGenerate = '';
    document.head.append(link);
  }

  function makeGenerateCopyGeneric() {
    if (typeof pageMeta !== 'undefined' && Array.isArray(pageMeta.generate)) {
      pageMeta.generate[1] = 'Create an image locally on your Radeon GPU.';
    }
    const page = document.querySelector('#page-generate');
    const subtitle = document.querySelector('#page-subtitle');
    if (page?.classList.contains('is-visible') && subtitle) {
      subtitle.textContent = 'Create an image locally on your Radeon GPU.';
    }
  }

  function modelFamily() {
    const select = document.querySelector('#model-select');
    const id = select?.value || '';
    const model = Array.isArray(state?.models)
      ? state.models.find((entry) => String(getValue(entry, 'id', 'Id') || '') === String(id))
      : null;
    const family = String(getValue(model, 'family', 'Family') || '').toLowerCase();
    if (family) return family;

    const label = String(select?.selectedOptions?.[0]?.textContent || '').toLowerCase();
    if (label.includes('z-image') || label.includes('z image')) return 'z-image-turbo';
    if (label.includes('sdxl')) return 'sdxl';
    return '';
  }

  function currentUiHints() {
    const family = modelFamily();
    const uiHints = {
      negativePrompt: family === 'sdxl' || family === 'sdxl-turbo',
    };
    return uiHints;
  }

  function syncNegativePromptVisibility() {
    const input = document.querySelector('#negative-prompt');
    const field = input?.closest('.field');
    if (!field) return;
    const uiHints = currentUiHints();
    field.hidden = !uiHints.negativePrompt;
    input.setAttribute('aria-hidden', uiHints.negativePrompt ? 'false' : 'true');
  }

  function syncCustomSizeVisibility() {
    const custom = document.querySelector('#custom-size-fields');
    const tier = document.querySelector('#resolution-tier');
    const presetPanel = document.querySelector('#resolution-preset-panel');
    if (!custom) return;
    custom.hidden = Boolean(presetPanel && !presetPanel.hidden && tier && tier.value !== 'custom');
  }

  function shortFieldLabel(field, label) {
    const span = field?.querySelector(':scope > span');
    if (!span || span.textContent === label) return;
    span.textContent = label;
  }

  function moveField(container, selector, label = null) {
    const control = document.querySelector(selector);
    const field = control?.closest('.field');
    if (!field || !container) return null;
    if (label) shortFieldLabel(field, label);
    if (field.parentElement !== container) container.append(field);
    return field;
  }

  function setGenerateMenuOpen(open) {
    const button = document.querySelector('.nav-item[data-page="generate"]');
    const submenu = document.querySelector('#generate-nav-submenu');
    if (!button || !submenu) return;
    const expanded = Boolean(open);
    button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    submenu.hidden = !expanded;
  }

  function ensureGenerateSidebarMode() {
    const nav = document.querySelector('.nav-list');
    const generateButton = nav?.querySelector('.nav-item[data-page="generate"]');
    const mode = document.querySelector('#generation-mode');
    const field = mode?.closest('.field');
    if (!nav || !generateButton || !field) return null;

    let submenu = document.querySelector('#generate-nav-submenu');
    if (!submenu) {
      submenu = document.createElement('div');
      submenu.id = 'generate-nav-submenu';
      submenu.className = 'nav-generate-submenu';
      generateButton.after(submenu);
    }

    shortFieldLabel(field, 'Mode');
    field.classList.add('nav-generate-mode-field');
    if (field.parentElement !== submenu) submenu.append(field);

    if (!generateButton.dataset.generateSubmenu) {
      generateButton.dataset.generateSubmenu = 'true';
      generateButton.setAttribute('aria-controls', 'generate-nav-submenu');
      generateButton.addEventListener('click', () => {
        const isOpen = generateButton.getAttribute('aria-expanded') === 'true';
        setGenerateMenuOpen(!isOpen);
      });
      for (const item of nav.querySelectorAll('.nav-item:not([data-page="generate"])')) {
        item.addEventListener('click', () => setGenerateMenuOpen(false));
      }
    }

    if (!generateButton.hasAttribute('aria-expanded')) {
      setGenerateMenuOpen(document.querySelector('#page-generate')?.classList.contains('is-visible'));
    }
    return field;
  }

  function hideModelSupportHint() {
    const hint = document.querySelector('#model-support-hint');
    if (!hint) return;
    hint.hidden = true;
    hint.setAttribute('aria-hidden', 'true');
  }

  function compactifyLoraRow(row) {
    if (!row || row.dataset.compactLora === 'true') return;
    const main = row.querySelector('.model-root-main');
    const actions = row.querySelector('.model-root-actions');
    const enabled = row.querySelector('[data-lora-enabled]')?.closest('.checkbox-field');
    const nameField = row.querySelector('[data-lora-name]')?.closest('.field');
    const modelField = row.querySelector('[data-lora-model-strength]')?.closest('.field');
    const clipField = row.querySelector('[data-lora-clip-strength]')?.closest('.field');
    const modelInput = row.querySelector('[data-lora-model-strength]');
    const clipInput = row.querySelector('[data-lora-clip-strength]');
    if (!main || !actions || !nameField || !modelField || !clipField || !modelInput || !clipInput) return;

    row.dataset.compactLora = 'true';
    row.classList.add('lora-stack-row-compact');
    shortFieldLabel(nameField, 'LoRA');
    shortFieldLabel(modelField, 'Strength');
    shortFieldLabel(clipField, 'CLIP strength');

    const toolbar = document.createElement('div');
    toolbar.className = 'lora-row-toolbar';
    if (enabled) {
      enabled.classList.add('lora-enable-toggle');
      const text = enabled.querySelector('span');
      if (text) text.textContent = 'On';
      toolbar.append(enabled);
    }
    nameField.classList.add('lora-name-field');
    modelField.classList.add('lora-strength-field');
    toolbar.append(nameField, modelField);

    const clipAdvanced = document.createElement('details');
    clipAdvanced.className = 'lora-clip-advanced';
    clipAdvanced.innerHTML = '<summary>CLIP override</summary><label class="checkbox-field lora-clip-toggle"><input type="checkbox" data-lora-clip-override> <span>Use separate CLIP strength</span></label>';
    clipAdvanced.append(clipField);
    main.replaceChildren(toolbar, clipAdvanced);

    const override = clipAdvanced.querySelector('[data-lora-clip-override]');
    const initialModel = Number(modelInput.value || 1);
    const initialClip = Number(clipInput.value || 1);
    override.checked = Number.isFinite(initialModel) && Number.isFinite(initialClip) && Math.abs(initialModel - initialClip) > 0.0001;
    clipField.hidden = !override.checked;
    if (override.checked) clipAdvanced.open = true;
    else clipInput.value = modelInput.value;

    modelInput.addEventListener('input', () => {
      if (!override.checked) clipInput.value = modelInput.value;
    });
    override.addEventListener('change', () => {
      clipField.hidden = !override.checked;
      if (!override.checked) clipInput.value = modelInput.value;
      else clipAdvanced.open = true;
    });

    const actionButtons = Array.from(actions.querySelectorAll('[data-lora-action]'));
    const iconMap = { up: '↑', down: '↓', remove: '×' };
    const labelMap = { up: 'Move LoRA up', down: 'Move LoRA down', remove: 'Remove LoRA' };
    for (const button of actionButtons) {
      const action = button.dataset.loraAction;
      button.classList.add('lora-icon-button');
      button.textContent = iconMap[action] || button.textContent;
      button.title = labelMap[action] || '';
      button.setAttribute('aria-label', labelMap[action] || action);
    }
    toolbar.append(actions);
  }

  function compactifyLoraStack() {
    const panel = document.querySelector('#lora-stack-panel');
    if (!panel) return;
    panel.classList.add('compact-lora-stack');
    const toolbar = panel.querySelector('.section-toolbar');
    toolbar?.classList.add('compact-lora-heading');
    const headingText = toolbar?.querySelector('p');
    const compactHelp = 'Stack adapters in order; one strength controls model + CLIP unless you override CLIP.';
    if (headingText && headingText.textContent !== compactHelp) headingText.textContent = compactHelp;
    for (const row of panel.querySelectorAll('[data-lora-stack-row]')) compactifyLoraRow(row);
  }

  function createSection(id, className) {
    let element = document.querySelector(`#${id}`);
    if (element) return element;
    element = document.createElement('div');
    element.id = id;
    element.className = className;
    return element;
  }

  function compactifyGenerateLayout() {
    const form = document.querySelector('#generate-form');
    const promptField = document.querySelector('#prompt')?.closest('.field');
    if (!form || !promptField) return;
    form.classList.add('compact-generate-form');

    const contextRow = createSection('generate-context-row', 'generate-context-row');
    const sizeRow = createSection('generate-size-row', 'generate-size-row');
    const customSize = createSection('custom-size-fields', 'custom-size-fields');
    const parameterRow = createSection('generate-parameter-row', 'generate-parameter-row');
    const modeWorkspace = createSection('generate-mode-workspace', 'generate-mode-workspace');

    if (!contextRow.isConnected) form.prepend(contextRow);
    ensureGenerateSidebarMode();
    moveField(contextRow, '#model-select', 'Model');
    moveField(contextRow, '#generation-profile', 'Preset');
    hideModelSupportHint();

    if (promptField.previousElementSibling !== contextRow) contextRow.after(promptField);
    promptField.classList.add('compact-prompt-field');

    const negativeField = document.querySelector('#negative-prompt')?.closest('.field');
    if (negativeField) {
      negativeField.classList.add('negative-prompt-field');
      if (negativeField.previousElementSibling !== promptField) promptField.after(negativeField);
    }

    if (!sizeRow.isConnected) (negativeField || promptField).after(sizeRow);
    const resolutionPanel = document.querySelector('#resolution-preset-panel');
    if (resolutionPanel) {
      resolutionPanel.classList.add('compact-resolution-panel');
      shortFieldLabel(document.querySelector('#resolution-tier')?.closest('.field'), 'Size');
      shortFieldLabel(document.querySelector('#aspect-ratio')?.closest('.field'), 'Ratio');
      if (resolutionPanel.parentElement !== sizeRow) sizeRow.append(resolutionPanel);
    }

    moveField(customSize, '#width', 'Width');
    moveField(customSize, '#height', 'Height');
    if (!customSize.isConnected) sizeRow.after(customSize);

    moveField(parameterRow, '#seed', 'Seed');
    moveField(parameterRow, '#sampler', 'Sampler');
    moveField(parameterRow, '#scheduler', 'Scheduler');
    moveField(parameterRow, '#steps', 'Steps');
    moveField(parameterRow, '#cfg', 'CFG');
    if (!parameterRow.isConnected) customSize.after(parameterRow);

    const stack = document.querySelector('#lora-stack-panel');
    if (stack && stack.previousElementSibling !== parameterRow) parameterRow.after(stack);

    const modePanel = document.querySelector('#generation-mode-panel');
    const img2img = document.querySelector('#img2img-controls');
    if (img2img && img2img.parentElement !== modeWorkspace) modeWorkspace.append(img2img);
    const inpaint = document.querySelector('#inpaint-controls');
    if (inpaint && inpaint.parentElement !== modeWorkspace) modeWorkspace.append(inpaint);
    if (!modeWorkspace.isConnected) (stack || parameterRow).after(modeWorkspace);
    if (modePanel && !modePanel.querySelector('.field') && !modePanel.querySelector('#img2img-controls')) modePanel.hidden = true;

    const advanced = document.querySelector('.advanced-panel');
    if (advanced) advanced.hidden = true;

    const button = document.querySelector('#generate-button');
    if (button) {
      button.classList.add('compact-generate-button');
      const submitRow = createSection('generate-submit-row', 'generate-submit-row');
      if (!submitRow.isConnected) form.append(submitRow);
      if (button.parentElement !== submitRow) submitRow.append(button);
    }

    compactifyLoraStack();
    syncNegativePromptVisibility();
    syncCustomSizeVisibility();
  }

  function installObservers() {
    const form = document.querySelector('#generate-form');
    if (form && !form.dataset.compactObserver) {
      form.dataset.compactObserver = 'true';
      new MutationObserver(() => {
        compactifyGenerateLayout();
        compactifyLoraStack();
        hideModelSupportHint();
        syncNegativePromptVisibility();
      }).observe(form, { childList: true, subtree: true });
    }

    document.querySelector('#model-select')?.addEventListener('change', () => {
      queueMicrotask(() => {
        hideModelSupportHint();
        syncNegativePromptVisibility();
        syncCustomSizeVisibility();
      });
    });
    document.querySelector('#resolution-tier')?.addEventListener('change', () => queueMicrotask(syncCustomSizeVisibility));
  }

  ensureCompactStylesheet();
  const boot = () => {
    makeGenerateCopyGeneric();
    compactifyGenerateLayout();
    installObservers();
    setTimeout(compactifyGenerateLayout, 50);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();

  window.compactifyStableAmdGenerate = compactifyGenerateLayout;
})();
