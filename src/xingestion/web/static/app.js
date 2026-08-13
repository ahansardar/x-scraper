const health = document.querySelector("#health");
const statusBanner = document.querySelector("#statusBanner");
const form = document.querySelector("#searchForm");
const summary = document.querySelector("#summary");
const tweets = document.querySelector("#tweets");
const tasks = document.querySelector("#tasks");
const retention = document.querySelector("#retention");
const runRetention = document.querySelector("#runRetention");
const outboxSummary = document.querySelector("#outboxSummary");
const outboxEvents = document.querySelector("#outboxEvents");
const refreshOutbox = document.querySelector("#refreshOutbox");
const processOutbox = document.querySelector("#processOutbox");
const startupSummary = document.querySelector("#startupSummary");
const startupChecks = document.querySelector("#startupChecks");
const validationSummary = document.querySelector("#validationSummary");
const validationResults = document.querySelector("#validationResults");
const validationReportsSummary = document.querySelector("#validationReportsSummary");
const validationReports = document.querySelector("#validationReports");
const runProtocolValidation = document.querySelector("#runProtocolValidation");
const metrics = document.querySelector("#metrics");
const sessions = document.querySelector("#sessions");
const importSessions = document.querySelector("#importSessions");
const networkHealthSummary = document.querySelector("#networkHealthSummary");
const networkHealth = document.querySelector("#networkHealth");
const taskActionsBody = document.querySelector("#taskActions");
const supportExportsSummary = document.querySelector("#supportExportsSummary");
const supportExportsBody = document.querySelector("#supportExports");
const runSupportExportRetention = document.querySelector("#runSupportExportRetention");
const releaseSummary = document.querySelector("#releaseSummary");
const releaseInventory = document.querySelector("#releaseInventory");
const releaseAuditsSummary = document.querySelector("#releaseAuditsSummary");
const releaseAuditsBody = document.querySelector("#releaseAudits");
const runReleaseAuditRetention = document.querySelector("#runReleaseAuditRetention");

function escapeHtml(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return text.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  })[character]);
}

function shortId(value, length = 18) {
  return escapeHtml(String(value || "").slice(0, length));
}

async function getJson(url, options) {
  const response = await fetch(url, options);
  const data = await parseJsonResponse(response, url);
  if (!response.ok) {
    throw new Error(data.message || data.error || response.statusText);
  }
  return data;
}

async function parseJsonResponse(response, url) {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch (error) {
    const contentType = response.headers.get("content-type") || "unknown content type";
    throw new Error(`${url} returned non-JSON ${contentType} with HTTP ${response.status}`);
  }
}

let lastHealth = null;
let lastStartup = null;
let lastTaskActionsCount = null;

function updateStatusBanner() {
  if (lastHealth === null || lastStartup === null || lastTaskActionsCount === null) {
    return;
  }
  const problems = [];
  if (!lastHealth.auth_ready) {
    problems.push("X login credentials are missing");
  }
  if (!lastStartup.ok) {
    problems.push("startup checks are failing");
  }
  if (lastTaskActionsCount > 0) {
    const noun = lastTaskActionsCount === 1 ? "search needs" : "searches need";
    problems.push(`${lastTaskActionsCount} ${noun} attention`);
  }

  if (!problems.length) {
    statusBanner.className = "status-banner ok";
    statusBanner.innerHTML = "<strong>All systems operational.</strong> Ready to run searches.";
    return;
  }
  const severity = !lastHealth.auth_ready || !lastStartup.ok ? "bad" : "warn";
  statusBanner.className = `status-banner ${severity}`;
  statusBanner.innerHTML = `<strong>Needs attention:</strong> ${problems.map(escapeHtml).join(" &middot; ")}`;
}

async function loadHealth() {
  const data = await getJson("/api/health");
  health.textContent = data.auth_ready
    ? `${data.mode} - ${data.release_id}`
    : "auth missing";
  health.classList.toggle("ok", data.auth_ready);
  lastHealth = data;
  updateStatusBanner();
}

async function loadTasks() {
  const data = await getJson("/api/tasks");
  tasks.innerHTML = data.tasks.map((task) => `
    <tr>
      <td><code>${shortId(task.task_id)}</code><br><span class="muted-cell">${escapeHtml(task.capability_id)}</span></td>
      <td><span class="${taskStateClass(task.state)}">${escapeHtml(task.state)}</span></td>
      <td>${taskActions(task)}</td>
    </tr>
  `).join("");
}

