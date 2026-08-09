(() => {
  const buttons = [...document.querySelectorAll("[data-view-button]")];
  const views = [...document.querySelectorAll("[data-view]")];
  const track = document.querySelector("#track-filter");
  const room = document.querySelector("#room-filter");
  const day = document.querySelector("#day-filter");
  const dayControl = document.querySelector("[data-day-control]");
  const status = document.querySelector("#schedule-status");
  let activeView = "list";

  function update() {
    views.forEach((view) => {
      view.hidden = view.dataset.view !== activeView;
    });
    buttons.forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.viewButton === activeView),
      );
    });
    dayControl.hidden = activeView !== "day";
    document.querySelectorAll("[data-day-section]").forEach((section) => {
      section.hidden =
        activeView === "day" && section.dataset.daySection !== day.value;
    });
    let visible = 0;
    document
      .querySelectorAll(`[data-view="${activeView}"] [data-session]`)
      .forEach((card) => {
        const matchesDay = activeView !== "day" || card.dataset.day === day.value;
        const matches =
          matchesDay &&
          (!track.value || card.dataset.track === track.value) &&
          (!room.value || card.dataset.room === room.value);
        card.hidden = !matches;
        if (matches) visible += 1;
      });
    status.textContent = `Showing ${visible} session${visible === 1 ? "" : "s"} in ${activeView} view.`;
  }

  buttons.forEach((button) =>
    button.addEventListener("click", () => {
      activeView = button.dataset.viewButton;
      update();
    }),
  );
  [track, room, day].forEach((control) =>
    control.addEventListener("change", update),
  );
  update();
})();
