async (page) => {
  const baseUrl = __BASE_URL__;
  const artifactDir = __ARTIFACT_DIR__;
  const axePath = __AXE_PATH__;
  const pdfFixture = __PDF_FIXTURE__;
  const viewport = __VIEWPORT__;
  const report = {
    started_at: new Date().toISOString(),
    base_url: baseUrl,
    viewport,
    stages: [],
    console_errors: [],
    request_failures: [],
    http_errors: [],
    accessibility: [],
    proofs: {},
    failures: [],
  };
  const expectedRequestFailures = new Set();
  const expectedHttpErrors = new Map();
  let expectedNetworkConsoleErrors = 0;
  let expectedHttpConsoleErrors = 0;

  await page.setViewportSize(viewport);
  page.on("console", (message) => {
    if (expectedHttpConsoleErrors && message.text().includes("status of 400")) {
      expectedHttpConsoleErrors -= 1;
      return;
    }
    if (expectedNetworkConsoleErrors && message.text().includes("Failed to load resource: net::ERR_FAILED")) {
      expectedNetworkConsoleErrors -= 1;
      return;
    }
    if (message.type() === "error") report.console_errors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    if (expectedRequestFailures.delete(request.url())) return;
    report.request_failures.push({ url: request.url(), error: request.failure()?.errorText });
  });
  page.on("response", (response) => {
    if (response.status() >= 400 && response.url().startsWith(baseUrl)) {
      const remaining = expectedHttpErrors.get(response.url()) || 0;
      if (remaining) {
        if (remaining === 1) expectedHttpErrors.delete(response.url());
        else expectedHttpErrors.set(response.url(), remaining - 1);
        return;
      }
      report.http_errors.push({ url: response.url(), status: response.status() });
    }
  });
  await page.addInitScript({ path: axePath });

  const check = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const slug = (value) => value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  const bodyText = () => page.locator("body").innerText();
  const tabTo = async (predicate, limit = 60, reset = true) => {
    if (reset) await page.evaluate(() => document.activeElement?.blur());
    for (let index = 0; index < limit; index += 1) {
      await page.keyboard.press("Tab");
      const active = await page.evaluate(() => ({
        text: (document.activeElement?.innerText || document.activeElement?.getAttribute("aria-label") || "").trim(),
        href: document.activeElement?.href || "",
      }));
      if (predicate(active)) return active;
    }
    throw new Error(`Keyboard traversal did not reach its target within ${limit} Tab presses`);
  };
  const goto = async (path) => {
    const response = await page.goto(`${baseUrl}${path}`, { waitUntil: "domcontentloaded" });
    check(response && response.status() < 400, `Navigation failed: ${path} (${response?.status()})`);
  };
  const login = async (email, organiser = false) => {
    await page.context().clearCookies();
    await goto(organiser ? "/orga/event/speakerops-demo/login/" : "/speakerops-demo/login/");
    await page.locator("[name=login_email]").fill(email);
    await page.locator("[name=login_password]").fill("speakerops-demo");
    const navigation = page.waitForNavigation({ waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await navigation;
  };
  const audit = async (name) => {
    const structure = await page.evaluate(() => {
      const visible = (element) => !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
      const controls = [...document.querySelectorAll("button, input:not([type=hidden]), select, textarea")].filter(visible);
      const unnamed = controls.filter((element) => {
        const idLabel = element.id && document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
        const wrapped = element.closest("label");
        const labels = element.labels?.length;
        const aria = element.getAttribute("aria-label") || element.getAttribute("aria-labelledby");
        const title = element.getAttribute("title");
        const text = element.tagName === "BUTTON" ? element.textContent.trim() : "";
        return !(idLabel || wrapped || labels || aria || title || text || element.getAttribute("aria-hidden") === "true");
      });
      return {
        main_count: document.querySelectorAll("main").length,
        unnamed_controls: unnamed.map((element) => `${element.tagName.toLowerCase()}#${element.id || "?"}[name=${element.getAttribute("name") || ""}]`),
        horizontal_overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth,
      };
    });
    if (structure.main_count !== 1) report.failures.push(`${name}: expected one main landmark, found ${structure.main_count}`);
    if (structure.unnamed_controls.length) report.failures.push(`${name}: unnamed controls: ${structure.unnamed_controls.join(", ")}`);
    if (structure.horizontal_overflow > 1) report.failures.push(`${name}: horizontal overflow ${structure.horizontal_overflow}px`);

    const axe = await page.evaluate(async () => {
      if (!window.axe) throw new Error("axe-core did not load before navigation");
      const result = await window.axe.run(document, { resultTypes: ["violations"] });
      return result.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        nodes: violation.nodes.map((node) => ({
          target: node.target,
          html: node.html,
          summary: node.failureSummary,
        })),
      }));
    });
    report.accessibility.push({ stage: name, url: page.url(), structure, axe });
    for (const violation of axe.filter((item) => ["critical", "serious"].includes(item.impact))) {
      report.failures.push(`${name}: ${violation.impact} axe violation ${violation.id} (${violation.nodes.length} nodes)`);
    }
  };
  const stage = async (name, action) => {
    const started = Date.now();
    try {
      await action();
      await audit(name);
      await page.screenshot({ path: `${artifactDir}/${slug(name)}.png`, fullPage: true });
      report.stages.push({ name, status: "passed", duration_ms: Date.now() - started, url: page.url() });
    } catch (error) {
      report.stages.push({ name, status: "failed", duration_ms: Date.now() - started, url: page.url(), error: String(error) });
      report.failures.push(`${name}: ${String(error)}`);
      await page.screenshot({ path: `${artifactDir}/${slug(name)}-failure.png`, fullPage: true }).catch(() => {});
    }
  };

  await stage("01-public-entry", async () => {
    await page.context().clearCookies();
    await goto("/speakerops-demo/");
    const releasedScheduleLink = page.getByRole("link", { name: "Browse the released schedule by list, day, or week" });
    check((await releasedScheduleLink.count()) === 1, "Public event landing does not expose the released schedule");
    await releasedScheduleLink.click();
    check(page.url().endsWith("/speaker-operations/embed/"), "Released schedule landing link reached the wrong surface");
    check((await page.locator('[data-view="list"] h2 a[href*="/speakerops-demo/talk/"]').count()) === 12, "Released schedule cards do not connect to all 12 native session details");
    report.proofs.released_schedule_discovery = { landing_link: true, session_detail_links: 12 };
    await goto("/speakerops-demo/cfp");
    check((await bodyText()).includes("Share your idea with DemoCon"), "CFP landing is missing its seeded headline");
    await goto("/speakerops-demo/speaker-operations/cfp-guide/");
    check((await bodyText()).includes("How to write a proposal"), "Public CFP guide is not reachable");
  });

  await stage("02-speaker-portal", async () => {
    await login("speaker@example.org");
    check(page.url().includes("/speaker-operations/checklist/"), "Speaker did not land on speaker tasks");

    const ordinaryTitle = "Browser proof: program reviewer routing";
    const vendorTitle = "Browser proof: systems reviewer routing";
    await goto("/speakerops-demo/submit/");
    await page.locator("input[name=title]").fill(ordinaryTitle);
    await page.locator("textarea[name=abstract]").fill("A detailed browser proof of the persisted ordinary CFP branch and its reviewer route.");
    await page.getByRole("button", { name: "Continue »" }).click();
    await page.waitForLoadState("domcontentloaded");
    check(page.url().includes("/questions/"), "Native speaker CFP did not reach additional questions");
    const ordinaryRelationship = page.getByLabel("No commercial relationship", { exact: true });
    const contextSelect = page.locator("select[name^=question_]").filter({ has: page.locator("option", { hasText: "Leadership program" }) });
    const contextState = () => contextSelect.evaluate((element) => {
      const container = element.closest(".form-group, fieldset, .mb-3") || element.parentElement;
      return { hidden: container.hidden, disabled: element.disabled, required: element.required };
    });
    check((await contextState()).hidden, "Conditional context question is visible before its trigger");
    await ordinaryRelationship.check();
    const ordinaryState = await contextState();
    check(ordinaryState.hidden && !ordinaryState.required, "Ordinary speaker branch did not keep the context question hidden and optional");
    await page.getByLabel("Program and leadership", { exact: true }).check();
    await page.getByLabel("Audience level", { exact: true }).selectOption({ label: "Intermediate" });
    await page.getByLabel("Key takeaway", { exact: true }).fill("Attendees leave with a repeatable evaluation workflow.");
    await page.locator("select[multiple]").filter({ has: page.locator("option", { hasText: "AI agents" }) }).evaluate((select) => {
      const option = [...select.options].find((item) => item.textContent.trim() === "AI agents");
      option.selected = true;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.getByLabel("Session abstract", { exact: true }).fill("A complete native browser submission routed to the program and leadership reviewer pool.");
    await page.screenshot({ path: `${artifactDir}/02a-speaker-cfp-ordinary-branch.png`, fullPage: true });
    await page.getByRole("button", { name: "Continue »" }).click();
    await page.waitForLoadState("domcontentloaded");
    check(page.url().includes("/profile/"), "Ordinary native proposal did not reach the profile step");
    await page.getByRole("button", { name: "Submit proposal! »" }).click();
    await page.waitForLoadState("domcontentloaded");
    check((await bodyText()).includes(ordinaryTitle), "Ordinary native proposal was not submitted");

    await goto("/speakerops-demo/submit/");
    await page.locator("input[name=title]").fill(vendorTitle);
    await page.locator("textarea[name=abstract]").fill("A detailed browser proof of the persisted vendor CFP branch and its reviewer route.");
    await page.getByLabel("Session type").selectOption({ label: "Workshop (90 minutes)" });
    await page.getByRole("button", { name: "Continue »" }).click();
    await page.waitForLoadState("domcontentloaded");
    check(page.url().includes("/questions/"), "Vendor native proposal did not reach additional questions");
    const vendorRelationshipSecond = page.getByLabel("I work for or represent a vendor discussed in this session", { exact: true });
    const contextSelectSecond = page.locator("select[name^=question_]").filter({ has: page.locator("option", { hasText: "Leadership program" }) });
    await vendorRelationshipSecond.check();
    await page.getByLabel("Systems and agents", { exact: true }).check();
    await page.getByLabel("Audience level", { exact: true }).selectOption({ label: "Advanced" });
    await page.getByLabel("Key takeaway", { exact: true }).fill("Attendees can operate a reliable agent system in production.");
    await page.getByLabel("Workshop prerequisites", { exact: true }).fill("Bring a laptop with Python and Docker installed.");
    await page.locator("select[multiple]").filter({ has: page.locator("option", { hasText: "Evals and observability" }) }).evaluate((select) => {
      const option = [...select.options].find((item) => item.textContent.trim() === "Evals and observability");
      option.selected = true;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const contextGroupSecond = contextSelectSecond.locator("xpath=ancestor::div[contains(@class, 'form-group')]");
    await contextGroupSecond.locator(".choices__inner").click();
    await contextGroupSecond.locator(".choices__item--choice", { hasText: "Workshop" }).click();
    await page.getByLabel("Session abstract", { exact: true }).fill("A complete native browser submission routed to the systems and agents reviewer pool.");
    const vendorState = await contextSelectSecond.evaluate((element) => {
      const container = element.closest(".form-group, fieldset, .mb-3") || element.parentElement;
      return { hidden: container.hidden, disabled: element.disabled, required: element.required };
    });
    check(!vendorState.hidden && !vendorState.disabled, "Vendor speaker branch did not reveal the context question");
    check(vendorState.required, "Vendor speaker branch did not require the revealed context question");
    await page.screenshot({ path: `${artifactDir}/02b-speaker-cfp-vendor-branch.png`, fullPage: true });
    await page.getByRole("button", { name: "Continue »" }).click();
    await page.waitForLoadState("domcontentloaded");
    check(page.url().includes("/profile/"), "Vendor native proposal did not reach the profile step");
    await page.getByRole("button", { name: "Submit proposal! »" }).click();
    await page.waitForLoadState("domcontentloaded");
    const submittedProposals = await bodyText();
    check(submittedProposals.includes(ordinaryTitle) && submittedProposals.includes(vendorTitle), "Both native reviewer-routing proposals were not submitted");
    report.proofs.conditional_cfp = {
      ordinary_hidden: true,
      vendor_visible_required: true,
      ordinary_title: ordinaryTitle,
      vendor_title: vendorTitle,
      native_submissions_completed: true,
    };
    await goto("/speakerops-demo/speaker-operations/checklist/");

    check((await bodyText()).includes("What do I need to do next?"), "Speaker checklist is missing");
    const biography = page.locator("textarea[name=response]").first();
    if (await biography.count()) {
      await biography.fill("Maya Chen builds calm, accountable systems for high-stakes program teams.");
      await page.getByRole("button", { name: "Save biography and complete" }).click();
      await page.waitForLoadState("domcontentloaded");
      check((await bodyText()).includes("Completed work"), "Onboarding completion did not return to the checklist");
    }
    const uploadForm = page.locator("form[data-upload-form]").first();
    check(await uploadForm.count(), "Seeded speaker checklist is missing a PDF upload task");
    const upload = uploadForm.locator("input[type=file][accept*='application/pdf']");
    const uploadAction = await uploadForm.getAttribute("action");
    const uploadUrl = uploadAction.startsWith("http") ? uploadAction : `${baseUrl}${uploadAction}`;
    const uploadState = page.locator("[data-upload-state]").first();
    const setSyntheticFile = (spec) => upload.evaluate((input, fileSpec) => {
      const bytes = new Uint8Array(fileSpec.size);
      if (fileSpec.pdfHeader) bytes.set([37, 80, 68, 70, 45, 49, 46, 55, 10]);
      else bytes.set([110, 111, 116, 32, 97, 32, 80, 68, 70]);
      const transfer = new DataTransfer();
      transfer.items.add(new File([bytes], fileSpec.name, { type: fileSpec.mimeType }));
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }, spec);

    expectedHttpErrors.set(uploadUrl, 2);
    expectedHttpConsoleErrors += 2;
    await setSyntheticFile({ name: "wrong-content.pdf", mimeType: "text/plain", size: 9, pdfHeader: false });
    await page.getByRole("button", { name: "Submit upload slides", exact: true }).click();
    await uploadState.filter({ hasText: /does not match|invalid/i }).waitFor({ timeout: 10000 });
    check((await upload.evaluate((input) => input.files[0]?.name)) === "wrong-content.pdf", "Invalid-type upload did not preserve the selected file");
    await page.screenshot({ path: `${artifactDir}/02c-upload-invalid-type.png`, fullPage: true });

    await setSyntheticFile({ name: "too-large.pdf", mimeType: "application/pdf", size: 20_000_010, pdfHeader: true });
    await page.getByRole("button", { name: "Submit upload slides", exact: true }).click();
    await uploadState.filter({ hasText: /20 MB|maximum|too large/i }).waitFor({ timeout: 10000 });
    check((await upload.evaluate((input) => input.files[0]?.name)) === "too-large.pdf", "Oversize upload did not preserve the selected file");
    report.proofs.upload_validation = { invalid_type_preserved: true, oversize_preserved: true };
    await page.screenshot({ path: `${artifactDir}/02d-upload-oversize.png`, fullPage: true });

    expectedRequestFailures.add(uploadUrl);
    expectedNetworkConsoleErrors += 1;
    await page.route(uploadUrl, (route) => route.abort(), { times: 1 });
    await upload.setInputFiles(pdfFixture);
    await page.getByRole("button", { name: "Submit upload slides", exact: true }).click();
    await uploadState.filter({ hasText: /network interrupted/i }).waitFor({ timeout: 10000 });
    check((await upload.evaluate((input) => input.files[0]?.name)) === "judge-ready-slides.pdf", "Interrupted upload did not preserve the selected file");
    await page.screenshot({ path: `${artifactDir}/02e-upload-interrupted.png`, fullPage: true });
    await upload.focus();
    const focusedRetry = await tabTo((active) => active.text === "Retry upload", 20, false);
    check(focusedRetry.text === "Retry upload", "Keyboard traversal did not focus the upload retry action");
    const uploadNavigation = page.waitForNavigation({ waitUntil: "domcontentloaded" });
    await page.keyboard.press("Enter");
    await uploadNavigation;
    const completedUpload = await bodyText();
    check(completedUpload.includes("judge-ready-slides") && completedUpload.includes(".pdf"), "Retried upload did not persist filename evidence");
    report.proofs.upload_validation.keyboard_retry = true;
    await page.getByRole("link", { name: /Back to your proposals/ }).click();
    await page.waitForLoadState("domcontentloaded");
    const proposals = await bodyText();
    for (const title of ["Draft: Responsible AI in Practice", "Review: Designing Trustworthy Systems", "Accepted: Operations That Scale"]) {
      check(proposals.includes(title), `Seeded proposal state is missing: ${title}`);
    }
    await page.getByRole("link", { name: "Draft: Responsible AI in Practice" }).click();
    await page.waitForLoadState("domcontentloaded");
    check((await bodyText()).includes("This is a draft proposal"), "Draft resume page did not open");
  });

  await stage("03-reviewer-workspace", async () => {
    await login("reviewer@example.org", true);
    check(page.url().includes("/speaker-operations/reviewer/"), "Reviewer did not land on the review queue");
    const programQueue = await bodyText();
    check(programQueue.includes("Browser proof: program reviewer routing"), "Program reviewer did not receive the ordinary native proposal");
    check(!programQueue.includes("Browser proof: systems reviewer routing"), "Program reviewer received the systems-only native proposal");
    await login("reviewer-systems@democon.test", true);
    const systemsQueue = await bodyText();
    check(systemsQueue.includes("Browser proof: systems reviewer routing"), "Systems reviewer did not receive the vendor native proposal");
    check(!systemsQueue.includes("Browser proof: program reviewer routing"), "Systems reviewer received the program-only native proposal");
    await page.screenshot({ path: `${artifactDir}/03a-distinct-native-reviewer-queue.png`, fullPage: true });
    report.proofs.conditional_cfp.reviewer_queues = {
      program_only: true,
      systems_only: true,
    };
    await login("reviewer@example.org", true);
    const scoreNames = await page.locator("fieldset.speakerops-score input[type=radio]").evaluateAll((items) => [...new Set(items.map((item) => item.name))]);
    check(scoreNames.length >= 3, "Reviewer rubric is incomplete");
    const reviewUrl = page.url();
    await page.route(reviewUrl, async (route) => {
      await page.waitForTimeout(1200);
      await route.continue();
    }, { times: 1 });
    await page.locator(`input[name="${scoreNames[0]}"]:not(:checked)`).first().check();
    await page.locator("[data-save-state]").filter({ hasText: /Saving/ }).waitFor({ timeout: 5000 });
    await page.locator("[data-save-state]").filter({ hasText: /All changes saved/ }).waitFor({ timeout: 10000 });

    expectedRequestFailures.add(reviewUrl);
    expectedNetworkConsoleErrors += 1;
    await page.route(reviewUrl, (route) => route.abort(), { times: 1 });
    await page.locator("#review-comments").fill(`Forced recovery proof ${new Date().toISOString()}: the operational path is concrete.`);
    await page.locator("[data-save-state]").filter({ hasText: /Not saved/ }).waitFor({ timeout: 10000 });
    check(await page.locator("[data-save-retry]").isVisible(), "Failed reviewer autosave did not expose Retry save");
    await page.locator("[data-save-retry]").click();
    await page.locator("[data-save-state]").filter({ hasText: /All changes saved/ }).waitFor({ timeout: 10000 });
    for (const name of scoreNames.slice(1)) {
      await page.locator(`input[name="${name}"]`).first().check();
      await page.locator(`input[name="${name}"]`).last().check();
    }
    await page.locator("input[name=recommendation][value=strong_accept]").check();
    const navigationProof = `Navigation flush proof ${new Date().toISOString()}`;
    await page.locator("#review-comments").fill(navigationProof);
    await page.route(reviewUrl, async (route) => {
      await page.waitForTimeout(1200);
      await route.continue();
    }, { times: 1 });
    const queueUrl = `${baseUrl}/orga/speakerops-demo/speaker-operations/reviewer/`;
    const queueNavigation = page.waitForURL(queueUrl, { timeout: 10000 });
    await page.locator("[data-review-nav]").first().click();
    await page.waitForTimeout(150);
    check(page.url() === reviewUrl, "Reviewer navigation did not wait for the pending save");
    check((await page.locator("[data-save-state]").innerText()).includes("Saving"), "Navigation flush did not expose Saving state");
    await queueNavigation;
    await goto(reviewUrl.replace(baseUrl, ""));
    await page.goBack({ waitUntil: "domcontentloaded" });
    await page.goForward({ waitUntil: "domcontentloaded" });
    await page.reload({ waitUntil: "domcontentloaded" });
    check((await page.locator("#review-comments").inputValue()) === navigationProof, "Back/reload did not restore the authoritative reviewer value");
    check(await page.locator("input[name=recommendation][value=strong_accept]").isChecked(), "Authoritative recommendation did not survive navigation");
    report.proofs.reviewer_navigation = { rapid_edits: true, slow_navigation_flush: true, reload_authoritative: true };
    await page.screenshot({ path: `${artifactDir}/03b-reviewer-authoritative-reload.png`, fullPage: true });
  });

  await stage("04-chair-control", async () => {
    await login("chair@example.org", true);
    check(page.url().endsWith("/speaker-operations/"), "Chair did not land on Operations");
    if (viewport.width >= 1000) {
      const focusedAgenda = await tabTo((active) => active.text === "Agenda / release");
      check(focusedAgenda.text.includes("Agenda"), "Keyboard navigation reached the agenda URL without a clear name");
      await page.keyboard.press("Enter");
      await page.waitForURL("**/speaker-operations/agenda/**");
      check(page.url().includes("/speaker-operations/agenda/"), "Keyboard activation did not open Agenda / release");
      report.proofs.role_navigation = { desktop_keyboard_to_agenda: true };
      await goto("/orga/speakerops-demo/speaker-operations/");
    } else {
      report.proofs.role_navigation = { mobile_named_navigation: true };
    }
    const dashboard = await bodyText();
    check(dashboard.includes("Speaker Operations"), "Chair Operations surface is missing");
    check((await page.locator(".speakerops-card").count()) >= 6, "Chair dashboard count cards are incomplete");
    await goto("/orga/speakerops-demo/speaker-operations/program-decisions/");
    check((await bodyText()).includes("Program decisions and waves"), "Program decision control is missing");
    await goto("/orga/speakerops-demo/speaker-operations/cfp-routing/");
    const routing = await bodyText();
    check(routing.includes("Vendor context disclosure"), "Conditional CFP rule is not visible to the chair");
    check(routing.includes("Program and leadership reviewers"), "First reviewer pool is missing");
    check(routing.includes("Systems and agents reviewers"), "Second reviewer pool is missing");
    report.proofs.conditional_cfp ||= {};
    report.proofs.conditional_cfp.chair_rule_and_two_pools = true;
  });

  await stage("05-agenda-release-gate", async () => {
    await goto("/orga/speakerops-demo/speaker-operations/agenda/");
    const agenda = await bodyText();
    check(agenda.includes("Release blocked"), "Seeded conflict gate is not blocking");
    const conflictCategories = (await page.locator("#conflicts tbody tr td[data-label='Shared resource'] strong").allTextContents()).map((value) => value.trim().toLowerCase());
    check(conflictCategories.includes("room") && conflictCategories.includes("speaker"), "Distinct room-only and speaker-only conflict rows are missing");
    check(conflictCategories.length >= 2, "Combined conflict state is incomplete");
    check((await page.getByRole("link", { name: /Resolve / }).count()) >= 2, "Conflicts do not expose direct Resolve actions");
    check(await page.getByRole("button", { name: "Release schedule" }).isDisabled(), "Release button bypasses blocking conflicts");
    await page.screenshot({ path: `${artifactDir}/05a-conflicts-combined-before.png`, fullPage: true });
    const roomConflictRow = page.locator("#conflicts tbody tr").filter({
      has: page.locator("td[data-label='Shared resource'] strong", { hasText: /^Room$/i }),
    });
    const popupPromise = page.waitForEvent("popup");
    await roomConflictRow.getByRole("link", { name: /Resolve / }).first().click();
    const popup = await popupPromise;
    await popup.waitForLoadState("domcontentloaded");
    check((await popup.locator("body").innerText()).length > 100, "Native resolution context did not open");
    await popup.locator("#id_room").selectOption({ label: "Studio" });
    await popup.locator("#id_start_time").fill("13:00");
    const firstSaveResponse = popup.waitForResponse((response) => response.request().method() === "POST" && response.url() === popup.url());
    await popup.getByRole("button", { name: /Save/ }).click();
    check((await firstSaveResponse).status() < 400, "Native room edit save failed");
    if (!popup.isClosed()) await popup.close();
    await goto("/orga/speakerops-demo/speaker-operations/agenda/?recheck=1#conflicts");
    const partialText = await bodyText();
    check(partialText.includes("still blocked") && partialText.includes("1 conflict cleared"), "Native room edit did not refresh the gate from two conflicts to one");
    const remainingCategories = (await page.locator("#conflicts tbody tr td[data-label='Shared resource'] strong").allTextContents()).map((value) => value.trim().toLowerCase());
    check(remainingCategories.length === 1 && remainingCategories[0] === "speaker", "Room edit did not leave the expected speaker-only conflict");
    await page.screenshot({ path: `${artifactDir}/05b-conflict-speaker-only-after-room-fix.png`, fullPage: true });

    const secondPopupPromise = page.waitForEvent("popup");
    await page.getByRole("link", { name: /Resolve / }).first().click();
    const secondPopup = await secondPopupPromise;
    await secondPopup.waitForLoadState("domcontentloaded");
    await secondPopup.locator("#id_start_time").fill("14:00");
    const secondSaveResponse = secondPopup.waitForResponse((response) => response.request().method() === "POST" && response.url() === secondPopup.url());
    await secondPopup.getByRole("button", { name: /Save/ }).click();
    check((await secondSaveResponse).status() < 400, "Native time edit save failed");
    if (!secondPopup.isClosed()) await secondPopup.close();
    await goto(`/orga/speakerops-demo/speaker-operations/agenda/?recheck=1&proof=${Date.now()}#conflicts`);
    check((await bodyText()).includes("release gate clear"), "Native time edit did not clear the remaining speaker conflict");
    check(!(await page.locator("#conflicts").count()), "Conflict rows remain after both native fixes");
    check(!(await page.getByRole("button", { name: "Release schedule" }).isDisabled()), "Release remained disabled after the server-authoritative gate cleared");
    report.proofs.conflicts = { room_only: true, speaker_only: true, combined_state: true, native_room_fix: true, native_time_fix: true, gate_cleared: true };
    await page.screenshot({ path: `${artifactDir}/05c-conflicts-cleared-after.png`, fullPage: true });
  });

  if (viewport.width >= 1000) await stage("05b-native-schedule", async () => {
    await goto("/orga/event/speakerops-demo/schedule/");
    await page.locator(".pretalx-schedule").waitFor();
    await page.locator(".c-linear-schedule-session.istalk").first().waitFor();
    const nativeTalkCount = await page.locator(".c-linear-schedule-session.istalk").count();
    check(nativeTalkCount >= 14 && nativeTalkCount <= 15, `Native WIP schedule contains ${nativeTalkCount} slots instead of the 14 canonical slots plus at most the current browser proposal`);
    check((await page.getByRole("tab").count()) === 3, "Native schedule does not expose all three event days");
    await page.getByRole("tab", { name: /Tuesday 11\. August/i }).click();
    check((await page.getByRole("tab", { name: /Tuesday 11\. August/i }).getAttribute("aria-selected")) === "true", "Day view did not select Tuesday");
    check(page.url().endsWith("#2026-08-11"), "Day selection did not persist in the schedule URL");
    await page.getByRole("tab", { name: /Monday 10\. August/i }).click();

    const studioHeader = page.locator(".grid > .room").filter({ hasText: "Studio" });
    await studioHeader.locator(".hide-room").click();
    check((await page.getByText("Hidden rooms (1)", { exact: true }).count()) === 1, "Room isolation did not hide Studio");
    await page.getByText("Hidden rooms (1)", { exact: true }).click();
    await page.locator(".room-entry").filter({ hasText: "Studio" }).click();
    check((await page.getByText("Hidden rooms (1)", { exact: true }).count()) === 0, "Room isolation did not restore Studio");

    const source = page.locator(".c-linear-schedule-session.istalk").filter({
      has: page.locator(".title", { hasText: "From Spreadsheet Chaos to Program Readiness" }),
    }).first();
    const slice = page.locator('.timeslice[data-slice="2026-08-10T11:00:00-04:00"]');
    const sourceBox = await source.boundingBox();
    const sliceBox = await slice.boundingBox();
    const studioBox = await studioHeader.boundingBox();
    check(sourceBox && sliceBox && studioBox, "Native schedule drag coordinates are unavailable");
    const patchResponse = page.waitForResponse((response) =>
      response.request().method() === "PATCH" && /\/schedule\/api\/talks\/\d+\/$/.test(response.url())
    );
    await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2);
    await page.mouse.down();
    const mainStageBox = await page.locator(".grid > .room").filter({ hasText: "Main Stage" }).boundingBox();
    check(mainStageBox, "Main Stage drag target is unavailable");
    await page.mouse.move(mainStageBox.x + mainStageBox.width / 2, sliceBox.y + sliceBox.height / 2, { steps: 20 });
    await page.mouse.up();
    const moved = await patchResponse;
    check(moved.status() === 200, `Native schedule drag PATCH failed (${moved.status()})`);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator(".pretalx-schedule").waitFor();
    const movedCard = page.locator(".c-linear-schedule-session.istalk").filter({
      has: page.locator(".title", { hasText: "From Spreadsheet Chaos to Program Readiness" }),
    }).first();
    const movedBox = await movedCard.boundingBox();
    const persistedMainStageBox = await page.locator(".grid > .room").filter({ hasText: "Main Stage" }).boundingBox();
    check(movedBox && persistedMainStageBox && movedBox.x >= persistedMainStageBox.x && movedBox.x < persistedMainStageBox.x + persistedMainStageBox.width, "Dragged room did not persist after reload");
    await page.screenshot({ path: `${artifactDir}/05d-native-schedule-drag-persisted.png`, fullPage: true });

    await page.context().clearCookies();
    await goto("/speakerops-demo/schedule/");
    await page.getByRole("button", { name: /Filter/i }).click();
    await page.getByLabel("Reliable AI Systems", { exact: true }).check();
    const filteredTracks = await page.locator(".track").allTextContents();
    check(filteredTracks.length === 5 && filteredTracks.every((value) => value.trim() === "Reliable AI Systems"), "Public track view did not isolate the five released systems sessions");
    await page.screenshot({ path: `${artifactDir}/05e-public-schedule-track-filter.png`, fullPage: true });
    await goto("/speakerops-demo/talk/");
    check((await page.locator('pretalx-schedule[format="list"]').count()) === 1, "Public list schedule is unavailable");
    const publicTalkLinks = await page.locator('a[href*="/speakerops-demo/talk/"]').evaluateAll((links) => new Set(
      links.map((link) => link.href).filter((href) => /\/speakerops-demo\/talk\/[^/]+\/$/.test(new URL(href).pathname))
    ).size);
    check(publicTalkLinks === 12, `Public list schedule exposes ${publicTalkLinks} talks instead of 12`);
    const nativeAccessibility = await page.evaluate(async () => {
      const result = await window.axe.run(document, { resultTypes: ["violations"] });
      return {
        violations: result.violations.map((item) => ({
          id: item.id,
          impact: item.impact,
          nodes: item.nodes.length,
        })),
        horizontal_overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth,
      };
    });
    report.proofs.native_schedule = {
      clean_wip_slots: nativeTalkCount,
      day_tabs: 3,
      room_isolation: true,
      track_filter_count: 5,
      list_count: 12,
      drag_patch_status: moved.status(),
      drag_persisted_after_reload: true,
      native_distinct_week_view: false,
      inherited_public_list_accessibility: nativeAccessibility,
    };
    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/agenda/");
  });

  await stage("06-sync-recovery", async () => {
    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/");
    const dashboardFailedBefore = Number((await page.locator(".speakerops-card").filter({ hasText: "Synchronization errors" }).locator(".speakerops-card__value").innerText()).trim());
    check(dashboardFailedBefore > 0, "Dashboard did not expose the seeded failed synchronization record");
    await page.screenshot({ path: `${artifactDir}/06a-dashboard-sync-exception-before.png`, fullPage: true });
    await page.getByRole("link", { name: "Retry this record" }).first().click();
    await page.waitForLoadState("domcontentloaded");
    const before = await bodyText();
    for (const state of ["create", "update", "noop", "failed"]) check(before.toLowerCase().includes(state), `Sync evidence is missing ${state}`);
    const failedBefore = await page.locator("tr").filter({ hasText: "failed" }).count();
    const retryForm = page.getByRole("button", { name: "Retry" }).first().locator("xpath=ancestor::form");
    await retryForm.locator("input[name=confirm_sync]").check();
    await retryForm.getByRole("button", { name: "Retry" }).click();
    await page.waitForLoadState("domcontentloaded");
    const failedAfter = await page.locator("tr").filter({ hasText: "failed" }).count();
    check(failedAfter < failedBefore || (await bodyText()).includes("Failed item retried"), "Failed sync item did not recover visibly");
    await page.screenshot({ path: `${artifactDir}/06b-sync-exception-recovered.png`, fullPage: true });
    await page.waitForTimeout(2200);
    await goto("/orga/speakerops-demo/speaker-operations/");
    const dashboardFailedAfter = Number((await page.locator(".speakerops-card").filter({ hasText: "Synchronization errors" }).locator(".speakerops-card__value").innerText()).trim());
    check(dashboardFailedAfter < dashboardFailedBefore, "Dashboard did not reconcile after selective synchronization recovery");
    report.proofs.dashboard_recovery = { before: dashboardFailedBefore, after: dashboardFailedAfter, action: "selective failed-item retry" };
    await page.screenshot({ path: `${artifactDir}/06c-dashboard-sync-exception-after.png`, fullPage: true });
  });

  await stage("07-released-outputs", async () => {
    await page.context().clearCookies();
    await goto("/speakerops-demo/speaker-operations/embed/");
    check((await bodyText()).includes("Designing Calm Systems for High-Stakes Work"), "Released embed is missing the curated program");
    check((await page.locator('[data-view="list"] [data-session]').count()) === 12, "Released list view does not contain exactly 12 sessions");
    check((await page.locator('[data-view="list"] h2 a[href*="/speakerops-demo/talk/"]').count()) === 12, "Released session cards do not link to native session details");
    const weekButton = page.getByRole("button", { name: "Week", exact: true });
    await weekButton.focus();
    await page.keyboard.press("Enter");
    check((await weekButton.getAttribute("aria-pressed")) === "true", "Released Week view is not keyboard operable");
    await page.getByLabel("Track").selectOption({ label: "Reliable AI Systems" });
    check((await page.getByRole("status").innerText()).includes("Showing 5 sessions in week view"), "Released Week/track view did not isolate five systems sessions");
    const releasedOverflow = await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth);
    check(releasedOverflow === 0, `Released Week view has ${releasedOverflow}px horizontal overflow`);
    await page.screenshot({ path: `${artifactDir}/07a-released-week-track.png`, fullPage: true });

    await page.getByRole("button", { name: "Day", exact: true }).click();
    await page.getByLabel("Room").selectOption({ label: "Main Stage" });
    await page.getByLabel("Day").selectOption({ label: "Tuesday, August 11" });
    check((await page.getByRole("status").innerText()).includes("Showing 2 sessions in day view"), "Released Day/track/room view did not isolate the two Tuesday Main Stage systems sessions");
    await page.getByRole("button", { name: "List", exact: true }).click();
    await page.getByLabel("Track").selectOption("");
    await page.getByLabel("Room").selectOption("");
    check((await page.getByRole("status").innerText()).includes("Showing 12 sessions in list view"), "Released List view did not restore all 12 sessions");
    report.proofs.released_schedule = {
      list_count: 12,
      day_track_room_count: 2,
      week_track_count: 5,
      keyboard_week_activation: true,
      horizontal_overflow: releasedOverflow,
    };
    await goto("/speakerops-demo/speaker-operations/gallery/");
    check((await page.locator("article").count()) >= 10, "Public gallery is unexpectedly sparse");
    const embed = await page.request.get(`${baseUrl}/speakerops-demo/speaker-operations/embed/`);
    check(embed.ok(), `Public embed failed (${embed.status()})`);
    const ics = await page.request.get(`${baseUrl}/speakerops-demo/speaker-operations/schedule.ics`);
    check(ics.ok() && (await ics.text()).includes("BEGIN:VCALENDAR"), "Released ICS is invalid or unavailable");
  });

  if (report.console_errors.length) report.failures.push(`${report.console_errors.length} console error(s)`);
  if (report.request_failures.length) report.failures.push(`${report.request_failures.length} failed network request(s)`);
  if (report.http_errors.length) report.failures.push(`${report.http_errors.length} first-party HTTP error response(s)`);
  report.finished_at = new Date().toISOString();
  report.ok = report.failures.length === 0 && report.stages.every((item) => item.status === "passed");
  return report;
}