async function loadTaskActions() {
  const data = await getJson("/api/task-actions");
  lastTaskActionsCount = data.actions.length;
  updateStatusBanner();
  if (!data.actions.length) {
    taskActionsBody.innerHTML = `<tr><td colspan="6">Nothing needs attention right now.</td></tr>`;
    return;
  }
  taskActionsBody.innerHTML = data.actions.map((action) => `
    <tr>
      <td><code>${shortId(action.task_id)}</code></td>
      <td><span class="${taskStateClass(action.state)}">${escapeHtml(action.state)}</span></td>
      <td><span class="${severityClass(action.severity)}">${escapeHtml(action.severity)}</span></td>
      <td>${action.attempt_count} / ${action.max_attempts}</td>
      <td>${escapeHtml(action.operator_action)}</td>
      <td>${taskActionControls(action)}</td>
    </tr>
  `).join("");
}

async function loadSupportExports() {
  const data = await getJson("/api/support-exports");
  supportExportsSummary.innerHTML = `
    <strong>${data.exports.length}</strong>
    recent support exports in <code>${escapeHtml(data.export_dir)}</code>.
    Cleanup currently matches <strong>${data.dry_run.matched_exports}</strong> files older than ${data.retention_days} days.
  `;
  if (!data.exports.length) {
    supportExportsBody.innerHTML = `<tr><td colspan="5">No support exports written yet.</td></tr>`;
    return;
  }
  supportExportsBody.innerHTML = data.exports.map((item) => `
    <tr>
      <td><code>${escapeHtml(item.name)}</code></td>
      <td>${item.task_id ? shortId(item.task_id) : ""}</td>
      <td><span class="${severityClass(item.severity)}">${escapeHtml(item.severity || "UNKNOWN")}</span></td>
      <td>${formatDateTime(item.modified_at)}</td>
      <td>
        <button class="small-button secondary" data-view-support-export="${escapeHtml(item.name)}">View</button>
        <button class="small-button secondary" data-download-support-export="${escapeHtml(item.name)}">Download</button>
      </td>
    </tr>
  `).join("");
}

async function loadRetention() {
  const data = await getJson("/api/retention");
  retention.innerHTML = `
    Keeping terminal tasks for <strong>${data.retention_days}</strong> days.
    Cleanup currently matches <strong>${data.dry_run.matched_tasks}</strong> tasks.
  `;
}

async function loadOutbox() {
  const data = await getJson("/api/outbox");
  const lag = data.stats.oldest_unpublished_lag_seconds;
  outboxSummary.innerHTML = `
    <strong>${data.stats.unpublished_events}</strong>
    unpublished events. Oldest lag:
    <strong>${lag === null || lag === undefined ? "none" : `${lag}s`}</strong>.
  `;
  if (!data.events.length) {
    outboxEvents.innerHTML = `<tr><td colspan="5">No unpublished outbox events.</td></tr>`;
    return;
  }
  outboxEvents.innerHTML = data.events.map((event) => `
    <tr>
      <td><code>${shortId(event.event_id)}</code></td>
      <td><code>${shortId(event.task_id)}</code></td>
      <td><span class="${taskStateClass(event.task_state)}">${escapeHtml(event.task_state)}</span></td>
      <td>${formatDuration(event.age_seconds)}</td>
      <td>${escapeHtml(event.event_type)}</td>
    </tr>
  `).join("");
}

async function loadStartup() {
  const data = await getJson("/api/startup");
  lastStartup = data;
  updateStatusBanner();
  startupSummary.innerHTML = data.ok
    ? "Startup checks are passing."
    : "Startup checks need operator attention.";
  startupChecks.innerHTML = data.checks.map((check) => `
    <div class="check-row">
      <strong>${escapeHtml(check.name)}</strong>
      <span class="${severityClass(check.status === "FAIL" ? "HIGH" : check.status === "WARN" ? "MEDIUM" : "LOW")}">${escapeHtml(check.status)}</span>
      <code>${escapeHtml(check.message)}</code>
    </div>
  `).join("");
}

async function loadProtocolValidation() {
  const data = await getJson("/api/protocol-validation");
  const validation = data.validation;
  validationSummary.innerHTML = `
    <strong>${validation.ok ? "PASS" : "FAIL"}</strong>
    ${validation.ok_sources}/${validation.checked_sources} sources passed parser revision
    <code>${escapeHtml(validation.parser_revision_id)}</code>.
  `;
  if (!validation.results.length) {
    validationResults.innerHTML = `<tr><td colspan="5">No validation sources found.</td></tr>`;
    return;
  }
  validationResults.innerHTML = validation.results.map((result) => `
    <tr>
      <td><code>${escapeHtml(shortPath(result.source))}</code><br>${escapeHtml(result.source_type)}</td>
      <td><span class="${severityClass(result.ok ? "LOW" : "HIGH")}">${result.ok ? "PASS" : "FAIL"}</span></td>
      <td>${result.tweet_count}</td>
      <td>${result.bottom_cursor_present ? "yes" : "no"}</td>
      <td>
        <code>${escapeHtml(result.structural_fingerprint)}</code>
        ${result.warnings.length ? `<br>${escapeHtml(result.warnings.join("; "))}` : ""}
        ${result.error ? `<br>${escapeHtml(result.error)}` : ""}
      </td>
    </tr>
  `).join("");
}

