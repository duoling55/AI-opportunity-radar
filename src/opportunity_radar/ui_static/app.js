const state = {
  sources: [],
  batches: [],
  results: { workbooks: [], reports: [] },
  currentBatch: null,
  currentWorkbook: null,
  prompts: null,
  jobs: [],
  jobLogOpen: {},
  analysisDocuments: [],
  analysisSelection: new Set(),
  pagination: {
    sources: 1,
    batch: 1,
    analysis: 1,
    collectionJobs: 1,
    analysisJobs: 1,
    results: 1,
  },
  pageSizes: {
    sources: 5,
    batch: 10,
    analysis: 10,
    collectionJobs: 3,
    analysisJobs: 3,
    results: 10,
  },
};

const pages = {
  sources: ["信源编辑", "管理政策入口、允许域名和访问节奏。"],
  collect: ["发起采集", "选择范围和信源，在后台生成本地政策批次。"],
  batches: ["结构化数据", "检索公文元数据、规范正文和原始快照。"],
  analyze: ["发起分析", "使用 MiMo 等模型从本地批次提取可验证商机。"],
  results: ["查看结果", "筛选重点商机与政策观察，并下载完整成果。"],
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body ? { "Content-Type": "application/json" } : {},
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
  return payload;
}

function notify(message, isError = false) {
  const notice = document.querySelector("#notice");
  notice.textContent = message;
  notice.classList.toggle("error", isError);
  notice.classList.remove("hidden");
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => notice.classList.add("hidden"), 5500);
}

function localDate(offsetDays = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatSize(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function selectOptions(select, items, label, value = "name") {
  select.innerHTML = items
    .map((item) => `<option value="${escapeHtml(item[value])}">${escapeHtml(label(item))}</option>`)
    .join("");
}

function paginated(items, key) {
  const size = state.pageSizes[key];
  const totalPages = Math.max(1, Math.ceil(items.length / size));
  state.pagination[key] = Math.min(Math.max(1, state.pagination[key]), totalPages);
  const start = (state.pagination[key] - 1) * size;
  return {
    items: items.slice(start, start + size),
    totalPages,
    start,
  };
}

function renderPagination(containerId, key, totalItems, onChange) {
  const container = document.querySelector(`#${containerId}`);
  const size = state.pageSizes[key];
  const totalPages = Math.max(1, Math.ceil(totalItems / size));
  state.pagination[key] = Math.min(Math.max(1, state.pagination[key]), totalPages);
  const current = state.pagination[key];
  const pageNumbers = [];
  for (let page = Math.max(1, current - 2); page <= Math.min(totalPages, current + 2); page++) {
    pageNumbers.push(page);
  }
  container.innerHTML = `
    <span>共 ${totalItems} 条</span>
    <select aria-label="每页数量">
      ${[5, 10, 20, 50]
        .map(
          (value) =>
            `<option value="${value}" ${value === size ? "selected" : ""}>${value} 条/页</option>`,
        )
        .join("")}
    </select>
    <button data-page="${current - 1}" ${current === 1 ? "disabled" : ""}>上一页</button>
    ${pageNumbers
      .map(
        (page) =>
          `<button data-page="${page}" class="${page === current ? "active" : ""}">${page}</button>`,
      )
      .join("")}
    <button data-page="${current + 1}" ${current === totalPages ? "disabled" : ""}>下一页</button>
  `;
  container.querySelector("select").addEventListener("change", (event) => {
    state.pageSizes[key] = Number(event.target.value);
    state.pagination[key] = 1;
    onChange();
  });
  container.querySelectorAll("button[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      state.pagination[key] = Number(button.dataset.page);
      onChange();
    });
  });
}

async function loadSummary() {
  const summary = await api("/api/summary");
  const report = summary.latest_report || {};
  const cards = [
    ["已配置信源", summary.source_count],
    ["最新批次公文", summary.latest_documents],
    ["分析结果文件", summary.workbook_count],
    ["运行中任务", summary.active_jobs],
  ];
  document.querySelector("#metrics").innerHTML = cards
    .map(
      ([label, value]) =>
        `<article class="metric-card"><small>${label}</small><strong>${value}</strong></article>`,
    )
    .join("");
  if (Object.keys(report).length) {
    document.querySelector("#metrics").title =
      `最近分析：${report.priority_rows || 0} 条重点商机，` +
      `${report.observation_rows || 0} 条政策观察`;
  }
}

