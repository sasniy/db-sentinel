/* DB Sentinel — фронтенд: вкладки, i18n, CRUD подключений и правил, настройки. */

let LANG = "ru";
let DICT = {};
let META = { db_types: [], rule_types: [] };
let CONNECTIONS = [];
let RULES = [];

const t = (key) => DICT[key] || key;
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(method, url, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return resp.json();
}

function toast(text, isError = false) {
  const el = $("#toast");
  el.textContent = text;
  el.className = isError ? "error" : "";
  el.classList.remove("hidden");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add("hidden"), 4000);
}

/* ------------------------------------------------------------------ i18n */

async function setLanguage(lang, save) {
  LANG = lang;
  DICT = await api("GET", `/api/i18n/${lang}`);
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.title = t("app.title");
  $("#lang-ru").classList.toggle("active", lang === "ru");
  $("#lang-en").classList.toggle("active", lang === "en");
  if (save) await api("POST", "/api/settings", { language: lang });
  renderAll();
}

/* ------------------------------------------------------------------ tabs */

function initTabs() {
  document.querySelectorAll("nav#tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("nav#tabs button").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab").forEach((s) => s.classList.remove("active"));
      btn.classList.add("active");
      $(`#tab-${btn.dataset.tab}`).classList.add("active");
      refreshTab(btn.dataset.tab);
    });
  });
}

function refreshTab(tab) {
  if (tab === "dashboard") loadDashboard();
  if (tab === "connections") loadConnections();
  if (tab === "rules") loadRules();
  if (tab === "history") loadHistory();
  if (tab === "settings") loadSettings();
}

function renderAll() {
  const active = document.querySelector("nav#tabs button.active");
  if (active) refreshTab(active.dataset.tab);
}

/* ------------------------------------------------------------- dashboard */

async function loadDashboard() {
  const [items, conns] = await Promise.all(
    [api("GET", "/api/dashboard"), api("GET", "/api/connections")]);
  CONNECTIONS = conns;
  renderDashStats(items);
  const sel = $("#dash-conn");
  const current = sel.value;
  sel.innerHTML = `<option value="">${esc(t("dash.all_connections"))}</option>` +
    conns.map((c) => `<option value="${c.id}">${esc(c.name)} (${c.db_type})</option>`).join("");
  sel.value = current;
  const box = $("#dashboard-list");
  if (!items.length) {
    box.innerHTML = `<div class="empty">${esc(t("dash.no_rules"))}</div>`;
    return;
  }
  box.innerHTML = items.map((it) => {
    const st = it.status || "never";
    const badge = it.enabled
      ? `<span class="badge ${st}">${esc(t("status." + st))}</span>`
      : `<span class="badge off">${esc(t("common.disabled"))}</span>`;
    return `
      <div class="dash-card ${it.enabled ? st : ""}">
        <div class="dash-main">
          <div class="dash-title">${esc(it.rule_name)}
            <span class="dash-sub">· ${esc(t("ruletype." + it.rule_type))}</span></div>
          <div class="dash-sub">${esc(it.connection_name)} (${esc(it.db_type)}) ·
            ${esc(t("rule.interval"))}: ${it.interval_minutes}</div>
          <div class="dash-sub">⏱ ${esc(t("dash.auto_run"))}: ${esc(it.last_auto_at || "—")}
            · 🖐 ${esc(t("dash.manual_run"))}: ${esc(it.last_manual_at || "—")}
            · ▶ ${esc(t("dash.next_run"))}: ${esc(fmtNextRun(it.next_run_at))}</div>
          <div class="dash-msg">${esc(it.message || "")}</div>
        </div>
        <div>
          ${badge}
          <div class="dash-sub">${esc(it.checked_at || t("status.never"))}</div>
        </div>
        <button class="btn small" onclick="runRule(${it.rule_id})">${esc(t("common.run_now"))}</button>
      </div>`;
  }).join("");
}

function fmtNextRun(ts) {
  if (!ts) return "—";
  const mins = Math.round((new Date(ts.replace(" ", "T")) - Date.now()) / 60000);
  if (mins <= 0) return t("dash.now");
  return `${ts.slice(11, 16)} (${t("dash.in_about")} ${mins} ${t("dash.min")})`;
}