async function loadProtocolValidationReports() {
  const data = await getJson("/api/protocol-validation/reports");
  validationReportsSummary.innerHTML = `
    <strong>${data.reports.length}</strong>
    saved validation reports in <code>${escapeHtml(data.report_dir)}</code>.
  `;
  if (!data.reports.length) {
    validationReports.innerHTML = `<tr><td colspan="4">No validation reports saved yet.</td></tr>`;
    return;
  }
  validationReports.innerHTML = data.reports.map((report) => `
    <tr>
      <td><code>${escapeHtml(report.name)}</code></td>
      <td><span class="${severityClass(report.ok ? "LOW" : "HIGH")}">${report.ok ? "PASS" : "FAIL"}</span></td>
      <td>${report.checked_sources - report.failed_sources}/${report.checked_sources}</td>
      <td>${formatDateTime(report.generated_at)}</td>
    </tr>
  `).join("");
}

async function loadMetrics() {
  const data = await getJson("/api/metrics");
  metrics.innerHTML = `
    <div><strong>${data.tasks.active}</strong><span>active tasks</span></div>
    <div><strong>${data.tasks.terminal}</strong><span>terminal tasks</span></div>
    <div><strong>${data.outbox.unpublished_events}</strong><span>outbox pending</span></div>
    <div><strong>${data.canonical.canonical_tweets}</strong><span>canonical tweets</span></div>
    <div><strong>${data.canonical.engagement_observations}</strong><span>engagement observations</span></div>
    <div><strong>${data.sessions.cooling_down}</strong><span>sessions cooling</span></div>
    <div><strong>${escapeHtml(data.release_risk.action)}</strong><span>release risk</span></div>
    <div><strong>${escapeHtml(data.search_route_monitoring.action)}</strong><span>search route</span></div>
    <div><strong>${data.auth_ready ? "ready" : "missing"}</strong><span>auth state</span></div>
    <div><strong>${data.storage.secret_backend.configured ? escapeHtml(data.storage.secret_backend.provider) : "check"}</strong><span>secret backend</span></div>
  `;
}

async function loadReleases() {
  const data = await getJson("/api/releases");
  const approved = data.approved_release?.release_id || "none";
  releaseSummary.innerHTML = `
    Approved release <strong>${escapeHtml(approved)}</strong>
    from <code>${escapeHtml(shortPath(data.manifest_dir))}</code>.
  `;
  if (!data.releases.length) {
    releaseInventory.innerHTML = `<tr><td colspan="5">No protocol release manifests found.</td></tr>`;
    return;
  }
  releaseInventory.innerHTML = data.releases.map((release) => `
    <tr>
      <td>
        <code>${escapeHtml(release.release_id)}</code>
        ${release.approved ? `<br><span class="state">APPROVED</span>` : ""}
      </td>
      <td>${escapeHtml(release.manifest_status)}</td>
      <td><span class="${releaseHealthClass(release.health)}">${escapeHtml(release.health)}</span></td>
      <td>
        <code>${escapeHtml((release.recipe_revision_ids || []).join(", "))}</code>
        <br>${formatPromotionSafety(release.promotion_safety)}
      </td>
      <td>${release.approved ? "" : release.approval_allowed ? `<button class="small-button" data-approve-release="${escapeHtml(release.release_id)}">Approve</button>` : `<span class="state bad">Blocked</span>`}</td>
    </tr>
  `).join("");
}

async function loadReleaseAudits() {
  const data = await getJson("/api/releases/audits");
  releaseAuditsSummary.innerHTML = `
    <strong>${data.audits.length}</strong>
    recent promotion audits in <code>${escapeHtml(data.audit_dir)}</code>.
    Cleanup currently matches <strong>${data.dry_run.matched_audits}</strong> files older than ${data.retention_days} days.
  `;
  if (!data.audits.length) {
    releaseAuditsBody.innerHTML = `<tr><td colspan="5">No promotion audits written yet.</td></tr>`;
    return;
  }
  releaseAuditsBody.innerHTML = data.audits.map((audit) => `
    <tr>
      <td><code>${escapeHtml(audit.name)}</code><br><span class="muted-cell">${shortId(audit.release_id, 24)}</span></td>
      <td>${escapeHtml(audit.action || "UNKNOWN")}</td>
      <td>
        <span class="${severityClass(audit.safety_ok ? "LOW" : "HIGH")}">${audit.safety_ok ? "safe" : "blocked"}</span>
        ${audit.approved ? `<br><span class="state">approved</span>` : ""}
        ${audit.forced ? `<br><span class="state warn">forced</span>` : ""}
      </td>
      <td>${formatDateTime(audit.modified_at)}</td>
      <td>
        <button class="small-button secondary" data-view-release-audit="${escapeHtml(audit.name)}">View</button>
        <button class="small-button secondary" data-download-release-audit="${escapeHtml(audit.name)}">Download</button>
      </td>
    </tr>
  `).join("");
}

