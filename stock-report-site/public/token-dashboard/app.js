const DATA_PATHS = ["../data", "./data"];
const formatter = new Intl.NumberFormat("en-US");
const percentFormatter = new Intl.NumberFormat("en-US", { style: "percent", minimumFractionDigits: 1 });
let chartInstance = null;

async function fetchJson(file) {
  for (const base of DATA_PATHS) {
    try {
      const res = await fetch(`${base}/${file}?t=${Date.now()}`);
      if (!res.ok) continue;
      return await res.json();
    } catch (err) {
      continue;
    }
  }
  throw new Error(`Failed to load ${file} from ${DATA_PATHS.join(", ")}`);
}

async function loadData() {
  const [sessions, daily, cron, contextFiles, contextTree] = await Promise.all([
    fetchJson("sessions_summary.json"),
    fetchJson("daily_model_usage.json"),
    fetchJson("cron_costs.json"),
    fetchJson("context_files.json"),
    fetchJson("context_tree.json"),
  ]);
  return { sessions, daily, cron, contextFiles, contextTree };
}

function sumTokens(items) {
  return items.reduce((acc, item) => acc + (item.total_tokens || 0), 0);
}

function renderSummary({ sessions, daily, contextFiles }) {
  const summaryEl = document.getElementById("summary");
  const totalDaily = sumTokens(daily);
  const topDay = daily.reduce((acc, day) => (day.total_tokens > (acc?.total_tokens || 0) ? day : acc), null);
  const topFile = contextFiles[0];
  const cards = [
    { label: "Tokens (last 5 days)", value: formatter.format(totalDaily) },
    { label: "Max daily usage", value: topDay ? `${formatter.format(topDay.total_tokens)} (${topDay.date})` : "–" },
    { label: "Sessions tracked", value: formatter.format(sessions.length) },
    { label: "Heaviest context file", value: topFile ? `${topFile.path} · ${formatter.format(topFile.est_tokens)} tkn` : "–" },
  ];
  summaryEl.innerHTML = cards
    .map(
      (card) => `
        <article class="card">
          <h3>${card.label}</h3>
          <strong>${card.value}</strong>
        </article>
      `,
    )
    .join("");
}

function renderChart(daily) {
  const ctx = document.getElementById("daily-chart").getContext("2d");
  const labels = daily.map((d) => d.date);
  const datasetsMap = new Map();
  daily.forEach((day, idx) => {
    day.models.forEach((model) => {
      if (!datasetsMap.has(model.model)) {
        datasetsMap.set(model.model, { label: model.model, data: new Array(daily.length).fill(0) });
      }
      datasetsMap.get(model.model).data[idx] = model.total_tokens;
    });
  });
  const datasets = Array.from(datasetsMap.values()).map((dataset, idx) => ({
    label: dataset.label,
    data: dataset.data,
    backgroundColor: `hsla(${(idx * 67) % 360}, 70%, 55%, 0.8)`,
    stack: "tokens",
  }));
  document.getElementById("chart-subtitle").textContent = `${formatter.format(sumTokens(daily))} tokens total`;
  if (chartInstance) chartInstance.destroy();
  chartInstance = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: datasets.length > 1, position: "bottom" },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${formatter.format(ctx.parsed.y)} tokens`,
          },
        },
      },
      scales: {
        x: { stacked: true },
        y: {
          stacked: true,
          ticks: {
            callback: (value) => formatter.format(value),
          },
        },
      },
    },
  });
}

function formatDate(str) {
  return new Date(str).toISOString().replace(".000", "");
}

function renderSessions(sessions) {
  const tbody = document.querySelector("#session-table tbody");
  const filterInput = document.getElementById("session-filter");

  function applyFilter() {
    const term = filterInput.value.toLowerCase();
    tbody.innerHTML = sessions
      .filter((s) => {
        if (!term) return true;
        return (
          (s.source_label || "").toLowerCase().includes(term) ||
          s.session_type.toLowerCase().includes(term) ||
          (s.first_user_message || "").toLowerCase().includes(term)
        );
      })
      .map(
        (s) => `
          <tr>
            <td>${formatDate(s.started_at)}</td>
            <td>${s.source_label || "–"}</td>
            <td>${s.session_type}</td>
            <td class="num">${formatter.format(s.total_tokens)}</td>
            <td class="num">${formatter.format(s.input_tokens)}</td>
            <td class="num">${formatter.format(s.output_tokens)}</td>
          </tr>
        `,
      )
      .join("");
  }

  filterInput.addEventListener("input", applyFilter);
  applyFilter();
}

function renderCron(cron) {
  const tbody = document.querySelector("#cron-table tbody");
  const status = document.getElementById("cron-status");
  if (!cron.length) {
    status.textContent = "No cron-labelled sessions yet";
    tbody.innerHTML = "";
    return;
  }
  status.textContent = `${cron.length} tracked job${cron.length > 1 ? "s" : ""}`;
  tbody.innerHTML = cron
    .map(
      (job) => `
        <tr>
          <td>${job.cron}</td>
          <td class="num">${formatter.format(job.runs)}</td>
          <td class="num">${formatter.format(Math.round(job.average_tokens))}</td>
          <td class="num">${formatter.format(job.min_tokens)}</td>
          <td class="num">${formatter.format(job.max_tokens)}</td>
          <td>${job.last_run_at || "–"}</td>
        </tr>
      `,
    )
    .join("");
}

function renderContextTree(root, container) {
  function createNode(node) {
    if (node.type === "file") {
      return `<div class="file">📄 ${node.path} <span>${formatter.format(node.est_tokens)} tkn</span></div>`;
    }
    const children = (node.children || []).map(createNode).join("");
    return `
      <details>
        <summary>📁 ${node.name} <span>${formatter.format(node.est_tokens)} tkn</span></summary>
        ${children}
      </details>
    `;
  }
  container.innerHTML = createNode(root);
}

function renderContextTable(contextFiles) {
  const tbody = document.querySelector("#context-table tbody");
  const top = [...contextFiles].sort((a, b) => b.est_tokens - a.est_tokens).slice(0, 20);
  const rows = top
    .map((file) => `
      <tr>
        <td>${file.path}</td>
        <td class="num">${formatter.format(file.est_tokens)}</td>
      </tr>
    `)
    .join("");
  tbody.innerHTML = rows;
}

async function init() {
  const refreshBtn = document.getElementById("refresh-btn");
  const timestampEl = document.getElementById("data-timestamp");

  async function refresh() {
    refreshBtn.disabled = true;
    refreshBtn.textContent = "Refreshing…";
    try {
      const data = await loadData();
      renderSummary(data);
      renderChart(data.daily);
      renderSessions(data.sessions);
      renderCron(data.cron);
      renderContextTree(data.contextTree, document.getElementById("context-tree"));
      renderContextTable(data.contextFiles);
      timestampEl.textContent = `Generated ${new Date().toLocaleString()}`;
    } catch (error) {
      alert(error.message);
      console.error(error);
    } finally {
      refreshBtn.disabled = false;
      refreshBtn.textContent = "Refresh Data";
    }
  }

  refreshBtn.addEventListener("click", refresh);
  refresh();
}

init();
