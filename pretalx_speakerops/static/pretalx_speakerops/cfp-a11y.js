(() => {
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
})();