async function loadSessions() {
  const data = await getJson("/api/sessions");
  sessions.innerHTML = data.sessions.map((session) => `
    <tr>
      <td><code>${escapeHtml(session.session_id)}</code></td>
      <td><span class="${sessionStateClass(session.health)}">${escapeHtml(session.health)}</span></td>
      <td>${escapeHtml(formatNetworkPolicy(session.network_policy, session.network_context))}</td>
      <td>${session.attempt_count} / ${session.success_count} / ${session.failure_count}</td>
      <td>${escapeHtml(session.cooldown_until || "")}</td>
      <td>${escapeHtml(formatSessionError(session))}</td>
      <td>${sessionActions(session)}</td>
    </tr>
  `).join("");
}

async function loadNetworkHealth() {
  const data = await getJson("/api/network-health");
  const workerRoute = data.worker_network_context || "any";
  networkHealthSummary.innerHTML = `
    Worker route <strong>${escapeHtml(workerRoute)}</strong>.
    <strong>${data.routes.length}</strong> routes have recorded protocol attempts.
  `;
  if (!data.routes.length) {
    networkHealth.innerHTML = `<tr><td colspan="7">No protocol attempts recorded yet.</td></tr>`;
    return;
  }
  networkHealth.innerHTML = data.routes.map((route) => `
    <tr>
      <td><code>${escapeHtml(route.network_context)}</code></td>
      <td>${route.successes} / ${route.failures} / ${route.total_attempts}</td>
      <td><span class="${networkRateClass(route.failure_rate)}">${formatPercent(route.failure_rate)}</span></td>
      <td>${route.distinct_sessions}</td>
      <td>${formatDateTime(route.last_attempt_at)}</td>
      <td>${escapeHtml(formatErrors(route.errors_by_class))}</td>
      <td>${formatRouteRecommendation(route.recommendation)}</td>
    </tr>
  `).join("");
}

function taskActions(task) {
  if (task.state === "DEAD_LETTER") {
    return `
      <button class="small-button" data-replay-task="${escapeHtml(task.task_id)}">Replay</button>
      <button class="small-button secondary" data-investigate-task="${escapeHtml(task.task_id)}">Investigate</button>
    `;
  }
  if (["CREATED", "ENQUEUED", "RETRY_SCHEDULED"].includes(task.state)) {
    return `<button class="small-button secondary" data-cancel-task="${escapeHtml(task.task_id)}">Cancel</button>`;
  }
  return "";
}

function taskActionControls(action) {
  const controls = [];
  if (action.replayable) {
    controls.push(`<button class="small-button" data-replay-task="${escapeHtml(action.task_id)}">Replay</button>`);
  }
  if (action.cancellable) {
    controls.push(`<button class="small-button secondary" data-cancel-task="${escapeHtml(action.task_id)}">Cancel</button>`);
  }
  if (action.exportable) {
    controls.push(`<button class="small-button secondary" data-investigate-task="${escapeHtml(action.task_id)}">Investigate</button>`);
    controls.push(`<button class="small-button secondary" data-export-task="${escapeHtml(action.task_id)}">Export</button>`);
  }
  return controls.join(" ");
}

function taskStateClass(state) {
  if (state === "RETRY_SCHEDULED") {
    return "state warn";
  }
  if (state === "DEAD_LETTER") {
    return "state bad";
  }
  return "state";
}

function severityClass(severity) {
  if (severity === "CRITICAL" || severity === "HIGH") {
    return "state bad";
  }
  if (severity === "MEDIUM") {
    return "state warn";
  }
  return "state";
}

function sessionActions(session) {
  if (session.health !== "HEALTHY") {
    return `<button class="small-button" data-restore-session="${escapeHtml(session.session_id)}">Restore</button>`;
  }
  return `<button class="small-button secondary" data-disable-session="${escapeHtml(session.session_id)}">Disable</button>`;
}

function sessionStateClass(health) {
  if (health === "HEALTHY") {
    return "state";
  }
  if (health === "DEGRADED") {
    return "state warn";
  }
  return "state bad";
}

function formatSessionError(session) {
  if (!session.last_error_class) {
    return "";
  }
  const message = session.last_error_message ? `: ${session.last_error_message}` : "";
  return `${session.last_error_class}${message}`;
}

function formatNetworkPolicy(policy, fallback) {
  if (!policy) {
    return fallback || "";
  }
  const details = [policy.route, policy.region].filter(Boolean).join(" / ");
  return details ? `${policy.kind}: ${details}` : policy.kind;
}

