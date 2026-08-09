(() => {
  const nameControl = (selector, fallback) => {
    const control = document.querySelector(selector);
    if (control && !control.getAttribute("aria-label")) {
      control.setAttribute("aria-label", fallback);
    }
  };

  nameControl("#sidebar-toggle", "Toggle organizer navigation");
  nameControl("#nav-search", "Switch event or organizer");

  document.querySelectorAll("[aria-expand]").forEach((element) => {
    element.removeAttribute("aria-expand");
  });
  document.querySelectorAll("details[role='menu']").forEach((element) => {
    element.removeAttribute("role");
    element.removeAttribute("aria-haspopup");
  });

  document.querySelectorAll(".sidebar a.nav-link").forEach((link) => {
    if (link.getAttribute("aria-label")) return;
    const label = link.querySelector(".sidebar-text, span")?.textContent.trim();
    if (label) link.setAttribute("aria-label", label);
  });

  document.querySelectorAll(".sidebar a.arrow[aria-controls]").forEach((control) => {
    const target = control.getAttribute("data-target")?.replace(/^#/, "");
    if (target) {
      control.setAttribute("aria-controls", target);
      control.setAttribute("href", `#${target}`);
    }
    const section = control
      .closest(".has-children")
      ?.querySelector(".nav-link-inner .sidebar-text")
      ?.textContent.trim();
    if (!control.getAttribute("aria-label")) {
      control.setAttribute("aria-label", `Toggle ${section || "navigation section"}`);
    }
  });

  document.querySelectorAll("input:not([type='hidden'])").forEach((control) => {
    if (control.labels?.length || control.getAttribute("aria-label") || control.getAttribute("aria-labelledby")) return;
    const label = control.getAttribute("placeholder")
      || (control.type === "search" ? "Filter options" : "Form field");
    control.setAttribute("aria-label", label);
  });
})();