function renderDashStats(items) {
  const counts = { ok: 0, alert: 0, error: 0, never: 0 };
  items.filter((it) => it.enabled).forEach((it) => { counts[it.status || "never"]++; });
  const cards = [
    ["total", items.length, ""],
    ["ok", counts.ok, "ok"],
    ["alert", counts.alert, "alert"],
    ["error", counts.error, "error"],
    ["never", counts.never, "never"],
  ];
  $("#dash-stats").innerHTML = cards.map(([key, num, cls]) => `
    <div class="stat-card ${cls} ${cls === "alert" && num > 0 ? "nonzero" : ""}">
      <div class="stat-num">${num}</div>
      <div class="stat-label">${esc(t("dash." + key + "_count"))}</div>
    </div>`).join("");
}

async function runAllChecks() {
  const btn = $("#dash-run-all");
  btn.disabled = true;
  toast(t("dash.running"));
  try {
    const connId = $("#dash-conn").value;
    const q = connId ? `?connection_id=${connId}` : "";
    const res = await api("POST", `/api/rules/run-all${q}`);
    const c = { ok: 0, alert: 0, error: 0 };
    res.forEach((r) => { c[r.status]++; });
    toast(`${t("dash.run_done")}: ${t("status.ok")} ${c.ok} · ` +
      `${t("status.alert")} ${c.alert} · ${t("status.error")} ${c.error}`,
      c.alert + c.error > 0);
    await loadDashboard();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function runRule(id) {
  try {
    const res = await api("POST", `/api/rules/${id}/run`);
    toast(`${t("status." + res.status)}: ${res.message}`, res.status !== "ok");
    renderAll();
  } catch (e) { toast(e.message, true); }
}

/* ----------------------------------------------------------- connections */

const CONN_FIELDS = {
  sqlite: [["path", "conn.path", "text"]],
  postgresql: [
    ["host", "conn.host", "text"], ["port", "conn.port", "number"],
    ["database", "conn.database", "text"], ["user", "conn.user", "text"],
    ["password", "conn.password", "password"],
  ],
  clickhouse: [
    ["host", "conn.host", "text"], ["port", "conn.port", "number"],
    ["database", "conn.database", "text"], ["user", "conn.user", "text"],
    ["password", "conn.password", "password"], ["secure", "conn.secure", "checkbox"],
    ["verify", "conn.verify", "checkbox"], ["ca_cert", "conn.ca_cert", "text"],
  ],
};
const CONN_DEFAULTS = {
  sqlite: { path: "" },
  postgresql: { host: "localhost", port: 5432, database: "postgres", user: "postgres", password: "" },
  clickhouse: { host: "localhost", port: 8123, database: "default", user: "default", password: "",
    secure: false, verify: true, ca_cert: "" },
};

/* Общий рендер поля формы; чекбоксы и текстовые поля рисуются по-разному. */
function fieldHtml(name, label, widget, val) {
  if (widget === "table")
    return `<label>${esc(t(label))}</label>
      <input data-param="${name}" list="dl-tables" autocomplete="off" value="${esc(val)}">`;
  if (widget === "column")
    return `<label>${esc(t(label))}</label>
      <input data-param="${name}" list="dl-columns" autocomplete="off" value="${esc(val)}">`;
  if (widget.startsWith("select:")) {
    const opts = widget.slice(7).split(",").map(
      (o) => `<option value="${o}" ${o === val ? "selected" : ""}>${esc(t("opt." + o))}</option>`).join("");
    return `<label>${esc(t(label))}</label><select data-param="${name}">${opts}</select>`;
  }
  if (widget === "checkbox")
    return `<label class="check"><input data-param="${name}" type="checkbox" ${val ? "checked" : ""}>
      <span>${esc(t(label))}</span></label>`;
  if (widget === "textarea")
    return `<label>${esc(t(label))}</label><textarea data-param="${name}">${esc(val)}</textarea>`;
  if (widget === "operator") {
    const ops = [">", ">=", "<", "<=", "==", "!="].map(
      (op) => `<option ${op === val ? "selected" : ""}>${op}</option>`).join("");
    return `<label>${esc(t(label))}</label><select data-param="${name}">${ops}</select>`;
  }
  return `<label>${esc(t(label))}</label><input data-param="${name}" type="${widget}" value="${esc(val)}">`;
}

function collectParams(rootSel) {
  const params = {};
  document.querySelectorAll(`${rootSel} [data-param]`).forEach((el) => {
    if (el.type === "checkbox") params[el.dataset.param] = el.checked;
    else params[el.dataset.param] = el.type === "number" ? Number(el.value) : el.value;
  });
  return params;
}

async function loadConnections() {
  CONNECTIONS = await api("GET", "/api/connections");
  const box = $("#connections-list");
  if (!CONNECTIONS.length) {
    box.innerHTML = `<div class="empty">${esc(t("common.empty"))}</div>`;
    return;
  }
  box.innerHTML = `<table><tr>
      <th>ID</th><th>${esc(t("common.name"))}</th><th>${esc(t("conn.db_type"))}</th>
      <th></th><th>${esc(t("common.actions"))}</th></tr>` +
    CONNECTIONS.map((c) => {
      const info = c.db_type === "sqlite"
        ? c.params.path
        : `${c.params.host}:${c.params.port}/${c.params.database}`;
      return `<tr><td>${c.id}</td><td>${esc(c.name)}</td><td>${esc(c.db_type)}</td>
        <td class="dash-sub">${esc(info)}</td>
        <td>
          <button class="btn small" onclick="editConnection(${c.id})">${esc(t("common.edit"))}</button>
          <button class="btn small danger" onclick="deleteConnection(${c.id})">${esc(t("common.delete"))}</button>
        </td></tr>`;
    }).join("") + "</table>";
}

function connectionForm(conn) {
  const dbType = conn ? conn.db_type : "sqlite";
  const typeOptions = META.db_types.map(
    (dt) => `<option value="${dt}" ${dt === dbType ? "selected" : ""}>${dt}</option>`).join("");
  const fields = (type, params) => CONN_FIELDS[type].map(
    ([name, label, kind]) => fieldHtml(name, label, kind, params[name] ?? "")).join("");
  openModal(t(conn ? "conn.edit" : "conn.new"), `
      <label>${esc(t("common.name"))}</label>
      <input id="f-conn-name" value="${esc(conn ? conn.name : "")}">
      <label>${esc(t("conn.db_type"))}</label>
      <select id="f-conn-type">${typeOptions}</select>
      <div id="f-conn-params">${fields(dbType, conn ? conn.params : CONN_DEFAULTS[dbType])}</div>
      <button class="btn" id="f-conn-test">${esc(t("common.test"))}</button>`,
    async () => {
      const body = collectConnectionForm();
      if (conn) await api("PUT", `/api/connections/${conn.id}`, body);
      else await api("POST", "/api/connections", body);
      closeModal(); toast(t("common.saved")); loadConnections();
    });
  $("#f-conn-type").addEventListener("change", (e) => {
    $("#f-conn-params").innerHTML = fields(e.target.value, CONN_DEFAULTS[e.target.value]);
  });
  $("#f-conn-test").addEventListener("click", async () => {
    try {
      await api("POST", "/api/connections/test", collectConnectionForm());
      toast(t("conn.test_ok"));
    } catch (err) { toast(`${t("conn.test_fail")}: ${err.message}`, true); }
  });
}

function collectConnectionForm() {
  return {
    name: $("#f-conn-name").value,
    db_type: $("#f-conn-type").value,
    params: collectParams("#f-conn-params"),
  };
}

function editConnection(id) {
  connectionForm(CONNECTIONS.find((c) => c.id === id));
}
async function deleteConnection(id) {
  if (!confirm(t("common.confirm_delete"))) return;
  await api("DELETE", `/api/connections/${id}`);
  loadConnections();
}

/* ----------------------------------------------------------------- rules */

/* Поля формы по типу правила: [param, label, widget, default] */
const RULE_FIELDS = {
  freshness: [
    ["table", "rule.table", "table", ""],
    ["source_sql", "rule.source_sql", "textarea", ""],
    ["time_column", "rule.time_column", "column", ""],
    ["max_age_minutes", "rule.max_age", "number", 120],
    ["use_utc", "rule.use_utc", "checkbox", false],
  ],
  row_count: [
    ["table", "rule.table", "table", ""],
    ["source_sql", "rule.source_sql", "textarea", ""],
    ["time_column", "rule.time_column", "column", ""],
    ["window_minutes", "rule.window", "number", 1440],
    ["min_rows", "rule.min_rows", "number", 1],
    ["use_utc", "rule.use_utc", "checkbox", false],
  ],
  null_check: [
    ["table", "rule.table", "table", ""],
    ["source_sql", "rule.source_sql", "textarea", ""],
    ["column", "rule.column", "column", ""],
    ["max_null_percent", "rule.max_null_pct", "number", 5],
  ],
  duplicates: [
    ["table", "rule.table", "table", ""],
    ["source_sql", "rule.source_sql", "textarea", ""],
    ["key_columns", "rule.key_columns", "column", ""],
    ["max_duplicates", "rule.max_duplicates", "number", 0],
  ],
  anomaly: [
    ["metric_sql", "rule.metric_sql", "textarea", "SELECT COUNT(*) FROM my_table"],
    ["sigma", "rule.sigma", "number", 3],
    ["min_samples", "rule.min_samples", "number", 5],
  ],
  anomaly_history: [
    ["table", "rule.table", "table", ""],
    ["source_sql", "rule.source_sql", "textarea", ""],
    ["time_column", "rule.time_column", "column", ""],
    ["metric", "rule.metric_expr", "text", "COUNT(*)"],
    ["granularity", "rule.granularity", "select:day,hour", "day"],
    ["history_days", "rule.history_days", "number", 30],
    ["sigma", "rule.sigma", "number", 3],
    ["min_samples", "rule.min_samples", "number", 5],
    ["seasonality", "rule.seasonality", "checkbox", false],
    ["use_utc", "rule.use_utc", "checkbox", false],
  ],
  custom_sql: [
    ["sql", "rule.custom_sql", "textarea", "SELECT COUNT(*) FROM my_table"],
    ["operator", "rule.operator", "operator", ">"],
    ["threshold", "rule.threshold", "number", 0],
  ],
};

async function loadRules() {
  [CONNECTIONS, RULES] = await Promise.all(
    [api("GET", "/api/connections"), api("GET", "/api/rules")]);
  const box = $("#rules-list");
  if (!RULES.length) {
    box.innerHTML = `<div class="empty">${esc(t("common.empty"))}</div>`;
    return;
  }
  const connName = (id) => (CONNECTIONS.find((c) => c.id === id) || { name: "?" }).name;
  box.innerHTML = `<table><tr>
      <th>ID</th><th>${esc(t("common.name"))}</th><th>${esc(t("rule.type"))}</th>
      <th>${esc(t("rule.connection"))}</th><th>${esc(t("rule.interval"))}</th>
      <th>${esc(t("common.enabled"))}</th><th>${esc(t("common.actions"))}</th></tr>` +
    RULES.map((r) => `<tr>
      <td>${r.id}</td><td>${esc(r.name)}</td>
      <td>${esc(t("ruletype." + r.rule_type))}</td>
      <td>${esc(connName(r.connection_id))}</td>
      <td>${r.interval_minutes}</td>
      <td>${r.enabled ? "✅" : "⏸️"}</td>
      <td>
        <button class="btn small" onclick="runRule(${r.id})">${esc(t("common.run_now"))}</button>
        <button class="btn small" onclick="editRule(${r.id})">${esc(t("common.edit"))}</button>
        <button class="btn small danger" onclick="deleteRule(${r.id})">${esc(t("common.delete"))}</button>
      </td></tr>`).join("") + "</table>";
}

/* Схема выбранного подключения для подсказок: {таблица: [колонки]} */
let SCHEMA = {};

async function loadSchemaFor(connId) {
  SCHEMA = {};
  try {
    SCHEMA = (await api("GET", `/api/connections/${connId}/schema`)).tables || {};
  } catch (e) { /* база недоступна — подсказок не будет, поля остаются ручными */ }
  fillTableList();
  fillColumnList();
}

function fillTableList() {
  const dl = $("#dl-tables");
  if (dl) dl.innerHTML = Object.keys(SCHEMA).map(
    (tb) => `<option value="${esc(tb)}">`).join("");
}

function fillColumnList() {
  const dl = $("#dl-columns");
  if (!dl) return;
  const tableInput = document.querySelector('#f-rule-params [data-param="table"]');
  const cols = (tableInput && SCHEMA[tableInput.value.trim()]) || [];
  dl.innerHTML = cols.map((c) => `<option value="${esc(c)}">`).join("");
}

function ruleForm(rule) {
  const ruleType = rule ? rule.rule_type : "freshness";
  const typeOptions = META.rule_types.map(
    (rt) => `<option value="${rt}" ${rt === ruleType ? "selected" : ""}>${esc(t("ruletype." + rt))}</option>`).join("");
  const connOptions = CONNECTIONS.map(
    (c) => `<option value="${c.id}" ${rule && rule.connection_id === c.id ? "selected" : ""}>${esc(c.name)} (${c.db_type})</option>`).join("");

  const fields = (type, params) => {
    const hint = `<p class="type-hint">${esc(t("ruletype." + type + ".hint"))}</p>`;
    return hint + RULE_FIELDS[type].map(
      ([name, label, widget, def]) => fieldHtml(name, label, widget, params[name] ?? def)).join("");
  };

  openModal(t(rule ? "rule.edit" : "rule.new"), `
      <label>${esc(t("common.name"))}</label>
      <input id="f-rule-name" value="${esc(rule ? rule.name : "")}">
      <label>${esc(t("rule.connection"))}</label>
      <select id="f-rule-conn">${connOptions}</select>
      <label>${esc(t("rule.type"))}</label>
      <select id="f-rule-type">${typeOptions}</select>
      <div id="f-rule-params">${fields(ruleType, rule ? rule.params : {})}</div>
      <label>${esc(t("rule.interval"))}</label>
      <input id="f-rule-interval" type="number" value="${rule ? rule.interval_minutes : 60}" min="1">
      <label>${esc(t("rule.cooldown"))}</label>
      <input id="f-rule-cooldown" type="number" value="${rule ? rule.cooldown_minutes : 60}" min="0">
      <label class="check"><input type="checkbox" id="f-rule-enabled" ${!rule || rule.enabled ? "checked" : ""}>
        <span>${esc(t("common.enabled"))}</span></label>
      <datalist id="dl-tables"></datalist>
      <datalist id="dl-columns"></datalist>`,
    async () => {
      const params = collectParams("#f-rule-params");
      const body = {
        name: $("#f-rule-name").value,
        connection_id: Number($("#f-rule-conn").value),
        rule_type: $("#f-rule-type").value,
        params,
        interval_minutes: Number($("#f-rule-interval").value),
        cooldown_minutes: Number($("#f-rule-cooldown").value),
        enabled: $("#f-rule-enabled").checked,
      };
      if (rule) await api("PUT", `/api/rules/${rule.id}`, body);
      else await api("POST", "/api/rules", body);
      closeModal(); toast(t("common.saved")); loadRules();
    });
  $("#f-rule-type").addEventListener("change", (e) => {
    $("#f-rule-params").innerHTML = fields(e.target.value, {});
    fillColumnList();
  });
  $("#f-rule-conn").addEventListener("change", (e) => loadSchemaFor(e.target.value));
  $("#f-rule-params").addEventListener("input", (e) => {
    if (e.target.dataset.param === "table") fillColumnList();
  });
  loadSchemaFor($("#f-rule-conn").value);
}

function editRule(id) { ruleForm(RULES.find((r) => r.id === id)); }
async function deleteRule(id) {
  if (!confirm(t("common.confirm_delete"))) return;
  await api("DELETE", `/api/rules/${id}`);
  loadRules();
}

/* --------------------------------------------------------------- history */

async function loadHistory() {
  RULES = await api("GET", "/api/rules");
  const sel = $("#history-filter");
  const current = sel.value;
  sel.innerHTML = `<option value="">${esc(t("hist.all_rules"))}</option>` +
    RULES.map((r) => `<option value="${r.id}">${esc(r.name)}</option>`).join("");
  sel.value = current;
  const url = sel.value ? `/api/results?rule_id=${sel.value}` : "/api/results";
  const rows = await api("GET", url);
  const box = $("#history-list");
  if (!rows.length) {
    box.innerHTML = `<div class="empty">${esc(t("common.empty"))}</div>`;
    return;
  }
  box.innerHTML = `<table><tr>
      <th>${esc(t("dash.checked_at"))}</th><th>${esc(t("dash.rule"))}</th>
      <th>${esc(t("hist.run_type"))}</th>
      <th>${esc(t("dash.status"))}</th><th>${esc(t("dash.value"))}</th>
      <th>${esc(t("dash.message"))}</th></tr>` +
    rows.map((r) => `<tr>
      <td>${esc(r.checked_at)}</td><td>${esc(r.rule_name)}</td>
      <td>${esc(t("trigger." + (r.run_type || "auto")))}</td>
      <td><span class="badge ${r.status}">${esc(t("status." + r.status))}</span></td>
      <td>${r.value ?? ""}</td><td>${esc(r.message)}</td></tr>`).join("") + "</table>";
}

/* -------------------------------------------------------------- settings */

async function loadSettings() {
  const s = await api("GET", "/api/settings");
  $("#setting-language").value = s.language;
  $("#setting-recovery").checked = !!s.notify_recovery;
  const tg = s.telegram || {}, em = s.email || {}, mm = s.mattermost || {};
  $("#tg-enabled").checked = !!tg.enabled;
  $("#tg-token").value = tg.bot_token || "";
  $("#tg-chat").value = tg.chat_id || "";
  $("#em-enabled").checked = !!em.enabled;
  $("#em-host").value = em.smtp_host || "";
  $("#em-port").value = em.smtp_port || 587;
  $("#em-tls").checked = em.use_tls !== false;
  $("#em-user").value = em.username || "";
  $("#em-pass").value = em.password || "";
  $("#em-from").value = em.from || "";
  $("#em-to").value = em.to || "";
  $("#mm-enabled").checked = !!mm.enabled;
  $("#mm-url").value = mm.base_url || "";
  $("#mm-token").value = mm.token || "";
  $("#mm-user").value = mm.user || "";
}

async function saveSettings() {
  const body = {
    language: $("#setting-language").value,
    notify_recovery: $("#setting-recovery").checked,
    telegram: {
      enabled: $("#tg-enabled").checked,
      bot_token: $("#tg-token").value,
      chat_id: $("#tg-chat").value,
    },
    email: {
      enabled: $("#em-enabled").checked,
      smtp_host: $("#em-host").value,
      smtp_port: Number($("#em-port").value),
      use_tls: $("#em-tls").checked,
      username: $("#em-user").value,
      password: $("#em-pass").value,
      from: $("#em-from").value,
      to: $("#em-to").value,
    },
    mattermost: {
      enabled: $("#mm-enabled").checked,
      base_url: $("#mm-url").value,
      token: $("#mm-token").value,
      user: $("#mm-user").value,
    },
  };
  await api("POST", "/api/settings", body);
  toast(t("common.saved"));
  if (body.language !== LANG) setLanguage(body.language, false);
}

/* ----------------------------------------------------------------- modal */

let modalOnSave = null;
function openModal(title, html, onSave) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = html;
  $("#modal-save").textContent = t("common.save");
  $("#modal-cancel").textContent = t("common.cancel");
  modalOnSave = onSave;
  $("#modal-backdrop").classList.remove("hidden");
}
function closeModal() { $("#modal-backdrop").classList.add("hidden"); }

/* ------------------------------------------------------------------ init */

async function init() {
  initTabs();
  META = await api("GET", "/api/meta");
  $("#lang-ru").addEventListener("click", () => setLanguage("ru", true));
  $("#lang-en").addEventListener("click", () => setLanguage("en", true));
  $("#conn-add").addEventListener("click", () => connectionForm(null));
  $("#rule-add").addEventListener("click", async () => {
    CONNECTIONS = await api("GET", "/api/connections");
    if (!CONNECTIONS.length) { toast(t("dash.no_rules"), true); return; }
    ruleForm(null);
  });
  $("#history-filter").addEventListener("change", loadHistory);
  $("#dash-run-all").addEventListener("click", runAllChecks);
  $("#settings-save").addEventListener("click", () =>
    saveSettings().catch((e) => toast(e.message, true)));
  $("#modal-save").addEventListener("click", () =>
    Promise.resolve(modalOnSave && modalOnSave()).catch((e) => toast(e.message, true)));
  $("#modal-cancel").addEventListener("click", closeModal);
  document.querySelectorAll("[data-test-channel]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api("POST", `/api/notify/test/${btn.dataset.testChannel}`);
        toast(t("set.test_sent"));
      } catch (e) { toast(e.message, true); }
    });
  });
  await setLanguage(META.language, false);
  // Автообновление активной вкладки раз в 30 секунд
  setInterval(() => {
    const active = document.querySelector("nav#tabs button.active");
    if (active && (active.dataset.tab === "dashboard" || active.dataset.tab === "history")) {
      refreshTab(active.dataset.tab);
    }
  }, 30000);
}

init();