function networkRateClass(value) {
  if (value >= 0.8) {
    return "state bad";
  }
  if (value >= 0.5) {
    return "state warn";
  }
  return "state";
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function formatErrors(errors) {
  const entries = Object.entries(errors || {});
  if (!entries.length) {
    return "";
  }
  return entries.map(([name, count]) => `${name}: ${count}`).join("; ");
}

function formatRouteRecommendation(recommendation) {
  if (!recommendation) {
    return `<span class="state">monitor</span>`;
  }
  return `
    <span class="${severityClass(recommendation.severity)}">${escapeHtml(recommendation.action)}</span>
    <br>${escapeHtml(recommendation.operator_action)}
  `;
}

function formatPromotionSafety(report) {
  if (!report) {
    return "";
  }
  const failed = (report.checks || []).filter((check) => !check.ok);
  if (!failed.length) {
    return `<span class="state">safety pass</span>`;
  }
  return `
    <span class="state bad">safety blocked</span>
    ${escapeHtml(failed.map((check) => check.name).join(", "))}
  `;
}

function renderOutput(data) {
  summary.innerHTML = `
    <strong>${escapeHtml(data.task.state)}</strong>
    task ${shortId(data.task.task_id)} stored raw evidence
    <code>${shortId(data.raw_evidence.content_sha256, 16)}</code>
    and parsed ${data.page.tweets.length} records.
  `;
  tweets.innerHTML = data.page.tweets.map((tweet) => `
    <article class="tweet">
      <strong>${escapeHtml(tweet.name)} @${escapeHtml(tweet.username)}</strong>
      <p>${escapeHtml(tweet.text)}</p>
      <div class="metrics">
        <span>${escapeHtml(tweet.like_count)} likes</span>
        <span>${escapeHtml(tweet.repost_count)} reposts</span>
        <span>${escapeHtml(tweet.reply_count)} replies</span>
        <span>${formatViews(tweet.view_count)}</span>
      </div>
    </article>
  `).join("");
}

function renderInvestigation(data) {
  const investigation = data.investigation;
  summary.innerHTML = `
    <strong>${escapeHtml(investigation.task.state)}</strong>
    investigation package for task ${shortId(investigation.task.task_id)}
    with ${investigation.diagnosis.telemetry_attempts} telemetry attempts.
  `;
  tweets.innerHTML = "";
  const packageView = document.createElement("pre");
  packageView.className = "diagnostic-pre";
  packageView.textContent = JSON.stringify(investigation, null, 2);
  tweets.appendChild(packageView);
}

function renderSupportExport(data) {
  const item = data.export;
  summary.innerHTML = `
    <strong>${escapeHtml(item.state)}</strong>
    support export for task ${shortId(item.task_id)}
    saved to <code>${escapeHtml(item.path)}</code>.
  `;
  tweets.innerHTML = "";
  const packageView = document.createElement("pre");
  packageView.className = "diagnostic-pre";
  packageView.textContent = JSON.stringify(item, null, 2);
  tweets.appendChild(packageView);
}

function renderSupportExportDetail(data) {
  const item = data.export;
  summary.innerHTML = `
    <strong>${escapeHtml(item.summary.package_type)}</strong>
    ${escapeHtml(item.summary.name)} for task ${item.summary.task_id ? shortId(item.summary.task_id) : "unknown"}.
  `;
  tweets.innerHTML = "";
  const packageView = document.createElement("pre");
  packageView.className = "diagnostic-pre";
  packageView.textContent = JSON.stringify(item.package, null, 2);
  tweets.appendChild(packageView);
}

function renderPromotionAuditDetail(data) {
  const item = data.audit;
  summary.innerHTML = `
    <strong>${escapeHtml(item.summary.package_type)}</strong>
    ${escapeHtml(item.summary.name)}
    ${item.summary.approved ? "approved" : "recorded"} release ${escapeHtml(item.summary.release_id || "unknown")}.
  `;
  tweets.innerHTML = "";
  const packageView = document.createElement("pre");
  packageView.className = "diagnostic-pre";
  packageView.textContent = JSON.stringify(item.package, null, 2);
  tweets.appendChild(packageView);
}

function formatViews(value) {
  return value === null || value === undefined || value === ""
    ? "views unavailable"
    : `${escapeHtml(value)} views`;
}

function releaseHealthClass(health) {
  if (health === "ACTIVE") {
    return "state";
  }
  if (health === "DEGRADED" || health === "STALE") {
    return "state warn";
  }
  return "state bad";
}

function formatDateTime(value) {
  if (!value) {
    return "";
  }
  return escapeHtml(value.replace("T", " ").replace("+00:00", " UTC"));
}

function formatDuration(value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (value < 60) {
    return `${value}s`;
  }
  if (value < 3600) {
    return `${Math.floor(value / 60)}m ${value % 60}s`;
  }
  return `${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m`;
}

function shortPath(value) {
  if (!value) {
    return "";
  }
  const parts = value.split(/[\\/]/);
  return parts.slice(-2).join("/");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  const payload = {
    query: formData.get("query"),
    product: formData.get("product"),
    page_size: Number(formData.get("page_size")),
    idempotency_key: `ui:${Date.now()}`
  };
  summary.textContent = "Planning capability request and dispatching worker...";
  tweets.innerHTML = "";
  try {
    const data = await getJson("/api/search-tweets", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify(payload)
    });
    summary.innerHTML = `
      <strong>${escapeHtml(data.task.state)}</strong>
      task ${shortId(data.task.task_id)} queued. Waiting for worker...
    `;
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
    await loadNetworkHealth();
    await waitForResult(data.result_url);
  } catch (error) {
    summary.textContent = error.message;
  }
});

