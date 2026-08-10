(() => {
  const rulesNode = document.querySelector("#speakerops-cfp-rules");
  const rules = rulesNode ? JSON.parse(rulesNode.textContent || "[]") : [];
  const firstController = rules.length
    ? document.querySelector(`[name="${rules[0].controllerName}"]`)
    : null;
  const form = firstController?.form
    || document.querySelector("#submission-steps + form, form[method='post']");
  if (!form) return;
  rules.forEach((rule) => {
    const controllerFields = [...document.querySelectorAll(`[name="${rule.controllerName}"]`)];
    const targetFields = [...form.querySelectorAll(`[name="${rule.targetName}"]`)];
    if (!controllerFields.length || !targetFields.length) return;
    const container = targetFields[0].closest(".form-group, fieldset, .mb-3") || targetFields[0].parentElement;
    if (!container) return;

    const updateVisibility = () => {
      const triggerOptions = rule.triggerOptions || [rule.triggerOption];
      const matches = controllerFields.some((field) => field.checked && triggerOptions.includes(field.value))
        || controllerFields.some((field) => field.tagName === "SELECT" && triggerOptions.includes(field.value));
      container.hidden = !matches;
      targetFields.forEach((field, index) => {
        // Pretalx upgrades enhanced selects with Choices.js. Initializing Choices
        // from a disabled select permanently locks its option list, even after the
        // native select is re-enabled. Keep that select enabled while hidden and
        // disable it immediately before submission instead.
        const enhancedSelect = field.matches("select.enhanced");
        field.disabled = !matches && !enhancedSelect;
        field.required = Boolean(matches && rule.targetRequired && index === 0);
      });
    };
    controllerFields.forEach((field) => field.addEventListener("change", updateVisibility));
    form.addEventListener("submit", () => {
      if (container.hidden) {
        targetFields.forEach((field) => { field.disabled = true; });
      }
    });
    updateVisibility();
  });

  if (form.querySelector("[data-speakerops-draft-state]")) return;
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
