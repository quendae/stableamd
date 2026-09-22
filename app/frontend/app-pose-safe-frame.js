(() => {
  const POSE_SAFE_FRAME_FRACTION = 0.82;
  const POSE_SAFE_FRAME_MAX_SIDE = 1024;
  const POSE_CONTENT_THRESHOLD = 8;
  const SAFE_FRAME_HINT = 'Built-in templates and editor poses are safe-frame fitted to the selected generation aspect ratio before provider-specific control scaling.';

  function clampDimension(value, fallback) {
    const numeric = Math.round(Number(value));
    return Number.isFinite(numeric) && numeric >= 64 ? numeric : fallback;
  }

  function poseTargetSize(width, height) {
    const requestedWidth = clampDimension(width, 1024);
    const requestedHeight = clampDimension(height, 1024);
    const scale = Math.min(1, POSE_SAFE_FRAME_MAX_SIDE / Math.max(requestedWidth, requestedHeight));
    return {
      width: Math.max(64, Math.round(requestedWidth * scale)),
      height: Math.max(64, Math.round(requestedHeight * scale)),
    };
  }

  function shouldAutoFitOpenPosePayload(payload) {
    const name = String(payload?.name || '').replace(/\\/g, '/').split('/').pop().toLowerCase();
    return name.endsWith('-openposefull.png') || name === 'stableamd-openpose-editor.png';
  }

  function payloadDataUrl(payload) {
    const mimeType = String(payload?.mimeType || 'image/png');
    const data = String(payload?.dataBase64 || '');
    if (!data) throw new Error('OpenPose control image is empty.');
    return `data:${mimeType};base64,${data}`;
  }

  function loadPayloadImage(payload) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error('Could not decode the OpenPose control image.'));
      image.src = payloadDataUrl(payload);
    });
  }

  function dataUrlToPayload(dataUrl, originalName) {
    const comma = String(dataUrl || '').indexOf(',');
    if (comma < 0) throw new Error('Could not encode the safe-frame OpenPose image.');
    const stem = String(originalName || 'openpose-map').replace(/\.[^.]+$/, '');
    return {
      name: `${stem}-safe-frame.png`,
      mimeType: 'image/png',
      dataBase64: dataUrl.slice(comma + 1),
    };
  }

  function findPoseContentBounds(ctx, width, height) {
    const pixels = ctx.getImageData(0, 0, width, height).data;
    let minX = width;
    let minY = height;
    let maxX = -1;
    let maxY = -1;

    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const offset = (y * width + x) * 4;
        if (pixels[offset + 3] === 0) continue;
        const brightest = Math.max(pixels[offset], pixels[offset + 1], pixels[offset + 2]);
        if (brightest <= POSE_CONTENT_THRESHOLD) continue;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }

    if (maxX < minX || maxY < minY) return null;
    const padding = Math.max(2, Math.round(Math.max(maxX - minX + 1, maxY - minY + 1) * 0.01));
    minX = Math.max(0, minX - padding);
    minY = Math.max(0, minY - padding);
    maxX = Math.min(width - 1, maxX + padding);
    maxY = Math.min(height - 1, maxY + padding);
    return {
      x: minX,
      y: minY,
      width: maxX - minX + 1,
      height: maxY - minY + 1,
    };
  }

  async function fitOpenPosePayloadToFrame(payload, requestedWidth, requestedHeight) {
    const image = await loadPayloadImage(payload);
    const source = document.createElement('canvas');
    source.width = Math.max(1, image.naturalWidth || image.width || 1);
    source.height = Math.max(1, image.naturalHeight || image.height || 1);
    const sourceContext = source.getContext('2d', { willReadFrequently: true });
    sourceContext.fillStyle = '#000';
    sourceContext.fillRect(0, 0, source.width, source.height);
    sourceContext.drawImage(image, 0, 0, source.width, source.height);

    const bounds = findPoseContentBounds(sourceContext, source.width, source.height);
    if (!bounds) return payload;

    const target = poseTargetSize(requestedWidth, requestedHeight);
    const canvas = document.createElement('canvas');
    canvas.width = target.width;
    canvas.height = target.height;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.imageSmoothingEnabled = false;

    const maxWidth = canvas.width * POSE_SAFE_FRAME_FRACTION;
    const maxHeight = canvas.height * POSE_SAFE_FRAME_FRACTION;
    const scale = Math.min(maxWidth / bounds.width, maxHeight / bounds.height);
    const drawWidth = Math.max(1, bounds.width * scale);
    const drawHeight = Math.max(1, bounds.height * scale);
    const drawX = (canvas.width - drawWidth) / 2;
    const drawY = (canvas.height - drawHeight) / 2;

    ctx.drawImage(
      source,
      bounds.x,
      bounds.y,
      bounds.width,
      bounds.height,
      drawX,
      drawY,
      drawWidth,
      drawHeight,
    );

    return dataUrlToPayload(canvas.toDataURL('image/png'), payload?.name);
  }

  function syncSafeFrameHint() {
    const type = document.querySelector('#controlnet-type');
    const hint = document.querySelector('#controlnet-image-hint');
    if (!hint || type?.value !== 'openpose') return;
    if (!hint.textContent.includes('safe-frame fitted')) {
      hint.textContent = `${hint.textContent} ${SAFE_FRAME_HINT}`.trim();
    }
  }

  function installApiWrapper() {
    if (window.__stableAmdPoseSafeFrameApiWrapped) return;
    window.__stableAmdPoseSafeFrameApiWrapped = true;
    const previousApi = api;
    api = async function poseSafeFrameApi(path, options = {}) {
      if (path === '/api/generate' && String(options.method || 'GET').toUpperCase() === 'POST') {
        const request = JSON.parse(options.body || '{}');
        const control = request?.control;
        if (
          control?.enabled !== false
          && control?.type === 'openpose'
          && control?.image?.dataBase64
          && shouldAutoFitOpenPosePayload(control.image)
        ) {
          const fitted = await fitOpenPosePayloadToFrame(
            control.image,
            request.width || 1024,
            request.height || 1024,
          );
          request.control = { ...control, image: fitted };
          options = { ...options, body: JSON.stringify(request) };
        }
      }
      return previousApi(path, options);
    };
  }

  function boot() {
    installApiWrapper();
    document.addEventListener('stableamd:control-visibility-changed', syncSafeFrameHint);
    document.addEventListener('stableamd:control-type-changed', syncSafeFrameHint);
    window.StableAmdPoseSafeFrame = {
      fitOpenPosePayloadToFrame,
      findPoseContentBounds,
      poseTargetSize,
      shouldAutoFitOpenPosePayload,
      fraction: POSE_SAFE_FRAME_FRACTION,
    };
  }

  boot();
})();