async function handleTaskControl(event) {
  const button = event.target.closest("[data-replay-task], [data-cancel-task], [data-investigate-task], [data-export-task]");
  if (!button) {
    return;
  }

  button.disabled = true;
  if (button.dataset.exportTask) {
    summary.textContent = "Writing support export...";
    tweets.innerHTML = "";
    try {
      const data = await getJson(`/api/tasks/${button.dataset.exportTask}/export`, {
        method: "POST"
      });
      renderSupportExport(data);
      await loadSupportExports();
    } catch (error) {
      summary.textContent = error.message;
    }
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
    await loadNetworkHealth();
    return;
  }

  if (button.dataset.investigateTask) {
    summary.textContent = "Building investigation package...";
    tweets.innerHTML = "";
    try {
      const data = await getJson(`/api/tasks/${button.dataset.investigateTask}/investigate`, {
        method: "POST"
      });
      renderInvestigation(data);
    } catch (error) {
      summary.textContent = error.message;
    }
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
    await loadNetworkHealth();
    return;
  }

  if (button.dataset.cancelTask) {
    summary.textContent = "Cancelling task...";
    try {
      const data = await getJson(`/api/tasks/${button.dataset.cancelTask}/cancel`, {
        method: "POST"
      });
      summary.innerHTML = `<strong>${escapeHtml(data.task.state)}</strong> task ${shortId(data.task.task_id)} cancelled.`;
    } catch (error) {
      summary.textContent = error.message;
    }
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
    await loadNetworkHealth();
    return;
  }

  summary.textContent = "Queuing replay task...";
  tweets.innerHTML = "";
  try {
    const data = await getJson(`/api/tasks/${button.dataset.replayTask}/replay`, {
      method: "POST"
    });
    summary.innerHTML = `
      <strong>${escapeHtml(data.task.state)}</strong>
      replay task ${shortId(data.task.task_id)} queued. Waiting for worker...
    `;
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
    await loadNetworkHealth();
    await waitForResult(data.result_url);
  } catch (error) {
    summary.textContent = error.message;
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
    await loadNetworkHealth();
  }
}

tasks.addEventListener("click", handleTaskControl);
taskActionsBody.addEventListener("click", handleTaskControl);

supportExportsBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-view-support-export], [data-download-support-export]");
  if (!button) {
    return;
  }

  button.disabled = true;
  if (button.dataset.downloadSupportExport) {
    summary.textContent = "Preparing support export download...";
    tweets.innerHTML = "";
    try {
      await downloadSupportExport(button.dataset.downloadSupportExport);
      summary.innerHTML = `Support export <code>${escapeHtml(button.dataset.downloadSupportExport)}</code> downloaded.`;
    } catch (error) {
      summary.textContent = error.message;
    } finally {
      button.disabled = false;
    }
    return;
  }

  summary.textContent = "Loading support export...";
  tweets.innerHTML = "";
  try {
    const data = await getJson(`/api/support-exports/${encodeURIComponent(button.dataset.viewSupportExport)}`);
    renderSupportExportDetail(data);
  } catch (error) {
    summary.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function downloadSupportExport(name) {
  const response = await fetch(`/api/support-exports/${encodeURIComponent(name)}/download`, {
    headers: {}
  });
  if (!response.ok) {
    const data = await parseJsonResponse(response, `/api/support-exports/${name}/download`);
    throw new Error(data.message || response.statusText);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

sessions.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-restore-session], [data-disable-session]");
  if (!button) {
    return;
  }

  button.disabled = true;
  const sessionId = button.dataset.restoreSession || button.dataset.disableSession;
  const action = button.dataset.restoreSession ? "restore" : "disable";
  summary.textContent = `${action === "restore" ? "Restoring" : "Disabling"} session...`;
  try {
    const data = await getJson(`/api/sessions/${sessionId}/${action}`, {
      method: "POST"
    });
    summary.innerHTML = `<strong>${escapeHtml(data.session.health)}</strong> session ${escapeHtml(data.session.session_id)} updated.`;
    await loadTaskActions();
    await loadSessions();
    await loadMetrics();
    await loadNetworkHealth();
  } catch (error) {
    summary.textContent = error.message;
    await loadTaskActions();
    await loadSessions();
    await loadMetrics();
    await loadNetworkHealth();
  }
});

