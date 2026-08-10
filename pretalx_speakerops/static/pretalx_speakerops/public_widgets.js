(() => {
  const root = document.querySelector("[data-public-widget]");
  if (!root) return;
  const eventKey = root.dataset.event;
  const cards = [...document.querySelectorAll("[data-filter-card]")];
  const query = document.querySelector("#widget-search");
  const track = document.querySelector("#widget-track");
  const room = document.querySelector("#widget-room");
  const status = document.querySelector("#widget-status");
  const selectedOnly = document.querySelector("#selected-only");
  const storageKey = `speakerops:${eventKey}:personal-schedule`;

  function selected() {
    try { return new Set(JSON.parse(localStorage.getItem(storageKey) || "[]")); }
    catch (_) { return new Set(); }
  }

  function updateExport(stars) {
    const link = document.querySelector("[data-calendar-export]");
    const count = document.querySelector("[data-selected-count]");
    if (count) count.textContent = String(stars.size);
    if (!link) return;
    const base = link.dataset.base;
    link.href = stars.size ? `${base}?sessions=${encodeURIComponent([...stars].join(","))}` : base;
    link.setAttribute("aria-disabled", String(!stars.size));
  }

  function syncStars() {
    const stars = selected();
    document.querySelectorAll("[data-star]").forEach((button) => {
      const active = stars.has(button.dataset.star);
      button.setAttribute("aria-pressed", String(active));
      button.textContent = active ? "★ In my schedule" : "☆ Add to my schedule";
      const card = button.closest("[data-filter-card]");
      if (root.dataset.widget === "itinerary") card.hidden = Boolean(selectedOnly?.checked && !active);
    });
    updateExport(stars);
  }

  function updateFilter() {
    const needle = (query?.value || "").trim().toLocaleLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      const matches =
        (!needle || card.dataset.search.includes(needle)) &&
        (!track?.value || card.dataset.track === track.value) &&
        (!room?.value || card.dataset.room === room.value);
      card.hidden = !matches;
      if (matches) visible += 1;
    });
    if (status) status.textContent = `${visible} result${visible === 1 ? "" : "s"}`;
  }

  if (track && root.dataset.selectedTrack) track.value = root.dataset.selectedTrack;

  document.querySelectorAll("[data-star]").forEach((button) => {
    button.addEventListener("click", () => {
      const stars = selected();
      if (stars.has(button.dataset.star)) stars.delete(button.dataset.star);
      else stars.add(button.dataset.star);
      localStorage.setItem(storageKey, JSON.stringify([...stars]));
      syncStars();
      if (root.dataset.widget !== "itinerary") updateFilter();
    });
  });
  [query, track, room].filter(Boolean).forEach((control) => {
    control.addEventListener(control === query ? "input" : "change", updateFilter);
  });
  const dayTabs = [...document.querySelectorAll("[data-day-tab]")];
  if (dayTabs.length) {
    const dayPanels = [...document.querySelectorAll("[data-day-panel]")];
    dayTabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        dayTabs.forEach((other) => other.setAttribute("aria-pressed", String(other === tab)));
        dayPanels.forEach((panel) => {
          panel.hidden = Boolean(tab.dataset.dayTab) && panel.dataset.dayPanel !== tab.dataset.dayTab;
        });
      });
    });
  }

  selectedOnly?.addEventListener("change", syncStars);
  syncStars();
  if (root.dataset.widget !== "itinerary") updateFilter();
})();
