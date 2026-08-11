(() => {
  const root = document.querySelector("[data-public-widget]");
  if (!root) return;
  const eventKey = root.dataset.event;
  const cards = [...document.querySelectorAll("[data-filter-card]")];
  const query = document.querySelector("#widget-search");
  const track = document.querySelector("#widget-track");
  const format = document.querySelector("#widget-format");
  const room = document.querySelector("#widget-room");
  const status = document.querySelector("#widget-status");
  const selectedOnly = document.querySelector("#selected-only");
  const dayTabs = [...document.querySelectorAll("[data-day-tab]")];
  const dayPanels = [...document.querySelectorAll("[data-day-panel]")];
  const speakerDetailLinks = [...document.querySelectorAll("[data-speaker-detail]")];
  const currentDay = document.querySelector("[data-current-day]");
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
        (!format?.value || card.dataset.format === format.value) &&
        (!room?.value || card.dataset.room === room.value);
      card.hidden = !matches;
      if (matches) visible += 1;
    });
    if (status) status.textContent = `${visible} result${visible === 1 ? "" : "s"}`;
    if (query) {
      const search = query.value.trim();
      const currentUrl = new URL(window.location.href);
      if (search) currentUrl.searchParams.set("q", search);
      else currentUrl.searchParams.delete("q");
      window.history.replaceState({}, "", currentUrl);
      if (["speakers", "gallery"].includes(root.dataset.widget)) {
        speakerDetailLinks.forEach((link) => {
          const detailUrl = new URL(link.href);
          if (search) detailUrl.searchParams.set("q", search);
          else detailUrl.searchParams.delete("q");
          link.href = detailUrl;
        });
      }
    }
  }

  function activateDay(tab, updateUrl = true) {
    const selectedDay = tab.dataset.dayTab;
    dayTabs.forEach((candidate) => {
      const active = candidate === tab;
      candidate.setAttribute("aria-selected", String(active));
      candidate.tabIndex = active ? 0 : -1;
    });
    dayPanels.forEach((panel) => {
      panel.hidden = selectedDay !== "all" && panel.dataset.dayPanel !== selectedDay;
    });
    if (currentDay) {
      currentDay.textContent = selectedDay === "all" ? "Showing all event days" : `Showing ${tab.textContent.trim()}`;
    }
    if (updateUrl) {
      const url = new URL(window.location.href);
      if (selectedDay === "all") url.searchParams.delete("day");
      else url.searchParams.set("day", selectedDay);
      window.history.replaceState({}, "", url);
    }
  }

  document.querySelectorAll("[data-avatar]").forEach((avatar) => {
    const showFallback = () => {
      avatar.hidden = true;
      const fallback = avatar.parentElement.querySelector("[data-avatar-fallback]");
      if (fallback) fallback.hidden = false;
    };
    avatar.addEventListener("error", showFallback, { once: true });
    if (avatar.complete && avatar.naturalWidth === 0) showFallback();
  });

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
  [query, track, format, room].filter(Boolean).forEach((control) => {
    control.addEventListener(control === query ? "input" : "change", updateFilter);
  });
  selectedOnly?.addEventListener("change", syncStars);
  dayTabs.forEach((tab, index) => {
    tab.addEventListener("click", (event) => {
      event.preventDefault();
      activateDay(tab);
    });
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const offset = event.key === "ArrowRight" ? 1 : -1;
      const next = dayTabs[(index + offset + dayTabs.length) % dayTabs.length];
      next.click();
      next.focus();
    });
  });
  const initialDay = dayTabs.find((tab) => tab.dataset.dayTab === root.dataset.selectedDay) || dayTabs[0];
  if (initialDay) activateDay(initialDay, false);
  syncStars();
  if (root.dataset.widget !== "itinerary") updateFilter();
})();