function setPage(page) {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.page === page);
  });
  document.querySelectorAll(".page").forEach((item) => {
    item.classList.toggle("active", item.id === `page-${page}`);
  });
  document.querySelector("#page-title").textContent = pages[page][0];
  document.querySelector("#page-subtitle").textContent = pages[page][1];
  if (page === "batches") loadSelectedBatch();
  if (page === "analyze") refreshAnalysisPage();
  if (page === "results") loadSelectedWorkbook();
}

async function loadSources() {
  state.sources = await api("/api/sources");
  state.pagination.sources = 1;
  renderSources();
  renderCollectionSourceChoices();
}

function renderSources() {
  const rows = document.querySelector("#source-rows");
  const page = paginated(state.sources, "sources");
  rows.innerHTML = page.items
    .map(
      (source) => `
        <tr data-source-id="${escapeHtml(source.source_id)}">
          <td><input class="source-enabled" type="checkbox" ${source.enabled ? "checked" : ""}></td>
          <td>
            <input class="source-name" type="text" value="${escapeHtml(source.display_name)}">
            <small>${escapeHtml(source.source_id)}</small>
          </td>
          <td><input class="source-region" type="text" value="${escapeHtml(source.region)}"></td>
          <td><input class="source-interval" type="number" min="0" step="0.5"
            value="${escapeHtml(source.request_interval_seconds)}"></td>
          <td><textarea class="source-urls">${escapeHtml(source.list_urls.join("\n"))}</textarea></td>
          <td><textarea class="source-domains">${escapeHtml(source.allowed_domains.join("\n"))}</textarea></td>
          <td><input class="source-version" type="text"
            value="${escapeHtml(source.adapter_version)}"></td>
        </tr>`,
    )
    .join("");
  renderPagination("source-pagination", "sources", state.sources.length, () => {
    syncVisibleSources();
    renderSources();
  });
}

function renderCollectionSourceChoices() {
  const enabled = state.sources.filter((source) => source.enabled);
  document.querySelector("#collect-sources").innerHTML = enabled
    .map(
      (source) => `
        <label class="choice-card">
          <input type="checkbox" name="collect-source" value="${escapeHtml(source.source_id)}"
            ${source.source_id === "zhejiang_huiqi" ? "checked" : ""}>
          <span>${escapeHtml(source.display_name)}<small>${escapeHtml(source.region)}</small></span>
        </label>`,
    )
    .join("");
}

function syncVisibleSources() {
  document.querySelectorAll("#source-rows tr").forEach((row) => {
    const source = state.sources.find((item) => item.source_id === row.dataset.sourceId);
    if (!source) return;
    source.display_name = row.querySelector(".source-name").value.trim();
    source.region = row.querySelector(".source-region").value.trim();
    source.enabled = row.querySelector(".source-enabled").checked;
    source.request_interval_seconds = Number(row.querySelector(".source-interval").value);
    source.list_urls = row
      .querySelector(".source-urls")
      .value.split(/\r?\n|;/)
      .map((item) => item.trim())
      .filter(Boolean);
    source.allowed_domains = row
      .querySelector(".source-domains")
      .value.split(/\r?\n|;/)
      .map((item) => item.trim())
      .filter(Boolean);
    source.adapter_version = row.querySelector(".source-version").value.trim();
  });
}

async function saveSources() {
  syncVisibleSources();
  state.sources = await api("/api/sources", {
    method: "PUT",
    body: JSON.stringify({ sources: state.sources }),
  });
  notify("信源配置已保存，下一次采集会使用新设置。");
  await loadSources();
  await loadSummary();
}

