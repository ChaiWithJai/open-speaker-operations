(() => {
  const form = document.querySelector("[data-review-autosave]");
  if (!form) return;
  const state = form.querySelector("[data-save-state]");
  let timer;
  let revision = 0;
  let savedRevision = 0;
  let saving = false;

  const save = async () => {
    if (saving || savedRevision === revision) return;
    saving = true;
    const savingRevision = revision;
    state.textContent = "Saving…";
    try {
      const response = await fetch(form.action || window.location.href, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error(`Save failed (${response.status})`);
      savedRevision = savingRevision;
      const savedAt = new Intl.DateTimeFormat([], {
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date());
      state.textContent = `All changes saved · ${savedAt}`;
    } catch (error) {
      state.textContent = "Not saved — use Save review";
    } finally {
      saving = false;
      if (savedRevision !== revision) save();
    }
  };

  form.addEventListener("input", () => {
    revision += 1;
    state.textContent = "Unsaved";
    window.clearTimeout(timer);
    timer = window.setTimeout(save, 700);
  });
})();
