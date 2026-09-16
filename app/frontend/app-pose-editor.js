(() => {
  const POSE_DEPOT_SHA = '10471a9df9a5f25fba422e542475e6a72b5f23b8';
  const OPENPOSE_STUDIO_SHA = '4071e2c1259956f219cca617ca8b73c6608e50d5';
  const POSE_DEPOT_ROOT = `https://raw.githubusercontent.com/a-lgil/pose-depot/${POSE_DEPOT_SHA}/collections`;
  const OPENPOSE_STUDIO_ROOT = `https://raw.githubusercontent.com/andreszs/ComfyUI-OpenPose-Studio/${OPENPOSE_STUDIO_SHA}/poses`;

  const templates = [
    ['Double peace sign', '1_Double_Peace_Sign'],
    ['Sitting on desk · F', '10F_Sitting_on_Desk'],
    ['Sitting on desk · M', '10M_Sitting_on_Desk'],
    ['Sitting on stairs · F', '11F_Sitting_on_Stairs'],
    ['Sitting on stairs · M', '11M_Sitting_on_Stairs'],
    ['Reaching / freefall · F', '12F_Reaching_during_Freefall'],
    ['Reaching / freefall · M', '12M_Reaching_during_Freefall'],
    ['Salute · F', '13F_Salute'],
    ['Salute · M', '13M_Salute'],
    ['Crossed legs · F', '14F_Crossed_Legs_on_Floor'],
    ['Crossed legs · M', '14M_Crossed_Legs_on_Floor'],
    ['Flying superhero · F', '15F_Flying_Superhero'],
    ['Flying superhero · M', '15M_Flying_Superhero'],
    ['Sitting and thinking · F', '16F_Sitting_and_Thinking'],
    ['Sitting and thinking · M', '16M_Sitting_and_Thinking'],
  ].map(([label, folder]) => ({
    id: folder,
    label,
    source: 'Pose Depot',
    license: 'Apache-2.0',
    controlUrl: `${POSE_DEPOT_ROOT}/${folder}/OpenPoseFull.png`,
    previewUrl: `${POSE_DEPOT_ROOT}/${folder}/Cover.png`,
    fallbackPreviewUrl: `${POSE_DEPOT_ROOT}/${folder}/Example.png`,
    url: `${POSE_DEPOT_ROOT}/${folder}/OpenPoseFull.png`,
  }));

  const presetSources = [
    ['Sitting', 'Sitting.json'],
    ['Walking', 'Walking.json'],
    ['Dynamic', 'dynamic.json'],
    ['Jumping', 'jumping.json'],
    ['Hugging / two people', 'hugging.json'],
    ['Leaning', 'leaning.json'],
    ['Back to back', 'back-to-back.json'],
    ['Reference sheet', 'reference-sheet.json'],
    ['Seiza', 'seiza.json'],
    ['Wariza', 'wariza.json'],
  ].map(([label, file]) => ({
    label,
    file,
    url: `${OPENPOSE_STUDIO_ROOT}/${file}`,
    source: 'ComfyUI OpenPose Studio',
    license: 'MIT',
  }));

  const edges = [
    [1, 2], [2, 3], [3, 4], [1, 5], [5, 6], [6, 7],
    [1, 8], [8, 9], [9, 10], [1, 11], [11, 12], [12, 13],
    [1, 0], [0, 14], [14, 16], [0, 15], [15, 17],
  ];
  const edgeColors = [
    '#ff0000', '#ff5500', '#ffaa00', '#ffff00', '#aaff00', '#55ff00',
    '#00ff00', '#00ff55', '#00ffaa', '#00ffff', '#00aaff', '#0055ff',
    '#0000ff', '#5500ff', '#aa00ff', '#ff00ff', '#ff0055',
  ];

  const defaultPose = [
    [256, 105, 1], [256, 190, 1], [190, 205, 1], [145, 310, 1], [120, 420, 1],
    [322, 205, 1], [367, 310, 1], [392, 420, 1], [215, 390, 1], [210, 535, 1],
    [205, 700, 1], [297, 390, 1], [302, 535, 1], [307, 700, 1], [235, 90, 1],
    [277, 90, 1], [220, 102, 1], [292, 102, 1],
  ];

  const state = {
    selectedPayload: null,
    selectedPreview: '',
    selectedLabel: '',
    points: defaultPose.map((point) => [...point]),
    canvasWidth: 512,
    canvasHeight: 768,
    dragging: -1,
    referenceImage: null,
    referenceObjectUrl: '',
    presetData: null,
  };

  function showToastSafe(message) {
    if (typeof showToast === 'function') showToast(message);
    else console.log(message);
  }

  function installStyles() {
    if (document.querySelector('#stableamd-pose-styles')) return;
    const style = document.createElement('style');
    style.id = 'stableamd-pose-styles';
    style.textContent = `
      .pose-control-tools { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:8px; }
      .pose-control-tools[hidden] { display:none !important; }
      .pose-control-status { font-size:12px; opacity:.78; min-width:180px; flex:1; }
      .pose-selected-preview { width:100%; max-height:220px; object-fit:contain; background:#05070a; border:1px solid var(--border,#303642); border-radius:9px; margin-top:8px; }
      .pose-modal-backdrop { position:fixed; inset:0; z-index:10050; background:rgba(0,0,0,.72); display:grid; place-items:center; padding:18px; }
      .pose-modal-backdrop[hidden] { display:none; }
      .pose-modal { width:min(1120px,96vw); max-height:92vh; overflow:auto; background:var(--panel,#171b22); border:1px solid var(--border,#303642); border-radius:14px; box-shadow:0 24px 80px rgba(0,0,0,.45); }
      .pose-modal-header { position:sticky; top:0; z-index:2; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 16px; background:var(--panel,#171b22); border-bottom:1px solid var(--border,#303642); }
      .pose-modal-header h3 { margin:0; font-size:16px; }
      .pose-modal-body { padding:14px 16px 18px; display:grid; gap:14px; }
      .pose-tabs { display:flex; gap:8px; flex-wrap:wrap; }
      .pose-tab-active { outline:2px solid rgba(85,150,255,.55); }
      .pose-template-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:12px; }
      .pose-template-card { border:1px solid var(--border,#303642); border-radius:12px; padding:8px; display:grid; gap:8px; background:rgba(127,127,127,.05); }
      .pose-template-preview-wrap { position:relative; overflow:hidden; border-radius:10px; background:#000; aspect-ratio:2/3; }
      .pose-template-preview { width:100%; height:100%; display:block; object-fit:cover; background:#000; }
      .pose-template-skeleton-badge { position:absolute; right:8px; bottom:8px; width:64px; height:96px; box-sizing:border-box; object-fit:contain; padding:4px; background:rgba(0,0,0,.76); border:1px solid rgba(255,255,255,.2); border-radius:8px; box-shadow:0 6px 18px rgba(0,0,0,.42); }
      .pose-template-card strong { font-size:12px; line-height:1.25; }
      .pose-template-meta { font-size:10px; opacity:.65; }
      .pose-template-actions { display:flex; gap:6px; }
      .pose-template-actions > * { flex:1; text-align:center; }
      .pose-editor-layout { display:grid; grid-template-columns:minmax(300px,540px) minmax(260px,1fr); gap:14px; align-items:start; }
      .pose-canvas-wrap { display:grid; place-items:center; background:#07090d; border:1px solid var(--border,#303642); border-radius:10px; padding:10px; overflow:auto; }
      #pose-editor-canvas { width:min(100%,512px); height:auto; touch-action:none; background:#000; border-radius:6px; }
      .pose-editor-side { display:grid; gap:10px; }
      .pose-editor-actions { display:flex; flex-wrap:wrap; gap:8px; }
      .pose-source-note { margin:0; font-size:11px; opacity:.68; line-height:1.45; }
      @media (max-width: 820px) { .pose-editor-layout { grid-template-columns:1fr; } }
    `;
    document.head.append(style);
  }

  function blobToPayload(blob, name) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Could not encode the pose image.'));
      reader.onload = () => {
        const value = String(reader.result || '');
        const comma = value.indexOf(',');
        if (comma < 0) return reject(new Error('Pose image encoding failed.'));
        resolve({ name, mimeType: blob.type || 'image/png', dataBase64: value.slice(comma + 1) });
      };
      reader.readAsDataURL(blob);
    });
  }

  function dataUrlToPayload(dataUrl, name) {
    const comma = String(dataUrl || '').indexOf(',');
    if (comma < 0) throw new Error('Pose image encoding failed.');
    return { name, mimeType: 'image/png', dataBase64: dataUrl.slice(comma + 1) };
  }

  function updateSelectedPreview() {
    const preview = document.querySelector('#pose-selected-preview');
    const status = document.querySelector('#pose-control-status');
    const clear = document.querySelector('#pose-clear-selection');
    if (preview) {
      preview.hidden = !state.selectedPreview;
      if (state.selectedPreview) preview.src = state.selectedPreview;
      else preview.removeAttribute('src');
    }
    if (status) {
      status.textContent = state.selectedPayload
        ? `Selected: ${state.selectedLabel || state.selectedPayload.name}`
        : 'Upload is optional — choose a template or create a pose.';
    }
    if (clear) clear.hidden = !state.selectedPayload;
  }

  function clearSelectedPose() {
    state.selectedPayload = null;
    state.selectedPreview = '';
    state.selectedLabel = '';
    updateSelectedPreview();
  }

  function controlIsOpenPose() {
    const enabled = document.querySelector('#controlnet-enabled');
    const type = document.querySelector('#controlnet-type');
    return Boolean(enabled?.checked && type?.value === 'openpose');
  }

  function syncToolsVisibility() {
    const tools = document.querySelector('#pose-control-tools');
    if (tools) tools.hidden = !controlIsOpenPose();
  }

  function installControlTools() {
    if (document.querySelector('#pose-control-tools')) return;
    const input = document.querySelector('#controlnet-image');
    if (!input) return;

    const tools = document.createElement('div');
    tools.id = 'pose-control-tools';
    tools.className = 'pose-control-tools';
    tools.hidden = true;
    tools.innerHTML = `
      <button id="pose-open-library" type="button" class="button button-secondary">Pose templates</button>
      <button id="pose-open-editor" type="button" class="button button-secondary">Interactive pose editor</button>
      <button id="pose-clear-selection" type="button" class="button button-secondary" hidden>Clear pose</button>
      <span id="pose-control-status" class="pose-control-status">Upload is optional — choose a template or create a pose.</span>
    `;
    input.insertAdjacentElement('afterend', tools);

    const preview = document.createElement('img');
    preview.id = 'pose-selected-preview';
    preview.className = 'pose-selected-preview';
    preview.alt = 'Selected OpenPose control map';
    preview.hidden = true;
    tools.insertAdjacentElement('afterend', preview);

    tools.querySelector('#pose-open-library')?.addEventListener('click', () => openModal('templates'));
    tools.querySelector('#pose-open-editor')?.addEventListener('click', () => openModal('editor'));
    tools.querySelector('#pose-clear-selection')?.addEventListener('click', clearSelectedPose);
    input.addEventListener('change', () => { if (input.files?.length) clearSelectedPose(); });
    syncToolsVisibility();
  }

  function createModal() {
    if (document.querySelector('#pose-modal-backdrop')) return document.querySelector('#pose-modal-backdrop');
    const backdrop = document.createElement('div');
    backdrop.id = 'pose-modal-backdrop';
    backdrop.className = 'pose-modal-backdrop';
    backdrop.hidden = true;
    backdrop.innerHTML = `
      <section class="pose-modal" role="dialog" aria-modal="true" aria-labelledby="pose-modal-title">
        <header class="pose-modal-header">
          <h3 id="pose-modal-title">Pose library & editor</h3>
          <button id="pose-modal-close" type="button" class="button button-secondary">Close</button>
        </header>
        <div class="pose-modal-body">
          <div class="pose-tabs">
            <button id="pose-tab-templates" type="button" class="button button-secondary">Image templates</button>
            <button id="pose-tab-editor" type="button" class="button button-secondary">Interactive editor</button>
          </div>
          <section id="pose-view-templates">
            <p class="pose-source-note">Curated pose pairs from a-lgil/pose-depot, pinned to ${POSE_DEPOT_SHA.slice(0, 8)} (Apache-2.0). Each card shows a realistic pose preview with its matching OpenPose skeleton; selecting a pose always sends the skeleton as the actual control image.</p>
            <div id="pose-template-grid" class="pose-template-grid"></div>
          </section>
          <section id="pose-view-editor" hidden>
            <div class="pose-editor-layout">
              <div class="pose-canvas-wrap"><canvas id="pose-editor-canvas" width="512" height="768"></canvas></div>
              <div class="pose-editor-side">
                <label class="field"><span>Editable preset collection</span><select id="pose-preset-source"></select></label>
                <label class="field"><span>Preset variant</span><select id="pose-preset-variant"></select></label>
                <button id="pose-load-preset" type="button" class="button button-secondary">Load preset</button>
                <label class="field">
                  <span>Optional reference photo</span>
                  <input id="pose-reference-file" type="file" accept="image/png,image/jpeg,image/webp">
                  <small class="pose-source-note">Reference is only an alignment overlay. It is not exported into the OpenPose map.</small>
                </label>
                <label class="field"><span>Reference opacity</span><input id="pose-reference-opacity" type="range" min="0" max="0.8" step="0.05" value="0.35"></label>
                <div class="pose-editor-actions">
                  <button id="pose-mirror" type="button" class="button button-secondary">Mirror</button>
                  <button id="pose-reset" type="button" class="button button-secondary">Reset</button>
                  <button id="pose-download" type="button" class="button button-secondary">Download PNG</button>
                </div>
                <button id="pose-use-editor" type="button" class="button">Use edited pose</button>
                <p class="pose-source-note">Preset JSON files come from andreszs/ComfyUI-OpenPose-Studio pinned to ${OPENPOSE_STUDIO_SHA.slice(0, 8)} (MIT). Drag joints directly on the canvas.</p>
              </div>
            </div>
          </section>
        </div>
      </section>
    `;
    document.body.append(backdrop);

    backdrop.querySelector('#pose-modal-close')?.addEventListener('click', closeModal);
    backdrop.addEventListener('pointerdown', (event) => { if (event.target === backdrop) closeModal(); });
    backdrop.querySelector('#pose-tab-templates')?.addEventListener('click', () => showModalView('templates'));
    backdrop.querySelector('#pose-tab-editor')?.addEventListener('click', () => showModalView('editor'));
    backdrop.querySelector('#pose-load-preset')?.addEventListener('click', loadSelectedPreset);
    backdrop.querySelector('#pose-preset-source')?.addEventListener('change', refreshPresetVariants);
    backdrop.querySelector('#pose-reference-file')?.addEventListener('change', loadReferenceImage);
    backdrop.querySelector('#pose-reference-opacity')?.addEventListener('input', drawEditor);
    backdrop.querySelector('#pose-mirror')?.addEventListener('click', mirrorPose);
    backdrop.querySelector('#pose-reset')?.addEventListener('click', () => {
      state.points = defaultPose.map((point) => [...point]);
      state.canvasWidth = 512;
      state.canvasHeight = 768;
      resizeEditorCanvas();
      drawEditor();
    });
    backdrop.querySelector('#pose-download')?.addEventListener('click', downloadEditorPose);
    backdrop.querySelector('#pose-use-editor')?.addEventListener('click', useEditorPose);

    buildTemplateGrid();
    buildPresetSources();
    installCanvasInteractions();
    return backdrop;
  }

  function openModal(view) {
    const modal = createModal();
    showModalView(view);
    modal.hidden = false;
    if (view === 'editor') requestAnimationFrame(drawEditor);
  }

  function closeModal() {
    const modal = document.querySelector('#pose-modal-backdrop');
    if (modal) modal.hidden = true;
  }

  function showModalView(view) {
    const templatesView = document.querySelector('#pose-view-templates');
    const editorView = document.querySelector('#pose-view-editor');
    const templatesTab = document.querySelector('#pose-tab-templates');
    const editorTab = document.querySelector('#pose-tab-editor');
    const editor = view === 'editor';
    if (templatesView) templatesView.hidden = editor;
    if (editorView) editorView.hidden = !editor;
    templatesTab?.classList.toggle('pose-tab-active', !editor);
    editorTab?.classList.toggle('pose-tab-active', editor);
    if (editor) requestAnimationFrame(drawEditor);
  }

  function buildTemplateGrid() {
    const grid = document.querySelector('#pose-template-grid');
    if (!grid || grid.childElementCount) return;
    templates.forEach((template) => {
      const card = document.createElement('article');
      card.className = 'pose-template-card';
      card.innerHTML = `
        <div class="pose-template-preview-wrap">
          <img class="pose-template-preview" loading="lazy" src="${template.previewUrl}" alt="${template.label} realistic pose preview">
          <img class="pose-template-skeleton-badge" loading="lazy" src="${template.controlUrl}" alt="${template.label} OpenPose skeleton">
        </div>
        <strong>${template.label}</strong>
        <span class="pose-template-meta">${template.source} · ${template.license}</span>
        <div class="pose-template-actions">
          <button type="button" class="button button-secondary" data-use-template="${template.id}">Use pose</button>
          <a class="button button-secondary" href="${template.controlUrl}" target="_blank" rel="noopener">Skeleton</a>
        </div>
      `;
      const preview = card.querySelector('.pose-template-preview');
      preview?.addEventListener('error', () => {
        const stage = preview.dataset.poseFallback || '';
        if (!stage) {
          preview.dataset.poseFallback = 'example';
          preview.src = template.fallbackPreviewUrl;
        } else if (stage === 'example') {
          preview.dataset.poseFallback = 'skeleton';
          preview.src = template.controlUrl;
          preview.style.objectFit = 'contain';
        }
      });
      card.querySelector('[data-use-template]')?.addEventListener('click', () => useTemplate(template));
      grid.append(card);
    });
  }

  async function useTemplate(template) {
    try {
      const response = await fetch(template.controlUrl, { cache: 'force-cache' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      state.selectedPayload = await blobToPayload(blob, `${template.id}-OpenPoseFull.png`);
      state.selectedPreview = template.controlUrl;
      state.selectedLabel = template.label;
      const file = document.querySelector('#controlnet-image');
      if (file) file.value = '';
      updateSelectedPreview();
      closeModal();
      showToastSafe(`Pose template selected: ${template.label}`);
    } catch (error) {
      showToastSafe(`Could not download pose template: ${error?.message || error}`);
    }
  }

  function buildPresetSources() {
    const select = document.querySelector('#pose-preset-source');
    if (!select || select.childElementCount) return;
    presetSources.forEach((source, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = source.label;
      select.append(option);
    });
    refreshPresetVariants();
  }

  async function refreshPresetVariants() {
    const sourceSelect = document.querySelector('#pose-preset-source');
    const variantSelect = document.querySelector('#pose-preset-variant');
    if (!sourceSelect || !variantSelect) return;
    const source = presetSources[Number(sourceSelect.value || 0)] || presetSources[0];
    variantSelect.replaceChildren();
    variantSelect.disabled = true;
    const loading = document.createElement('option');
    loading.textContent = 'Loading…';
    variantSelect.append(loading);
    try {
      const response = await fetch(source.url, { cache: 'force-cache' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.presetData = data && typeof data === 'object' ? data : null;
      variantSelect.replaceChildren();
      Object.keys(state.presetData || {}).forEach((name) => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        variantSelect.append(option);
      });
      variantSelect.disabled = !variantSelect.options.length;
      if (variantSelect.options.length) loadSelectedPreset();
    } catch (error) {
      state.presetData = null;
      variantSelect.replaceChildren();
      const failed = document.createElement('option');
      failed.textContent = 'Could not load presets';
      variantSelect.append(failed);
      showToastSafe(`Pose preset download failed: ${error?.message || error}`);
    }
  }

  function loadSelectedPreset() {
    const variantSelect = document.querySelector('#pose-preset-variant');
    const preset = state.presetData?.[variantSelect?.value || ''];
    const values = preset?.people?.[0]?.pose_keypoints_2d;
    if (!preset || !Array.isArray(values) || values.length < 54) {
      showToastSafe('This preset does not contain a usable 18-joint body pose.');
      return;
    }
    state.canvasWidth = Math.max(64, Number(preset.canvas_width) || 512);
    state.canvasHeight = Math.max(64, Number(preset.canvas_height) || 768);
    state.points = Array.from({ length: 18 }, (_, index) => [
      Number(values[index * 3]) || 0,
      Number(values[index * 3 + 1]) || 0,
      Number(values[index * 3 + 2]) || 0,
    ]);
    resizeEditorCanvas();
    drawEditor();
  }

  function resizeEditorCanvas() {
    const canvas = document.querySelector('#pose-editor-canvas');
    if (!canvas) return;
    canvas.width = state.canvasWidth;
    canvas.height = state.canvasHeight;
  }

  function drawSkeleton(ctx, points) {
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    const scale = Math.max(1, Math.min(state.canvasWidth, state.canvasHeight) / 512);
    edges.forEach(([a, b], index) => {
      const pa = points[a];
      const pb = points[b];
      if (!pa || !pb || pa[2] <= 0 || pb[2] <= 0) return;
      ctx.strokeStyle = edgeColors[index % edgeColors.length];
      ctx.lineWidth = 6 * scale;
      ctx.beginPath();
      ctx.moveTo(pa[0], pa[1]);
      ctx.lineTo(pb[0], pb[1]);
      ctx.stroke();
    });
    points.forEach((point, index) => {
      if (!point || point[2] <= 0) return;
      ctx.fillStyle = edgeColors[index % edgeColors.length];
      ctx.beginPath();
      ctx.arc(point[0], point[1], 7 * scale, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function drawEditor() {
    const canvas = document.querySelector('#pose-editor-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const opacity = Number(document.querySelector('#pose-reference-opacity')?.value || 0);
    if (state.referenceImage && opacity > 0) {
      ctx.save();
      ctx.globalAlpha = opacity;
      const scale = Math.max(canvas.width / state.referenceImage.width, canvas.height / state.referenceImage.height);
      const width = state.referenceImage.width * scale;
      const height = state.referenceImage.height * scale;
      ctx.drawImage(state.referenceImage, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height);
      ctx.restore();
      ctx.fillStyle = 'rgba(0,0,0,.18)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
    drawSkeleton(ctx, state.points);
  }

  function renderPoseDataUrl() {
    const canvas = document.createElement('canvas');
    canvas.width = state.canvasWidth;
    canvas.height = state.canvasHeight;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    drawSkeleton(ctx, state.points);
    return canvas.toDataURL('image/png');
  }

  function installCanvasInteractions() {
    const canvas = document.querySelector('#pose-editor-canvas');
    if (!canvas || canvas.dataset.poseInteractive === '1') return;
    canvas.dataset.poseInteractive = '1';
    const eventPoint = (event) => {
      const rect = canvas.getBoundingClientRect();
      return [
        (event.clientX - rect.left) * canvas.width / rect.width,
        (event.clientY - rect.top) * canvas.height / rect.height,
      ];
    };
    canvas.addEventListener('pointerdown', (event) => {
      const [x, y] = eventPoint(event);
      let best = -1;
      let bestDistance = Math.max(22, Math.min(canvas.width, canvas.height) * 0.045);
      state.points.forEach((point, index) => {
        if (!point || point[2] <= 0) return;
        const distance = Math.hypot(point[0] - x, point[1] - y);
        if (distance < bestDistance) { best = index; bestDistance = distance; }
      });
      if (best >= 0) {
        state.dragging = best;
        canvas.setPointerCapture(event.pointerId);
        event.preventDefault();
      }
    });
    canvas.addEventListener('pointermove', (event) => {
      if (state.dragging < 0) return;
      const [x, y] = eventPoint(event);
      const point = state.points[state.dragging];
      point[0] = Math.max(0, Math.min(canvas.width, x));
      point[1] = Math.max(0, Math.min(canvas.height, y));
      point[2] = 1;
      drawEditor();
    });
    const stop = () => { state.dragging = -1; };
    canvas.addEventListener('pointerup', stop);
    canvas.addEventListener('pointercancel', stop);
  }

  function mirrorPose() {
    const swaps = [[2, 5], [3, 6], [4, 7], [8, 11], [9, 12], [10, 13], [14, 15], [16, 17]];
    state.points.forEach((point) => { if (point) point[0] = state.canvasWidth - point[0]; });
    swaps.forEach(([a, b]) => { const temp = state.points[a]; state.points[a] = state.points[b]; state.points[b] = temp; });
    drawEditor();
  }

  function loadReferenceImage(event) {
    const file = event.target.files?.[0];
    if (state.referenceObjectUrl) URL.revokeObjectURL(state.referenceObjectUrl);
    state.referenceObjectUrl = '';
    state.referenceImage = null;
    if (!file) { drawEditor(); return; }
    state.referenceObjectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => { state.referenceImage = image; drawEditor(); };
    image.onerror = () => showToastSafe('Could not load the reference image.');
    image.src = state.referenceObjectUrl;
  }

  function downloadEditorPose() {
    const link = document.createElement('a');
    link.href = renderPoseDataUrl();
    link.download = 'stableamd-openpose.png';
    document.body.append(link);
    link.click();
    link.remove();
  }

  function useEditorPose() {
    const dataUrl = renderPoseDataUrl();
    state.selectedPayload = dataUrlToPayload(dataUrl, 'stableamd-openpose-editor.png');
    state.selectedPreview = dataUrl;
    state.selectedLabel = 'Interactive pose editor';
    const file = document.querySelector('#controlnet-image');
    if (file) file.value = '';
    updateSelectedPreview();
    closeModal();
    showToastSafe('Edited pose selected as the OpenPose control map.');
  }

  function boot() {
    installStyles();
    installControlTools();
    createModal();
    document.addEventListener('stableamd:control-type-changed', syncToolsVisibility);
    document.addEventListener('stableamd:control-visibility-changed', syncToolsVisibility);
    document.querySelector('#controlnet-enabled')?.addEventListener('change', syncToolsVisibility);
    document.querySelector('#model-select')?.addEventListener('change', () => setTimeout(syncToolsVisibility, 0));
    updateSelectedPreview();
    window.StableAmdPose = {
      getControlImagePayload: async () => state.selectedPayload,
      clear: clearSelectedPose,
      hasSelection: () => Boolean(state.selectedPayload),
      selectedLabel: () => state.selectedLabel,
      sources: {
        poseDepot: { commit: POSE_DEPOT_SHA, license: 'Apache-2.0' },
        openPoseStudio: { commit: OPENPOSE_STUDIO_SHA, license: 'MIT' },
      },
    };
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();