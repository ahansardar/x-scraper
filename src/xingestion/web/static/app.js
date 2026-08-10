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
    </tr>
  `).join("");
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
  summary.textContent = "Planning capability request and calling X...";
  tweets.innerHTML = "";
  try {
    const data = await getJson("/api/search-tweets", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify(payload)
    });
    renderOutput(data);
    await loadTasks();
  } catch (error) {
    summary.textContent = error.message;
  }
});

loadHealth().catch((error) => {
  health.textContent = error.message;
});
loadTasks();
