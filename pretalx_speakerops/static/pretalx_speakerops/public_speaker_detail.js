(() => {
  document.querySelectorAll("[data-avatar]").forEach((avatar) => {
    avatar.addEventListener("error", () => {
      avatar.hidden = true;
      const fallback = avatar.parentElement.querySelector("[data-avatar-fallback]");
      if (fallback) fallback.hidden = false;
    }, { once: true });
  });
  const biography = document.querySelector("[data-biography]");
  const toggle = document.querySelector("[data-biography-toggle]");
  if (!biography || !toggle) return;

  biography.dataset.collapsed = "true";
  toggle.hidden = false;
  toggle.addEventListener("click", () => {
    const expanded = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", String(!expanded));
    biography.dataset.collapsed = String(expanded);
    toggle.textContent = expanded ? "Show more biography" : "Show less biography";
  });
})();
