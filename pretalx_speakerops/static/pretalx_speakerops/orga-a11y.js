(() => {
  const nameControl = (selector, fallback) => {
    const control = document.querySelector(selector);
    if (control && !control.getAttribute("aria-label")) {
      control.setAttribute("aria-label", fallback);
    }
  };

  nameControl("#sidebar-toggle", "Toggle organizer navigation");
  nameControl("#nav-search", "Switch event or organizer");

  document.querySelectorAll(".sidebar a.nav-link").forEach((link) => {
    if (link.getAttribute("aria-label")) return;
    const label = link.querySelector(".sidebar-text, span")?.textContent.trim();
    if (label) link.setAttribute("aria-label", label);
  });

  document.querySelectorAll(".sidebar a.arrow[aria-controls]").forEach((control) => {
    if (control.getAttribute("aria-label")) return;
    const section = control
      .closest(".has-children")
      ?.querySelector(".nav-link-inner .sidebar-text")
      ?.textContent.trim();
    control.setAttribute("aria-label", `Toggle ${section || "navigation section"}`);
  });
})();
