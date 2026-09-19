(() => {
  const workspaceState = {
    syncQueued: false,
    observer: null,
    modeObserver: null,
    previewUrls: new WeakMap(),
    boundInputs: new WeakSet(),
    lastMode: '',
  };

  const MODE_COPY = {
    txt2img: {
      label: 'Text to image',
      title: 'Text to image',
      subtitle: 'Describe the image, then tune only the generation tools you need.',
    },
    img2img: {
      label: 'Image to image',
      title: 'Image to image',
      subtitle: 'Transform a source image with the selected model and edit workflow.',
    },
    inpaint: {
      label: 'Inpaint',
      title: 'Inpaint',
      subtitle: 'Edit a selected region while preserving the rest of the image.',
    },
  };

  function ensureWorkspaceStylesheet() {
    if (document.querySelector('link[data-stableamd-generate-workspace]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/generate-workspace.css';
    link.dataset.stableamdGenerateWorkspace = '';
    document.head.append(link);
  }

  function selectedModelFamily() {
    const select = document.querySelector('#model-select');
    const id = String(select?.value || '');
    const models = typeof state !== 'undefined' && Array.isArray(state?.models) ? state.models : [];
    const readValue = typeof getValue === 'function'
      ? getValue
      : ((entry, ...keys) => keys.map((key) => entry?.[key]).find((value) => value !== undefined));
    const model = models.find((entry) => String(readValue(entry, 'id', 'Id') || '') === id) || null;
    const family = String(readValue(model, 'family', 'Family') || '').toLowerCase();
    if (family) return family;
    const label = String(select?.selectedOptions?.[0]?.textContent || '').toLowerCase();
    if (label.includes('krea')) return 'krea2';
    if (label.includes('z-image') || label.includes('z image')) return 'z-image-turbo';
    if (label.includes('sdxl')) return 'sdxl';
    return '';
  }

  function currentMode() {
    return String(document.querySelector('#generation-mode')?.value || 'txt2img').toLowerCase();
  }

  function isGenerateVisible() {
    return document.querySelector('#page-generate')?.classList.contains('is-visible') === true;
  }

  function modeCopy(mode = currentMode()) {
    return MODE_COPY[mode] || {
      label: mode || 'Generate',
      title: mode || 'Generate',
      subtitle: 'Create locally with the selected StableAMD workflow.',
    };
  }

  function syncPageIdentity() {
    const visible = isGenerateVisible();
    document.body.classList.toggle('generate-studio-page', visible);
    if (!visible) return;
    const copy = modeCopy();
    const title = document.querySelector('#page-title');
    const subtitle = document.querySelector('#page-subtitle');
    if (title) title.textContent = copy.title;
    if (subtitle) subtitle.textContent = copy.subtitle;
  }

  function ensureModeChoices() {
    const submenu = document.querySelector('#generate-nav-submenu');
    const select = document.querySelector('#generation-mode');
    if (!submenu || !select) return null;

    const canonicalField = select.closest('.field');
    canonicalField?.classList.add('studio-canonical-mode-field');

    let choices = submenu.querySelector('#generate-mode-choices');
    if (!choices) {
      choices = document.createElement('div');
      choices.id = 'generate-mode-choices';
      choices.className = 'generate-mode-choices';
      choices.setAttribute('aria-label', 'Generation type');
      if (canonicalField) canonicalField.before(choices);
      else submenu.prepend(choices);
    }

    const options = Array.from(select.options).filter((option) => !option.dataset.stableamdModePlaceholder);
    const allowedValues = new Set(options.map((option) => option.value));
    for (const existing of Array.from(choices.querySelectorAll('.generate-mode-choice'))) {
      if (!allowedValues.has(existing.dataset.mode || '')) existing.remove();
    }

    for (const option of options) {
      const mode = String(option.value || '');
      if (!mode) continue;
      let button = choices.querySelector(`[data-mode="${CSS.escape(mode)}"]`);
      if (!button) {
        button = document.createElement('button');
        button.type = 'button';
        button.className = 'generate-mode-choice';
        button.dataset.mode = mode;
        button.addEventListener('click', () => {
          if (button.disabled || select.value === mode) return;
          select.value = mode;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          animateModeChange();
          queueSync();
        });
        choices.append(button);
      }
      button.textContent = modeCopy(mode).label;
      button.hidden = Boolean(option.hidden);
      button.disabled = Boolean(select.disabled || option.disabled || option.hidden);
      const selected = select.value === mode;
      button.classList.toggle('is-active', selected);
      if (selected) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
      button.title = button.disabled
        ? `${modeCopy(mode).label} is unavailable for the selected model.`
        : modeCopy(mode).label;
    }
    return choices;
  }

  function createInspectorSection(inspector, id, label, open = false) {
    let section = inspector.querySelector(`#${id}`);
    if (section) return section;
    section = document.createElement('details');
    section.id = id;
    section.className = 'studio-inspector-section';
    section.open = open;
    const summary = document.createElement('summary');
    summary.textContent = label;
    const body = document.createElement('div');
    body.className = 'studio-inspector-body';
    section.append(summary, body);
    inspector.append(section);
    return section;
  }

  function ensureInspector(layout) {
    let inspector = layout.querySelector('#generate-studio-inspector');
    if (inspector) return inspector;
    inspector = document.createElement('aside');
    inspector.id = 'generate-studio-inspector';
    inspector.className = 'studio-inspector';
    inspector.setAttribute('aria-label', 'Generation settings');

    const header = document.createElement('div');
    header.className = 'studio-inspector-header';
    header.innerHTML = '<strong>Settings</strong><span>contextual</span>';
    inspector.append(header);

    createInspectorSection(inspector, 'studio-output-section', 'Output', true);
    createInspectorSection(inspector, 'studio-lora-section', 'LoRA', false);
    createInspectorSection(inspector, 'studio-control-section', 'Control guidance', false);
    createInspectorSection(inspector, 'studio-upscale-section', 'Upscale', false);
    const advanced = createInspectorSection(inspector, 'studio-advanced-section', 'Advanced', false);
    advanced.hidden = true;

    layout.append(inspector);
    return inspector;
  }

  function sectionBody(inspector, id) {
    return inspector.querySelector(`#${id} > .studio-inspector-body`);
  }

  function moveInto(body, element) {
    if (!body || !element || element.parentElement === body) return;
    body.append(element);
  }

  function syncInspectorContent(inspector) {
    const output = sectionBody(inspector, 'studio-output-section');
    const lora = sectionBody(inspector, 'studio-lora-section');
    const control = sectionBody(inspector, 'studio-control-section');
    const upscale = sectionBody(inspector, 'studio-upscale-section');
    const advanced = sectionBody(inspector, 'studio-advanced-section');

    for (const selector of ['#generate-size-row', '#custom-size-fields', '#generate-parameter-row']) {
      moveInto(output, document.querySelector(selector));
    }
    moveInto(lora, document.querySelector('#lora-stack-panel'));
    moveInto(control, document.querySelector('#controlnet-panel'));
    moveInto(upscale, document.querySelector('#upscale-after-generation'));

    const legacyAdvanced = document.querySelector('.advanced-panel');
    if (legacyAdvanced && legacyAdvanced.children.length && !legacyAdvanced.hidden) moveInto(advanced, legacyAdvanced);

    const loraSection = inspector.querySelector('#studio-lora-section');
    const controlSection = inspector.querySelector('#studio-control-section');
    const upscaleSection = inspector.querySelector('#studio-upscale-section');
    const advancedSection = inspector.querySelector('#studio-advanced-section');
    const mode = currentMode();

    if (loraSection) loraSection.hidden = !lora?.children.length;
    if (controlSection) controlSection.hidden = mode !== 'txt2img' || !control?.children.length;
    if (upscaleSection) upscaleSection.hidden = !upscale?.children.length;
    if (advancedSection) advancedSection.hidden = !advanced?.children.length;
  }

  function ensureStudioLayout() {
    const page = document.querySelector('#page-generate');
    const layout = page?.querySelector('.generate-layout');
    const form = document.querySelector('#generate-form');
    const result = page?.querySelector('.result-panel');
    if (!page || !layout || !form || !result) return null;

    layout.classList.add('studio-workspace');
    form.classList.add('studio-recipe');
    result.classList.add('studio-canvas');

    const inspector = ensureInspector(layout);
    syncInspectorContent(inspector);
    return { page, layout, form, result, inspector };
  }

  function syncKreaDenoise() {
    const mode = currentMode();
    const family = selectedModelFamily();
    const denoise = document.querySelector('#img2img-denoise');
    const field = denoise?.closest('.field');
    if (!denoise || !field) return;
    const kreaImageEdit = family === 'krea2' && mode === 'img2img';
    if (kreaImageEdit) {
      field.hidden = true;
      denoise.disabled = true;
      denoise.setAttribute('aria-hidden', 'true');
    } else {
      field.hidden = mode !== 'img2img';
      denoise.disabled = mode !== 'img2img';
      denoise.setAttribute('aria-hidden', mode === 'img2img' ? 'false' : 'true');
    }
  }

  function decorateFileInput(input) {
    if (!input || workspaceState.boundInputs.has(input)) return;
    workspaceState.boundInputs.add(input);
    const field = input.closest('.field');
    if (!field) return;
    field.classList.add('studio-file-field');

    const preview = document.createElement('div');
    preview.className = 'studio-file-preview';
    preview.hidden = true;
    preview.innerHTML = '<img alt=""><span></span>';
    input.after(preview);

    const update = () => {
      const previousUrl = workspaceState.previewUrls.get(input);
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      workspaceState.previewUrls.delete(input);
      const file = input.files?.[0];
      if (!file) {
        preview.hidden = true;
        return;
      }
      const url = URL.createObjectURL(file);
      workspaceState.previewUrls.set(input, url);
      const image = preview.querySelector('img');
      const label = preview.querySelector('span');
      if (image) {
        image.src = url;
        image.alt = `Preview of ${file.name}`;
      }
      if (label) label.textContent = `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MiB`;
      preview.hidden = false;
    };
    input.addEventListener('change', update);
    update();
  }

  function enhanceFileInputs() {
    for (const selector of ['#input-image', '#krea-reference-image', '#controlnet-image']) {
      decorateFileInput(document.querySelector(selector));
    }
  }

  function animateModeChange() {
    const page = document.querySelector('#page-generate');
    if (!page) return;
    page.classList.remove('studio-mode-transition');
    void page.offsetWidth;
    page.classList.add('studio-mode-transition');
    window.setTimeout(() => page.classList.remove('studio-mode-transition'), 220);
  }

  function syncModeTransition() {
    const mode = currentMode();
    if (workspaceState.lastMode && workspaceState.lastMode !== mode) animateModeChange();
    workspaceState.lastMode = mode;
  }

  function syncWorkspace() {
    workspaceState.syncQueued = false;
    const built = ensureStudioLayout();
    if (!built) return;
    ensureModeChoices();
    syncKreaDenoise();
    enhanceFileInputs();
    syncPageIdentity();
    syncModeTransition();
  }

  function queueSync() {
    if (workspaceState.syncQueued) return;
    workspaceState.syncQueued = true;
    queueMicrotask(syncWorkspace);
  }

  function installObservers() {
    if (!workspaceState.observer) {
      workspaceState.observer = new MutationObserver(queueSync);
      const target = document.querySelector('#page-generate') || document.body;
      workspaceState.observer.observe(target, {
        childList: true,
        subtree: true,
      });
    }

    const select = document.querySelector('#generation-mode');
    if (select && !workspaceState.modeObserver) {
      workspaceState.modeObserver = new MutationObserver(queueSync);
      workspaceState.modeObserver.observe(select, { childList: true, subtree: true, attributes: true });
      select.addEventListener('change', queueSync);
    }

    const model = document.querySelector('#model-select');
    if (model && !model.dataset.studioWorkspaceBound) {
      model.dataset.studioWorkspaceBound = 'true';
      model.addEventListener('change', () => {
        window.setTimeout(queueSync, 0);
        window.setTimeout(queueSync, 80);
      });
    }

    const nav = document.querySelector('.nav-list');
    if (nav && !nav.dataset.studioWorkspaceBound) {
      nav.dataset.studioWorkspaceBound = 'true';
      nav.addEventListener('click', () => window.setTimeout(queueSync, 0));
    }

    for (const eventName of ['stableamd:control-visibility-changed', 'stableamd:control-type-changed']) {
      document.addEventListener(eventName, queueSync);
    }
  }

  function boot() {
    ensureWorkspaceStylesheet();
    syncWorkspace();
    installObservers();
    window.setTimeout(queueSync, 60);
    window.setTimeout(queueSync, 220);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();

  window.syncStableAmdGenerateWorkspace = queueSync;
})();
