(() => {
  const form = document.querySelector("#submission-steps + form, form[method='post']");
  if (!form || form.querySelector("[data-speakerops-draft-state]")) return;
  const heading = form.querySelector("h2");
  if (!heading) return;

  const status = document.createElement("span");
  status.className = "speakerops-cfp-state";
  status.dataset.speakeropsDraftState = "";
  status.setAttribute("aria-live", "polite");
  status.textContent = "Draft changes not saved";
  heading.parentElement.append(status);

  form.addEventListener("input", () => { status.textContent = "Draft changes not saved"; });
  form.addEventListener("submit", () => { status.textContent = "Saving…"; });
})();
