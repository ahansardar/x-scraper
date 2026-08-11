const health = document.querySelector("#health");
const form = document.querySelector("#searchForm");
const summary = document.querySelector("#summary");
const tweets = document.querySelector("#tweets");
const tasks = document.querySelector("#tasks");
const retention = document.querySelector("#retention");
const runRetention = document.querySelector("#runRetention");
const metrics = document.querySelector("#metrics");
const sessions = document.querySelector("#sessions");
const taskActionsBody = document.querySelector("#taskActions");
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

async function loadRetention() {
  const data = await getJson("/api/retention");
  retention.innerHTML = `
    Keeping terminal tasks for <strong>${data.retention_days}</strong> days.
    Cleanup currently matches <strong>${data.dry_run.matched_tasks}</strong> tasks.
  `;
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
  `;
}

async function loadSessions() {
  const data = await getJson("/api/sessions");
  sessions.innerHTML = data.sessions.map((session) => `
    <tr>
      <td>${session.session_id}</td>
      <td><span class="${sessionStateClass(session.health)}">${session.health}</span></td>
      <td>${session.attempt_count} / ${session.success_count} / ${session.failure_count}</td>
      <td>${session.cooldown_until || ""}</td>
      <td>${formatSessionError(session)}</td>
      <td>${sessionActions(session)}</td>
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

function formatViews(value) {
  return value === null || value === undefined || value === ""
    ? "views unavailable"
    : `${value} views`;
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
    await waitForResult(data.result_url);
  } catch (error) {
    summary.textContent = error.message;
  }
});

async function handleTaskControl(event) {
  const button = event.target.closest("[data-replay-task], [data-cancel-task], [data-investigate-task]");
  if (!button) {
    return;
  }

  button.disabled = true;
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
    await waitForResult(data.result_url);
  } catch (error) {
    summary.textContent = error.message;
    await loadTasks();
    await loadTaskActions();
    await loadMetrics();
    await loadSessions();
  }
}

tasks.addEventListener("click", handleTaskControl);
taskActionsBody.addEventListener("click", handleTaskControl);

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
  } catch (error) {
    summary.textContent = error.message;
    await loadTaskActions();
    await loadSessions();
    await loadMetrics();
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
  } catch (error) {
    retention.textContent = error.message;
  } finally {
    runRetention.disabled = false;
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
loadRetention().catch((error) => {
  retention.textContent = error.message;
});
loadMetrics().catch((error) => {
  metrics.innerHTML = `<div><strong>error</strong><span>${error.message}</span></div>`;
});
loadSessions().catch((error) => {
  sessions.innerHTML = `<tr><td colspan="6">${error.message}</td></tr>`;
});
