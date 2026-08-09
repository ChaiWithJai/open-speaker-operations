(() => {
  const form = document.querySelector("[data-embed-builder]");
  if (!form) return;
  const preview = document.querySelector("#embed-preview");
  const snippet = document.querySelector("#embed-snippet");
  const share = document.querySelector("#embed-share");
  function update() {
    const widget = form.elements.widget.value;
    const url = new URL(form.dataset.base.replace("__widget__", widget), window.location.origin);
    url.searchParams.set("theme", form.elements.theme.value);
    url.searchParams.set("fields", form.elements.fields.value);
    if (form.elements.track.value) url.searchParams.set("track", form.elements.track.value);
    preview.src = url.toString();
    share.href = url.toString();
    const title = `${widget[0].toUpperCase()}${widget.slice(1)} for ${form.dataset.eventName}`;
    snippet.value = form.elements.format.value === "link"
      ? `<a href="${url}">${title}</a>`
      : `<iframe src="${url}" title="${title}" loading="lazy" width="100%" height="720"></iframe>`;
  }
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  document.querySelector("#copy-snippet").addEventListener("click", async () => {
    await navigator.clipboard.writeText(snippet.value);
    document.querySelector("#copy-status").textContent = "Snippet copied.";
  });
  update();
})();
