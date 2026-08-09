(() => {
  const form = document.querySelector("[data-review-autosave]");
  if (!form) return;
  const state = form.querySelector("[data-save-state]");
  const sessionField = form.querySelector("[data-save-session]");
  const revisionField = form.querySelector("[data-save-revision]");
  const versionField = form.querySelector("[data-save-version]");
  const retry = form.querySelector("[data-save-retry]");
  const next = form.querySelector("[data-save-next]");
  let timer;
  let revision = 0;
  let savedRevision = 0;
  let saving = false;
  let failed = false;
  let savePromise = Promise.resolve(true);
  sessionField.value = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;

  const save = async () => {
    if (saving || savedRevision === revision) return savedRevision === revision;
    saving = true;
    const savingRevision = revision;
    revisionField.value = String(savingRevision);
    state.textContent = "Saving…";
    retry.hidden = true;
    try {
      const response = await fetch(form.action || window.location.href, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `Save failed (${response.status})`);
      savedRevision = payload.stale ? revision : savingRevision;
      versionField.value = String(payload.save_version ?? versionField.value);
      failed = false;
      const savedAt = new Intl.DateTimeFormat([], {
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date());
      state.textContent = `All changes saved · ${savedAt}`;
      return true;
    } catch (error) {
      failed = true;
      state.textContent = `Not saved — ${error.message} Your changes remain here.`;
      retry.hidden = false;
      return false;
    } finally {
      saving = false;
      if (!failed && savedRevision !== revision) savePromise = save();
    }
  };

  const flush = async () => {
    window.clearTimeout(timer);
    if (saving) await savePromise;
    if (savedRevision !== revision || failed) savePromise = save();
    return savePromise;
  };

  form.addEventListener("input", () => {
    revision += 1;
    revisionField.value = String(revision);
    failed = false;
    retry.hidden = true;
    state.textContent = "Unsaved";
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { savePromise = save(); }, 700);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await flush();
  });
  retry.addEventListener("click", () => { savePromise = save(); });
  if (next) next.addEventListener("click", async () => {
    if (await flush()) window.location.assign(next.dataset.nextUrl);
  });
  document.querySelectorAll("[data-review-nav]").forEach((link) => {
    link.addEventListener("click", async (event) => {
      if (savedRevision === revision) return;
      event.preventDefault();
      if (await flush()) window.location.assign(link.href);
    });
  });
  document.addEventListener("keydown", async (event) => {
    if (!event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key.toLowerCase() === "s") {
      event.preventDefault();
      await flush();
    }
    if (event.key.toLowerCase() === "n" && next) {
      event.preventDefault();
      if (await flush()) window.location.assign(next.dataset.nextUrl);
    }
  });
  window.addEventListener("beforeunload", () => {
    if (savedRevision === revision) return;
    revisionField.value = String(revision);
    navigator.sendBeacon(form.action || window.location.href, new FormData(form));
  });
  window.addEventListener("pagehide", () => {
    if (savedRevision !== revision) {
      revisionField.value = String(revision);
      navigator.sendBeacon(form.action || window.location.href, new FormData(form));
    }
  });
})();
