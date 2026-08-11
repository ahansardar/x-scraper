const health = document.querySelector("#health");
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
let adminToken = "";

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

function adminHeaders() {
  if (!adminToken) {
    adminToken = window.prompt("Admin token") || "";
  }
  return {"x-admin-token": adminToken};
}

async function loadHealth() {
  const data = await getJson("/api/health");
  health.textContent = data.auth_ready
    ? `${data.mode} - ${data.release_id}`
    : "auth missing";
  health.classList.toggle("ok", data.auth_ready);
}

async function loadTasks() {
  const data = await getJson("/api/tasks");
  tasks.innerHTML = data.tasks.map((task) => `
    <tr>
      <td>${task.task_id.slice(0, 18)}</td>
      <td>${task.capability_id}</td>
      <td><span class="state">${task.state}</span></td>
      <td>${taskActions(task)}</td>
    </tr>
  `).join("");
}

async function loadTaskActions() {
  const data = await getJson("/api/task-actions");
  if (!data.actions.length) {
    taskActionsBody.innerHTML = `<tr><td colspan="6">No failed or retryable tasks.</td></tr>`;
    return;
  }
  taskActionsBody.innerHTML = data.actions.map((action) => `
    <tr>
      <td>${action.task_id.slice(0, 18)}</td>
      <td><span class="${taskStateClass(action.state)}">${action.state}</span></td>
      <td><span class="${severityClass(action.severity)}">${action.severity}</span></td>
      <td>${action.attempt_count} / ${action.max_attempts}</td>
      <td>${action.operator_action}</td>
      <td>${taskActionControls(action)}</td>
    </tr>
  `).join("");
}

async function loadSupportExports() {
  const data = await getJson("/api/support-exports");
  supportExportsSummary.innerHTML = `
    <strong>${data.exports.length}</strong>
    recent support exports in <code>${data.export_dir}</code>.
    Cleanup currently matches <strong>${data.dry_run.matched_exports}</strong> files older than ${data.retention_days} days.
  `;
  if (!data.exports.length) {
    supportExportsBody.innerHTML = `<tr><td colspan="5">No support exports written yet.</td></tr>`;
    return;
  }
  supportExportsBody.innerHTML = data.exports.map((item) => `
    <tr>
      <td><code>${item.name}</code></td>
      <td>${item.task_id ? item.task_id.slice(0, 18) : ""}</td>
      <td><span class="${severityClass(item.severity)}">${item.severity || "UNKNOWN"}</span></td>
      <td>${formatDateTime(item.modified_at)}</td>
      <td>
        <button class="small-button secondary" data-view-support-export="${item.name}">View</button>
        <button class="small-button secondary" data-download-support-export="${item.name}">Download</button>
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
      <td>${event.event_id.slice(0, 18)}</td>
      <td>${event.task_id.slice(0, 18)}</td>
      <td><span class="${taskStateClass(event.task_state)}">${event.task_state}</span></td>
      <td>${formatDuration(event.age_seconds)}</td>
      <td>${event.event_type}</td>
    </tr>
  `).join("");
}

async function loadStartup() {
  const data = await getJson("/api/startup");
  startupSummary.innerHTML = data.ok
    ? "Startup checks are passing."
    : "Startup checks need operator attention.";
  startupChecks.innerHTML = data.checks.map((check) => `
    <div class="check-row">
      <strong>${check.name}</strong>
      <span class="${severityClass(check.status === "FAIL" ? "HIGH" : check.status === "WARN" ? "MEDIUM" : "LOW")}">${check.status}</span>
      <code>${check.message}</code>
    </div>
  `).join("");
}

async function loadProtocolValidation() {
  const data = await getJson("/api/protocol-validation");
  const validation = data.validation;
  validationSummary.innerHTML = `
    <strong>${validation.ok ? "PASS" : "FAIL"}</strong>
    ${validation.ok_sources}/${validation.checked_sources} sources passed parser revision
    <code>${validation.parser_revision_id}</code>.
  `;
  if (!validation.results.length) {
    validationResults.innerHTML = `<tr><td colspan="5">No validation sources found.</td></tr>`;
    return;
  }
  validationResults.innerHTML = validation.results.map((result) => `
    <tr>
      <td><code>${shortPath(result.source)}</code><br>${result.source_type}</td>
      <td><span class="${severityClass(result.ok ? "LOW" : "HIGH")}">${result.ok ? "PASS" : "FAIL"}</span></td>
      <td>${result.tweet_count}</td>
      <td>${result.bottom_cursor_present ? "yes" : "no"}</td>
      <td>
        <code>${result.structural_fingerprint}</code>
        ${result.warnings.length ? `<br>${result.warnings.join("; ")}` : ""}
        ${result.error ? `<br>${result.error}` : ""}
      </td>
    </tr>
  `).join("");
}

