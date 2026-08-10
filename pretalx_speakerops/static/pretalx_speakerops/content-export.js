document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-content-export]").forEach((form) => {
    form.addEventListener("submit", () => {
      const status = form.querySelector("[data-export-status]");
      const selected = document.querySelectorAll(
        `input[form="${form.id}"][name="tasks"]:checked`,
      ).length;
      if (status && selected) {
        status.textContent = `Generating latest-version ZIP for ${selected} selected deliverable${selected === 1 ? "" : "s"}. Your download will start when ready.`;
      }
    });
  });
});
