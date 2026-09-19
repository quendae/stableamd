(() => {
  const DEPENDENCY_ID = 'dwpose-openpose';

  function showMessage(message, kind = 'success') {
    if (typeof showToast === 'function') showToast(message, kind);
    else console.log(message);
  }

  function readFilePayload(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Could not read the pose source photo.'));
      reader.onload = () => {
        const value = String(reader.result || '');
        const comma = value.indexOf(',');
        if (comma < 0) return reject(new Error('Pose source photo encoding failed.'));
        resolve({
          name: file.name,
          mimeType: file.type || 'application/octet-stream',
          dataBase64: value.slice(comma + 1),
        });
      };
      reader.readAsDataURL(file);
    });
  }

  function payloadToFile(payload) {
    const binary = atob(String(payload?.dataBase64 || ''));
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return new File(
      [bytes],
      'stableamd-openpose-extracted.png',
      { type: payload?.mimeType || 'image/png' },
    );
  }

  async function dependencyStatus() {
    const payload = await api('/api/controlnet/dependencies');
    return (payload?.dependencies || []).find((item) => String(item?.id || '') === DEPENDENCY_ID) || null;
  }

  async function ensureDependency(button, status) {
    let dependency = await dependencyStatus();
    if (dependency?.ready) return dependency;
    if (!dependency?.installable) {
      throw new Error('The managed DWPose photo extractor is not available for installation.');
    }

    if (status) status.textContent = 'Installing DWPose extractor…';
    if (button) button.textContent = 'Installing DWPose…';
    const result = await api('/api/controlnet/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: DEPENDENCY_ID }),
    });
    if (result?.restartRequired) {
      if (status) status.textContent = 'Restarting backend…';
      await api('/api/backend/restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
    }
    dependency = await dependencyStatus();
    if (!dependency?.ready) throw new Error('DWPose installed, but the preprocessor is not ready yet.');
    return dependency;
  }

  function applyExtractedPose(payload, peopleDetected) {
    const controlInput = document.querySelector('#controlnet-image');
    if (!controlInput) throw new Error('OpenPose control input is not available.');
    const file = payloadToFile(payload);
    const transfer = new DataTransfer();
    transfer.items.add(file);
    controlInput.files = transfer.files;
    controlInput.dispatchEvent(new Event('change', { bubbles: true }));

    const preview = document.querySelector('#pose-selected-preview');
    if (preview) {
      preview.src = `data:${payload?.mimeType || 'image/png'};base64,${payload?.dataBase64 || ''}`;
      preview.alt = 'DWPose extracted OpenPose control map';
      preview.hidden = false;
    }
    const status = document.querySelector('#pose-control-status');
    if (status) {
      const noun = Number(peopleDetected) === 1 ? 'person' : 'people';
      status.textContent = `DWPose extracted ${peopleDetected} ${noun} · body + hands + face`;
    }
  }

  async function extractFromPhoto(file, button) {
    const status = document.querySelector('#pose-control-status');
    const oldText = button.textContent;
    button.disabled = true;
    try {
      await ensureDependency(button, status);
      button.textContent = 'Extracting…';
      if (status) status.textContent = 'Extracting all people with DWPose…';
      const source = await readFilePayload(file);
      const result = await api('/api/controlnet/preprocess/openpose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: source }),
      });
      if (!result?.image?.dataBase64) throw new Error('DWPose did not return an OpenPose map.');
      const peopleDetected = Number(result.peopleDetected || 0);
      if (peopleDetected < 1) throw new Error('DWPose did not find a usable person in this photo.');
      applyExtractedPose(result.image, peopleDetected);
      showMessage(`OpenPose extracted from photo: ${peopleDetected} ${peopleDetected === 1 ? 'person' : 'people'}.`);
    } catch (error) {
      if (status) status.textContent = error?.message || String(error);
      showMessage(error?.message || String(error), 'error');
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  function installExtractorUi() {
    if (document.querySelector('#pose-extract-photo')) return;
    const tools = document.querySelector('#pose-control-tools');
    if (!tools) return;

    const button = document.createElement('button');
    button.id = 'pose-extract-photo';
    button.type = 'button';
    button.className = 'button button-secondary';
    button.textContent = 'Extract from photo';

    const input = document.createElement('input');
    input.id = 'pose-extract-photo-file';
    input.type = 'file';
    input.accept = 'image/png,image/jpeg,image/webp';
    input.hidden = true;

    const clear = tools.querySelector('#pose-clear-selection');
    if (clear) clear.before(button, input);
    else tools.prepend(button, input);

    button.addEventListener('click', () => {
      input.value = '';
      input.click();
    });
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      if (file) void extractFromPhoto(file, button);
    });
  }

  function boot() {
    installExtractorUi();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