async function loadProtocolValidationReports() {
  const data = await getJson("/api/protocol-validation/reports");
  validationReportsSummary.innerHTML = `
    <strong>${data.reports.length}</strong>
    saved validation reports in <code>${data.report_dir}</code>.
  `;
  if (!data.reports.length) {
    validationReports.innerHTML = `<tr><td colspan="4">No validation reports saved yet.</td></tr>`;
    return;
  }
  validationReports.innerHTML = data.reports.map((report) => `
    <tr>
      <td><code>${report.name}</code></td>
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
    <div><strong>${data.release_risk.action}</strong><span>release risk</span></div>
    <div><strong>${data.auth_ready ? "ready" : "missing"}</strong><span>auth state</span></div>
    <div><strong>${data.storage.secret_backend.configured ? data.storage.secret_backend.provider : "check"}</strong><span>secret backend</span></div>
  `;
}

async function loadSessions() {
  const data = await getJson("/api/sessions");
  sessions.innerHTML = data.sessions.map((session) => `
    <tr>
      <td>${session.session_id}</td>
      <td><span class="${sessionStateClass(session.health)}">${session.health}</span></td>
      <td>${formatNetworkPolicy(session.network_policy, session.network_context)}</td>
      <td>${session.attempt_count} / ${session.success_count} / ${session.failure_count}</td>
      <td>${session.cooldown_until || ""}</td>
      <td>${formatSessionError(session)}</td>
      <td>${sessionActions(session)}</td>
    </tr>
  `).join("");
}

async function loadNetworkHealth() {
  const data = await getJson("/api/network-health");
  const workerRoute = data.worker_network_context || "any";
  networkHealthSummary.innerHTML = `
    Worker route <strong>${workerRoute}</strong>.
    <strong>${data.routes.length}</strong> routes have recorded protocol attempts.
  `;
  if (!data.routes.length) {
    networkHealth.innerHTML = `<tr><td colspan="6">No protocol attempts recorded yet.</td></tr>`;
    return;
  }
  networkHealth.innerHTML = data.routes.map((route) => `
    <tr>
      <td>${route.network_context}</td>
      <td>${route.successes} / ${route.failures} / ${route.total_attempts}</td>
      <td><span class="${networkRateClass(route.failure_rate)}">${formatPercent(route.failure_rate)}</span></td>
      <td>${route.distinct_sessions}</td>
      <td>${formatDateTime(route.last_attempt_at)}</td>
      <td>${formatErrors(route.errors_by_class)}</td>
    </tr>
  `).join("");
}

function taskActions(task) {
  if (task.state === "DEAD_LETTER") {
    return `
      <button class="small-button" data-replay-task="${task.task_id}">Replay</button>
      <button class="small-button secondary" data-investigate-task="${task.task_id}">Investigate</button>
    `;
  }
  if (["CREATED", "ENQUEUED", "RETRY_SCHEDULED"].includes(task.state)) {
    return `<button class="small-button secondary" data-cancel-task="${task.task_id}">Cancel</button>`;
  }
  return "";
}

function taskActionControls(action) {
  const controls = [];
  if (action.replayable) {
    controls.push(`<button class="small-button" data-replay-task="${action.task_id}">Replay</button>`);
  }
  if (action.cancellable) {
    controls.push(`<button class="small-button secondary" data-cancel-task="${action.task_id}">Cancel</button>`);
  }
  if (action.exportable) {
    controls.push(`<button class="small-button secondary" data-investigate-task="${action.task_id}">Investigate</button>`);
    controls.push(`<button class="small-button secondary" data-export-task="${action.task_id}">Export</button>`);
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
    return `<button class="small-button" data-restore-session="${session.session_id}">Restore</button>`;
  }
  return `<button class="small-button secondary" data-disable-session="${session.session_id}">Disable</button>`;
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

function renderOutput(data) {
  summary.innerHTML = `
    <strong>${data.task.state}</strong>
    task ${data.task.task_id.slice(0, 18)} stored raw evidence
    <code>${data.raw_evidence.content_sha256.slice(0, 16)}</code>
    and parsed ${data.page.tweets.length} records.
  `;
  tweets.innerHTML = data.page.tweets.map((tweet) => `
    <article class="tweet">
      <strong>${tweet.name} @${tweet.username}</strong>
      <p>${tweet.text}</p>
      <div class="metrics">
        <span>${tweet.like_count} likes</span>
        <span>${tweet.repost_count} reposts</span>
        <span>${tweet.reply_count} replies</span>
        <span>${formatViews(tweet.view_count)}</span>
      </div>
    </article>
  `).join("");
}

function renderInvestigation(data) {
  const investigation = data.investigation;
  summary.innerHTML = `
    <strong>${investigation.task.state}</strong>
    investigation package for task ${investigation.task.task_id.slice(0, 18)}
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
    <strong>${item.state}</strong>
    support export for task ${item.task_id.slice(0, 18)}
    saved to <code>${item.path}</code>.
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
    <strong>${item.summary.package_type}</strong>
    ${item.summary.name} for task ${item.summary.task_id ? item.summary.task_id.slice(0, 18) : "unknown"}.
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
    : `${value} views`;
}

function formatDateTime(value) {
  if (!value) {
    return "";
  }
  return value.replace("T", " ").replace("+00:00", " UTC");
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
      <strong>${data.task.state}</strong>
      task ${data.task.task_id.slice(0, 18)} queued. Waiting for worker...
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
        method: "POST",
        headers: adminHeaders()
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
        method: "POST",
        headers: adminHeaders()
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
        method: "POST",
        headers: adminHeaders()
      });
      summary.innerHTML = `<strong>${data.task.state}</strong> task ${data.task.task_id.slice(0, 18)} cancelled.`;
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
      method: "POST",
      headers: adminHeaders()
    });
    summary.innerHTML = `
      <strong>${data.task.state}</strong>
      replay task ${data.task.task_id.slice(0, 18)} queued. Waiting for worker...
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
      summary.innerHTML = `Support export <code>${button.dataset.downloadSupportExport}</code> downloaded.`;
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
    headers: adminHeaders()
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
      method: "POST",
      headers: adminHeaders()
    });
    summary.innerHTML = `<strong>${data.session.health}</strong> session ${data.session.session_id} updated.`;
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

importSessions.addEventListener("click", async () => {
  importSessions.disabled = true;
  summary.textContent = "Importing session registry...";
  try {
    const data = await getJson("/api/sessions/import", {
      method: "POST",
      headers: adminHeaders()
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
      method: "POST",
      headers: adminHeaders()
    });
    retention.innerHTML = `
      Deleted <strong>${data.retention.deleted_tasks}</strong> terminal tasks
      older than <code>${data.retention.cutoff}</code>.
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
      method: "POST",
      headers: adminHeaders()
    });
    supportExportsSummary.innerHTML = `
      Deleted <strong>${data.retention.deleted_exports}</strong> support exports
      older than <code>${data.retention.cutoff}</code>.
    `;
    await loadSupportExports();
  } catch (error) {
    supportExportsSummary.textContent = error.message;
  } finally {
    runSupportExportRetention.disabled = false;
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
        "content-type": "application/json",
        ...adminHeaders()
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
      method: "POST",
      headers: adminHeaders()
    });
    validationSummary.innerHTML = `
      Saved validation report to <code>${data.saved_path}</code>.
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
      <strong>${data.task.state}</strong>
      task ${data.task.task_id.slice(0, 18)} waiting for worker...
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
});
loadTasks().catch((error) => {
  tasks.innerHTML = `<tr><td colspan="4">${error.message}</td></tr>`;
});
loadTaskActions().catch((error) => {
  taskActionsBody.innerHTML = `<tr><td colspan="6">${error.message}</td></tr>`;
});
loadSupportExports().catch((error) => {
  supportExportsSummary.textContent = error.message;
  supportExportsBody.innerHTML = `<tr><td colspan="5">${error.message}</td></tr>`;
});
loadRetention().catch((error) => {
  retention.textContent = error.message;
});
loadOutbox().catch((error) => {
  outboxSummary.textContent = error.message;
  outboxEvents.innerHTML = `<tr><td colspan="5">${error.message}</td></tr>`;
});
loadStartup().catch((error) => {
  startupSummary.textContent = error.message;
});
loadProtocolValidation().catch((error) => {
  validationSummary.textContent = error.message;
  validationResults.innerHTML = `<tr><td colspan="5">${error.message}</td></tr>`;
});
loadProtocolValidationReports().catch((error) => {
  validationReportsSummary.textContent = error.message;
  validationReports.innerHTML = `<tr><td colspan="4">${error.message}</td></tr>`;
});
loadMetrics().catch((error) => {
  metrics.innerHTML = `<div><strong>error</strong><span>${error.message}</span></div>`;
});
loadSessions().catch((error) => {
  sessions.innerHTML = `<tr><td colspan="7">${error.message}</td></tr>`;
});
loadNetworkHealth().catch((error) => {
  networkHealthSummary.textContent = error.message;
  networkHealth.innerHTML = `<tr><td colspan="6">${error.message}</td></tr>`;
});
