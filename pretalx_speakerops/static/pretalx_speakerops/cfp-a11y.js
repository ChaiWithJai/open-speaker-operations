(() => {
  /* A draft must be savable before required proposal fields are complete. */
  document.querySelectorAll('button[name="action"][value="draft"]').forEach((button) => {
    button.formNoValidate = true;
  });

  document.querySelectorAll("details[role='menu']").forEach((details) => {
    details.removeAttribute("role");
    details.removeAttribute("aria-haspopup");
  });

  document.querySelectorAll(".markdown-nav[role='tablist']").forEach((tablist) => {
    /* The native widget is a radio group, not an ARIA tab implementation. */
    tablist.removeAttribute("role");
    tablist.querySelectorAll("input[role='tab']").forEach((input) => {
      input.removeAttribute("role");
      input.removeAttribute("aria-selected");
      input.removeAttribute("aria-controls");
    });
  });

  document.querySelectorAll("h5").forEach((heading) => {
    if (!heading.querySelector("form.add-speaker")) return;
    const replacement = document.createElement("div");
    replacement.className = heading.className;
    replacement.setAttribute("role", "heading");
    replacement.setAttribute("aria-level", "3");
    while (heading.firstChild) replacement.append(heading.firstChild);
    heading.replaceWith(replacement);
  });
  document.querySelectorAll("h4").forEach((heading) => {
    if (!/I already have an account|I need a new account/.test(heading.textContent)) return;
    heading.setAttribute("role", "heading");
    heading.setAttribute("aria-level", "3");
  });

  document.querySelectorAll("[role='progressbar']").forEach((bar) => {
    if (!bar.getAttribute("aria-label") && !bar.getAttribute("aria-labelledby")) {
      bar.setAttribute("aria-label", "Password strength");
    }
  });
  document.querySelectorAll("input.password_strength, .password_strength input").forEach((input) => {
    if (!input.labels?.length && !input.getAttribute("aria-label")) {
      input.setAttribute("aria-label", "New account password");
    }
  });

  /*
   * pretalx's schedule is a third-party web component. Keep the native view,
   * but repair the accessibility metadata it emits so the public fallback is
   * as trustworthy as the Speaker Operations widgets.
   */
  const enhanceSchedule = (host) => {
    const apply = () => {
      const root = host.shadowRoot;
      if (!root) return;

      root.querySelectorAll("[role='tab'][aria-controls]").forEach((tab) => {
        const controlled = tab.getAttribute("aria-controls");
        if (!controlled || !root.getElementById(controlled)) tab.removeAttribute("aria-controls");
      });
      root.querySelectorAll("button.btn-fav-container").forEach((button) => {
        if (button.getAttribute("aria-label")) return;
        const session = button.closest("a");
        const title = session?.querySelector(".title")?.textContent?.trim();
        button.setAttribute("aria-label", title ? `Add ${title} to favorites` : "Add session to favorites");
      });

      if (!root.getElementById("speakerops-native-schedule-a11y")) {
        const style = document.createElement("style");
        style.id = "speakerops-native-schedule-a11y";
        style.textContent = `
          .timezone-label { color: #5f5f5f !important; }
          .time-box .duration { color: #ffffff !important; }
        `;
        root.append(style);
      }
    };

    apply();
    const observer = new MutationObserver(apply);
    if (host.shadowRoot) observer.observe(host.shadowRoot, { childList: true, subtree: true });
    else {
      const rootObserver = new MutationObserver(() => {
        if (!host.shadowRoot) return;
        rootObserver.disconnect();
        apply();
        observer.observe(host.shadowRoot, { childList: true, subtree: true });
      });
      rootObserver.observe(host, { childList: true });
    }
  };
  customElements.whenDefined("pretalx-schedule").then(() => {
    document.querySelectorAll("pretalx-schedule").forEach(enhanceSchedule);
  });
})();
