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
    if (message.type() === "error") {
      const location = message.location()?.url;
      report.console_errors.push(location ? `${message.text()} @ ${location}` : message.text());
    }
  });
  page.on("requestfailed", (request) => {
    if (expectedRequestFailures.delete(request.url())) return;
    const error = request.failure()?.errorText;
    // A rapid form update legitimately replaces the embed preview navigation.
    // Chromium reports that cancelled navigation as ERR_ABORTED, not as a
    // server or connectivity failure.
    if (error === "net::ERR_ABORTED") return;
    report.request_failures.push({ url: request.url(), error });
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
    const loginPath = organiser ? "/orga/event/speakerops-demo/login/" : "/speakerops-demo/login/";
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const consoleStart = report.console_errors.length;
      const httpStart = report.http_errors.length;
      await page.context().clearCookies();
      // Force a document boundary after clearing the prior role. This prevents Chromium's
      // network service from pairing a stale CSRF cookie with the new login form during
      // rapid multi-role evaluator switches.
      await page.goto("about:blank");
      await goto(loginPath);
      await page.locator("[name=login_email]").fill(email);
      await page.locator("[name=login_password]").fill("speakerops-demo");
      const navigation = page.waitForNavigation({ waitUntil: "domcontentloaded" });
      await page.getByRole("button", { name: "Log in", exact: true }).click();
      const response = await navigation;
      if (response?.status() < 400 && !page.url().includes("/login/")) return;
      if (attempt === 0 && response?.status() === 403) {
        // A fresh GET/token pair on the retry is authoritative; discard only the transient
        // failed attempt from the harness error ledger.
        report.console_errors.splice(consoleStart);
        report.http_errors.splice(httpStart);
        continue;
      }
      throw new Error(`Login failed for ${email} (${response?.status() || "no response"})`);
    }
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
        overflow_nodes: [
          ...[...document.querySelectorAll("body *")]
            .filter((node) => node.getBoundingClientRect().right > window.innerWidth + 1)
            .slice(0, 12)
            .map((node) => ({ selector: `${node.tagName.toLowerCase()}.${[...node.classList].join(".")}`, right: Math.round(node.getBoundingClientRect().right), scroll_width: node.scrollWidth, client_width: node.clientWidth })),
          ...[...document.querySelectorAll("pretalx-schedule")].flatMap((host) =>
            [...(host.shadowRoot?.querySelectorAll("*") || [])]
              .filter((node) => node.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 12)
              .map((node) => ({ selector: `pretalx-schedule::${node.tagName.toLowerCase()}.${[...node.classList].join(".")}`, right: Math.round(node.getBoundingClientRect().right), scroll_width: node.scrollWidth, client_width: node.clientWidth })),
          ),
        ],
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

  const ordinaryInitialTitle = "Browser proof: program reviewer routing";
  const ordinaryTitle = `${ordinaryInitialTitle} — edited`;
  const ordinaryEditedAbstract = "A browser-edited abstract that must remain visible to the organizer after submission.";
  const draftProofTitle = "Browser proof: title-only draft resume";
  const vendorTitle = "Browser proof: systems reviewer routing";
  const signupTitle = "Taming 40-Minute CI: Incremental Builds at Monorepo Scale";

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
    const publicCfpText = await bodyText();
    check(publicCfpText.includes("Share your idea with DemoCon"), "CFP landing is missing its seeded headline");
    check(publicCfpText.includes("Submissions close on") && publicCfpText.includes("America/New_York"), "Logged-out CFP does not state its open deadline and event timezone");
    check((await page.getByRole("link", { name: "How to write a proposal" }).count()) === 1, "Logged-out CFP does not expose the proposal guide");
    await goto("/speakerops-demo/speaker-operations/cfp-guide/");
    const guideText = await bodyText();
    check(guideText.includes("Write a proposal reviewers can champion"), "Public CFP guide is not reachable");
    check(guideText.includes("Choose one format and one to five topics") && guideText.includes("Every proposal receives human review"), "Public CFP guide omits format/topic choices or the human-review promise");
    report.proofs.public_cfp = { branded: true, open_deadline_timezone: true, guide_linked: true, format_topic_policy: true };
  });

  await stage("01b-cfp-account-submit-confirm-dashboard", async () => {
    await page.context().clearCookies();
    await goto("/speakerops-demo/login/?next=%2Fspeakerops-demo%2Fsubmit%2F");
    check((await page.getByText("I need a new account", { exact: true }).count()) === 1, "Public CFP login does not expose account creation");
    await page.locator("[name=register_name]").fill("Priya Raman");
    await page.locator("[name=register_email]").fill("priya.raman-cfp@example.invalid");
    await page.locator("[name=register_password]").fill("speakerops-demo");
    await page.locator("[name=register_password_repeat]").fill("speakerops-demo");
    await page.screenshot({ path: `${artifactDir}/01b-cfp-signup-filled.png`, fullPage: true });
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.getByRole("button", { name: "Register", exact: true }).click(),
    ]);
    check(page.url().includes("/submit/"), "New submitter account did not reach the proposal form");

    await page.locator("input[name=title]").fill(signupTitle);
    await page.locator("textarea[name=abstract]").fill("A practical account-to-submission proof for incremental build investments in large monorepos.");
    await page.getByRole("button", { name: "Continue »" }).click();
    await page.waitForLoadState("domcontentloaded");
    check(page.url().includes("/questions/"), "New-account proposal did not reach additional questions");
    await page.getByLabel("No commercial relationship", { exact: true }).check();
    await page.getByLabel("Program and leadership", { exact: true }).check();
    await page.getByLabel("Audience level", { exact: true }).selectOption({ label: "Intermediate" });
    await page.getByLabel("Key takeaway", { exact: true }).fill("A decision framework for which incremental-build investments pay off");
    await page.locator("select[multiple]").filter({ has: page.locator("option", { hasText: "Evals and observability" }) }).evaluate((select) => {
      const option = [...select.options].find((item) => item.textContent.trim() === "Evals and observability");
      option.selected = true;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.getByLabel("Session abstract", { exact: true }).fill("A complete proposal created by a brand-new submitter account through the public CFP portal.");
    await page.screenshot({ path: `${artifactDir}/01c-cfp-new-account-filled-proposal.png`, fullPage: true });
    await page.getByRole("button", { name: "Continue »" }).click();
    await page.waitForLoadState("domcontentloaded");
    check(page.url().includes("/profile/"), "New-account proposal did not reach the speaker profile step");
    await page.locator("textarea[name=biography]").fill(
      "Engineering leader helping teams shorten feedback loops without sacrificing reliability.",
    );
    await page.getByRole("button", { name: "Submit proposal! »" }).click();
    await page.waitForLoadState("domcontentloaded");
    const confirmation = await bodyText();
    check(confirmation.includes(signupTitle), "Submitted proposal is absent from the new speaker dashboard");
    check(/submitted|under review|pending|successfully/i.test(confirmation), "Submission confirmation/status wording is not visible");
    await page.screenshot({ path: `${artifactDir}/01d-cfp-new-account-confirmation-dashboard.png`, fullPage: true });
    report.proofs.cfp_account_lifecycle = {
      account_created: true,
      proposal_submitted: signupTitle,
      confirmation_visible: true,
      dashboard_status_visible: true,
    };
  });

  await stage("02-speaker-portal", async () => {
    await login("speaker@example.org");
    check(page.url().includes("/speaker-operations/checklist/"), "Speaker did not land on speaker tasks");

    await goto("/speakerops-demo/submit/");
    await page.locator("input[name=title]").fill(draftProofTitle);
    const saveDraft = page.getByRole("button", { name: /save as draft for now/i });
    check((await saveDraft.count()) === 1, "Native title-only CFP does not expose save as draft");
    await saveDraft.click();
    await page.waitForTimeout(500);
    check(page.url().includes("/me/submissions/") && (await bodyText()).includes(draftProofTitle), "Title-only draft did not persist in the native draft list");
    await goto("/speakerops-demo/speaker-operations/checklist/");
    await goto("/speakerops-demo/me/submissions/");
    await page.getByRole("link", { name: draftProofTitle, exact: true }).click();
    await page.waitForLoadState("domcontentloaded");
    check((await page.locator("input[name=title]").inputValue()) === draftProofTitle, "Title-only draft did not resume with its saved title");
    check((await bodyText()).toLowerCase().includes("draft"), "Resumed title-only proposal is not identified as a draft");
    report.proofs.title_only_draft_resume = { title_only: true, left_draft: true, resumed_native_editor: true };

    await goto("/speakerops-demo/submit/");
    await page.locator("input[name=title]").fill(ordinaryInitialTitle);
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
    check((await bodyText()).includes(ordinaryInitialTitle), "Ordinary native proposal was not submitted");
    await page.getByRole("link", { name: ordinaryInitialTitle, exact: true }).click();
    await page.waitForLoadState("domcontentloaded");
    const ordinaryCode = page.url().match(/\/me\/submissions\/([^/]+)/)?.[1];
    check(ordinaryCode, "Could not capture the native submitted proposal code");
    await page.locator("input[name=title]").fill(ordinaryTitle);
    await page.locator("textarea[name=abstract]").fill(ordinaryEditedAbstract);
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.getByRole("button", { name: "Save", exact: true }).click(),
    ]);
    check((await page.locator("input[name=title]").inputValue()) === ordinaryTitle, "Submitted proposal edit did not survive save and reload");
    check((await page.locator("textarea[name=abstract]").inputValue()) === ordinaryEditedAbstract, "Submitted abstract edit did not survive save and reload");
    await goto("/speakerops-demo/me/submissions/");
    check((await page.getByRole("link", { name: ordinaryTitle, exact: true }).count()) === 1 && (await page.getByRole("link", { name: ordinaryInitialTitle, exact: true }).count()) === 0, "Submitted proposal list did not reflect the saved edit");

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
      ordinary_original_title: ordinaryInitialTitle,
      post_submit_edit_roundtrip: true,
      ordinary_code: ordinaryCode,
      ordinary_edited_abstract: ordinaryEditedAbstract,
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
    const versionHistory = page.getByText("File version history and replacement", { exact: true }).first();
    check(await versionHistory.count(), "Completed upload does not expose replacement/version history");
    await versionHistory.click();
    const replacementForm = page.locator("form[data-upload-form]").filter({ hasText: "Submit new version" }).first();
    await replacementForm.locator("input[type=file]").setInputFiles(pdfFixture);
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      replacementForm.getByRole("button", { name: "Submit new version" }).click(),
    ]);
    const replacementHistory = page.getByText("File version history and replacement", { exact: true }).first();
    await replacementHistory.click();
    const historyText = await replacementHistory.locator("xpath=ancestor::details[1]").innerText();
    check(historyText.includes("v2") && historyText.includes("v1") && historyText.includes("Current/latest"), "Replacement upload did not preserve both versions or identify the latest");
    report.proofs.upload_validation.replacement_versions = 2;
    const supportingTask = page.locator("article.speakerops-task").filter({ has: page.getByRole("heading", { name: "Upload supporting document", exact: true }) });
    check((await supportingTask.count()) === 1, "Seeded checklist is missing the second upload task");
    const supportingForm = supportingTask.locator("form[data-upload-form]");
    await supportingForm.locator("input[type=file]").setInputFiles(pdfFixture);
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      supportingForm.getByRole("button", { name: "Submit upload supporting document", exact: true }).click(),
    ]);
    check((await page.getByRole("button", { name: "Submit upload supporting document", exact: true }).count()) === 0 && (await page.locator("#history-title").locator("xpath=ancestor::section[1]").innerText()).includes("Upload supporting document"), "Second upload task did not persist its first version");
    report.proofs.upload_validation.two_completed_upload_tasks = true;
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
    check(programQueue.includes(ordinaryTitle), "Program reviewer did not receive the ordinary native proposal");
    check(!programQueue.includes("Browser proof: systems reviewer routing"), "Program reviewer received the systems-only native proposal");
    await login("reviewer-systems@democon.test", true);
    const systemsQueue = await bodyText();
    check(systemsQueue.includes("Browser proof: systems reviewer routing"), "Systems reviewer did not receive the vendor native proposal");
    check(!systemsQueue.includes(ordinaryTitle), "Systems reviewer received the program-only native proposal");
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
    await goto("/orga/speakerops-demo/speaker-operations/content/");
    const editedProposal = page.locator("article").filter({ has: page.getByRole("heading", { name: ordinaryTitle, exact: true }) });
    check((await editedProposal.count()) === 1, "Organizer content view does not show the edited submitted title");
    check((await editedProposal.getByLabel("Abstract").inputValue()) === ordinaryEditedAbstract, "Organizer content view does not show the edited submitted abstract");
    report.proofs.conditional_cfp.organizer_observed_post_submit_edit = true;
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

  await stage("04a-independent-round-evidence", async () => {
    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/abstract-management/");
    const roundSuffix = Date.now();
    const blindRoundName = `Browser Blind Round ${roundSuffix}`;
    const visibleRoundName = `Browser Visible Round ${roundSuffix}`;
    const createRound = async ({ name, preset, blinded }) => {
      if (await page.getByRole("heading", { name, exact: true }).count()) return;
      const form = page.locator("#create-round-title").locator("xpath=ancestor::section[1]").locator("form");
      await form.getByLabel("Round name").fill(name);
      await form.getByLabel("Open date").fill("2026-08-10");
      await form.getByLabel("Close date").fill("2026-08-20");
      await form.getByLabel("Scorecard").selectOption(preset);
      if (blinded) await form.getByLabel(/Blind review/).check();
      await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded" }),
        form.getByRole("button", { name: "Save evaluation round" }).click(),
      ]);
      check((await page.locator("#evaluation-rounds h3").filter({ hasText: name }).count()) === 1, `${name} did not persist`);
    };
    await createRound({ name: blindRoundName, preset: "initial", blinded: true });
    await createRound({ name: visibleRoundName, preset: "final", blinded: false });

    const assignExact = async ({ roundName, reviewerEmail, submissionTitle }) => {
      const panel = page.locator("article.speakerops-panel").filter({ has: page.getByRole("heading", { name: roundName, exact: true }) });
      const form = panel.locator("form");
      const reviewerSelect = form.locator("select[name=reviewer_id]");
      const reviewerValue = await reviewerSelect.locator("option").filter({ hasText: reviewerEmail }).getAttribute("value");
      check(reviewerValue, `${reviewerEmail} is not available in ${roundName}`);
      await reviewerSelect.selectOption(reviewerValue);
      await form.locator("input[name=assignment_limit]").fill("1");
      const submissionChoice = form.locator("label", { hasText: submissionTitle }).locator("input[type=checkbox]");
      await submissionChoice.check();
      await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded" }),
        form.getByRole("button", { name: "Replace with selected — exact queue" }).click(),
      ]);
      check((await bodyText()).includes("queue now exactly matches the selection"), `${roundName} exact assignment did not report success`);
    };
    await assignExact({ roundName: blindRoundName, reviewerEmail: "reviewer@example.org", submissionTitle: ordinaryTitle });
    await assignExact({ roundName: blindRoundName, reviewerEmail: "reviewer-systems@democon.test", submissionTitle: ordinaryTitle });
    await assignExact({ roundName: visibleRoundName, reviewerEmail: "reviewer-systems@democon.test", submissionTitle: "Browser proof: systems reviewer routing" });

    const reminderChoice = page.getByLabel(`Remind Reviewer for ${blindRoundName}`, { exact: true });
    const reminderRow = reminderChoice.locator("xpath=ancestor::tr[1]");
    check((await reminderRow.count()) === 1, "Blind-round reviewer progress row is missing");
    check((await reminderRow.innerText()).includes("0 of 1") && (await reminderRow.innerText()).includes("0%"), "Reviewer progress did not expose exact pending counts");
    await reminderChoice.check();
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.getByRole("button", { name: "Send reminders to selected lagging reviewers" }).click(),
    ]);
    check((await bodyText()).includes("Reminder queued for 1 lagging reviewer"), "Reviewer reminder did not produce a queued outcome");
    const remindedRow = page.locator("#progress tbody tr").filter({ hasText: blindRoundName }).first();
    check(!(await remindedRow.innerText()).includes("Never"), "Reviewer reminder timestamp did not persist");
    await goto("/orga/event/speakerops-demo/mails/outbox/");
    const reviewerMailRow = page.locator("tr").filter({ hasText: "Review assignments waiting: DemoCon 2026" }).filter({ hasText: "Reviewer" }).first();
    check((await reviewerMailRow.count()) === 1, "Reviewer reminder did not reach the native queued-mail outbox");
    await reviewerMailRow.getByRole("link", { name: "Review assignments waiting: DemoCon 2026", exact: true }).click();
    await page.waitForLoadState("domcontentloaded");
    const reviewerMailText = await page.getByLabel("Text").inputValue();
    check((await page.getByLabel("Subject").inputValue()) === "Review assignments waiting: DemoCon 2026" && reviewerMailText.includes(blindRoundName) && reviewerMailText.includes("1 outstanding review assignment") && reviewerMailText.includes("/round-review/"), "Queued reviewer reminder omitted its round, pending count, or action link");
    report.proofs.reviewer_reminder_outbox = { native_queued_mail: true, rendered_round_count_link: true };

    await login("reviewer@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/round-review/");
    await page.locator("aside.speakerops-queue a").filter({ hasText: blindRoundName }).click();
    await page.waitForLoadState("domcontentloaded");
    const blindText = await page.locator(".speakerops--review main").innerText();
    check(blindText.toLowerCase().includes(blindRoundName.toLowerCase()), "Blind reviewer view opened the wrong round assignment");
    check(blindText.toLowerCase().includes("blind review active") && blindText.includes("Author identity hidden"), "Blind reviewer view did not hide presenter identity");
    check(!blindText.includes("Maya Chen"), "Blind reviewer view leaked the presenter's identity");
    const roundForm = page.locator("form.speakerops-review-form");
    for (const input of await roundForm.locator("input[type=number]").all()) await input.fill("5");
    for (const select of await roundForm.locator("select").all()) await select.selectOption({ index: 1 });
    for (const textarea of await roundForm.locator("textarea").all()) await textarea.fill("Exact browser evidence for the independent blind round.");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      roundForm.getByRole("button", { name: "Save round evaluation" }).click(),
    ]);
    check((await bodyText()).includes("Round evaluation saved and marked complete"), "Blind-round evaluation did not complete");

    await login("reviewer-systems@democon.test", true);
    await goto("/orga/speakerops-demo/speaker-operations/round-review/");
    await page.locator("aside.speakerops-queue a").filter({ hasText: blindRoundName }).click();
    await page.waitForLoadState("domcontentloaded");
    const isolatedForm = page.locator("form.speakerops-review-form");
    const isolatedText = await page.locator(".speakerops--review main").innerText();
    check(isolatedText.includes("Author identity hidden") && !isolatedText.includes("Maya Chen"), "Second reviewer did not receive the same blinded submission independently");
    check(!(await isolatedText.includes("Exact browser evidence for the independent blind round.")), "Second reviewer could see the first reviewer's private comment");
    for (const input of await isolatedForm.locator("input[type=number]").all()) check((await input.inputValue()) === "", "Second reviewer inherited the first reviewer's numeric score");
    for (const textarea of await isolatedForm.locator("textarea").all()) check((await textarea.inputValue()) === "", "Second reviewer inherited the first reviewer's comment");
    report.proofs.abstract_reviewer_isolation = { same_blind_round: true, first_reviewer_values_hidden: true, organizer_identity_visible: true };
    await goto("/orga/speakerops-demo/speaker-operations/round-review/");
    await page.locator("aside.speakerops-queue a").filter({ hasText: visibleRoundName }).click();
    await page.waitForLoadState("domcontentloaded");
    const visibleText = await page.locator(".speakerops--review main").innerText();
    check(visibleText.toLowerCase().includes(visibleRoundName.toLowerCase()) && visibleText.toLowerCase().includes("identity-visible review") && visibleText.includes("Presenters:"), "Identity-visible round did not expose its presenter label");
    check(visibleText.includes("Maya Chen"), "Identity-visible round omitted the assigned presenter");

    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/abstract-management/");
    const resultsText = await page.locator("#review-results").innerText();
    check(resultsText.includes(blindRoundName) && resultsText.includes(ordinaryTitle) && resultsText.includes("1"), "Organizer aggregate results omitted the completed blind review");
    const exportResponse = await page.request.get(`${baseUrl}/orga/speakerops-demo/speaker-operations/abstract-management/?export=csv`);
    const exportText = await exportResponse.text();
    check(exportResponse.ok() && (exportResponse.headers()["content-type"] || "").includes("text/csv"), "Round results CSV did not download");
    const exportedReviewRow = exportText.split(/\r?\n/).find((line) => line.includes(ordinaryTitle)) || "";
    check(
      exportText.includes("round,code,title,weighted_average,review_count,reviewer,assignment_status,criterion_scores") &&
      exportText.includes(blindRoundName) &&
      exportedReviewRow.includes(",1,reviewer@example.org,complete,") &&
      exportedReviewRow.includes('""Originality"": ""5.00""') &&
      exportedReviewRow.includes('""Recommendation"": ""Accept""'),
      "Downloaded round CSV does not reconcile with the completed browser review",
    );
    report.proofs.abstract_rounds = { blind_identity_hidden: true, visible_presenter: true, exact_progress: "0 of 1", reminder_timestamped: true, completed_score: 5, csv_reconciled: true };
  });

  if (viewport.width >= 1000) await stage("04b-speaker-lifecycle-and-aie-memory", async () => {
    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/speakers/");
    const unique = Date.now();
    const createdEmail = `browser-speaker-${unique}@democon.test`;
    const addForm = page.locator("#add-speaker-title").locator("xpath=ancestor::section[1]").locator("form");
    await addForm.getByLabel("Name", { exact: true }).fill("Browser Lifecycle Speaker");
    await addForm.getByLabel("Email", { exact: true }).fill(createdEmail);
    await addForm.getByLabel(/Biography/).fill("A browser-created speaker with an auditable lifecycle.");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      addForm.getByRole("button", { name: "Add speaker" }).click(),
    ]);
    const createdRow = page.locator("details.speakerops-task").filter({ hasText: createdEmail });
    check((await createdRow.count()) === 1, "Individual speaker creation did not persist in the roster");
    await createdRow.locator("summary").click();
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      createdRow.getByRole("button", { name: "Send onboarding invitation" }).click(),
    ]);
    check((await bodyText()).includes("Sent 1 personalized message"), "Invitation did not report a successful delivery handoff");
    const communicationRow = page.locator("#communication-log-title").locator("xpath=ancestor::section[1]").locator("tbody tr").filter({ hasText: "Browser Lifecycle Speaker" }).first();
    check((await communicationRow.count()) === 1 && (await communicationRow.innerText()).includes("Sent"), "Invitation outcome is missing from the communication log");

    const emailSection = page.locator("#speaker-email-title").locator("xpath=ancestor::section[1]");
    const emailForm = emailSection.locator("form");
    await emailForm.locator("label", { hasText: createdEmail }).locator("input[type=checkbox]").check();
    await emailForm.locator("label", { hasText: "speaker@example.org" }).locator("input[type=checkbox]").check();
    await emailForm.getByLabel("Subject").fill("Browser proof for {{ full_name }}");
    await emailForm.getByLabel("Message").fill("Hello {{ first_name }}. Sessions: {{ session_titles }}. Portal: {{ speaker_portal_url }}");
    await emailForm.getByRole("button", { name: "Preview personalization" }).click();
    await page.waitForLoadState("domcontentloaded");
    const preview = page.locator("#email-preview-title").locator("xpath=ancestor::section[1]");
    check((await preview.count()) === 1, "Personalized speaker email preview did not render");
    const previewText = await preview.innerText();
    check(previewText.includes("Browser Lifecycle Speaker") && previewText.includes("Maya Chen"), "Bulk preview omitted a selected speaker");
    check(!previewText.includes("{{"), "Bulk preview leaked unresolved merge fields");
    await emailSection.getByRole("button", { name: "Send selected email" }).click();
    await page.waitForLoadState("domcontentloaded");
    check((await bodyText()).includes("Sent 2 personalized messages"), "Selected bulk email did not report two outcomes");

    await goto("/orga/event/speakerops-demo/mails/sent");
    const onboardingSubject = "Your DemoCon 2026 speaker onboarding";
    const onboardingMail = page.locator("tr").filter({ hasText: onboardingSubject }).filter({ hasText: "Browser Lifecycle Speaker" }).first();
    check((await onboardingMail.count()) === 1, "Speaker invitation is missing from native sent-mail history");
    await onboardingMail.getByRole("link", { name: onboardingSubject, exact: true }).click();
    await page.waitForLoadState("domcontentloaded");
    const onboardingText = await bodyText();
    check(onboardingText.includes("Set up your account or sign in: http://127.0.0.1:38001/speakerops-demo/reset/") && onboardingText.includes("Open your private speaker portal: http://127.0.0.1:38001/speakerops-demo/speaker-operations/profile/") && !onboardingText.includes("{{"), "Sent invitation omitted its account setup or private portal link");

    await goto("/orga/event/speakerops-demo/mails/sent");
    const lifecycleSubject = "Browser proof for Browser Lifecycle Speaker";
    const lifecycleMail = page.locator("tr").filter({ hasText: lifecycleSubject }).filter({ hasText: "Browser Lifecycle Speaker" }).first();
    check((await lifecycleMail.count()) === 1, "Personalized general message is missing from native sent-mail history");
    await lifecycleMail.getByRole("link", { name: lifecycleSubject, exact: true }).click();
    await page.waitForLoadState("domcontentloaded");
    const lifecycleText = await bodyText();
    check(lifecycleText.includes("Hello Browser.") && lifecycleText.includes("No sessions assigned.") && lifecycleText.includes("/speaker-operations/profile/") && !lifecycleText.includes("{{"), "Sent general message does not reconcile with its selected speaker preview");
    report.proofs.speaker_mail_history = { invitation_setup_and_portal_links: true, personalized_general_message_opened: true, no_unresolved_merge_fields: true };

    await goto("/orga/event/speakerops-demo/mails/sent");
    const confirmationSubject = `Your proposal: ${ordinaryInitialTitle}`;
    const confirmationMail = page.locator("tr").filter({ hasText: confirmationSubject }).filter({ hasText: "Maya Chen" }).first();
    check((await confirmationMail.count()) === 1, "Submitted proposal confirmation is missing from native sent-mail history");
    await confirmationMail.getByRole("link", { name: confirmationSubject, exact: true }).click();
    await page.waitForLoadState("domcontentloaded");
    const confirmationText = await bodyText();
    check(confirmationText.includes(`We have received your proposal “${ordinaryInitialTitle}”`) && confirmationText.includes(`/me/submissions/${report.proofs.conditional_cfp.ordinary_code}/`) && confirmationText.includes("Review category: Program and leadership"), "Proposal confirmation omitted receipt, edit link, or routed review category");
    report.proofs.submission_confirmation_mail = { native_sent_history: true, receipt_and_edit_link: true, routed_category: true };
    await goto("/orga/speakerops-demo/speaker-operations/speakers/");

    let mayaRow = page.locator("details.speakerops-task").filter({ hasText: "speaker@example.org" }).first();
    await mayaRow.locator("summary").click();
    check((await mayaRow.innerText()).includes("Accepted: Operations That Scale"), "Organizer speaker record omitted its session assignment");
    await mayaRow.getByLabel("Workflow status").selectOption("confirmed");
    await mayaRow.getByLabel("Travel preferences").fill("Train preferred; arrive the evening before rehearsal.");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      mayaRow.getByRole("button", { name: "Save speaker workflow" }).click(),
    ]);
    const rosterFilter = page.getByRole("search");
    await rosterFilter.getByLabel("Search name or email").fill("Maya Chen");
    await rosterFilter.getByLabel("Workflow status").selectOption("confirmed");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      rosterFilter.getByRole("button", { name: "Filter roster" }).click(),
    ]);
    const filteredRows = page.locator("details.speakerops-task");
    check((await filteredRows.count()) === 1, "Combined name/status roster filter did not isolate one speaker");
    const filteredSummary = await filteredRows.first().locator("summary").innerText();
    check(filteredSummary.includes("Maya Chen") && filteredSummary.toLowerCase().includes("confirmed") && /\d+\/\d+ tasks resolved/.test(filteredSummary), "Filtered roster omitted workflow status or per-speaker progress");
    await filteredRows.first().locator("summary").click();
    check((await filteredRows.first().getByLabel("Travel preferences").inputValue()).includes("Train preferred"), "Roster filter/reload lost speaker logistics data");
    report.proofs.speaker_roster = { combined_search_status: true, persisted_logistics: true, per_speaker_progress: true };
    await login("speaker@example.org");
    await goto("/speakerops-demo/speaker-operations/profile/");
    const speakerProfileText = await bodyText();
    check(speakerProfileText.includes("Your session assignments"), "Speaker portal omitted its assignment region");
    check(speakerProfileText.includes("Accepted: Operations That Scale"), "Speaker portal omitted its assigned session");

    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/speakers/");
    const removableRow = page.locator("details.speakerops-task").filter({ hasText: createdEmail });
    await removableRow.locator("summary").click();
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      removableRow.getByRole("button", { name: "Remove unassigned speaker" }).click(),
    ]);
    check((await page.locator("details.speakerops-task").filter({ hasText: createdEmail }).count()) === 0, "Safe speaker removal did not remove the event record");

    await goto("/orga/speakerops-demo/speaker-operations/conference-memory/");
    check((await page.getByRole("heading", { name: "What has this community programmed?" }).count()) === 1, "Conference memory does not distinguish programmed evidence from already-heard claims");
    await page.getByLabel("Talk, speaker, topic, format, track, or edition").fill("Ankur Goyal");
    await page.locator("#memory-series").selectOption({ label: "AI Engineer" });
    await page.getByLabel("Program timing").selectOption("past");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.getByRole("button", { name: "Search memory" }).click(),
    ]);
    check((await page.getByRole("link", { name: "Ankur Goyal", exact: true }).count()) >= 2, "AIE memory did not return Ankur Goyal across sourced talks");
    await page.screenshot({ path: `${artifactDir}/04c-aie-memory-filtered-results.png`, fullPage: true });
    await page.getByRole("link", { name: "Ankur Goyal", exact: true }).first().click();
    await page.waitForLoadState("domcontentloaded");
    const memoryText = await bodyText();
    check(memoryText.includes("Verified recurrence"), "Curated AIE identity evidence did not produce verified recurrence");
    check(memoryText.includes("3 sourced talks") && memoryText.includes("2 editions"), "Returning-speaker summary does not match the sourced AIE evidence");
    check((await page.locator("a[href^='http']").count()) >= 1, "AIE identity detail omits its source evidence link");
    await page.screenshot({ path: `${artifactDir}/04d-aie-memory-identity-evidence.png`, fullPage: true });
    const contextForm = page.locator("#crm-context-title").locator("xpath=ancestor::section[1]").locator("form");
    await contextForm.getByLabel(/Tags/).fill("AIE alum, verified recurrence, invite shortlist");
    await contextForm.getByLabel("Internal notes").fill("Buyer proof: evaluate for a future reliability and evals program.");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      contextForm.getByRole("button", { name: "Save CRM context" }).click(),
    ]);
    const addToCrm = page.getByRole("button", { name: "Add to organization CRM" });
    if (await addToCrm.count()) {
      await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded" }),
        addToCrm.click(),
      ]);
    } else {
      await page.getByRole("link", { name: "Ankur Goyal", exact: true }).last().click();
      await page.waitForLoadState("domcontentloaded");
    }
    check(page.url().includes("/speaker-operations/crm/"), "Conference memory did not hand the sourced speaker into organization CRM");
    let ankurContact = page.locator("details.speakerops-task").filter({ hasText: "Ankur Goyal" }).first();
    check((await ankurContact.count()) === 1, "Organization CRM omitted the handed-off AIE speaker");
    check((await ankurContact.locator(":scope > summary").innerText()).includes("No email"), "Memory handoff invented an unknown speaker email");
    await ankurContact.locator(":scope > summary").click();
    const contactText = await ankurContact.innerText();
    check(contactText.includes("Sourced history linked") && contactText.includes("verified recurrence"), "CRM handoff lost source provenance or operator context");
    check(contactText.includes("Verify an email before event handoff") && contactText.includes("will not infer or invent contact data"), "CRM does not explain the honest missing-email gate");
    check((await ankurContact.getByRole("button", { name: "Add without re-entry" }).count()) === 0, "CRM incorrectly offers event handoff without a verified email");
    const stageSelect = ankurContact.getByLabel("Sourcing stage");
    if ((await stageSelect.inputValue()) !== "contacted") {
      await stageSelect.selectOption("contacted");
      await ankurContact.getByLabel("Transition note").fill("Evidence-backed shortlist review started in the buyer demo.");
      await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded" }),
        ankurContact.getByRole("button", { name: "Move and record history" }).click(),
      ]);
      ankurContact = page.locator("details.speakerops-task").filter({ hasText: "Ankur Goyal" }).first();
    }
    if (!(await ankurContact.getByLabel("Sourcing stage").isVisible())) await ankurContact.locator(":scope > summary").click();
    check((await ankurContact.getByLabel("Sourcing stage").inputValue()) === "contacted", "CRM pipeline did not retain the next operator action");
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `${artifactDir}/04e-aie-memory-crm-pre-handoff-gate.png`, fullPage: true });
    report.proofs.speaker_lifecycle = {
      individual_create_remove: true,
      invitation_logged: true,
      bulk_preview_personalized: true,
      bulk_send_outcomes: 2,
      assignments_both_roles: true,
    };
    report.proofs.aie_memory = {
      speaker: "Ankur Goyal",
      sourced_talks: 3,
      verified_editions: 2,
      timing_scope: "past",
      verified_recurrence: true,
      crm_handoff: true,
      unknown_email_preserved: true,
      missing_email_handoff_blocked_and_explained: true,
      pipeline_stage: "contacted",
    };
  });

  if (viewport.width < 1000) await stage("04b-aie-memory-mobile-buyer-path", async () => {
    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/conference-memory/");
    await page.getByLabel("Talk, speaker, topic, format, track, or edition").fill("Ankur Goyal");
    await page.locator("#memory-series").selectOption({ label: "AI Engineer" });
    await page.getByLabel("Program timing").selectOption("past");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.getByRole("button", { name: "Search memory" }).click(),
    ]);
    check((await page.getByRole("link", { name: "Ankur Goyal", exact: true }).count()) >= 2, "Mobile AIE memory did not expose the recurring speaker evidence");
    await page.screenshot({ path: `${artifactDir}/04b-mobile-aie-memory-results.png`, fullPage: true });
    await page.getByRole("link", { name: "Ankur Goyal", exact: true }).first().click();
    await page.waitForLoadState("domcontentloaded");
    const memoryText = await bodyText();
    check(memoryText.includes("Verified recurrence") && memoryText.includes("3 sourced talks") && memoryText.includes("2 editions"), "Mobile identity detail lost recurrence depth");
    check((await page.locator("a[href^='http']").count()) >= 1, "Mobile identity detail omits its source evidence link");
    await page.screenshot({ path: `${artifactDir}/04c-mobile-aie-identity-evidence.png`, fullPage: true });
    const addToCrm = page.getByRole("button", { name: "Add to organization CRM" });
    if (await addToCrm.count()) {
      await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded" }),
        addToCrm.click(),
      ]);
    } else {
      await page.getByRole("link", { name: "Ankur Goyal", exact: true }).last().click();
      await page.waitForLoadState("domcontentloaded");
    }
    check(page.url().includes("/speaker-operations/crm/"), "Mobile memory path did not reach organization CRM");
    const contact = page.locator("details.speakerops-task").filter({ hasText: "Ankur Goyal" }).first();
    check((await contact.count()) === 1 && (await contact.locator(":scope > summary").innerText()).includes("No email"), "Mobile CRM handoff invented or lost the unknown email state");
    await contact.locator(":scope > summary").click();
    const contactText = await contact.innerText();
    check(contactText.includes("Sourced history linked") && contactText.includes("Verify an email before event handoff") && contactText.includes("will not infer or invent contact data"), "Mobile CRM omitted provenance or the missing-email explanation");
    check((await contact.getByRole("button", { name: "Add without re-entry" }).count()) === 0, "Mobile CRM incorrectly enables event handoff without verified email");
    const overflow = await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth);
    check(overflow === 0, `Mobile AIE buyer path has ${overflow}px horizontal overflow`);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `${artifactDir}/04d-mobile-aie-crm-pre-handoff-gate.png`, fullPage: true });
    report.proofs.aie_memory_mobile = {
      speaker: "Ankur Goyal",
      sourced_talks: 3,
      verified_editions: 2,
      source_evidence_link: true,
      unknown_email_preserved: true,
      missing_email_handoff_blocked_and_explained: true,
      horizontal_overflow: overflow,
    };
  });

  await stage("04c-content-library-and-live-propagation", async () => {
    await goto("/speakerops-demo/speaker-operations/widgets/sessions/");
    const originalPublicTitle = (await page.locator("article.card h2").first().innerText()).trim();
    check(originalPublicTitle, "Released sessions did not provide a title for propagation proof");

    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/content/");
    const requestName = `Browser final deck ${Date.now()}`;
    const requestForm = page.locator("#new-file-request form");
    await requestForm.getByLabel("Request name").fill(requestName);
    await requestForm.getByLabel("Instructions").fill("Upload the final presentation used on stage.");
    await requestForm.getByLabel("File rules and completion criteria").fill("PDF or PPTX, maximum 25 MB");
    await requestForm.getByLabel("Allowed extensions (operator note)").fill(".pdf,.pptx");
    await requestForm.getByLabel("Due date").fill("2026-08-20");
    await requestForm.locator("label", { hasText: "Maya Chen" }).locator("input[type=checkbox]").check();
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      requestForm.getByRole("button", { name: "Create and assign file request" }).click(),
    ]);
    check((await bodyText()).includes("assigned it to 1 speaker"), "New file request did not report one assignment");
    const library = page.locator("#deliverables-title").locator("xpath=ancestor::section[1]");
    let slideTask = library.locator("li[id^=task-]").filter({ hasText: "judge-ready-slides" }).first();
    check((await slideTask.count()) === 1, "Organizer deliverable library omitted the speaker's uploaded slides");
    let slideTaskText = await slideTask.innerText();
    check(slideTaskText.includes("v2") && slideTaskText.includes("Current/latest") && slideTaskText.includes("v1"), "Central library did not preserve and label both upload versions");
    check((await slideTask.getByRole("link", { name: /Download judge-ready-slides/ }).count()) === 2, "Central library does not expose both downloadable versions");
    const latestDownload = slideTask.getByRole("link", { name: /Download judge-ready-slides/ }).first();
    const latestHref = await latestDownload.getAttribute("href");
    const latestResponse = await page.request.get(latestHref.startsWith("http") ? latestHref : `${baseUrl}${latestHref}`);
    const latestBytes = await latestResponse.body();
    check(latestResponse.ok() && latestBytes[0] === 0x25 && latestBytes[1] === 0x50 && latestBytes[2] === 0x44 && latestBytes[3] === 0x46, "Organizer download did not open as the uploaded PDF");

    const filters = library.getByRole("form", { name: "Filter deliverables" });
    await filters.getByLabel("Speaker").selectOption({ label: "Maya Chen" });
    await filters.getByLabel("Review status").selectOption("pending");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      filters.getByRole("button", { name: "Apply filters" }).click(),
    ]);
    const filteredLibrary = page.locator("#deliverables-title").locator("xpath=ancestor::section[1]");
    const filteredTasks = filteredLibrary.locator("li[id^=task-]");
    check((await filteredTasks.count()) >= 1, "Speaker/status filters returned no pending deliverables");
    for (const row of await filteredTasks.all()) check((await row.innerText()).includes("Maya Chen"), "Faceted deliverable result leaked another speaker");
    check((await filteredLibrary.getByLabel("Speaker").inputValue()) && (await filteredLibrary.getByLabel("Review status").inputValue()) === "pending", "Deliverable filters did not survive reload");
    slideTask = filteredTasks.filter({ hasText: "judge-ready-slides" }).first();
    check((await slideTask.count()) === 1, "Filtered library omitted the expected slide task");
    const supportingUploadTask = filteredTasks.filter({ hasText: "Upload supporting document" }).first();
    check((await supportingUploadTask.count()) === 1, "Filtered library omitted the second uploaded task");

    const zipCheckbox = slideTask.locator("input[form=zip-form]");
    await zipCheckbox.check();
    await supportingUploadTask.locator("input[form=zip-form]").check();
    const zipResponsePromise = page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes("/content/latest.zip"));
    const zipDownloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download latest selected versions (.zip)" }).click();
    const [zipResponse, zipDownload] = await Promise.all([zipResponsePromise, zipDownloadPromise]);
    check(zipResponse.ok() && zipResponse.headers()["x-speakerops-file-count"] === "2", "Latest-only ZIP did not report exactly two selected files");
    const zipStream = await zipDownload.createReadStream();
    const zipChunks = [];
    for await (const chunk of zipStream) zipChunks.push(...chunk);
    const zipBytes = new Uint8Array(zipChunks);
    const zipText = zipBytes.reduce((value, byte) => value + String.fromCharCode(byte), "");
    check(zipBytes[0] === 0x50 && zipBytes[1] === 0x4b && zipText.includes("/upload-slides/v2-") && !zipText.includes("/upload-slides/v1-") && zipText.includes("/upload-supporting-document/v1-"), "Downloaded ZIP did not contain the latest version of each selected task");
    await zipDownload.saveAs(`${artifactDir}/latest-selected-deliverables.zip`);

    await goto("/orga/speakerops-demo/speaker-operations/content/");
    const reminderTask = page.locator("li[id^=task-]").filter({ hasText: requestName }).first();
    const reminderChoice = reminderTask.locator("input[form=reminder-form]");
    check(await reminderChoice.count(), "Content dashboard has no selectable outstanding reminder recipient");
    await reminderChoice.check();
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.getByRole("button", { name: "Send reminders to selected outstanding tasks" }).click(),
    ]);
    check((await bodyText()).includes("Queued 1 selected outstanding reminder"), "Selected content reminder did not queue exactly one delivery");
    await goto("/orga/event/speakerops-demo/mails/outbox/");
    await page.locator("#id_q").fill(requestName);
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.getByRole("button", { name: "Search", exact: true }).click(),
    ]);
    const contentReminderSubject = `Speaker action needed: ${requestName} · DemoCon 2026`;
    const contentMailRow = page.locator("tr").filter({ hasText: contentReminderSubject }).filter({ hasText: "Maya Chen" }).first();
    check((await contentMailRow.count()) === 1, "Selected content reminder did not reach the native queued-mail outbox");
    await contentMailRow.getByRole("link", { name: contentReminderSubject, exact: true }).click();
    await page.waitForLoadState("domcontentloaded");
    const contentMailText = await page.getByLabel("Text").inputValue();
    check((await page.getByLabel("Subject").inputValue()) === contentReminderSubject && contentMailText.includes(requestName) && contentMailText.includes("2026-08-20"), "Queued content reminder omitted its requested deliverable or due date");
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      page.getByRole("button", { name: "Save and send" }).click(),
    ]);
    await goto("/orga/event/speakerops-demo/mails/sent");
    const sentContentRow = page.locator("tr").filter({ hasText: contentReminderSubject }).filter({ hasText: "Maya Chen" }).first();
    check((await sentContentRow.count()) === 1, "Content reminder left the outbox but did not appear in sent mail");

    await goto("/orga/speakerops-demo/speaker-operations/content/");
    let contentArticle = page.locator("article[id^=session-content-]").filter({ has: page.getByRole("heading", { name: originalPublicTitle, exact: true }) }).first();
    check((await contentArticle.count()) === 1, "Content editor omitted the released session chosen for propagation proof");
    const propagatedTitle = `${originalPublicTitle} — live browser proof`;
    await contentArticle.getByLabel(/Session title/).fill(propagatedTitle);
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      contentArticle.getByRole("button", { name: "Save session content" }).click(),
    ]);
    check((await bodyText()).includes(propagatedTitle), "Organizer session edit did not persist after reload");
    for (const widget of ["sessions", "agenda", "itinerary", "speakers", "gallery"]) {
      await goto(`/speakerops-demo/speaker-operations/widgets/${widget}/`);
      check((await bodyText()).includes(propagatedTitle), `${widget} did not reflect the organizer edit without republishing`);
    }
    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/content/");
    contentArticle = page.locator("article[id^=session-content-]").filter({ has: page.getByRole("heading", { name: propagatedTitle, exact: true }) }).first();
    const revisionHistory = contentArticle.getByText(/Session revision history/).first();
    await revisionHistory.click();
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded" }),
      contentArticle.getByRole("button", { name: "Restore this session version" }).first().click(),
    ]);
    check((await bodyText()).includes(originalPublicTitle), "Session revision restore did not recover the original title");
    await goto("/speakerops-demo/speaker-operations/widgets/sessions/");
    const restoredPublicText = await bodyText();
    check(restoredPublicText.includes(originalPublicTitle) && !restoredPublicText.includes(propagatedTitle), "Public sessions did not reflect the restored content version");
    report.proofs.content_operations = { faceted_library: true, versions: 2, organizer_pdf_opened: true, latest_only_zip_files: 2, two_tasks_selected: true, slide_old_version_excluded: true, selected_reminder_queued: 1, live_widgets_without_republish: 5, revision_restored: true };
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
    await source.scrollIntoViewIfNeeded();
    await page.waitForTimeout(100);
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
          nodes: item.nodes.map((node) => ({
            target: node.target,
            html: node.html,
            summary: node.failureSummary,
          })),
        })),
        horizontal_overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth,
        overflow_nodes: [
          ...[...document.querySelectorAll("body *")]
            .filter((node) => node.getBoundingClientRect().right > window.innerWidth + 1)
            .slice(0, 12)
            .map((node) => ({ selector: `${node.tagName.toLowerCase()}.${[...node.classList].join(".")}`, right: Math.round(node.getBoundingClientRect().right), scroll_width: node.scrollWidth, client_width: node.clientWidth })),
          ...[...document.querySelectorAll("pretalx-schedule")].flatMap((host) =>
            [...(host.shadowRoot?.querySelectorAll("*") || [])]
              .filter((node) => node.getBoundingClientRect().right > window.innerWidth + 1)
              .slice(0, 12)
              .map((node) => ({ selector: `pretalx-schedule::${node.tagName.toLowerCase()}.${[...node.classList].join(".")}`, right: Math.round(node.getBoundingClientRect().right), scroll_width: node.scrollWidth, client_width: node.clientWidth })),
          ),
        ],
      };
    });
    const nativeSevere = nativeAccessibility.violations.filter((item) => ["critical", "serious"].includes(item.impact));
    check(nativeSevere.length === 0, `Native public list has serious accessibility violations: ${nativeSevere.map((item) => item.id).join(", ")}`);
    check(nativeAccessibility.horizontal_overflow <= 1, `Native public list has ${nativeAccessibility.horizontal_overflow}px horizontal overflow`);
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

  await stage("07b-public-widget-depth-and-handoffs", async () => {
    await page.context().clearCookies();
    await goto("/speakerops-demo/speaker-operations/widgets/sessions/");
    await page.evaluate(() => localStorage.clear());
    await page.reload({ waitUntil: "domcontentloaded" });
    const sessionCards = page.locator("article.card[data-filter-card]");
    check((await sessionCards.count()) === 12, "Sessions widget does not expose all 12 released sessions");
    const firstSession = sessionCards.first();
    check((await firstSession.getByText("Show more", { exact: true }).count()) === 1, "Rich session card omits its expandable description");
    check((await firstSession.locator(".speaker-line a").count()) >= 1, "Rich session card omits linked speakers");
    check((await firstSession.locator(".pill").count()) >= 3, "Rich session card omits format, track, or room metadata");
    check((await page.locator(".speaker-line .meta").count()) >= 1, "Sessions widget omits speaker title/company metadata");
    const sessionQuery = page.getByLabel("Search sessions");
    await sessionQuery.fill("Designing Calm Systems for High-Stakes Work");
    check((await page.locator("article.card[data-filter-card]:visible").count()) === 1, "Session title search did not narrow to one released card");
    const filteredSessionTitle = await page.locator("article.card[data-filter-card]:visible h2").innerText();
    await page.locator("article.card[data-filter-card]:visible h2 a").click();
    await page.waitForLoadState("domcontentloaded");
    check((await bodyText()).includes(filteredSessionTitle), "Native session detail lost the selected released session");
    await page.goBack({ waitUntil: "domcontentloaded" });
    check((await sessionQuery.inputValue()) === "Designing Calm Systems for High-Stakes Work", "Back navigation lost the session search state");
    check((await page.locator("article.card[data-filter-card]:visible").count()) === 1, "Back navigation did not restore the filtered session set");

    await goto("/speakerops-demo/speaker-operations/widgets/agenda/");
    const agendaTabs = page.locator("[data-agenda-day]");
    check((await agendaTabs.count()) >= 2, "Agenda does not expose multiple event days");
    await agendaTabs.nth(1).click();
    const selectedAgendaDay = await agendaTabs.nth(1).getAttribute("data-agenda-day");
    check(page.url().includes(`day=${selectedAgendaDay}`) && (await agendaTabs.nth(1).getAttribute("aria-selected")) === "true", "Agenda day selection did not persist in URL/ARIA state");
    const agendaRow = page.locator("[data-agenda-panel]:not([hidden]) tbody tr").first();
    const agendaCells = await agendaRow.locator("td").allTextContents();
    check(agendaCells.length === 5 && agendaCells.every((value) => value.trim()), "Agenda row omits time, session, speakers, room, or track");
    const agendaSessionTitle = (await agendaRow.locator("td[data-label=Session]").innerText()).trim();
    const agendaSpeaker = (await agendaRow.locator("td[data-label=Speakers]").innerText()).trim();
    const agendaRoom = (await agendaRow.locator("td[data-label=Room]").innerText()).trim();
    const agendaTrack = (await agendaRow.locator("td[data-label=Track]").innerText()).trim();
    await agendaRow.locator("td[data-label=Session] a").click();
    await page.waitForLoadState("domcontentloaded");
    const agendaDetailText = await bodyText();
    check(agendaDetailText.includes(agendaSessionTitle) && agendaDetailText.includes(agendaSpeaker), "Agenda detail omitted the chosen title or presenter");
    const detailRange = (await page.locator("main.detail > p time").innerText()).trim();
    check(/\d{1,2}:\d{2}\s[AP]M–\d{1,2}:\d{2}\s[AP]M/.test(detailRange), "Agenda detail omitted the full start-end time range");
    const detailFacts = await page.locator(".detail-facts").innerText();
    check(detailFacts.includes(`Room\n${agendaRoom}`) && detailFacts.includes("Format\n") && !detailFacts.includes("Format\nNot specified") && detailFacts.includes(`Track\n${agendaTrack}`), "Agenda detail omitted room, format, or track values");
    check((await page.locator("#description-title + p").innerText()).trim().length > 20, "Agenda detail omitted its session description");
    const agendaBack = page.locator("a[data-return-to=agenda]");
    check((await agendaBack.getAttribute("href")).includes(`day=${selectedAgendaDay}`) && (await agendaBack.getAttribute("href")).includes("#session-"), "Agenda detail Back control did not preserve day and row state");
    await agendaBack.click();
    await page.waitForLoadState("domcontentloaded");
    check(page.url().includes(`day=${selectedAgendaDay}`), "Agenda Back navigation lost the selected day URL");
    check((await page.locator(`[data-agenda-day='${selectedAgendaDay}']`).getAttribute("aria-selected")) === "true", "Agenda Back navigation lost the selected tab");
    check((await page.locator("[data-agenda-panel]:not([hidden]) tbody tr").first().innerText()).includes(agendaSessionTitle), "Agenda Back navigation did not restore the selected day's rows");
    report.proofs.agenda_session_detail = { full_time_range: true, room: agendaRoom, format: true, track: agendaTrack, description: true, back_restored_day_and_row: true };

    await goto("/speakerops-demo/speaker-operations/widgets/speakers/");
    const speakerCards = page.locator(".speaker-grid article.card");
    check((await speakerCards.count()) >= 10, "Speakers list is unexpectedly sparse");
    const speakerNames = await speakerCards.locator("h2").allTextContents();
    const surnameSorted = [...speakerNames].sort((left, right) => {
      const surname = (name) => name.trim().split(/\s+/).slice(-1)[0];
      return surname(left).localeCompare(surname(right)) || left.localeCompare(right);
    });
    check(JSON.stringify(speakerNames) === JSON.stringify(surnameSorted), "Speakers list is not alphabetized by surname");
    check((await speakerCards.locator(".avatar").count()) === (await speakerCards.count()), "Speaker cards do not gracefully provide a headshot or fallback");
    const speakerHeadshots = speakerCards.locator("img.avatar");
    check((await speakerHeadshots.count()) === 11, "Speakers list does not expose eleven real loaded demo headshots");
    check((await speakerCards.locator(".avatar-fallback").count()) === 1, "Speakers list does not retain exactly one deliberate photo-less fallback");
    await speakerHeadshots.first().waitFor({ state: "visible" });
    check(await speakerHeadshots.evaluateAll((images) => images.every((image) => image.complete && image.naturalWidth > 0)), "One or more speaker headshot files failed to load");
    check((await speakerCards.locator(".speaker-role").count()) >= 1, "Speakers list omits job title/company data");
    await page.getByLabel("Search speakers").fill("Maya Chen");
    check((await page.locator(".speaker-grid article.card:visible").count()) === 1, "Speaker search did not narrow the list to Maya Chen");

    await goto("/speakerops-demo/speaker-operations/widgets/gallery/");
    const galleryCards = page.locator(".speaker-grid article.card");
    check((await galleryCards.locator("img.avatar").count()) === 11, "Gallery does not expose eleven real demo headshots");
    check((await galleryCards.locator(".avatar-fallback").count()) === 1, "Gallery does not expose one intentional photo-less fallback");
    check(await galleryCards.locator("img.avatar").evaluateAll((images) => images.every((image) => image.complete && image.naturalWidth > 0)), "One or more gallery headshot files failed to load");
    check((await galleryCards.locator(".speaker-role").count()) === 12, "Gallery omits a speaker title or company");
    const gallerySearch = page.locator("#widget-search");
    await gallerySearch.fill("Maya Chen");
    const galleryFilterNavigation = page.waitForNavigation({ waitUntil: "domcontentloaded" });
    await gallerySearch.press("Enter");
    await galleryFilterNavigation;
    check((await page.locator(".speaker-grid article.card:visible").count()) === 1, "Gallery did not preserve its name filter");
    await page.locator(".speaker-grid article.card:visible").getByRole("link", { name: "Maya Chen", exact: true }).click();
    await page.waitForLoadState("domcontentloaded");
    check((await page.getByRole("heading", { name: "Biography" }).count()) === 1, "Speaker detail omits biography");
    check((await page.getByRole("heading", { name: "Scheduled sessions" }).count()) === 1, "Speaker detail omits scheduled sessions");
    const detailHeadshot = page.locator(".detail-head img.avatar");
    check((await detailHeadshot.count()) === 1 && await detailHeadshot.evaluate((image) => image.complete && image.naturalWidth > 0), "Speaker detail headshot failed to load");
    check((await page.locator(".detail-head .speaker-role").innerText()).includes("Principal Product Designer") && (await page.locator(".detail-head .speaker-role").innerText()).includes("Calm Systems Lab"), "Speaker detail omits title or company");
    const detailSession = (await page.locator(".session-list li").first().innerText()).trim();
    check(/\d{1,2}:\d{2}\s[AP]M–\d{1,2}:\d{2}\s[AP]M/.test(detailSession) && detailSession.includes("Main Stage"), "Speaker detail omits the session time range or room");
    const bioToggle = page.locator("[data-biography-toggle]");
    check(await bioToggle.isVisible(), "Speaker biography does not expose an accessible expansion control");
    check((await bioToggle.innerText()) === "Show more biography", "Speaker biography expansion control has an unclear initial name");
    await bioToggle.click();
    check((await bioToggle.getAttribute("aria-expanded")) === "true", "Speaker biography did not expand");
    const backToGallery = page.locator("a[data-return-to='gallery']");
    check((await backToGallery.getAttribute("href")).includes("q=Maya") && (await backToGallery.getAttribute("href")).includes("#speaker-"), "Speaker detail return link lost gallery filter or anchor state");
    await backToGallery.click();
    await page.waitForLoadState("domcontentloaded");
    check((await page.locator("#widget-search").inputValue()) === "Maya Chen", "Gallery return did not restore its query");
    check((await page.locator(".speaker-grid article.card:visible").count()) === 1, "Gallery return did not restore its filtered grid");

    await goto("/speakerops-demo/speaker-operations/widgets/itinerary/");
    const visibleStars = page.locator("button[data-star]:visible");
    check((await visibleStars.count()) >= 2, "Itinerary does not expose two selectable sessions on its initial day");
    const selectedTitles = await page.locator("article.card:visible h2").evaluateAll((headings) => headings.slice(0, 2).map((heading) => heading.textContent.trim()));
    await visibleStars.nth(0).click();
    await visibleStars.nth(1).click();
    check((await page.locator("[data-selected-count]").innerText()) === "2", "Personal schedule did not count two selections");
    await page.reload({ waitUntil: "domcontentloaded" });
    check((await page.locator("button[data-star][aria-pressed='true']").count()) === 2, "Personal schedule selections did not survive reload");
    const exportHref = await page.locator("[data-calendar-export]").getAttribute("href");
    check(exportHref && exportHref.includes("sessions="), "Selected-session calendar export is not active");
    const selectedIcs = await page.request.get(exportHref.startsWith("http") ? exportHref : `${baseUrl}${exportHref}`);
    const selectedIcsText = await selectedIcs.text();
    const selectedEvents = selectedIcsText.match(/BEGIN:VEVENT[\s\S]*?END:VEVENT/g) || [];
    check(selectedIcs.ok() && (selectedIcs.headers()["content-type"] || "").includes("text/calendar") && selectedEvents.length === 2, "Selected calendar export does not contain exactly two events");
    check((selectedIcs.headers()["content-disposition"] || "").includes("speakerops-demo-my-schedule.ics"), "Personal calendar export has no importable filename");
    for (const eventBlock of selectedEvents) {
      for (const property of ["UID:", "DTSTART", "DTEND", "SUMMARY:", "LOCATION:"]) check(eventBlock.includes(property), `Selected calendar event omits ${property}`);
    }
    for (const title of selectedTitles) check(selectedIcsText.includes(title), `Selected calendar export omitted ${title}`);

    await login("chair@example.org", true);
    await goto("/orga/speakerops-demo/speaker-operations/embed-builder/");
    await page.getByLabel("Widget type").selectOption("gallery");
    await page.getByLabel("Branding").selectOption("dark");
    await page.getByLabel("Fields").selectOption("compact");
    await page.getByLabel("Format", { exact: true }).selectOption("iframe");
    const iframeSnippet = await page.locator("#embed-snippet").inputValue();
    check(iframeSnippet.includes("<iframe") && iframeSnippet.includes("theme=dark") && iframeSnippet.includes("fields=compact"), "Embed builder did not encode the configured widget");
    const externalPage = await page.context().newPage();
    try {
      // Give the synthetic host a real, distinct HTTP origin. Lazy iframes in
      // Chromium are not reliably scheduled inside an about:blank document.
      await externalPage.goto("http://127.0.0.1:39001/", { waitUntil: "domcontentloaded" });
      await externalPage.setContent(`<!doctype html><title>External host</title>${iframeSnippet}`);
      const externalIframe = externalPage.locator("iframe");
      check((await externalIframe.count()) === 1, "External host did not create the generated widget frame");
      await externalIframe.scrollIntoViewIfNeeded();
      const externalWidget = externalIframe.contentFrame();
      await externalWidget.locator("[data-public-widget][data-widget='gallery']").waitFor();
      check((await externalWidget.locator(".speaker-grid article.card").count()) >= 10, "Cross-origin generated widget omitted live gallery data");
    } finally {
      await externalPage.close();
    }
    const exportChecks = [
      ["json", "application/json", "schedule"],
      ["xml", "xml", "<?xml"],
      ["ical", "text/calendar", "BEGIN:VCALENDAR"],
    ];
    for (const [format, contentType, marker] of exportChecks) {
      await page.getByLabel("Format", { exact: true }).selectOption(format);
      const outputUrl = await page.locator("#embed-snippet").inputValue();
      const output = await page.request.get(outputUrl);
      check(output.ok(), `${format} embed-builder output failed (${output.status()})`);
      check((output.headers()["content-type"] || "").toLowerCase().includes(contentType), `${format} output has the wrong content type`);
      check((await output.text()).includes(marker), `${format} output omitted its expected data marker`);
    }
    report.proofs.public_widget_depth = {
      rich_sessions: 12,
      speaker_search_and_surname_order: true,
      loaded_speaker_headshots: 11,
      deliberate_photo_less_fallbacks: 1,
      gallery_profile_fields: ["name", "headshot", "job title", "company", "biography", "sessions"],
      speaker_detail_fields: ["headshot", "name", "job title", "company", "biography", "session", "time range", "room"],
      gallery_detail_return_state: true,
      persistent_personal_schedule: 2,
      selected_ics_events: 2,
      selected_ics_import_fields: ["UID", "DTSTART", "DTEND", "SUMMARY", "LOCATION"],
      cross_origin_gallery_cards: true,
      output_formats: ["iframe", "link", "json", "xml", "ical"],
    };
  });

  if (report.console_errors.length) report.failures.push(`${report.console_errors.length} console error(s)`);
  if (report.request_failures.length) report.failures.push(`${report.request_failures.length} failed network request(s)`);
  if (report.http_errors.length) report.failures.push(`${report.http_errors.length} first-party HTTP error response(s)`);
  report.finished_at = new Date().toISOString();
  report.ok = report.failures.length === 0 && report.stages.every((item) => item.status === "passed");
  return report;
}
