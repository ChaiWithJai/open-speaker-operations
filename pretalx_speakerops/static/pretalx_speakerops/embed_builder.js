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
    if (form.elements.q.value.trim()) url.searchParams.set("q", form.elements.q.value.trim());
    if (form.elements.track.value) url.searchParams.set("track", form.elements.track.value);
    if (form.elements.session_format.value) url.searchParams.set("format", form.elements.session_format.value);
    if (form.elements.room.value) url.searchParams.set("room", form.elements.room.value);
    const format = form.elements.format.value;
    const exportPath = format === "json" ? form.dataset.json : format === "xml" ? form.dataset.xml : format === "ical" ? form.dataset.ical : "";
    const outputUrl = exportPath ? new URL(exportPath, window.location.origin) : url;
    preview.src = url.toString();
    share.href = outputUrl.toString();
    const title = `${widget[0].toUpperCase()}${widget.slice(1)} for ${form.dataset.eventName}`;
    if (format === "iframe") snippet.value = `<iframe src="${url}" title="${title}" loading="lazy" width="100%" height="720"></iframe>`;
    else if (format === "link") snippet.value = `<a href="${url}">${title}</a>`;
    else snippet.value = outputUrl.toString();
  }
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  document.querySelector("#copy-snippet").addEventListener("click", async () => {
    await navigator.clipboard.writeText(snippet.value);
    document.querySelector("#copy-status").textContent = "Snippet copied.";
  });
  update();
})();