releaseInventory.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-approve-release]");
  if (!button) {
    return;
  }

  button.disabled = true;
  releaseSummary.textContent = "Approving protocol release...";
  try {
    const data = await getJson("/api/releases/approve", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({
        release_id: button.dataset.approveRelease,
        reason: "operator_console_approved",
        force: false
      })
    });
    releaseSummary.innerHTML = `
      Approved <strong>${escapeHtml(data.approved_release.release_id)}</strong>
      from <code>${escapeHtml(shortPath(data.manifest_path))}</code>.
    `;
    await loadHealth();
    await loadReleases();
    await loadReleaseAudits();
    await loadMetrics();
  } catch (error) {
    releaseSummary.textContent = error.message;
    await loadReleaseAudits();
  } finally {
    button.disabled = false;
  }
});

releaseAuditsBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-view-release-audit], [data-download-release-audit]");
  if (!button) {
    return;
  }

  button.disabled = true;
  if (button.dataset.downloadReleaseAudit) {
    summary.textContent = "Preparing promotion audit download...";
    tweets.innerHTML = "";
    try {
      await downloadReleaseAudit(button.dataset.downloadReleaseAudit);
      summary.innerHTML = `Promotion audit <code>${escapeHtml(button.dataset.downloadReleaseAudit)}</code> downloaded.`;
    } catch (error) {
      summary.textContent = error.message;
    } finally {
      button.disabled = false;
    }
    return;
  }

  summary.textContent = "Loading promotion audit...";
  tweets.innerHTML = "";
  try {
    const data = await getJson(`/api/releases/audits/${encodeURIComponent(button.dataset.viewReleaseAudit)}`);
    renderPromotionAuditDetail(data);
  } catch (error) {
    summary.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function downloadReleaseAudit(name) {
  const response = await fetch(`/api/releases/audits/${encodeURIComponent(name)}/download`, {
    headers: {}
  });
  if (!response.ok) {
    const data = await parseJsonResponse(response, `/api/releases/audits/${name}/download`);
    throw new Error(data.message || response.statusText);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

importSessions.addEventListener("click", async () => {
  importSessions.disabled = true;
  summary.textContent = "Importing session registry...";
  try {
    const data = await getJson("/api/sessions/import", {
      method: "POST"
    });
      summary.innerHTML = `
        Imported <strong>${data.session_import.imported}</strong>
        sessions from registry.
    `;
    await loadSessions();
    await loadMetrics();
    await loadNetworkHealth();
  } catch (error) {
    summary.textContent = error.message;
  } finally {
    importSessions.disabled = false;
  }
});

runRetention.addEventListener("click", async () => {
  runRetention.disabled = true;
  try {
    const data = await getJson("/api/retention/run", {
      method: "POST"
    });
    retention.innerHTML = `
      Deleted <strong>${data.retention.deleted_tasks}</strong> terminal tasks
      older than <code>${escapeHtml(data.retention.cutoff)}</code>.
    `;
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
    await loadNetworkHealth();
  } catch (error) {
    retention.textContent = error.message;
  } finally {
    runRetention.disabled = false;
  }
});

runSupportExportRetention.addEventListener("click", async () => {
  runSupportExportRetention.disabled = true;
  try {
    const data = await getJson("/api/support-exports/retention", {
      method: "POST"
    });
    supportExportsSummary.innerHTML = `
      Deleted <strong>${data.retention.deleted_exports}</strong> support exports
      older than <code>${escapeHtml(data.retention.cutoff)}</code>.
    `;
    await loadSupportExports();
  } catch (error) {
    supportExportsSummary.textContent = error.message;
  } finally {
    runSupportExportRetention.disabled = false;
  }
});

runReleaseAuditRetention.addEventListener("click", async () => {
  runReleaseAuditRetention.disabled = true;
  try {
    const data = await getJson("/api/releases/audits/retention", {
      method: "POST"
    });
    releaseAuditsSummary.innerHTML = `
      Deleted <strong>${data.retention.deleted_audits}</strong> promotion audits
      older than <code>${escapeHtml(data.retention.cutoff)}</code>.
    `;
    await loadReleaseAudits();
  } catch (error) {
    releaseAuditsSummary.textContent = error.message;
  } finally {
    runReleaseAuditRetention.disabled = false;
  }
});

refreshOutbox.addEventListener("click", async () => {
  refreshOutbox.disabled = true;
  try {
    await loadOutbox();
  } catch (error) {
    outboxSummary.textContent = error.message;
  } finally {
    refreshOutbox.disabled = false;
  }
});

processOutbox.addEventListener("click", async () => {
  processOutbox.disabled = true;
  summary.textContent = "Processing queued outbox events through the local worker...";
  tweets.innerHTML = "";
  try {
    const data = await getJson("/api/outbox/process", {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({limit: 5})
    });
    const result = data.outbox_process;
    outboxSummary.innerHTML = `
      Processed <strong>${result.processed_events}</strong> events.
      Pending before <strong>${result.before.unpublished_events}</strong>,
      after <strong>${result.after.unpublished_events}</strong>.
    `;
    const packageView = document.createElement("pre");
    packageView.className = "diagnostic-pre";
    packageView.textContent = JSON.stringify(result.worker_results, null, 2);
    tweets.appendChild(packageView);
    await loadOutbox();
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
  } catch (error) {
    outboxSummary.textContent = error.message;
    summary.textContent = error.message;
  } finally {
    processOutbox.disabled = false;
  }
});

runProtocolValidation.addEventListener("click", async () => {
  runProtocolValidation.disabled = true;
  validationSummary.textContent = "Running parser validation and saving report...";
  try {
    const data = await getJson("/api/protocol-validation/run", {
      method: "POST"
    });
    validationSummary.innerHTML = `
      Saved validation report to <code>${escapeHtml(data.saved_path)}</code>.
      Status <strong>${data.validation.ok ? "PASS" : "FAIL"}</strong>.
    `;
    await loadProtocolValidation();
    await loadProtocolValidationReports();
  } catch (error) {
    validationSummary.textContent = error.message;
  } finally {
    runProtocolValidation.disabled = false;
  }
});

async function waitForResult(resultUrl) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const response = await fetch(resultUrl);
    const data = await parseJsonResponse(response, resultUrl);
    if (response.status === 200) {
      renderOutput(data);
      await loadTasks();
      await loadTaskActions();
      await loadMetrics();
      await loadSessions();
      return;
    }
    if (response.status >= 500) {
      summary.textContent = data.error?.message || data.message || "Task failed";
      await loadTasks();
      await loadTaskActions();
      await loadMetrics();
      await loadSessions();
      return;
    }
    summary.innerHTML = `
      <strong>${escapeHtml(data.task.state)}</strong>
      task ${shortId(data.task.task_id)} waiting for worker...
    `;
    await delay(1500);
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
    await loadNetworkHealth();
  }
  summary.textContent = "Timed out waiting for worker result.";
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

loadHealth().catch((error) => {
  health.textContent = error.message;
  statusBanner.className = "status-banner bad";
  statusBanner.textContent = `Could not reach the API: ${error.message}`;
});
loadTasks().catch((error) => {
  tasks.innerHTML = `<tr><td colspan="3">${escapeHtml(error.message)}</td></tr>`;
});
loadTaskActions().catch((error) => {
  taskActionsBody.innerHTML = `<tr><td colspan="6">${escapeHtml(error.message)}</td></tr>`;
  lastTaskActionsCount = 0;
  updateStatusBanner();
});
loadSupportExports().catch((error) => {
  supportExportsSummary.textContent = error.message;
  supportExportsBody.innerHTML = `<tr><td colspan="5">${escapeHtml(error.message)}</td></tr>`;
});
loadRetention().catch((error) => {
  retention.textContent = error.message;
});
loadOutbox().catch((error) => {
  outboxSummary.textContent = error.message;
  outboxEvents.innerHTML = `<tr><td colspan="5">${escapeHtml(error.message)}</td></tr>`;
});
loadStartup().catch((error) => {
  startupSummary.textContent = error.message;
  lastStartup = { ok: false };
  updateStatusBanner();
});
loadProtocolValidation().catch((error) => {
  validationSummary.textContent = error.message;
  validationResults.innerHTML = `<tr><td colspan="5">${escapeHtml(error.message)}</td></tr>`;
});
loadProtocolValidationReports().catch((error) => {
  validationReportsSummary.textContent = error.message;
  validationReports.innerHTML = `<tr><td colspan="4">${escapeHtml(error.message)}</td></tr>`;
});
loadMetrics().catch((error) => {
  metrics.innerHTML = `<div><strong>error</strong><span>${escapeHtml(error.message)}</span></div>`;
});
loadReleases().catch((error) => {
  releaseSummary.textContent = error.message;
  releaseInventory.innerHTML = `<tr><td colspan="5">${escapeHtml(error.message)}</td></tr>`;
});
loadReleaseAudits().catch((error) => {
  releaseAuditsSummary.textContent = error.message;
  releaseAuditsBody.innerHTML = `<tr><td colspan="5">${escapeHtml(error.message)}</td></tr>`;
});
loadSessions().catch((error) => {
  sessions.innerHTML = `<tr><td colspan="7">${escapeHtml(error.message)}</td></tr>`;
});
loadNetworkHealth().catch((error) => {
  networkHealthSummary.textContent = error.message;
  networkHealth.innerHTML = `<tr><td colspan="7">${escapeHtml(error.message)}</td></tr>`;
});
