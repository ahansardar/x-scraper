const health = document.querySelector("#health");
const form = document.querySelector("#searchForm");
const summary = document.querySelector("#summary");
const tweets = document.querySelector("#tweets");
const tasks = document.querySelector("#tasks");

async function getJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || response.statusText);
  }
  return data;
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

function taskActions(task) {
  if (task.state === "DEAD_LETTER") {
    return `<button class="small-button" data-replay-task="${task.task_id}">Replay</button>`;
  }
  if (["CREATED", "ENQUEUED", "RETRY_SCHEDULED"].includes(task.state)) {
    return `<button class="small-button secondary" data-cancel-task="${task.task_id}">Cancel</button>`;
  }
  return "";
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
    await waitForResult(data.result_url);
  } catch (error) {
    summary.textContent = error.message;
  }
});

tasks.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-replay-task], [data-cancel-task]");
  if (!button) {
    return;
  }

  button.disabled = true;
  if (button.dataset.cancelTask) {
    summary.textContent = "Cancelling task...";
    try {
      const data = await getJson(`/api/tasks/${button.dataset.cancelTask}/cancel`, {
        method: "POST"
      });
      summary.innerHTML = `<strong>${data.task.state}</strong> task ${data.task.task_id.slice(0, 18)} cancelled.`;
    } catch (error) {
      summary.textContent = error.message;
    }
    await loadTasks();
    return;
  }

  summary.textContent = "Queuing replay task...";
  tweets.innerHTML = "";
  try {
    const data = await getJson(`/api/tasks/${button.dataset.replayTask}/replay`, {
      method: "POST"
    });
    summary.innerHTML = `
      <strong>${data.task.state}</strong>
      replay task ${data.task.task_id.slice(0, 18)} queued. Waiting for worker...
    `;
    await loadTasks();
    await waitForResult(data.result_url);
  } catch (error) {
    summary.textContent = error.message;
    await loadTasks();
  }
});

async function waitForResult(resultUrl) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const response = await fetch(resultUrl);
    const data = await response.json();
    if (response.status === 200) {
      renderOutput(data);
      await loadTasks();
      return;
    }
    if (response.status >= 500) {
      summary.textContent = data.error?.message || data.message || "Task failed";
      await loadTasks();
      return;
    }
    summary.innerHTML = `
      <strong>${data.task.state}</strong>
      task ${data.task.task_id.slice(0, 18)} waiting for worker...
    `;
    await delay(1500);
    await loadTasks();
  }
  summary.textContent = "Timed out waiting for worker result.";
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

loadHealth().catch((error) => {
  health.textContent = error.message;
});
loadTasks();
