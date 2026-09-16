(() => {
  const baseApi = api;
  const POLL_INTERVAL_MS = 1000;

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function waitForGenerationJob(jobId) {
    const encoded = encodeURIComponent(jobId);
    for (;;) {
      const status = await baseApi(`/api/generation-jobs/${encoded}`);
      const state = String(status?.status || "").toLowerCase();
      if (state === "completed") {
        return baseApi(`/api/generation-jobs/${encoded}/result`);
      }
      if (state === "failed") {
        throw new Error(status?.error || "Generation failed.");
      }
      if (state !== "queued" && state !== "running") {
        throw new Error(`Generation job entered an unknown state: ${state || "missing"}.`);
      }
      await sleep(POLL_INTERVAL_MS);
    }
  }

  api = async function generationJobApi(path, options = {}) {
    if (path === "/api/generate" && String(options?.method || "GET").toUpperCase() === "POST") {
      let payload = {};
      try { payload = options.body ? JSON.parse(options.body) : {}; }
      catch { payload = {}; }
      payload.asyncJob = true;

      const submitted = await baseApi(path, { ...options, body: JSON.stringify(payload) });
      const jobId = String(submitted?.jobId || "");
      if (!jobId) return submitted;
      return waitForGenerationJob(jobId);
    }
    return baseApi(path, options);
  };
})();