async function startCollection(event) {
  event.preventDefault();
  const sourceIds = [...document.querySelectorAll('[name="collect-source"]:checked')].map(
    (item) => item.value,
  );
  await api("/api/collect", {
    method: "POST",
    body: JSON.stringify({
      start_date: document.querySelector("#collect-start").value,
      end_date: document.querySelector("#collect-end").value,
      source_ids: sourceIds,
      browser_mode: document.querySelector("#browser-mode").value,
      max_pages: Number(document.querySelector("#max-pages").value),
      development_mode: document.querySelector("#development-mode").checked,
      headed: document.querySelector("#headed-browser").checked,
    }),
  });
  notify("采集任务已启动，可在任务进度中查看日志。");
  await loadJobs();
  await loadSummary();
}

function jobMarkup(job) {
  const labels = {
    running: "运行中",
    success: "已完成",
    warning: "完成但有错误",
    failed: "任务失败",
    stopped_gracefully: "已停止",
    force_stopped: "已强制停止",
    already_stopped: "已停止",
  };
  const report = job.report;
  const defaultOpen = ["running", "warning", "failed"].includes(job.status);
  const logOpen = Object.hasOwn(state.jobLogOpen, job.job_id)
    ? state.jobLogOpen[job.job_id]
    : defaultOpen;
  const reportMarkup = report
    ? `<div class="job-summary">
        <span>进入分析 ${report.changed || 0}</span>
        <span>重点商机 ${report.priority_rows || 0}</span>
        <span>政策观察 ${report.observation_rows || 0}</span>
        <span class="${report.analysis_failures ? "has-error" : ""}">
          分析失败 ${report.analysis_failures || 0}
        </span>
      </div>`
    : "";
  const stopButton =
    job.status === "running"
      ? `<button class="danger-button stop-job-button" data-job-id="${escapeHtml(job.job_id)}">
           停止采集
         </button>`
      : "";
  const statusLabel = labels[job.status] || job.status;
  return `
    <article class="job">
      <header>
        <span>${escapeHtml(job.label)}</span>
        <span class="job-status ${job.status}">${statusLabel}</span>
      </header>
      <small>${formatTime(job.started_at)}</small>
      ${stopButton}
      ${reportMarkup}
      <details class="job-log" data-job-id="${escapeHtml(job.job_id)}" ${logOpen ? "open" : ""}>
        <summary>查看详细日志（${formatSize(job.log_size || 0)}）</summary>
        <pre>${escapeHtml(job.log || "等待任务输出……")}</pre>
      </details>
      <a class="text-link job-download" href="${escapeHtml(job.log_url)}">
        下载完整日志
      </a>
    </article>`;
}

async function loadJobs() {
  state.jobs = await api("/api/jobs");
  renderJobs();
}

async function stopJob(jobId) {
  try {
    const result = await api("/api/stop-job", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    });
    if (result.status === "stopped_gracefully") {
      notify("采集任务已优雅停止，浏览器和资源已安全释放。");
    } else if (result.status === "force_stopped") {
      notify("采集任务已强制停止（优雅停止超时）。");
    } else {
      notify("采集任务已停止。");
    }
    await loadJobs();
    await loadSummary();
  } catch (error) {
    notify(error.message, true);
  }
}

function renderJobs() {
  const collectionJobs = state.jobs.filter((job) => job.label.startsWith("采集"));
  const analysisJobs = state.jobs.filter((job) => job.label.startsWith("分析"));
  const collectionPage = paginated(collectionJobs, "collectionJobs");
  const analysisPage = paginated(analysisJobs, "analysisJobs");
  document.querySelector("#collection-jobs").innerHTML =
    collectionPage.items.map(jobMarkup).join("") ||
    '<div class="empty-state">暂无采集任务</div>';
  document.querySelector("#analysis-jobs").innerHTML =
    analysisPage.items.map(jobMarkup).join("") || '<div class="empty-state">暂无分析任务</div>';
  document.querySelectorAll(".job-log").forEach((details) => {
    details.addEventListener("toggle", () => {
      state.jobLogOpen[details.dataset.jobId] = details.open;
    });
  });
  document.querySelectorAll(".stop-job-button").forEach((button) => {
    button.addEventListener("click", () => {
      stopJob(button.dataset.jobId);
    });
  });
  renderPagination(
    "collection-job-pagination",
    "collectionJobs",
    collectionJobs.length,
    renderJobs,
  );
  renderPagination(
    "analysis-job-pagination",
    "analysisJobs",
    analysisJobs.length,
    renderJobs,
  );
}

