(() => {
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.async = false;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`Could not load ${src}`));
      document.head.append(script);
    });
  }

  loadScript('/app-generate-upscale-base.js')
    .then(() => loadScript('/app-pose-safe-frame.js'))
    .then(() => loadScript('/app-controlnet.js'))
    .then(() => loadScript('/app-pose-editor.js'))
    .catch((error) => {
      console.error('StableAMD late frontend extension failed:', error);
      if (typeof showToast === 'function') showToast(error.message || String(error));
    });
})();
