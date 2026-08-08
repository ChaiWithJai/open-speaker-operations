(() => {
  const form = document.querySelector("[data-review-autosave]");
  if (!form) return;
  const state = form.querySelector("[data-save-state]");
  let timer;

  const save = async () => {
    state.textContent = "Saving…";
    try {
      const response = await fetch(form.action || window.location.href, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error(`Save failed (${response.status})`);
      state.textContent = "Saved";
    } catch (error) {
      state.textContent = "Not saved — use Save review";
    }
  };

  form.addEventListener("input", () => {
    state.textContent = "Unsaved";
    window.clearTimeout(timer);
    timer = window.setTimeout(save, 700);
  });
})();