async function loadBatches() {
  state.batches = await api("/api/batches");
  const label = (item) =>
    `${item.name} · ${item.document_count} 篇 · ${formatTime(item.modified_at)}`;
  selectOptions(document.querySelector("#batch-select"), state.batches, label);
  selectOptions(document.querySelector("#analysis-batch"), state.batches, label);
  if (state.batches.length) {
    await Promise.all([loadSelectedBatch(), loadAnalysisDocuments()]);
  }
}

async function loadSelectedBatch() {
  const name = document.querySelector("#batch-select").value;
  if (!name) return;
  const query = encodeURIComponent(document.querySelector("#batch-query").value);
  const source = encodeURIComponent(document.querySelector("#batch-source").value);
  state.currentBatch = await api(
    `/api/batch?name=${encodeURIComponent(name)}&q=${query}&source=${source}`,
  );
  state.pagination.batch = 1;
  renderBatchDocuments();
}

function renderBatchDocuments() {
  const batch = state.currentBatch;
  if (!batch) return;
  document.querySelector("#batch-summary").innerHTML = [
    ["当前公文", batch.documents.length],
    ["发现", batch.report.discovered],
    ["采集", batch.report.collected],
    ["跳过", batch.report.skipped],
    ["解析失败", batch.report.parse_failures],
    ["模式", batch.development_mode ? "开发" : "合规"],
  ]
    .map(([label, value]) => `<span class="stat-pill">${label}<strong>${value}</strong></span>`)
    .join("");
  const sourceSelect = document.querySelector("#batch-source");
  const currentSource = sourceSelect.value;
  sourceSelect.innerHTML =
    '<option value="">全部信源</option>' +
    batch.source_ids
      .map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`)
      .join("");
  sourceSelect.value = batch.source_ids.includes(currentSource) ? currentSource : "";
  const page = paginated(batch.documents, "batch");
  document.querySelector("#batch-rows").innerHTML =
    page.items
      .map(
        (document) => `
          <tr>
            <td>${escapeHtml(document.publish_date || "—")}</td>
            <td><a class="text-link" href="${escapeHtml(document.detail_url)}"
              target="_blank" rel="noreferrer">${escapeHtml(document.title)}</a></td>
            <td>${escapeHtml(document.source_name)}</td>
            <td>${escapeHtml(document.region)}</td>
            <td>${escapeHtml(document.publisher || "—")}</td>
            <td>${document.text_length.toLocaleString()}</td>
            <td><button class="secondary-button document-button"
              data-id="${escapeHtml(document.policy_id)}">详情</button></td>
          </tr>`,
      )
      .join("") || '<tr><td colspan="7"><div class="empty-state">没有匹配公文</div></td></tr>';
  document.querySelectorAll(".document-button").forEach((button) => {
    button.addEventListener("click", () => showDocument(button.dataset.id));
  });
  renderPagination(
    "batch-pagination",
    "batch",
    batch.documents.length,
    renderBatchDocuments,
  );
}

async function showDocument(policyId) {
  const batchName = document.querySelector("#batch-select").value;
  const policy = await api(
    `/api/document?batch=${encodeURIComponent(batchName)}&id=${encodeURIComponent(policyId)}`,
  );
  document.querySelector("#modal-title").textContent = policy.title;
  document.querySelector("#modal-content").innerHTML = `
    <dl>
      <dt>信源</dt><dd>${escapeHtml(policy.source_name)}</dd>
      <dt>地区</dt><dd>${escapeHtml(policy.region)}</dd>
      <dt>发布机构</dt><dd>${escapeHtml(policy.publisher || "—")}</dd>
      <dt>文号</dt><dd>${escapeHtml(policy.document_number || "—")}</dd>
      <dt>发布日期</dt><dd>${escapeHtml(policy.publish_date || "—")}</dd>
      <dt>原文</dt><dd><a class="text-link" href="${escapeHtml(policy.detail_url)}"
        target="_blank" rel="noreferrer">打开政府网站</a></dd>
      <dt>快照</dt><dd><a class="text-link"
        href="/download/raw?batch=${encodeURIComponent(batchName)}&id=${encodeURIComponent(policyId)}">
        下载原始 HTML</a></dd>
    </dl>
    <div class="document-text">${escapeHtml(policy.normalized_text)}</div>`;
  document.querySelector("#document-modal").showModal();
}

async function loadAnalysisDocuments() {
  const batchName = document.querySelector("#analysis-batch").value;
  if (!batchName) return;
  const batch = await api(`/api/batch?name=${encodeURIComponent(batchName)}`);
  state.analysisDocuments = batch.documents;
  state.analysisSelection = new Set();
  state.pagination.analysis = 1;
  document.querySelector("#analysis-policy-query").value = "";
  renderAnalysisDocuments();
}

function filteredAnalysisDocuments() {
  const normalized = document
    .querySelector("#analysis-policy-query")
    .value.toLocaleLowerCase()
    .trim();
  if (!normalized) return state.analysisDocuments;
  return state.analysisDocuments.filter((policy) =>
    [policy.title, policy.publisher || "", policy.document_number || ""]
      .join(" ")
      .toLocaleLowerCase()
      .includes(normalized),
  );
}

function renderAnalysisDocuments() {
  const documents = filteredAnalysisDocuments();
  const page = paginated(documents, "analysis");
  document.querySelector("#analysis-policy-rows").innerHTML =
    page.items
      .map(
        (policy) => `
          <tr>
            <td class="check-column">
              <input class="analysis-policy-check" type="checkbox"
                data-id="${escapeHtml(policy.policy_id)}"
                ${state.analysisSelection.has(policy.policy_id) ? "checked" : ""}>
            </td>
            <td>${escapeHtml(policy.publish_date || "—")}</td>
            <td>${escapeHtml(policy.title)}</td>
            <td>${escapeHtml(policy.source_name)}</td>
            <td>${escapeHtml(policy.publisher || "—")}</td>
            <td>${policy.text_length.toLocaleString()}</td>
          </tr>`,
      )
      .join("") ||
    '<tr><td colspan="6"><div class="empty-state">没有匹配公文</div></td></tr>';
  document.querySelectorAll(".analysis-policy-check").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.analysisSelection.add(checkbox.dataset.id);
      else state.analysisSelection.delete(checkbox.dataset.id);
      renderAnalysisSelectionCount();
    });
  });
  renderAnalysisSelectionCount();
  renderPagination(
    "analysis-policy-pagination",
    "analysis",
    documents.length,
    renderAnalysisDocuments,
  );
}

function renderAnalysisSelectionCount() {
  document.querySelector("#analysis-selected-count").textContent =
    state.analysisSelection.size;
}

function selectCurrentAnalysisPage() {
  const documents = filteredAnalysisDocuments();
  const page = paginated(documents, "analysis");
  page.items.forEach((policy) => state.analysisSelection.add(policy.policy_id));
  renderAnalysisDocuments();
}

function clearAnalysisSelection() {
  state.analysisSelection.clear();
  renderAnalysisDocuments();
}

async function startAnalysis(event) {
  event.preventDefault();
  if (!state.analysisSelection.size) {
    throw new Error("请至少选择一篇公文进行分析。");
  }
  await api("/api/analyze", {
    method: "POST",
    body: JSON.stringify({
      batch_name: document.querySelector("#analysis-batch").value,
      provider: document.querySelector("#llm-provider").value,
      base_url: document.querySelector("#llm-base-url").value.trim(),
      model: document.querySelector("#llm-model").value.trim(),
      api_key: document.querySelector("#llm-api-key").value.trim(),
      system_prompt: document.querySelector("#system-prompt").value.trim(),
      user_prompt_template: document.querySelector("#user-prompt-template").value.trim(),
      policy_ids: [...state.analysisSelection],
      force: document.querySelector("#force-analysis").checked,
    }),
  });
  document.querySelector("#llm-api-key").value = "";
  notify(`已启动 ${state.analysisSelection.size} 篇公文的分析任务，API Key 未写入磁盘。`);
  await loadJobs();
  await loadSummary();
}

function renderPrompts(useBuiltIn = false) {
  if (!state.prompts) return;
  document.querySelector("#system-prompt").value = useBuiltIn
    ? state.prompts.built_in_system_prompt
    : state.prompts.system_prompt;
  document.querySelector("#user-prompt-template").value = useBuiltIn
    ? state.prompts.built_in_user_prompt_template
    : state.prompts.user_prompt_template;
  document.querySelector("#prompt-placeholders").innerHTML = state.prompts.placeholders
    .map(
      (placeholder) =>
        `<button class="placeholder" type="button" data-placeholder="${escapeHtml(placeholder)}">
          ${escapeHtml(placeholder)}
        </button>`,
    )
    .join("");
  document.querySelectorAll(".placeholder").forEach((button) => {
    button.addEventListener("click", () => {
      const editor = document.querySelector("#user-prompt-template");
      const start = editor.selectionStart;
      const end = editor.selectionEnd;
      editor.setRangeText(button.dataset.placeholder, start, end, "end");
      editor.focus();
    });
  });
}

async function loadPrompts() {
  state.prompts = await api("/api/prompts");
  renderPrompts();
}

async function savePrompts() {
  state.prompts = await api("/api/prompts", {
    method: "PUT",
    body: JSON.stringify({
      system_prompt: document.querySelector("#system-prompt").value.trim(),
      user_prompt_template: document.querySelector("#user-prompt-template").value.trim(),
    }),
  });
  renderPrompts();
  notify("提示词已保存为本机默认，后续打开页面会自动加载。");
}

function resetPrompts() {
  renderPrompts(true);
  notify("已恢复到内置默认；点击“保存为本机默认”可持久化。");
}

async function loadResults() {
  state.results = await api("/api/results");
  const workbookLabel = (item) =>
    `${item.name} · ${formatSize(item.size)} · ${formatTime(item.modified_at)}`;
  selectOptions(
    document.querySelector("#workbook-select"),
    state.results.workbooks,
    workbookLabel,
  );
  renderLatestReport();
  if (state.results.workbooks.length) await loadSelectedWorkbook();
}

function renderLatestReport() {
  const container = document.querySelector("#result-report");
  if (!state.results.reports.length) {
    container.innerHTML = "";
    return;
  }
  const report = state.results.reports[0].data;
  container.innerHTML = [
    ["进入分析", report.changed || 0],
    ["重点商机", report.priority_rows || 0],
    ["政策观察", report.observation_rows || 0],
    ["分析失败", report.analysis_failures || 0],
    ["跳过", report.skipped || 0],
  ]
    .map(([label, value]) => `<span class="stat-pill">${label}<strong>${value}</strong></span>`)
    .join("");
}

async function loadSelectedWorkbook(resetSheet = false) {
  const name = document.querySelector("#workbook-select").value;
  if (!name) return;
  const currentSheet = resetSheet ? "" : document.querySelector("#sheet-select").value;
  const query = encodeURIComponent(document.querySelector("#result-query").value);
  state.currentWorkbook = await api(
    `/api/workbook?name=${encodeURIComponent(name)}&sheet=${encodeURIComponent(currentSheet)}&q=${query}`,
  );
  state.pagination.results = 1;
  const workbook = state.currentWorkbook;
  selectOptions(
    document.querySelector("#sheet-select"),
    workbook.sheets.map((name) => ({ name })),
    (item) => item.name,
  );
  document.querySelector("#sheet-select").value = workbook.selected_sheet;
  const visibleHeaders = workbook.headers.filter(
    (header) =>
      !["免责声明", "政策原文依据", "依据位置", "行业营销开场白"].includes(header),
  );
  workbook.visibleHeaders = visibleHeaders;
  document.querySelector("#result-head").innerHTML =
    `<tr>${visibleHeaders.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr>`;
  renderWorkbookRows();
  document.querySelector("#download-workbook").href =
    `/download/result?name=${encodeURIComponent(name)}`;
}

function renderWorkbookRows() {
  const workbook = state.currentWorkbook;
  if (!workbook) return;
  const visibleHeaders = workbook.visibleHeaders;
  const page = paginated(workbook.rows, "results");
  document.querySelector("#result-rows").innerHTML =
    page.items
      .map(
        (row) =>
          `<tr>${visibleHeaders
            .map((header) => {
              const value = row[header] ?? "";
              if (header.includes("链接") && String(value).startsWith("http")) {
                return `<td><a class="text-link" href="${escapeHtml(value)}"
                  target="_blank" rel="noreferrer">打开链接</a></td>`;
              }
              return `<td>${escapeHtml(value)}</td>`;
            })
            .join("")}</tr>`,
      )
      .join("") ||
    `<tr><td colspan="${visibleHeaders.length}"><div class="empty-state">没有匹配结果</div></td></tr>`;
  renderPagination(
    "result-pagination",
    "results",
    workbook.rows.length,
    renderWorkbookRows,
  );
}

async function refreshAll() {
  try {
    await Promise.all([loadSummary(), loadSources(), loadJobs(), loadPrompts()]);
    await loadBatches();
    await loadResults();
    notify("数据已刷新。");
  } catch (error) {
    notify(error.message, true);
  }
}

async function refreshAnalysisPage() {
  try {
    await Promise.all([loadSummary(), loadJobs()]);
    await loadBatches();
  } catch (error) {
    notify(error.message, true);
  }
}

document.querySelector("#navigation").addEventListener("click", (event) => {
  const button = event.target.closest(".nav-item");
  if (button) setPage(button.dataset.page);
});
document.querySelector("#refresh-all").addEventListener("click", refreshAll);
document.querySelector("#save-sources").addEventListener("click", () => {
  saveSources().catch((error) => notify(error.message, true));
});
document.querySelector("#collect-form").addEventListener("submit", (event) => {
  startCollection(event).catch((error) => notify(error.message, true));
});
document.querySelector("#analyze-form").addEventListener("submit", (event) => {
  startAnalysis(event).catch((error) => notify(error.message, true));
});
document.querySelector("#save-prompts").addEventListener("click", () => {
  savePrompts().catch((error) => notify(error.message, true));
});
document.querySelector("#reset-prompts").addEventListener("click", resetPrompts);
document.querySelector("#batch-select").addEventListener("change", loadSelectedBatch);
document.querySelector("#search-batch").addEventListener("click", loadSelectedBatch);
document.querySelector("#batch-query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadSelectedBatch();
});
document.querySelector("#workbook-select").addEventListener("change", () => {
  loadSelectedWorkbook(true);
});
document.querySelector("#sheet-select").addEventListener("change", () => {
  loadSelectedWorkbook();
});
document.querySelector("#search-result").addEventListener("click", () => {
  loadSelectedWorkbook();
});
document.querySelector("#result-query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadSelectedWorkbook();
});
document.querySelector("#analysis-batch").addEventListener("change", loadAnalysisDocuments);
document.querySelector("#analysis-policy-query").addEventListener("input", () => {
  state.pagination.analysis = 1;
  renderAnalysisDocuments();
});
document
  .querySelector("#select-analysis-page")
  .addEventListener("click", selectCurrentAnalysisPage);
document
  .querySelector("#clear-analysis-selection")
  .addEventListener("click", clearAnalysisSelection);
document.querySelector("#close-document-modal").addEventListener("click", () => {
  document.querySelector("#document-modal").close();
});
document.querySelector("#document-modal").addEventListener("click", (event) => {
  if (event.target.id === "document-modal") event.target.close();
});
document.querySelector("#sidebar-toggle").addEventListener("click", () => {
  const collapsed = document.body.classList.toggle("sidebar-collapsed");
  const toggle = document.querySelector("#sidebar-toggle");
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.setAttribute("aria-label", collapsed ? "展开左侧菜单" : "收起左侧菜单");
  toggle.title = collapsed ? "展开左侧菜单" : "收起左侧菜单";
  window.localStorage.setItem("radar-sidebar-collapsed", String(collapsed));
});

document.querySelector("#collect-start").value = localDate(-30);
document.querySelector("#collect-end").value = localDate(0);
if (window.localStorage.getItem("radar-sidebar-collapsed") === "true") {
  document.body.classList.add("sidebar-collapsed");
  const toggle = document.querySelector("#sidebar-toggle");
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-label", "展开左侧菜单");
  toggle.title = "展开左侧菜单";
}

refreshAll();
window.setInterval(async () => {
  try {
    await loadJobs();
    await loadSummary();
  } catch {
    // A transient refresh error is surfaced on the next explicit action.
  }
}, 2500);
