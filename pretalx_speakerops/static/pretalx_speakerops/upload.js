(() => {
  document.querySelectorAll("[data-upload-form]").forEach((form) => {
    const input = form.querySelector("input[type='file']");
    const summary = form.querySelector("[data-upload-summary]");
    const name = form.querySelector("[data-upload-name]");
    const size = form.querySelector("[data-upload-size]");
    const progress = form.querySelector("[data-upload-progress]");
    const state = form.querySelector("[data-upload-state]");
    const cancel = form.querySelector("[data-upload-cancel]");
    const retry = form.querySelector("[data-upload-retry]");
    const submit = form.querySelector("button[type='submit'], button:not([type])");
    let request;

    const describeFile = () => {
      const file = input.files[0];
      summary.hidden = !file;
      if (!file) return;
      name.textContent = file.name;
      size.textContent = `· ${(file.size / 1_000_000).toFixed(2)} MB`;
      progress.value = 0;
      state.textContent = "Ready to upload. Choose Submit when you are ready.";
      retry.hidden = true;
    };

    const send = () => {
      if (!input.files.length) return;
      request = new XMLHttpRequest();
      request.open("POST", form.action);
      request.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      submit.disabled = true;
      retry.hidden = true;
      state.textContent = "Uploading… You can cancel without losing your checklist.";
      request.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) progress.value = Math.round((event.loaded / event.total) * 100);
      });
      request.addEventListener("load", () => {
        submit.disabled = false;
        let payload = {};
        try { payload = JSON.parse(request.responseText); } catch (_error) { /* handled below */ }
        if (request.status >= 200 && request.status < 300 && payload.saved) {
          progress.value = 100;
          state.textContent = `Uploaded ${payload.filename}. Returning to your updated checklist…`;
          window.location.assign(payload.redirect);
          return;
        }
        state.textContent = payload.error || "Upload failed. Your selection is preserved; retry when ready.";
        retry.hidden = false;
      });
      request.addEventListener("error", () => {
        submit.disabled = false;
        state.textContent = "The network interrupted the upload. Your selection is preserved; retry when ready.";
        retry.hidden = false;
      });
      request.addEventListener("abort", () => {
        submit.disabled = false;
        state.textContent = "Upload canceled. Select a replacement or submit this file again.";
        retry.hidden = false;
      });
      request.send(new FormData(form));
    };

    input.addEventListener("change", describeFile);
    cancel.addEventListener("click", () => {
      if (request && request.readyState !== XMLHttpRequest.DONE) request.abort();
      input.value = "";
      summary.hidden = true;
      input.focus();
    });
    retry.addEventListener("click", send);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      send();
    });
  });
})();
