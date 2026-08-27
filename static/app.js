const API = "";

function themeColors() {
  const cs = getComputedStyle(document.documentElement);
  return {
    green: cs.getPropertyValue("--green").trim() || "#33c07c",
    blue: cs.getPropertyValue("--accent").trim() || "#4d8dff",
    red: cs.getPropertyValue("--red").trim() || "#f0556b",
    track: cs.getPropertyValue("--border").trim() || "#2a3450",
    muted: cs.getPropertyValue("--muted").trim() || "#8993ab",
  };
}

// ---------- Theme ----------
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById("theme-toggle");
  if (theme === "light") {
    btn.textContent = "🌙";
    btn.dataset.i18nTitle = "theme.toggleDark";
  } else {
    btn.textContent = "☀️";
    btn.dataset.i18nTitle = "theme.toggleLight";
  }
  btn.title = t(btn.dataset.i18nTitle);
}

document.getElementById("theme-toggle").addEventListener("click", () => {
  const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  const next = current === "light" ? "dark" : "light";
  applyTheme(next);
  localStorage.setItem("theme", next);
  // Re-render chart/gauge SVGs so they pick up the new theme colors.
  loadDashboard();
});

(function initTheme() {
  const saved = localStorage.getItem("theme");
  const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  applyTheme(saved || (prefersLight ? "light" : "dark"));
})();

// ---------- Sidebar nav ----------
document.querySelectorAll(".side-nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".side-nav-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "dashboard") loadDashboard();
    if (btn.dataset.tab === "trades") loadTrades();
    if (btn.dataset.tab === "performance") loadPerformance();
    if (btn.dataset.tab === "propfirms") loadPropFirms();
    if (btn.dataset.tab === "account") loadAccount();
    if (btn.dataset.tab === "import") loadImportLog();
    if (btn.dataset.tab === "analyses") renderAnalysisCalendar();
  });
});

document.getElementById("sidebar-toggle").addEventListener("click", () => {
  const sidebar = document.getElementById("sidebar");
  sidebar.classList.toggle("collapsed");
  localStorage.setItem("sidebarCollapsed", sidebar.classList.contains("collapsed") ? "1" : "0");
});
if (localStorage.getItem("sidebarCollapsed") === "1") {
  document.getElementById("sidebar").classList.add("collapsed");
}

// ---------- Global filters (date range + accounts) ----------
let allAccounts = [];
let allTagCategories = [];
let allStrategies = [];
let filterAccountIds = []; // empty = all accounts
let filterDateFrom = null;
let filterDateTo = null;
let filterTagIds = [];
let filterStrategies = [];

function filterParams(extra = {}) {
  const p = new URLSearchParams();
  if (filterAccountIds.length) p.set("account_ids", filterAccountIds.join(","));
  if (filterDateFrom) p.set("date_from", filterDateFrom);
  if (filterDateTo) p.set("date_to", filterDateTo);
  if (filterTagIds.length) p.set("tag_ids", filterTagIds.join(","));
  if (filterStrategies.length) p.set("strategies", filterStrategies.join(","));
  // Caller-supplied overrides (e.g. a specific day) always win over the active global filter.
  for (const [k, val] of Object.entries(extra)) p.set(k, val);
  return p;
}

function reloadFilteredViews() {
  loadDashboard();
  if (document.getElementById("tab-trades").classList.contains("active")) loadTrades();
  if (document.getElementById("tab-performance").classList.contains("active")) loadPerformance();
  if (document.getElementById("tab-propfirms").classList.contains("active")) loadPropFirms();
}

async function loadAccountsList() {
  const res = await fetch(`${API}/api/accounts`);
  allAccounts = await res.json();
  renderAccountFilterList();
  populateAccountSelects();
}

function populateAccountSelects() {
  const active = allAccounts.filter(a => !a.archived);
  for (const selId of ["f-account", "cf-account", "csv-account"]) {
    const sel = document.getElementById(selId);
    const prevValue = sel.value;
    sel.innerHTML = active.map(a => `<option value="${a.id}">${a.name}</option>`).join("");
    if (prevValue && active.some(a => String(a.id) === prevValue)) sel.value = prevValue;
  }
}

function updateDateFilterLabel() {
  const label = document.getElementById("date-filter-label");
  if (!filterDateFrom && !filterDateTo) {
    label.textContent = t("filter.allTime");
  } else {
    const from = filterDateFrom ? fmtShortDate(filterDateFrom) : "…";
    const to = filterDateTo ? fmtShortDate(filterDateTo) : "…";
    label.textContent = `${from} → ${to}`;
  }
}

function updateAccountFilterLabel() {
  const label = document.getElementById("account-filter-label");
  if (filterAccountIds.length === 0) {
    label.textContent = t("filter.allAccounts");
  } else if (filterAccountIds.length === 1) {
    const acc = allAccounts.find(a => a.id === filterAccountIds[0]);
    label.textContent = acc ? acc.name : t("filter.allAccounts");
  } else {
    label.textContent = t("filter.accountsSelected", { n: filterAccountIds.length });
  }
}

function renderAccountFilterList() {
  const showArchived = document.getElementById("account-filter-show-archived").checked;
  const list = document.getElementById("account-filter-list");
  const accounts = allAccounts.filter(a => showArchived || !a.archived);
  list.innerHTML = accounts.map(a => `
    <label class="account-filter-row">
      <input type="checkbox" class="acc-filter-check" data-id="${a.id}" ${filterAccountIds.includes(a.id) ? "checked" : ""}>
      <span>${a.name}</span>
      ${a.archived ? `<span class="archived-badge">${t("account.archived")}</span>` : ""}
    </label>
  `).join("");
  list.querySelectorAll(".acc-filter-check").forEach(cb => {
    cb.addEventListener("change", () => {
      const id = parseInt(cb.dataset.id);
      if (cb.checked) {
        if (!filterAccountIds.includes(id)) filterAccountIds.push(id);
      } else {
        filterAccountIds = filterAccountIds.filter(x => x !== id);
      }
      document.getElementById("account-filter-all").checked = filterAccountIds.length === 0;
      updateAccountFilterLabel();
      reloadFilteredViews();
    });
  });
}

document.getElementById("account-filter-show-archived").addEventListener("change", renderAccountFilterList);

document.getElementById("account-filter-all").addEventListener("change", e => {
  if (e.target.checked) {
    filterAccountIds = [];
    renderAccountFilterList();
    updateAccountFilterLabel();
    reloadFilteredViews();
  }
});

document.getElementById("account-filter-manage").addEventListener("click", () => {
  closeAllFilterPanels();
  document.querySelector('.side-nav-btn[data-tab="account"]').click();
});

// ---------- Tag categories & strategy filter ----------
async function loadTagCategories() {
  const res = await fetch(`${API}/api/tag-categories`);
  allTagCategories = await res.json();
  renderTagsFilterList();
  renderCategoriesTable();
}

async function loadStrategies() {
  const res = await fetch(`${API}/api/strategies`);
  allStrategies = await res.json();
  renderStrategyFilterList();
  const datalist = document.getElementById("strategy-options");
  if (datalist) datalist.innerHTML = allStrategies.map(s => `<option value="${s}">`).join("");
}

function updateTagsFilterLabel() {
  const label = document.getElementById("tags-filter-label");
  const count = filterTagIds.length + filterStrategies.length;
  label.textContent = count === 0 ? t("filter.tagsStrategy") : t("filter.tagsStrategySelected", { n: count });
}

function renderTagsFilterList() {
  const list = document.getElementById("tags-filter-list");
  const allTags = allTagCategories.flatMap(c => c.tags.map(tag => ({ ...tag, color: c.color, categoryName: c.name })));
  if (allTags.length === 0) {
    list.innerHTML = `<p class="muted" style="font-size:0.8rem">${t("filter.noTags")}</p>`;
    return;
  }
  list.innerHTML = allTags.map(tag => `
    <label class="account-filter-row">
      <input type="checkbox" class="tag-filter-check" data-id="${tag.id}" ${filterTagIds.includes(tag.id) ? "checked" : ""}>
      <span class="tag-chip-dot" style="background:${tag.color};display:inline-block;width:7px;height:7px;border-radius:50%"></span>
      <span>${tag.name}</span>
    </label>
  `).join("");
  list.querySelectorAll(".tag-filter-check").forEach(cb => {
    cb.addEventListener("change", () => {
      const id = parseInt(cb.dataset.id);
      filterTagIds = cb.checked ? [...filterTagIds, id] : filterTagIds.filter(x => x !== id);
      updateTagsFilterLabel();
      reloadFilteredViews();
    });
  });
}

function renderStrategyFilterList() {
  const list = document.getElementById("strategy-filter-list");
  if (allStrategies.length === 0) {
    list.innerHTML = `<p class="muted" style="font-size:0.8rem">${t("filter.noStrategies")}</p>`;
    return;
  }
  list.innerHTML = allStrategies.map(s => `
    <label class="account-filter-row">
      <input type="checkbox" class="strategy-filter-check" data-name="${s}" ${filterStrategies.includes(s) ? "checked" : ""}>
      <span>${s}</span>
    </label>
  `).join("");
  list.querySelectorAll(".strategy-filter-check").forEach(cb => {
    cb.addEventListener("change", () => {
      const name = cb.dataset.name;
      filterStrategies = cb.checked ? [...filterStrategies, name] : filterStrategies.filter(x => x !== name);
      updateTagsFilterLabel();
      reloadFilteredViews();
    });
  });
}

document.getElementById("tags-filter-manage").addEventListener("click", () => {
  closeAllFilterPanels();
  document.querySelector('.side-nav-btn[data-tab="account"]').click();
});

// ---------- Filter dropdown open/close ----------
function closeAllFilterPanels() {
  document.querySelectorAll(".filter-panel").forEach(p => p.classList.remove("open"));
}
document.getElementById("date-filter-btn").addEventListener("click", e => {
  e.stopPropagation();
  const panel = document.getElementById("date-filter-panel");
  const isOpen = panel.classList.contains("open");
  closeAllFilterPanels();
  if (!isOpen) panel.classList.add("open");
});
document.getElementById("account-filter-btn").addEventListener("click", e => {
  e.stopPropagation();
  const panel = document.getElementById("account-filter-panel");
  const isOpen = panel.classList.contains("open");
  closeAllFilterPanels();
  if (!isOpen) panel.classList.add("open");
});
document.getElementById("tags-filter-btn").addEventListener("click", e => {
  e.stopPropagation();
  const panel = document.getElementById("tags-filter-panel");
  const isOpen = panel.classList.contains("open");
  closeAllFilterPanels();
  if (!isOpen) panel.classList.add("open");
});
document.querySelectorAll(".filter-panel").forEach(p => p.addEventListener("click", e => e.stopPropagation()));
document.addEventListener("click", closeAllFilterPanels);

function isoDate(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

document.querySelectorAll("#date-presets button").forEach(btn => {
  btn.addEventListener("click", () => {
    const now = new Date();
    let from = null, to = null;
    switch (btn.dataset.preset) {
      case "today":
        from = to = isoDate(now);
        break;
      case "week": {
        const start = new Date(now);
        start.setDate(now.getDate() - now.getDay());
        from = isoDate(start); to = isoDate(now);
        break;
      }
      case "month":
        from = isoDate(new Date(now.getFullYear(), now.getMonth(), 1));
        to = isoDate(now);
        break;
      case "last30": {
        const start = new Date(now);
        start.setDate(now.getDate() - 30);
        from = isoDate(start); to = isoDate(now);
        break;
      }
      case "lastmonth": {
        const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
        const end = new Date(now.getFullYear(), now.getMonth(), 0);
        from = isoDate(start); to = isoDate(end);
        break;
      }
      case "quarter": {
        const qStartMonth = Math.floor(now.getMonth() / 3) * 3;
        from = isoDate(new Date(now.getFullYear(), qStartMonth, 1));
        to = isoDate(now);
        break;
      }
      case "ytd":
        from = isoDate(new Date(now.getFullYear(), 0, 1));
        to = isoDate(now);
        break;
      case "all":
        from = null; to = null;
        break;
    }
    filterDateFrom = from;
    filterDateTo = to;
    document.getElementById("date-from-input").value = from || "";
    document.getElementById("date-to-input").value = to || "";
    updateDateFilterLabel();
    closeAllFilterPanels();
    reloadFilteredViews();
  });
});

document.getElementById("date-filter-apply").addEventListener("click", () => {
  filterDateFrom = document.getElementById("date-from-input").value || null;
  filterDateTo = document.getElementById("date-to-input").value || null;
  updateDateFilterLabel();
  closeAllFilterPanels();
  reloadFilteredViews();
});

function fmt(n, digits = 2) {
  if (n === null || n === undefined) return "-";
  return Number(n).toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function parseDateSafe(iso) {
  // A bare "YYYY-MM-DD" string is parsed by `new Date()` as UTC midnight, which then
  // renders as the previous day in any timezone behind UTC. Build it in local time instead.
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(iso);
}
function fmtDate(iso) {
  if (!iso) return "-";
  const d = parseDateSafe(iso);
  return d.toLocaleString(locale(), { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function fmtShortDate(iso) {
  if (!iso) return "";
  const d = parseDateSafe(iso);
  return d.toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" });
}
function toDatetimeLocal(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ---------- Dashboard ----------
async function loadDashboard() {
  const res = await fetch(`${API}/api/stats?` + filterParams().toString());
  const s = await res.json();

  const balEl = document.getElementById("stat-balance");
  balEl.textContent = fmt(s.current_balance);
  balEl.className = "stat-value " + (s.current_balance >= 0 ? "pos" : "neg");
  document.getElementById("stat-total").textContent = s.total_trades;
  const pnlEl = document.getElementById("stat-pnl");
  pnlEl.textContent = fmt(s.total_pnl);
  pnlEl.className = "stat-value " + (s.total_pnl >= 0 ? "pos" : "neg");
  document.getElementById("stat-avgr").textContent = s.avg_r_multiple !== null ? s.avg_r_multiple + "R" : "-";

  renderEquityChart(s.balance_curve);
  renderDailyPnlChart(s.daily_pnl);
  renderDailyCumulativeChart(s.daily_cumulative_pnl);
  renderTradeWinGauge(s.trade_counts, s.win_rate);
  renderDayWinGauge(s.day_counts, s.day_win_rate);
  renderProfitFactorGauge(s.profit_factor);
  renderAvgWinLoss(s.avg_win, s.avg_loss);
  renderRecentAndOpen(s.recent_trades, s.open_positions);
  lastDailyStats = s.daily_stats;
  renderCalendar();

  const tbody = document.querySelector("#symbol-table tbody");
  tbody.innerHTML = "";
  for (const row of s.by_symbol) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${row.symbol}</td><td>${row.trades}</td><td>${row.win_rate}%</td>
      <td class="${row.pnl >= 0 ? "pos" : "neg"}">${fmt(row.pnl)}</td>`;
    tbody.appendChild(tr);
  }
}

// ---------- Balance curve (with axes) ----------
function renderEquityChart(points) {
  const container = document.getElementById("equity-chart");
  container.innerHTML = "";
  if (!points || points.length === 0) {
    container.innerHTML = `<p class="muted">${t("dash.noBalance")}</p>`;
    return;
  }
  const { green, red, track, muted } = themeColors();
  const w = Math.max(600, container.clientWidth);
  const h = 280;
  const padL = 70;
  const padR = 20;
  const padT = 16;
  const padB = 30;
  const values = points.map(p => p.balance);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const range = (max - min) || 1;

  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  const xStep = plotW / Math.max(1, points.length - 1);
  const xy = points.map((p, i) => {
    const x = padL + i * xStep;
    const y = padT + plotH - ((p.balance - min) / range) * plotH;
    return [x, y];
  });
  const pathD = xy.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const zeroY = padT + plotH - ((0 - min) / range) * plotH;
  const last = values[values.length - 1];
  const lineColor = last >= 0 ? green : red;

  // Y axis: 5 evenly spaced ticks from min to max
  const yTickCount = 5;
  let yTicks = "";
  for (let i = 0; i < yTickCount; i++) {
    const val = min + (range * i) / (yTickCount - 1);
    const y = padT + plotH - ((val - min) / range) * plotH;
    yTicks += `
      <line x1="${padL}" y1="${y.toFixed(1)}" x2="${w - padR}" y2="${y.toFixed(1)}" stroke="${track}" stroke-dasharray="3 4" />
      <text x="${padL - 8}" y="${(y + 4).toFixed(1)}" fill="${muted}" font-size="11" text-anchor="end">${fmt(val, 0)}</text>
    `;
  }

  // X axis: up to 6 evenly spaced date labels
  const xTickCount = Math.min(6, points.length);
  let xTicks = "";
  for (let i = 0; i < xTickCount; i++) {
    const idx = Math.round((i * (points.length - 1)) / Math.max(1, xTickCount - 1));
    const p = points[idx];
    const label = p.time === "0000" ? t("chart.initialBalance") : fmtShortDate(p.time);
    const x = xy[idx][0];
    xTicks += `<text x="${x.toFixed(1)}" y="${h - 8}" fill="${muted}" font-size="11" text-anchor="middle">${label}</text>`;
  }

  const svg = `
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
      ${yTicks}
      <line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${w - padR}" y2="${zeroY.toFixed(1)}" stroke="${muted}" stroke-dasharray="4 4" />
      <path d="${pathD}" fill="none" stroke="${lineColor}" stroke-width="2" />
      ${xTicks}
    </svg>`;
  container.innerHTML = svg;
}

// ---------- Net daily P&L bar chart ----------
function renderDailyPnlChart(days) {
  const container = document.getElementById("daily-pnl-chart");
  container.innerHTML = "";
  if (!days || days.length === 0) {
    container.innerHTML = `<p class="muted">${t("dash.noDailyPnl")}</p>`;
    return;
  }
  const { green, red, track, muted } = themeColors();
  const w = Math.max(600, container.clientWidth);
  const h = 220;
  const padL = 70;
  const padR = 20;
  const padT = 16;
  const padB = 30;
  const values = days.map(d => d.pnl);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const range = (max - min) || 1;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const zeroY = padT + plotH - ((0 - min) / range) * plotH;

  const slot = plotW / days.length;
  const barW = Math.max(2, Math.min(28, slot * 0.6));

  let bars = "";
  const xTickEvery = Math.max(1, Math.ceil(days.length / 8));
  let xTicks = "";
  days.forEach((d, i) => {
    const cx = padL + slot * i + slot / 2;
    const y = padT + plotH - ((d.pnl - min) / range) * plotH;
    const barTop = Math.min(y, zeroY);
    const barH = Math.abs(y - zeroY);
    const color = d.pnl >= 0 ? green : red;
    bars += `<rect class="daily-pnl-bar" x="${(cx - barW / 2).toFixed(1)}" y="${barTop.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(1, barH).toFixed(1)}" fill="${color}"><title>${d.date}: ${fmt(d.pnl)}</title></rect>`;
    if (i % xTickEvery === 0 || i === days.length - 1) {
      xTicks += `<text x="${cx.toFixed(1)}" y="${h - 8}" fill="${muted}" font-size="10" text-anchor="middle">${fmtShortDate(d.date)}</text>`;
    }
  });

  const yTickCount = 4;
  let yTicks = "";
  for (let i = 0; i < yTickCount; i++) {
    const val = min + (range * i) / (yTickCount - 1);
    const y = padT + plotH - ((val - min) / range) * plotH;
    yTicks += `
      <line x1="${padL}" y1="${y.toFixed(1)}" x2="${w - padR}" y2="${y.toFixed(1)}" stroke="${track}" stroke-dasharray="3 4" />
      <text x="${padL - 8}" y="${(y + 4).toFixed(1)}" fill="${muted}" font-size="11" text-anchor="end">${fmt(val, 0)}</text>
    `;
  }

  const svg = `
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
      ${yTicks}
      ${bars}
      <line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${w - padR}" y2="${zeroY.toFixed(1)}" stroke="${muted}" />
      ${xTicks}
    </svg>`;
  container.innerHTML = svg;
}

// ---------- Gauges ----------
function polarPoint(cx, cy, r, thetaDeg) {
  const rad = (thetaDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy - r * Math.sin(rad) };
}
function arcPath(cx, cy, r, thetaStart, thetaEnd) {
  const p1 = polarPoint(cx, cy, r, thetaStart);
  const p2 = polarPoint(cx, cy, r, thetaEnd);
  const largeArc = thetaStart - thetaEnd > 180 ? 1 : 0;
  return `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
}

function renderSemiGauge(containerId, legendId, valueId, counts, pct) {
  const { green, blue, red, track } = themeColors();
  const total = counts.wins + counts.breakeven + counts.losses;
  const w = 130, h = 74, cx = 65, cy = 68, r = 54, strokeW = 12;
  let arcs;
  if (total === 0) {
    arcs = `<path d="${arcPath(cx, cy, r, 180, 0)}" stroke="${track}" stroke-width="${strokeW}" fill="none" stroke-linecap="round" />`;
  } else {
    const segs = [
      { n: counts.wins, color: green },
      { n: counts.breakeven, color: blue },
      { n: counts.losses, color: red },
    ];
    let theta = 180;
    arcs = "";
    segs.forEach(seg => {
      if (seg.n <= 0) return;
      const span = (seg.n / total) * 180;
      const thetaEnd = theta - span;
      arcs += `<path d="${arcPath(cx, cy, r, theta, thetaEnd)}" stroke="${seg.color}" stroke-width="${strokeW}" fill="none" />`;
      theta = thetaEnd;
    });
  }
  document.getElementById(containerId).innerHTML =
    `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${arcs}</svg>`;
  document.getElementById(valueId).textContent = total === 0 ? "-" : pct + "%";
  document.getElementById(legendId).innerHTML = `
    <span><span class="dot" style="background:${green}"></span>${counts.wins}</span>
    <span><span class="dot" style="background:${blue}"></span>${counts.breakeven}</span>
    <span><span class="dot" style="background:${red}"></span>${counts.losses}</span>
  `;
}

function renderTradeWinGauge(counts, pct) {
  renderSemiGauge("gauge-tradewin", "legend-tradewin", "gauge-tradewin-value", counts, pct);
}
function renderDayWinGauge(counts, pct) {
  renderSemiGauge("gauge-daywin", "legend-daywin", "gauge-daywin-value", counts, pct);
}

function renderProfitFactorGauge(pf) {
  const { green, red, track } = themeColors();
  const w = 90, h = 90, cx = 45, cy = 45, r = 36, strokeW = 10;
  const circumference = 2 * Math.PI * r;
  let svg;
  if (pf === null || pf === undefined) {
    svg = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
      <circle cx="${cx}" cy="${cy}" r="${r}" stroke="${red}" stroke-width="${strokeW}" fill="none" />
    </svg>`;
  } else {
    const frac = Math.max(0, Math.min(1, pf / 3));
    const dash = frac * circumference;
    const color = pf >= 1 ? green : red;
    svg = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
      <circle cx="${cx}" cy="${cy}" r="${r}" stroke="${track}" stroke-width="${strokeW}" fill="none" />
      <circle cx="${cx}" cy="${cy}" r="${r}" stroke="${color}" stroke-width="${strokeW}" fill="none"
        stroke-dasharray="${dash.toFixed(1)} ${circumference.toFixed(1)}" stroke-linecap="round"
        transform="rotate(-90 ${cx} ${cy})" />
    </svg>`;
  }
  document.getElementById("gauge-profitfactor").innerHTML = svg;
  document.getElementById("gauge-profitfactor-value").textContent = pf === null || pf === undefined ? "-" : fmt(pf);
}

function renderAvgWinLoss(avgWin, avgLoss) {
  const winMag = Math.abs(avgWin || 0);
  const lossMag = Math.abs(avgLoss || 0);
  const total = winMag + lossMag;
  const winPct = total > 0 ? (winMag / total) * 100 : 50;
  const el = document.getElementById("avgwl-body");
  el.innerHTML = `
    <div class="avgwl-values">
      <span class="pos">${avgWin ? fmt(avgWin) : "-"}</span>
      <span class="neg">${avgLoss ? fmt(avgLoss) : "-"}</span>
    </div>
    <div class="avgwl-bar-track">
      <div class="avgwl-bar-win" style="width:${winPct.toFixed(1)}%"></div>
      <div class="avgwl-bar-loss" style="width:${(100 - winPct).toFixed(1)}%"></div>
    </div>
  `;
}

function fmtCompact(n) {
  if (n === null || n === undefined) return "-";
  return Number(n).toLocaleString(locale(), { notation: "compact", maximumFractionDigits: 1 });
}

// ---------- Daily net cumulative P&L (area chart with tooltip) ----------
function renderDailyCumulativeChart(points) {
  const container = document.getElementById("daily-cumulative-chart");
  container.innerHTML = "";
  if (!points || points.length === 0) {
    container.innerHTML = `<p class="muted">${t("dash.noDailyPnl")}</p>`;
    return;
  }
  const { green, red, muted } = themeColors();
  const w = Math.max(600, container.clientWidth);
  const h = 260;
  const padL = 70, padR = 20, padT = 16, padB = 30;
  const values = points.map(p => p.cumulative_pnl);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const range = (max - min) || 1;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const zeroY = padT + plotH - ((0 - min) / range) * plotH;

  const xStep = plotW / Math.max(1, points.length - 1);
  const xy = points.map((p, i) => [
    padL + i * xStep,
    padT + plotH - ((p.cumulative_pnl - min) / range) * plotH,
  ]);
  const lineD = xy.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const areaD = `M ${xy[0][0].toFixed(1)},${zeroY.toFixed(1)} ` +
    xy.map(p => `L ${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ") +
    ` L ${xy[xy.length - 1][0].toFixed(1)},${zeroY.toFixed(1)} Z`;

  const yTickCount = 5;
  let yTicks = "";
  for (let i = 0; i < yTickCount; i++) {
    const val = min + (range * i) / (yTickCount - 1);
    const y = padT + plotH - ((val - min) / range) * plotH;
    yTicks += `
      <line x1="${padL}" y1="${y.toFixed(1)}" x2="${w - padR}" y2="${y.toFixed(1)}" stroke="${muted}" stroke-opacity="0.2" stroke-dasharray="3 4" />
      <text x="${padL - 8}" y="${(y + 4).toFixed(1)}" fill="${muted}" font-size="11" text-anchor="end">${fmt(val, 0)}</text>
    `;
  }
  const xTickCount = Math.min(6, points.length);
  let xTicks = "";
  for (let i = 0; i < xTickCount; i++) {
    const idx = Math.round((i * (points.length - 1)) / Math.max(1, xTickCount - 1));
    xTicks += `<text x="${xy[idx][0].toFixed(1)}" y="${h - 8}" fill="${muted}" font-size="11" text-anchor="middle">${fmtShortDate(points[idx].date)}</text>`;
  }

  const svg = `
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
      <defs>
        <linearGradient id="gradGreen" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stop-color="${green}" stop-opacity="0.05" />
          <stop offset="100%" stop-color="${green}" stop-opacity="0.45" />
        </linearGradient>
        <linearGradient id="gradRed" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${red}" stop-opacity="0.05" />
          <stop offset="100%" stop-color="${red}" stop-opacity="0.45" />
        </linearGradient>
        <clipPath id="clipAbove"><rect x="0" y="0" width="${w}" height="${zeroY.toFixed(1)}" /></clipPath>
        <clipPath id="clipBelow"><rect x="0" y="${zeroY.toFixed(1)}" width="${w}" height="${(h - zeroY).toFixed(1)}" /></clipPath>
      </defs>
      ${yTicks}
      <path d="${areaD}" fill="url(#gradGreen)" clip-path="url(#clipAbove)" />
      <path d="${areaD}" fill="url(#gradRed)" clip-path="url(#clipBelow)" />
      <line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${w - padR}" y2="${zeroY.toFixed(1)}" stroke="${muted}" stroke-dasharray="4 4" />
      <path d="${lineD}" fill="none" stroke="${muted}" stroke-width="1.75" />
      ${xTicks}
      <line id="dcp-hover-line" x1="0" y1="${padT}" x2="0" y2="${h - padB}" stroke="${muted}" stroke-width="1" style="display:none" />
      <circle id="dcp-hover-dot" r="4" fill="${muted}" style="display:none" />
      <rect id="dcp-hover-capture" x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="transparent" />
    </svg>
    <div class="chart-tooltip" id="dcp-tooltip"></div>`;
  container.innerHTML = svg;

  const capture = container.querySelector("#dcp-hover-capture");
  const hoverLine = container.querySelector("#dcp-hover-line");
  const hoverDot = container.querySelector("#dcp-hover-dot");
  const tooltip = container.querySelector("#dcp-tooltip");

  capture.addEventListener("mousemove", e => {
    const rect = container.querySelector("svg").getBoundingClientRect();
    const scaleX = w / rect.width;
    const mouseX = (e.clientX - rect.left) * scaleX;
    let idx = Math.round((mouseX - padL) / xStep);
    idx = Math.max(0, Math.min(points.length - 1, idx));
    const [px, py] = xy[idx];
    hoverLine.setAttribute("x1", px);
    hoverLine.setAttribute("x2", px);
    hoverLine.style.display = "block";
    hoverDot.setAttribute("cx", px);
    hoverDot.setAttribute("cy", py);
    hoverDot.setAttribute("fill", points[idx].cumulative_pnl >= 0 ? green : red);
    hoverDot.style.display = "block";

    const val = points[idx].cumulative_pnl;
    tooltip.innerHTML = `
      <div class="tt-date">${fmtShortDate(points[idx].date)}</div>
      <div class="tt-value"><span class="tt-dot" style="background:${val >= 0 ? green : red}"></span>${fmt(val)}</div>
    `;
    tooltip.style.display = "block";
    const scaleXcss = rect.width / w;
    let left = px * scaleXcss + 12;
    if (left + 140 > rect.width) left = px * scaleXcss - 152;
    tooltip.style.left = left + "px";
    tooltip.style.top = "8px";
  });
  capture.addEventListener("mouseleave", () => {
    hoverLine.style.display = "none";
    hoverDot.style.display = "none";
    tooltip.style.display = "none";
  });
}

// ---------- Recent trades / open positions ----------
document.querySelectorAll(".mini-tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mini-tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".minitab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("minitab-" + btn.dataset.minitab).classList.add("active");
  });
});

function renderRecentAndOpen(recent, open) {
  const recentBody = document.getElementById("recent-trades-tbody");
  recentBody.innerHTML = "";
  if (!recent || recent.length === 0) {
    recentBody.innerHTML = `<tr><td colspan="3" class="muted">${t("dash.noRecentTrades")}</td></tr>`;
  } else {
    for (const r of recent) {
      const cls = (r.pnl || 0) >= 0 ? "pos" : "neg";
      recentBody.innerHTML += `<tr><td>${fmtDate(r.close_date)}</td><td>${r.symbol}</td><td class="${cls}">${fmt(r.pnl)}</td></tr>`;
    }
  }

  const openBody = document.getElementById("open-positions-tbody");
  openBody.innerHTML = "";
  if (!open || open.length === 0) {
    openBody.innerHTML = `<tr><td colspan="3" class="muted">${t("dash.noOpenPositions")}</td></tr>`;
  } else {
    for (const p of open) {
      openBody.innerHTML += `<tr><td>${fmtDate(p.open_date)}</td><td>${p.symbol}</td><td>${fmt(p.volume, 0)}</td></tr>`;
    }
  }
}

// ---------- Monthly calendar ----------
let calendarDate = new Date();
let lastDailyStats = [];

function renderCalendar() {
  const byDate = {};
  for (const d of lastDailyStats) byDate[d.date] = d;

  const year = calendarDate.getFullYear();
  const month = calendarDate.getMonth();
  const monthLabel = calendarDate.toLocaleDateString(locale(), { month: "long", year: "numeric" });
  document.getElementById("cal-month-label").textContent = monthLabel;

  const weekdayRow = document.getElementById("calendar-weekday-row");
  weekdayRow.innerHTML = "";
  const refSunday = new Date(2023, 0, 1); // a Sunday
  for (let i = 0; i < 7; i++) {
    const d = new Date(refSunday);
    d.setDate(refSunday.getDate() + i);
    weekdayRow.innerHTML += `<div>${d.toLocaleDateString(locale(), { weekday: "short" })}</div>`;
  }

  const firstOfMonth = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const startWeekday = firstOfMonth.getDay();

  const grid = document.getElementById("calendar-grid");
  grid.innerHTML = "";
  const cells = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let day = 1; day <= daysInMonth; day++) cells.push(day);
  while (cells.length % 7 !== 0) cells.push(null);

  let monthTotal = 0;
  let monthTradingDays = 0;

  for (const day of cells) {
    if (day === null) {
      grid.innerHTML += `<div class="calendar-day empty"></div>`;
      continue;
    }
    const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const stat = byDate[dateStr];
    if (stat) {
      monthTotal += stat.pnl;
      monthTradingDays += 1;
      const cls = stat.pnl > 0 ? "win" : (stat.pnl < 0 ? "loss" : "breakeven");
      const pnlCls = stat.pnl > 0 ? "pos" : (stat.pnl < 0 ? "neg" : "");
      grid.innerHTML += `
        <div class="calendar-day ${cls}" data-date="${dateStr}">
          <span class="cd-num">${day}</span>
          <span class="cd-pnl ${pnlCls}">${fmtCompact(stat.pnl)}</span>
          <span class="cd-meta">${stat.trades} ${t("dash.tradeLabel")}</span>
          <span class="cd-meta">${stat.win_rate}%</span>
        </div>`;
    } else {
      grid.innerHTML += `<div class="calendar-day"><span class="cd-num">${day}</span></div>`;
    }
  }

  const monthPnlCls = monthTotal > 0 ? "pos" : (monthTotal < 0 ? "neg" : "open");
  document.getElementById("cal-stats").innerHTML = `
    ${t("dash.monthlyStatsLabel")}
    <span class="badge ${monthPnlCls}">${fmtCompact(monthTotal)}</span>
    <span class="badge open">${monthTradingDays} ${t("dash.dayLabel")}</span>
  `;

  // Weekly summary: one card per row of the grid.
  const weeksEl = document.getElementById("calendar-weeks");
  weeksEl.innerHTML = "";
  const weekCount = cells.length / 7;
  for (let w = 0; w < weekCount; w++) {
    let weekPnl = 0;
    let weekDays = 0;
    for (let i = 0; i < 7; i++) {
      const day = cells[w * 7 + i];
      if (day === null) continue;
      const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const stat = byDate[dateStr];
      if (stat) { weekPnl += stat.pnl; weekDays += 1; }
    }
    const cls = weekPnl > 0 ? "pos" : (weekPnl < 0 ? "neg" : "");
    weeksEl.innerHTML += `
      <div class="week-card">
        <div class="week-label">${t("dash.weekLabel", { n: w + 1 })}</div>
        <div class="week-pnl ${cls}">${fmtCompact(weekPnl)}</div>
        <div class="week-label">${weekDays} ${t("dash.dayLabel")}</div>
      </div>`;
  }
}

document.getElementById("cal-prev").addEventListener("click", () => {
  calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth() - 1, 1);
  renderCalendar();
});
document.getElementById("cal-next").addEventListener("click", () => {
  calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth() + 1, 1);
  renderCalendar();
});
document.getElementById("cal-thismonth").addEventListener("click", () => {
  calendarDate = new Date();
  renderCalendar();
});

// ---------- Month/year picker ----------
let pickerMonth = calendarDate.getMonth();
let pickerYear = calendarDate.getFullYear();
let pickerView = "month"; // "month" | "year"

function monthShortName(m) {
  return new Date(2023, m, 1).toLocaleDateString(locale(), { month: "short" });
}

function renderPicker() {
  const headerLabel = new Date(pickerYear, pickerMonth, 1).toLocaleDateString(locale(), { month: "long", year: "numeric" });
  const headerBtn = document.getElementById("cal-picker-header-btn");
  headerBtn.innerHTML = `${headerLabel} <span class="chevron">${pickerView === "month" ? "&#9662;" : "&#9652;"}</span>`;

  const grid = document.getElementById("cal-picker-grid");
  if (pickerView === "month") {
    grid.innerHTML = "";
    for (let m = 0; m < 12; m++) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cal-picker-cell" + (m === pickerMonth ? " selected" : "");
      btn.textContent = monthShortName(m);
      btn.addEventListener("click", () => { pickerMonth = m; renderPicker(); });
      grid.appendChild(btn);
    }
  } else {
    const startYear = pickerYear - 6;
    grid.innerHTML = "";
    for (let i = 0; i < 15; i++) {
      const y = startYear + i;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cal-picker-cell" + (y === pickerYear ? " selected" : "");
      btn.textContent = y;
      btn.addEventListener("click", () => { pickerYear = y; pickerView = "month"; renderPicker(); });
      grid.appendChild(btn);
    }
  }
}

document.getElementById("cal-picker-header-btn").addEventListener("click", () => {
  pickerView = pickerView === "month" ? "year" : "month";
  renderPicker();
});

document.getElementById("cal-month-label-btn").addEventListener("click", e => {
  e.stopPropagation();
  const panel = document.getElementById("cal-picker-panel");
  const isOpen = panel.classList.contains("open");
  closeAllFilterPanels();
  if (!isOpen) {
    pickerMonth = calendarDate.getMonth();
    pickerYear = calendarDate.getFullYear();
    pickerView = "month";
    renderPicker();
    panel.classList.add("open");
  }
});

document.getElementById("cal-picker-ok").addEventListener("click", () => {
  calendarDate = new Date(pickerYear, pickerMonth, 1);
  renderCalendar();
  closeAllFilterPanels();
});

// ---------- Day detail modal ----------
const dayModal = document.getElementById("day-modal");
let dayModalTrades = [];

document.getElementById("calendar-grid").addEventListener("click", e => {
  const cell = e.target.closest(".calendar-day[data-date]");
  if (cell) openDayDetail(cell.dataset.date);
});

document.getElementById("day-modal-close").addEventListener("click", () => dayModal.classList.remove("open"));
dayModal.addEventListener("click", e => { if (e.target === dayModal) dayModal.classList.remove("open"); });

async function openDayDetail(dateStr) {
  const params = filterParams({ date_from: dateStr, date_to: dateStr });
  const res = await fetch(`${API}/api/trades?` + params.toString());
  const trades = await res.json();
  dayModalTrades = trades;

  const closed = trades.filter(tr => tr.status === "closed");
  const wins = closed.filter(tr => (tr.display_pnl || 0) > 0);
  const losses = closed.filter(tr => (tr.display_pnl || 0) < 0);
  const grossProfit = wins.reduce((s, tr) => s + (tr.display_pnl || 0), 0);
  const grossLoss = Math.abs(losses.reduce((s, tr) => s + (tr.display_pnl || 0), 0));
  const netPnl = closed.reduce((s, tr) => s + (tr.display_pnl || 0), 0);
  const commissions = trades.reduce((s, tr) => s + (tr.commission || 0), 0);
  const volume = trades.reduce((s, tr) => s + (tr.quantity || 0), 0);
  const winRate = (wins.length || losses.length) ? Math.round(1000 * wins.length / (wins.length + losses.length)) / 10 : 0;
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : null;

  const d = parseDateSafe(dateStr);
  document.getElementById("day-modal-date").textContent =
    d.toLocaleDateString(locale(), { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
  const pnlEl = document.getElementById("day-modal-pnl");
  pnlEl.textContent = t("day.netPnl") + ": " + fmt(netPnl);
  pnlEl.className = "day-modal-pnl " + (netPnl >= 0 ? "pos" : "neg");

  document.getElementById("day-stat-total").textContent = trades.length;
  document.getElementById("day-stat-gross").textContent = fmt(grossProfit - grossLoss);
  document.getElementById("day-stat-winlose").textContent = `${wins.length} / ${losses.length}`;
  document.getElementById("day-stat-commissions").textContent = fmt(commissions);
  document.getElementById("day-stat-winrate").textContent = winRate + "%";
  document.getElementById("day-stat-volume").textContent = fmt(volume, 0);
  document.getElementById("day-stat-pf").textContent = profitFactor != null ? fmt(profitFactor) : "-";

  renderDayChart(closed);

  const tbody = document.getElementById("day-modal-tbody");
  tbody.innerHTML = "";
  if (trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="muted">${t("day.noTrades")}</td></tr>`;
  }
  const sorted = [...trades].sort((a, b) => (a.entry_time || "").localeCompare(b.entry_time || ""));
  for (const tr_ of sorted) {
    const tr = document.createElement("tr");
    const sideLabel = tr_.side === "long" ? t("form.long") : t("form.short");
    const timeLabel = new Date(tr_.entry_time).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
    const openBadge = tr_.status === "open" ? ` <span class="badge open">${t("day.openBadge")}</span>` : "";
    const notional = Math.abs(tr_.entry_price * tr_.quantity);
    const roi = tr_.display_pnl != null && notional > 0 ? (tr_.pnl_native / notional * 100) : null;
    const pnlCls = tr_.display_pnl == null ? "" : (tr_.display_pnl >= 0 ? "pos" : "neg");
    tr.innerHTML = `
      <td>${timeLabel}${openBadge}</td>
      <td>${tr_.symbol}</td>
      <td><span class="badge ${tr_.side}">${sideLabel}</span></td>
      <td class="${pnlCls}">${tr_.display_pnl != null ? fmt(tr_.display_pnl) : "-"}</td>
      <td>${roi != null ? fmt(roi) + "%" : "-"}</td>
      <td>${tr_.r_multiple != null ? tr_.r_multiple + "R" : "-"}</td>
      <td>${tr_.strategy || "-"}</td>
      <td>${tr_.tags || "-"}</td>
    `;
    tr.addEventListener("click", () => {
      dayModal.classList.remove("open");
      openTradeModal(tr_);
    });
    tbody.appendChild(tr);
  }

  dayModal.classList.add("open");
}

function renderDayChart(closedTrades) {
  const container = document.getElementById("day-modal-chart");
  container.innerHTML = "";
  if (closedTrades.length === 0) {
    container.innerHTML = `<p class="muted">${t("day.noTrades")}</p>`;
    return;
  }
  const { green, red, muted } = themeColors();
  const sorted = [...closedTrades].sort((a, b) => (a.exit_time || "").localeCompare(b.exit_time || ""));
  const points = [{ cum: 0 }];
  let cum = 0;
  for (const tr_ of sorted) {
    cum += tr_.display_pnl || 0;
    points.push({ cum });
  }
  const w = 320, h = 160, padL = 56, padR = 10, padT = 10, padB = 10;
  const values = points.map(p => p.cum);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const range = (max - min) || 1;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const xStep = plotW / Math.max(1, points.length - 1);
  const xy = points.map((p, i) => [padL + i * xStep, padT + plotH - ((p.cum - min) / range) * plotH]);
  const lineD = xy.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const zeroY = padT + plotH - ((0 - min) / range) * plotH;
  const areaD = `M ${xy[0][0]},${zeroY} ` + xy.map(p => `L ${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ") + ` L ${xy[xy.length - 1][0]},${zeroY} Z`;
  const last = values[values.length - 1];
  const color = last >= 0 ? green : red;

  const yTicks = [0, min, max].filter((v, i, arr) => arr.indexOf(v) === i);
  let yTicksSvg = "";
  for (const val of yTicks) {
    const y = padT + plotH - ((val - min) / range) * plotH;
    yTicksSvg += `<text x="${padL - 6}" y="${(y + 3).toFixed(1)}" fill="${muted}" font-size="10" text-anchor="end">${fmt(val, 0)}</text>`;
  }

  container.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">
      ${yTicksSvg}
      <path d="${areaD}" fill="${color}" fill-opacity="0.18" />
      <line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${w - padR}" y2="${zeroY.toFixed(1)}" stroke="${muted}" stroke-dasharray="3 3" />
      <path d="${lineD}" fill="none" stroke="${color}" stroke-width="2" />
    </svg>`;
}

// ---------- Performance ----------
function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "-";
  seconds = Math.round(seconds);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (days) parts.push(days + t("unit.days"));
  if (days || hours) parts.push(hours + t("unit.hours"));
  parts.push(minutes + t("unit.minutes"));
  return parts.join(" ");
}

function drillIntoDay(date) {
  filterDateFrom = date;
  filterDateTo = date;
  document.getElementById("date-from-input").value = date;
  document.getElementById("date-to-input").value = date;
  updateDateFilterLabel();
  document.querySelector('.side-nav-btn[data-tab="trades"]').click();
}

async function openTradeById(id) {
  const res = await fetch(`${API}/api/trades`);
  const trades = await res.json();
  const trade = trades.find(tr => tr.id === id);
  if (trade) {
    document.querySelector('.side-nav-btn[data-tab="trades"]').click();
    openTradeModal(trade);
  }
}

async function loadPerformance() {
  const res = await fetch(`${API}/api/performance?` + filterParams().toString());
  const p = await res.json();
  const v = (val, digits = 2) => (val === null || val === undefined ? "-" : fmt(val, digits));
  const setPnl = (id, val) => {
    const el = document.getElementById(id);
    el.textContent = v(val);
    el.className = "perf-value " + (val == null ? "" : (val >= 0 ? "pos" : "neg"));
  };

  // ---- Overview tab ----
  const o = p.overview;
  const fmtMonth = key => {
    if (!key) return "";
    const [y, m] = key.split("-").map(Number);
    return new Date(y, m - 1, 1).toLocaleDateString(locale(), { month: "short", year: "numeric" });
  };
  const setMonthCard = (valId, labelId, entry) => {
    const valEl = document.getElementById(valId);
    valEl.textContent = entry ? fmt(entry.pnl) : "-";
    valEl.className = "stat-value " + (entry ? (entry.pnl >= 0 ? "pos" : "neg") : "");
    document.getElementById(labelId).textContent = entry ? t("chart.inMonth", { month: fmtMonth(entry.month) }) : "";
  };
  setMonthCard("ov-best-month", "ov-best-month-label", o.best_month);
  setMonthCard("ov-lowest-month", "ov-lowest-month-label", o.lowest_month);
  const avgMonthEl = document.getElementById("ov-avg-month");
  avgMonthEl.textContent = v(o.avg_per_month);
  avgMonthEl.className = "stat-value " + (o.avg_per_month == null ? "" : (o.avg_per_month >= 0 ? "pos" : "neg"));

  const pctOrDash = val => (val === null || val === undefined ? "-" : fmt(val) + "%");
  const OVERVIEW_ROWS = [
    ["perf.totalPnl", o.total_pnl, "pnl"],
    ["perf.avgDailyVolume2", v(o.avg_daily_volume, 0)],
    ["perf.avgWinningTrade", o.avg_winning_trade, "pnl"],
    ["perf.avgLosingTrade", o.avg_losing_trade, "pnl"],
    ["perf.totalTrades", o.total_trades],
    ["perf.numWinningTrades", o.winning_trades],
    ["perf.numLosingTrades", o.losing_trades],
    ["perf.numBreakEvenTrades", o.breakeven_trades],
    ["perf.maxConsecWins", o.max_consecutive_wins],
    ["perf.maxConsecLosses", o.max_consecutive_losses],
    ["perf.totalCommissions", v(o.total_commissions)],
    ["perf.totalFees", fmt(0), null, "perf.notTracked"],
    ["perf.totalSwap", fmt(0), null, "perf.notTracked"],
    ["perf.largestProfit", o.largest_profit, "pnl"],
    ["perf.largestLoss", o.largest_loss, "pnl"],
    ["perf.avgHoldAll", fmtDuration(o.avg_hold_all)],
    ["perf.avgHoldWinning", fmtDuration(o.avg_hold_winning)],
    ["perf.avgHoldLosing", fmtDuration(o.avg_hold_losing)],
    ["perf.avgHoldScratch", o.avg_hold_scratch != null ? fmtDuration(o.avg_hold_scratch) : "N/A"],
    ["perf.avgTradePnl", o.avg_trade_pnl, "pnl"],
    ["perf.profitFactor", v(o.profit_factor)],
    ["perf.openTrades", o.open_trades],
    ["perf.totalTradingDays", o.total_trading_days],
    ["perf.winningDays", o.winning_days],
    ["perf.losingDays", o.losing_days],
    ["perf.breakevenDays", o.breakeven_days],
    ["perf.maxConsecWinDays", o.max_consecutive_winning_days],
    ["perf.maxConsecLossDays", o.max_consecutive_losing_days],
    ["perf.avgDailyPnl2", o.avg_daily_pnl, "pnl"],
    ["perf.avgWinningDayPnl", o.avg_winning_day_pnl, "pnl"],
    ["perf.avgLosingDayPnl", o.avg_losing_day_pnl, "pnl"],
    ["perf.largestProfitableDay2", o.largest_profitable_day, "pnl"],
    ["perf.largestLosingDay2", o.largest_losing_day, "pnl"],
    ["perf.avgPlannedR2", (o.avg_planned_r ?? 0) + "R"],
    ["perf.avgRealizedR2", (o.avg_realized_r ?? 0) + "R"],
    ["perf.tradeExpectancy2", o.trade_expectancy, "pnl"],
    ["perf.maxDrawdown", o.max_drawdown, "pnl"],
    ["perf.maxDrawdownPct", pctOrDash(o.max_drawdown_pct)],
    ["perf.avgDrawdown2", o.avg_drawdown, "pnl"],
    ["perf.avgDrawdownPct", pctOrDash(o.avg_drawdown_pct)],
  ];
  const listEl = document.getElementById("overview-list");
  listEl.innerHTML = OVERVIEW_ROWS.map(([labelKey, val, kind, tipKey]) => {
    let displayVal, cls = "ov-value";
    if (kind === "pnl") {
      displayVal = v(val);
      if (val != null) cls += val >= 0 ? " pos" : " neg";
    } else {
      displayVal = val === null || val === undefined ? "-" : val;
    }
    const tip = tipKey ? `<span class="info-icon" title="${t(tipKey)}">&#9432;</span>` : "";
    return `<div class="overview-row"><span class="ov-label">${t(labelKey)}${tip}</span><span class="${cls}">${displayVal}</span></div>`;
  }).join("");

  // ---- Summary tab ----
  setPnl("perf-net-pnl", p.net_pnl);
  document.getElementById("perf-expectancy").textContent = v(p.trade_expectancy);
  document.getElementById("perf-avg-net-trade").textContent = v(p.avg_net_trade_pnl);
  document.getElementById("perf-avg-volume").textContent = v(p.avg_daily_volume, 0);
  document.getElementById("perf-win-pct").textContent = p.win_pct + "%";
  document.getElementById("perf-avg-daily-winloss").textContent = v(p.avg_daily_win_loss);
  document.getElementById("perf-avg-daily-pnl").textContent = v(p.avg_daily_net_pnl);
  document.getElementById("perf-logged-days").textContent = p.logged_days;
  document.getElementById("perf-avg-daily-winpct").textContent = p.avg_daily_win_pct + "%";
  document.getElementById("perf-avg-daily-winpct-frac").textContent = `(${p.avg_daily_win_fraction})`;
  document.getElementById("perf-avg-trade-winloss").textContent = v(p.avg_trade_win_loss);
  document.getElementById("perf-avg-planned-r").textContent = (p.avg_planned_r ?? 0) + "R";
  document.getElementById("perf-max-drawdown").textContent = v(p.max_daily_net_drawdown);
  document.getElementById("perf-profit-factor").textContent = v(p.profit_factor);
  document.getElementById("perf-avg-hold").textContent = fmtDuration(p.avg_hold_seconds);
  document.getElementById("perf-avg-realized-r").textContent = (p.avg_realized_r ?? 0) + "R";
  document.getElementById("perf-avg-drawdown").textContent = v(p.avg_daily_net_drawdown);

  // ---- Days tab ----
  document.getElementById("perf2-avg-daily-winpct").textContent = p.avg_daily_win_pct + "%";
  document.getElementById("perf2-avg-daily-winpct-frac").textContent = `(${p.avg_daily_win_fraction})`;
  document.getElementById("perf2-avg-daily-winloss").textContent = v(p.avg_daily_win_loss);
  document.getElementById("perf2-avg-daily-pnl").textContent = v(p.avg_daily_net_pnl);
  document.getElementById("perf2-avg-day-duration").textContent = fmtDuration(p.avg_day_duration_seconds);

  const bestDayEl = document.getElementById("perf2-best-day");
  bestDayEl.textContent = p.largest_profitable_day ? fmt(p.largest_profitable_day.pnl) : "-";
  bestDayEl.onclick = p.largest_profitable_day ? () => drillIntoDay(p.largest_profitable_day.date) : null;

  const worstDayEl = document.getElementById("perf2-worst-day");
  worstDayEl.textContent = p.largest_losing_day ? fmt(p.largest_losing_day.pnl) : "-";
  worstDayEl.onclick = p.largest_losing_day ? () => drillIntoDay(p.largest_losing_day.date) : null;

  // ---- Trades tab ----
  document.getElementById("perf3-win-pct").textContent = p.win_pct + "%";
  document.getElementById("perf3-avg-trade-winloss").textContent = v(p.avg_trade_win_loss);
  document.getElementById("perf3-longs-winpct").textContent = p.longs_win_pct + "%";
  document.getElementById("perf3-expectancy").textContent = v(p.trade_expectancy);
  document.getElementById("perf3-shorts-winpct").textContent = p.shorts_win_pct + "%";
  document.getElementById("perf3-avg-net-trade").textContent = v(p.avg_net_trade_pnl);

  const bestTradeEl = document.getElementById("perf3-best-trade");
  bestTradeEl.textContent = p.largest_profitable_trade ? fmt(p.largest_profitable_trade.pnl) : "-";
  bestTradeEl.onclick = p.largest_profitable_trade ? () => openTradeById(p.largest_profitable_trade.id) : null;

  const worstTradeEl = document.getElementById("perf3-worst-trade");
  worstTradeEl.textContent = p.largest_losing_trade ? fmt(p.largest_losing_trade.pnl) : "-";
  worstTradeEl.onclick = p.largest_losing_trade ? () => openTradeById(p.largest_losing_trade.id) : null;

  const longestTradeEl = document.getElementById("perf3-longest-trade");
  longestTradeEl.textContent = fmtDuration(p.longest_trade_seconds);
  longestTradeEl.onclick = p.longest_trade_id ? () => openTradeById(p.longest_trade_id) : null;
}

document.querySelectorAll(".perf-tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".perf-tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll("#tab-performance .minitab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("perftab-" + btn.dataset.perftab).classList.add("active");
  });
});

// ---------- Trades table ----------
function tradesFilterParams() {
  const symbol = document.getElementById("filter-symbol").value;
  const status = document.getElementById("filter-status").value;
  const source = document.getElementById("filter-source").value;
  const params = filterParams();
  if (symbol) params.set("symbol", symbol);
  if (status) params.set("status", status);
  if (source) params.set("source", source);
  return params;
}

let selectedTradeIds = new Set();

function updateSelectAllTradesState() {
  const boxes = document.querySelectorAll(".trade-row-check");
  const selectAll = document.getElementById("select-all-trades");
  selectAll.checked = boxes.length > 0 && [...boxes].every(b => b.checked);
  updateExportButtonLabel();
}

function updateExportButtonLabel() {
  const btn = document.getElementById("export-trades");
  btn.textContent = selectedTradeIds.size > 0
    ? t("trades.exportSelected", { n: selectedTradeIds.size })
    : t("trades.export");
}

async function loadTrades() {
  const params = tradesFilterParams();
  const res = await fetch(`${API}/api/trades?` + params.toString());
  const trades = await res.json();
  selectedTradeIds = new Set();
  const tbody = document.querySelector("#trades-table tbody");
  tbody.innerHTML = "";
  for (const tr_ of trades) {
    const tr = document.createElement("tr");
    tr.addEventListener("click", e => {
      if (e.target.closest(".trade-row-check")) return;
      openTradeModal(tr_);
    });
    const pnlClass = tr_.display_pnl == null ? "" : (tr_.display_pnl >= 0 ? "pos" : "neg");
    const sideLabel = tr_.side === "long" ? t("form.long") : t("form.short");
    const sourceLabel = tr_.source === "manual" ? t("trades.manual") : t("trades.csv");
    tr.innerHTML = `
      <td><input type="checkbox" class="trade-row-check" data-id="${tr_.id}"></td>
      <td>${tr_.account_name ?? "-"}</td>
      <td>${tr_.symbol}</td>
      <td><span class="badge ${tr_.side}">${sideLabel}</span></td>
      <td>${fmt(tr_.quantity, 0)}</td>
      <td>${fmt(tr_.entry_price, 5)}</td>
      <td>${tr_.exit_price !== null ? fmt(tr_.exit_price, 5) : "-"}</td>
      <td>${fmtDate(tr_.entry_time)}</td>
      <td>${tr_.status === "open" ? `<span class="badge open">${t("trades.open")}</span>` : fmtDate(tr_.exit_time)}</td>
      <td class="${pnlClass}">${tr_.display_pnl != null ? fmt(tr_.display_pnl) + " " + tr_.display_currency : "-"}</td>
      <td>${tr_.r_multiple != null ? tr_.r_multiple + "R" : "-"}</td>
      <td>${sourceLabel}</td>
      <td>${tr_.screenshots && tr_.screenshots.length ? "📷" + (tr_.screenshots.length > 1 ? ` ${tr_.screenshots.length}` : "") : ""}</td>
    `;
    tbody.appendChild(tr);
  }
  document.getElementById("select-all-trades").checked = false;
  updateExportButtonLabel();
}

document.querySelector("#trades-table tbody").addEventListener("change", e => {
  const box = e.target.closest(".trade-row-check");
  if (!box) return;
  const id = parseInt(box.dataset.id);
  if (box.checked) selectedTradeIds.add(id);
  else selectedTradeIds.delete(id);
  updateSelectAllTradesState();
});

document.getElementById("select-all-trades").addEventListener("change", e => {
  const checked = e.target.checked;
  document.querySelectorAll(".trade-row-check").forEach(box => {
    box.checked = checked;
    const id = parseInt(box.dataset.id);
    if (checked) selectedTradeIds.add(id);
    else selectedTradeIds.delete(id);
  });
  updateExportButtonLabel();
});

document.getElementById("refresh-trades").addEventListener("click", loadTrades);
document.getElementById("export-trades").addEventListener("click", () => {
  const params = tradesFilterParams();
  if (selectedTradeIds.size > 0) params.set("trade_ids", [...selectedTradeIds].join(","));
  window.location.href = `${API}/api/trades/export?` + params.toString();
});
document.getElementById("filter-symbol").addEventListener("input", debounce(loadTrades, 300));
document.getElementById("filter-status").addEventListener("change", loadTrades);
document.getElementById("filter-source").addEventListener("change", loadTrades);

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

// ---------- Notes link previews ----------
const linkPreviewCache = {};

function extractUrls(text) {
  const matches = (text || "").match(/https?:\/\/[^\s<>"')]+/g) || [];
  // Strip trailing punctuation a URL is unlikely to end with (sentence-final
  // periods, closing parens picked up when the link sits inside a sentence).
  const cleaned = matches.map(u => u.replace(/[.,;:!?)\]]+$/, ""));
  return [...new Set(cleaned)];
}

function renderLinkPreviewCard(data) {
  const hostname = (() => { try { return new URL(data.url).hostname; } catch { return data.url; } })();
  const image = data.image ? `<div class="lp-image" style="background-image:url('${escapeHtml(data.image)}')"></div>` : "";
  const favicon = data.favicon ? `<img class="lp-favicon" src="${escapeHtml(data.favicon)}" alt="">` : "";
  return `
    <a class="link-preview-card" href="${escapeHtml(data.url)}" target="_blank" rel="noopener noreferrer" data-url="${escapeHtml(data.url)}">
      ${image}
      <div class="lp-body">
        <div class="lp-title">${escapeHtml(data.title || data.url)}</div>
        ${data.description ? `<div class="lp-desc">${escapeHtml(data.description)}</div>` : ""}
        <div class="lp-site">${favicon}<span>${escapeHtml(data.site_name || hostname)}</span></div>
      </div>
    </a>`;
}

function renderBareLinkCard(url) {
  return `<a class="link-preview-card bare" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" data-url="${escapeHtml(url)}">${escapeHtml(url)}</a>`;
}

// ---------- Notes rich text editor (bold/italic/underline/color/link) ----------
// Notes are stored as sanitized HTML now (previously plain text) - only a small
// allowlist of tags/attributes survives sanitizeNotesHtml, so pasting from an
// external page (or any execCommand quirk) can't smuggle in scripts, event
// handlers, images, iframes, or arbitrary styles.
const NOTES_ALLOWED_TAGS = new Set(["B", "I", "U", "A", "BR", "DIV", "SPAN"]);

function sanitizeNotesHtml(html) {
  const container = document.createElement("div");
  container.innerHTML = html;
  const clean = (node) => {
    [...node.childNodes].forEach(child => {
      if (child.nodeType === Node.ELEMENT_NODE) {
        if (!NOTES_ALLOWED_TAGS.has(child.tagName)) {
          while (child.firstChild) node.insertBefore(child.firstChild, child);
          node.removeChild(child);
          return;
        }
        [...child.attributes].forEach(attr => {
          const name = attr.name.toLowerCase();
          if (child.tagName === "A" && name === "href") {
            if (!/^https?:\/\//i.test(attr.value)) child.removeAttribute(attr.name);
            return;
          }
          if (child.tagName === "SPAN" && name === "style") {
            const m = attr.value.match(/color\s*:\s*(#[0-9a-fA-F]{3,8}|rgb\([^)]+\))/i);
            if (m) child.setAttribute("style", `color:${m[1]}`);
            else child.removeAttribute("style");
            return;
          }
          child.removeAttribute(attr.name);
        });
        if (child.tagName === "A") {
          child.setAttribute("target", "_blank");
          child.setAttribute("rel", "noopener noreferrer");
        }
        clean(child);
      } else if (child.nodeType !== Node.TEXT_NODE) {
        child.remove();
      }
    });
  };
  clean(container);
  return container.innerHTML;
}

function isLikelyHtml(s) {
  return /<[a-z][\s\S]*>/i.test(s || "");
}

// Wires up one rich-text notes editor (toolbar + contenteditable + link
// previews). Used for both the trade notes field and the analysis journal
// notes field, so the formatting/sanitization/link-preview behavior stays
// identical everywhere notes are edited instead of being copy-pasted per use.
function initRichNotesEditor({ editorId, toolbarId, colorPickerId, previewsId }) {
  const editor = document.getElementById(editorId);
  const toolbar = document.getElementById(toolbarId);
  const colorPicker = document.getElementById(colorPickerId);
  const previews = document.getElementById(previewsId);

  toolbar.addEventListener("mousedown", e => {
    if (e.target.closest("button[data-cmd]")) e.preventDefault(); // keep the text selection alive
  });
  toolbar.addEventListener("click", e => {
    const btn = e.target.closest("button[data-cmd]");
    if (!btn) return;
    editor.focus();
    if (btn.dataset.cmd === "link") {
      const url = prompt(t("notes.linkPrompt"));
      if (!url) return;
      document.execCommand("createLink", false, /^https?:\/\//i.test(url) ? url : `https://${url}`);
      return;
    }
    document.execCommand(btn.dataset.cmd, false, null);
  });
  colorPicker.addEventListener("input", e => {
    editor.focus();
    document.execCommand("foreColor", false, e.target.value);
  });
  editor.addEventListener("paste", e => {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData("text/plain");
    document.execCommand("insertText", false, text);
  });

  async function updatePreviews() {
    const urls = extractUrls(editor.innerText);
    if (!urls.length) { previews.innerHTML = ""; return; }
    previews.innerHTML = urls.map(u => linkPreviewCache[u] ? renderLinkPreviewCard(linkPreviewCache[u]) : renderBareLinkCard(u)).join("");
    await Promise.all(urls.filter(u => !linkPreviewCache[u]).map(async u => {
      try {
        const res = await fetch(`${API}/api/link-preview?url=${encodeURIComponent(u)}`);
        const data = await res.json();
        linkPreviewCache[u] = data;
        const card = previews.querySelector(`a[data-url="${CSS.escape(u)}"]`);
        if (card) card.outerHTML = renderLinkPreviewCard(data);
      } catch (e) { /* keep the bare-link fallback already rendered */ }
    }));
  }

  let debounceHandle;
  editor.addEventListener("input", () => {
    clearTimeout(debounceHandle);
    debounceHandle = setTimeout(updatePreviews, 500);
  });

  return {
    setContent(raw) {
      editor.innerHTML = raw ? (isLikelyHtml(raw) ? sanitizeNotesHtml(raw) : escapeHtml(raw).replace(/\n/g, "<br>")) : "";
      updatePreviews();
    },
    getValue() {
      return editor.innerText.trim() ? sanitizeNotesHtml(editor.innerHTML) : null;
    },
  };
}

const tradeNotesEditor = initRichNotesEditor({
  editorId: "f-notes", toolbarId: "notes-toolbar",
  colorPickerId: "notes-color-picker", previewsId: "notes-link-previews",
});

// ---------- Screenshot gallery (multiple images per trade or analysis) ----------
// Reused for both the trade modal and the analysis modal: a live-preview
// gallery of already-saved images plus newly-picked-but-not-yet-uploaded
// ones, each removable (saved ones call the API immediately, pending ones
// just drop out of the pending selection).
function initScreenshotGallery({ fileInputId, galleryId, apiBase, getEntityId }) {
  let saved = []; // [{id, filename}] already saved for the entity being edited
  let pending = []; // File[] picked but not uploaded yet (uploaded on save)

  const fileInput = document.getElementById(fileInputId);
  const gallery = document.getElementById(galleryId);

  function syncInputFromPending() {
    const dt = new DataTransfer();
    pending.forEach(f => dt.items.add(f));
    fileInput.files = dt.files;
  }

  function render() {
    const savedHtml = saved.map(s => `
      <div class="screenshot-thumb">
        <img src="/screenshots/${s.filename}">
        <button type="button" class="thumb-remove" data-kind="saved" data-id="${s.id}" title="${t("form.delete")}">&times;</button>
      </div>`).join("");
    const pendingHtml = pending.map((f, i) => `
      <div class="screenshot-thumb pending">
        <img src="${URL.createObjectURL(f)}">
        <button type="button" class="thumb-remove" data-kind="pending" data-idx="${i}" title="${t("form.delete")}">&times;</button>
      </div>`).join("");
    gallery.innerHTML = savedHtml + pendingHtml;
  }

  fileInput.addEventListener("change", e => {
    pending.push(...e.target.files);
    syncInputFromPending();
    render();
  });

  gallery.addEventListener("click", async e => {
    const btn = e.target.closest(".thumb-remove");
    if (!btn) return;
    if (btn.dataset.kind === "pending") {
      pending.splice(parseInt(btn.dataset.idx), 1);
      syncInputFromPending();
      render();
      return;
    }
    if (!confirm(t("confirm.deleteScreenshot"))) return;
    const entityId = getEntityId();
    const screenshotId = parseInt(btn.dataset.id);
    await fetch(`${API}/api/${apiBase}/${entityId}/screenshots/${screenshotId}`, { method: "DELETE" });
    saved = saved.filter(s => s.id !== screenshotId);
    render();
  });

  return {
    setSaved(list) {
      saved = list || [];
      pending = [];
      render();
    },
    async uploadPending(entityId) {
      for (const file of pending) {
        const fd = new FormData();
        fd.append("file", file);
        await fetch(`${API}/api/${apiBase}/${entityId}/screenshots`, { method: "POST", body: fd });
      }
      pending = [];
    },
  };
}

const tradeScreenshots = initScreenshotGallery({
  fileInputId: "f-screenshot", galleryId: "f-screenshot-gallery",
  apiBase: "trades", getEntityId: () => document.getElementById("trade-id").value,
});

function renderMaeMfeBadges() {
  const maeVal = document.getElementById("f-mae-price").value;
  const mfeVal = document.getElementById("f-mfe-price").value;
  const row = document.getElementById("mae-mfe-badges");
  if (maeVal === "" && mfeVal === "") { row.style.display = "none"; return; }
  row.style.display = "flex";
  document.getElementById("mae-badge").textContent = maeVal !== "" ? fmt(parseFloat(maeVal), 5) : "-";
  document.getElementById("mfe-badge").textContent = mfeVal !== "" ? fmt(parseFloat(mfeVal), 5) : "-";
}
document.getElementById("f-mae-price").addEventListener("input", renderMaeMfeBadges);
document.getElementById("f-mfe-price").addEventListener("input", renderMaeMfeBadges);

const modal = document.getElementById("trade-modal");
const form = document.getElementById("trade-form");

function openTradeModal(trade = null) {
  form.reset();
  tradeScreenshots.setSaved(trade && trade.screenshots);
  if (trade) {
    document.getElementById("trade-modal-title").textContent = t("modal.editTitle");
    document.getElementById("trade-id").value = trade.id;
    document.getElementById("f-account").value = trade.account_id ?? "";
    document.getElementById("f-symbol").value = trade.symbol;
    document.getElementById("f-side").value = trade.side;
    document.getElementById("f-quantity").value = trade.quantity;
    document.getElementById("f-entry-price").value = trade.entry_price;
    document.getElementById("f-exit-price").value = trade.exit_price ?? "";
    document.getElementById("f-stop-price").value = trade.stop_price ?? "";
    document.getElementById("f-target-price").value = trade.target_price ?? "";
    document.getElementById("f-mae-price").value = trade.mae_price ?? "";
    document.getElementById("f-mfe-price").value = trade.mfe_price ?? "";
    document.getElementById("f-commission").value = trade.commission ?? 0;
    document.getElementById("f-entry-time").value = toDatetimeLocal(trade.entry_time);
    document.getElementById("f-exit-time").value = toDatetimeLocal(trade.exit_time);
    document.getElementById("f-strategy").value = trade.strategy ?? "";
    tradeNotesEditor.setContent(trade.notes);
    document.getElementById("delete-trade-btn").style.display = "inline-block";
    renderTradeModalTagCategories((trade.trade_tags || []).map(tg => tg.id));
  } else {
    document.getElementById("trade-modal-title").textContent = t("modal.addTitle");
    document.getElementById("trade-id").value = "";
    document.getElementById("delete-trade-btn").style.display = "none";
    const now = new Date();
    now.setSeconds(0, 0);
    document.getElementById("f-entry-time").value = toDatetimeLocal(now.toISOString());
    tradeNotesEditor.setContent("");
    renderTradeModalTagCategories([]);
  }
  renderMaeMfeBadges();
  modal.classList.add("open");
}

function renderTradeModalTagCategories(selectedTagIds) {
  const box = document.getElementById("f-tag-categories");
  if (allTagCategories.length === 0) {
    box.innerHTML = `<p class="muted" style="font-size:0.85rem">${t("tags.noCategories")} ${t("tags.goToSettings")}</p>`;
    return;
  }
  box.innerHTML = allTagCategories.map(cat => {
    const selectedInCat = cat.tags.find(tg => selectedTagIds.includes(tg.id));
    return `
      <div class="tag-category-row" data-category-id="${cat.id}">
        <span class="tag-cat-dot" style="background:${cat.color}"></span>
        <span class="tag-cat-name">${cat.name}</span>
        <select class="tag-cat-select" data-category-id="${cat.id}">
          <option value="">${t("tags.selectTag")}</option>
          ${cat.tags.map(tg => `<option value="${tg.id}" ${selectedInCat && selectedInCat.id === tg.id ? "selected" : ""}>${tg.name}</option>`).join("")}
        </select>
        <button type="button" class="tag-cat-add" data-category-id="${cat.id}" title="+">+</button>
      </div>`;
  }).join("");

  box.querySelectorAll(".tag-cat-add").forEach(btn => {
    btn.addEventListener("click", async () => {
      const name = prompt(t("tags.newTagPrompt"));
      if (!name || !name.trim()) return;
      const catId = parseInt(btn.dataset.categoryId);
      const res = await fetch(`${API}/api/tags`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: catId, name: name.trim() }),
      });
      const newTag = await res.json();
      const currentlySelected = getSelectedTagIdsFromModal();
      await loadTagCategories();
      renderTradeModalTagCategories([...currentlySelected, newTag.id]);
    });
  });
}

function getSelectedTagIdsFromModal() {
  return Array.from(document.querySelectorAll(".tag-cat-select"))
    .map(sel => sel.value)
    .filter(v => v)
    .map(v => parseInt(v));
}

document.getElementById("open-add-trade").addEventListener("click", () => openTradeModal());
document.getElementById("cancel-trade-btn").addEventListener("click", () => modal.classList.remove("open"));
modal.addEventListener("click", e => { if (e.target === modal) modal.classList.remove("open"); });

form.addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("trade-id").value;
  const payload = {
    account_id: parseInt(document.getElementById("f-account").value),
    symbol: document.getElementById("f-symbol").value.trim(),
    side: document.getElementById("f-side").value,
    quantity: parseFloat(document.getElementById("f-quantity").value),
    entry_price: parseFloat(document.getElementById("f-entry-price").value),
    exit_price: document.getElementById("f-exit-price").value ? parseFloat(document.getElementById("f-exit-price").value) : null,
    stop_price: document.getElementById("f-stop-price").value ? parseFloat(document.getElementById("f-stop-price").value) : null,
    target_price: document.getElementById("f-target-price").value ? parseFloat(document.getElementById("f-target-price").value) : null,
    mae_price: document.getElementById("f-mae-price").value ? parseFloat(document.getElementById("f-mae-price").value) : null,
    mfe_price: document.getElementById("f-mfe-price").value ? parseFloat(document.getElementById("f-mfe-price").value) : null,
    commission: parseFloat(document.getElementById("f-commission").value || 0),
    entry_time: new Date(document.getElementById("f-entry-time").value).toISOString(),
    exit_time: document.getElementById("f-exit-time").value ? new Date(document.getElementById("f-exit-time").value).toISOString() : null,
    strategy: document.getElementById("f-strategy").value.trim() || null,
    notes: tradeNotesEditor.getValue(),
    tag_ids: getSelectedTagIdsFromModal(),
  };

  let savedId = id;
  if (id) {
    await fetch(`${API}/api/trades/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } else {
    const res = await fetch(`${API}/api/trades`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const created = await res.json();
    savedId = created.id;
  }

  await tradeScreenshots.uploadPending(savedId);

  modal.classList.remove("open");
  loadTrades();
  loadDashboard();
  loadStrategies();
});

document.getElementById("delete-trade-btn").addEventListener("click", async () => {
  const id = document.getElementById("trade-id").value;
  if (!id) return;
  if (!confirm(t("confirm.deleteTrade"))) return;
  await fetch(`${API}/api/trades/${id}`, { method: "DELETE" });
  modal.classList.remove("open");
  loadTrades();
  loadDashboard();
});

// ---------- Analysis journal ----------
let analysisCalendarDate = new Date();
let currentMonthAnalyses = [];

const analysisNotesEditor = initRichNotesEditor({
  editorId: "an-notes", toolbarId: "an-notes-toolbar",
  colorPickerId: "an-notes-color-picker", previewsId: "an-notes-link-previews",
});
const analysisScreenshots = initScreenshotGallery({
  fileInputId: "an-screenshot", galleryId: "an-screenshot-gallery",
  apiBase: "analyses", getEntityId: () => document.getElementById("an-id").value,
});

function toDateStr(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

async function renderAnalysisCalendar() {
  const year = analysisCalendarDate.getFullYear();
  const month = analysisCalendarDate.getMonth();
  const monthLabel = analysisCalendarDate.toLocaleDateString(locale(), { month: "long", year: "numeric" });
  document.getElementById("an-cal-month-label").textContent = monthLabel;

  const weekdayRow = document.getElementById("an-calendar-weekday-row");
  weekdayRow.innerHTML = "";
  const refSunday = new Date(2023, 0, 1); // a Sunday
  for (let i = 0; i < 7; i++) {
    const d = new Date(refSunday);
    d.setDate(refSunday.getDate() + i);
    weekdayRow.innerHTML += `<div>${d.toLocaleDateString(locale(), { weekday: "short" })}</div>`;
  }

  const firstOfMonth = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const startWeekday = firstOfMonth.getDay();

  const dateFrom = toDateStr(firstOfMonth);
  const dateTo = toDateStr(new Date(year, month, daysInMonth));
  const res = await fetch(`${API}/api/analyses?date_from=${dateFrom}&date_to=${dateTo}`);
  currentMonthAnalyses = await res.json();
  const byDate = {};
  for (const a of currentMonthAnalyses) {
    (byDate[a.date] = byDate[a.date] || []).push(a);
  }

  const grid = document.getElementById("analysis-calendar-grid");
  grid.innerHTML = "";
  const cells = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let day = 1; day <= daysInMonth; day++) cells.push(day);
  while (cells.length % 7 !== 0) cells.push(null);

  for (const day of cells) {
    if (day === null) {
      grid.innerHTML += `<div class="analysis-day empty"></div>`;
      continue;
    }
    const dateStr = toDateStr(new Date(year, month, day));
    const entries = byDate[dateStr] || [];
    const entriesHtml = entries.map(a =>
      `<div class="an-entry" data-id="${a.id}">${escapeHtml(a.title)}</div>`
    ).join("");
    grid.innerHTML += `
      <div class="analysis-day" data-date="${dateStr}">
        <span class="an-day-num">${day}</span>
        ${entriesHtml}
        <button type="button" class="an-add-btn" data-date="${dateStr}">+</button>
      </div>`;
  }
}

document.getElementById("an-cal-prev").addEventListener("click", () => {
  analysisCalendarDate = new Date(analysisCalendarDate.getFullYear(), analysisCalendarDate.getMonth() - 1, 1);
  renderAnalysisCalendar();
});
document.getElementById("an-cal-next").addEventListener("click", () => {
  analysisCalendarDate = new Date(analysisCalendarDate.getFullYear(), analysisCalendarDate.getMonth() + 1, 1);
  renderAnalysisCalendar();
});
document.getElementById("an-cal-thismonth").addEventListener("click", () => {
  analysisCalendarDate = new Date();
  renderAnalysisCalendar();
});

document.getElementById("analysis-calendar-grid").addEventListener("click", e => {
  const addBtn = e.target.closest(".an-add-btn");
  if (addBtn) { openAnalysisModal(null, addBtn.dataset.date); return; }
  const entry = e.target.closest(".an-entry");
  if (entry) {
    const analysis = currentMonthAnalyses.find(a => a.id === parseInt(entry.dataset.id));
    if (analysis) openAnalysisModal(analysis);
  }
});

const analysisModal = document.getElementById("analysis-modal");
const analysisForm = document.getElementById("analysis-form");

function openAnalysisModal(analysis = null, defaultDate = null) {
  analysisForm.reset();
  analysisScreenshots.setSaved(analysis && analysis.screenshots);
  if (analysis) {
    document.getElementById("analysis-modal-title").textContent = t("analysis.editTitle");
    document.getElementById("an-id").value = analysis.id;
    document.getElementById("an-date").value = analysis.date;
    document.getElementById("an-title").value = analysis.title;
    analysisNotesEditor.setContent(analysis.notes);
    document.getElementById("delete-analysis-btn").style.display = "inline-block";
  } else {
    document.getElementById("analysis-modal-title").textContent = t("analysis.addTitle");
    document.getElementById("an-id").value = "";
    document.getElementById("an-date").value = defaultDate || toDateStr(new Date());
    analysisNotesEditor.setContent("");
    document.getElementById("delete-analysis-btn").style.display = "none";
  }
  analysisModal.classList.add("open");
}

document.getElementById("cancel-analysis-btn").addEventListener("click", () => analysisModal.classList.remove("open"));
analysisModal.addEventListener("click", e => { if (e.target === analysisModal) analysisModal.classList.remove("open"); });

analysisForm.addEventListener("submit", async e => {
  e.preventDefault();
  const id = document.getElementById("an-id").value;
  const payload = {
    date: document.getElementById("an-date").value,
    title: document.getElementById("an-title").value.trim(),
    notes: analysisNotesEditor.getValue(),
  };
  let savedId = id;
  if (id) {
    await fetch(`${API}/api/analyses/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } else {
    const res = await fetch(`${API}/api/analyses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const created = await res.json();
    savedId = created.id;
  }
  await analysisScreenshots.uploadPending(savedId);

  analysisModal.classList.remove("open");
  renderAnalysisCalendar();
});

document.getElementById("delete-analysis-btn").addEventListener("click", async () => {
  const id = document.getElementById("an-id").value;
  if (!id) return;
  if (!confirm(t("confirm.deleteAnalysis"))) return;
  await fetch(`${API}/api/analyses/${id}`, { method: "DELETE" });
  analysisModal.classList.remove("open");
  renderAnalysisCalendar();
});

// ---------- Account tab: accounts management + deposits/withdrawals ----------
async function loadAccount() {
  const settingsRes = await fetch(`${API}/api/settings`);
  const settings = await settingsRes.json();
  document.getElementById("lang-select").value = settings.language || "fr";

  await loadAccountsList();
  renderAccountsTable();
  await loadTagCategories();
  await loadStrategies();

  const cfRes = await fetch(`${API}/api/cashflows`);
  const cashflows = await cfRes.json();
  const tbody = document.querySelector("#cashflow-table tbody");
  tbody.innerHTML = "";
  for (const cf of cashflows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${cf.date}</td>
      <td>${cf.account_name ?? "-"}</td>
      <td>${cf.type === "deposit" ? t("account.deposit") : t("account.withdrawal")}</td>
      <td class="${cf.type === "deposit" ? "pos" : "neg"}">${cf.type === "deposit" ? "+" : "-"}${fmt(cf.amount)}</td>
      <td>${cf.note ?? ""}</td>
      <td><button class="btn danger cf-delete" data-id="${cf.id}">${t("table.delete")}</button></td>
    `;
    tbody.appendChild(tr);
  }
  document.querySelectorAll(".cf-delete").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(t("confirm.deleteCashflow"))) return;
      await fetch(`${API}/api/cashflows/${btn.dataset.id}`, { method: "DELETE" });
      loadAccount();
      loadDashboard();
    });
  });
}

function renderAccountsTable() {
  const tbody = document.querySelector("#accounts-table tbody");
  tbody.innerHTML = "";
  for (const a of allAccounts) {
    const tr = document.createElement("tr");
    const statusBadge = a.archived
      ? `<span class="badge archived">${t("account.archived")}</span>`
      : `<span class="badge active-status">${t("account.active")}</span>`;
    tr.innerHTML = `
      <td><input type="text" class="acc-name" data-id="${a.id}" value="${a.name}"></td>
      <td><input type="number" step="any" class="acc-balance" data-id="${a.id}" value="${a.initial_balance}"></td>
      <td><input type="date" class="acc-date" data-id="${a.id}" value="${a.initial_balance_date ?? ""}"></td>
      <td><input type="checkbox" class="acc-is-propfirm" data-id="${a.id}" ${a.is_prop_firm ? "checked" : ""}></td>
      <td><input type="text" class="acc-firm-name" data-id="${a.id}" value="${a.firm_name ?? ""}" placeholder="FTMO, MFF..."></td>
      <td>${statusBadge}</td>
      <td class="acc-actions">
        <button class="btn acc-save" data-id="${a.id}">${t("form.save")}</button>
        <button class="btn acc-toggle-archive" data-id="${a.id}">${a.archived ? t("account.unarchive") : t("account.archive")}</button>
        <button class="btn danger acc-delete" data-id="${a.id}">${t("account.delete")}</button>
      </td>
    `;
    tbody.appendChild(tr);
  }

  tbody.querySelectorAll(".acc-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const name = tbody.querySelector(`.acc-name[data-id="${id}"]`).value.trim();
      if (!name) { alert(t("account.nameRequired")); return; }
      const balance = parseFloat(tbody.querySelector(`.acc-balance[data-id="${id}"]`).value || 0);
      const date = tbody.querySelector(`.acc-date[data-id="${id}"]`).value || null;
      const isPropFirm = tbody.querySelector(`.acc-is-propfirm[data-id="${id}"]`).checked;
      const firmName = tbody.querySelector(`.acc-firm-name[data-id="${id}"]`).value.trim() || null;
      await fetch(`${API}/api/accounts/${id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, initial_balance: balance, initial_balance_date: date, is_prop_firm: isPropFirm, firm_name: firmName }),
      });
      await loadAccountsList();
      renderAccountsTable();
      loadDashboard();
    });
  });
  tbody.querySelectorAll(".acc-toggle-archive").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const acc = allAccounts.find(a => a.id === parseInt(id));
      await fetch(`${API}/api/accounts/${id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ archived: !acc.archived }),
      });
      await loadAccountsList();
      renderAccountsTable();
      loadDashboard();
    });
  });
  tbody.querySelectorAll(".acc-delete").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(t("account.confirmDelete"))) return;
      const res = await fetch(`${API}/api/accounts/${btn.dataset.id}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json();
        alert(err.detail === "cannot delete the only remaining account"
          ? t("account.cannotDeleteLast") : t("account.cannotDeleteInUse"));
        return;
      }
      await loadAccountsList();
      renderAccountsTable();
      loadDashboard();
    });
  });
}

// ---------- Prop firms ----------
const PROP_EVENT_TYPES = ["purchase", "phase_pass", "funded", "payout", "scaling", "reset", "breach", "other"];

async function loadPropFirms() {
  const res = await fetch(`${API}/api/prop-firms?` + filterParams().toString());
  const firms = await res.json();
  document.getElementById("propfirms-empty").style.display = firms.length === 0 ? "block" : "none";
  const list = document.getElementById("propfirms-list");
  list.innerHTML = firms.map(f => renderPropFirmCard(f)).join("");
  wirePropFirmCardEvents(firms);
}

function renderPropFirmCard(f) {
  const a = f.account;
  const netCls = f.net >= 0 ? "pos" : "neg";
  const tradingCls = f.trading_pnl >= 0 ? "pos" : "neg";
  const eventsHtml = f.events.length === 0
    ? `<p class="muted">${t("propfirm.noEvents")}</p>`
    : `<table class="data-table"><thead><tr>
         <th>${t("propfirm.eventDate")}</th><th>${t("propfirm.eventType")}</th>
         <th>${t("propfirm.label")}</th><th>${t("propfirm.amount")}</th><th></th>
       </tr></thead><tbody>
       ${f.events.map(e => `
         <tr>
           <td>${parseDateSafe(e.event_date).toLocaleDateString(locale())}</td>
           <td><span class="propfirm-event-type-badge ${e.event_type}">${t("propfirm.type." + e.event_type)}</span></td>
           <td>${e.label ?? "-"}${e.note ? ` <span class="muted">(${e.note})</span>` : ""}</td>
           <td>${e.amount != null ? fmt(e.amount) : "-"}</td>
           <td><button class="btn danger prop-event-delete" data-id="${e.id}">${t("table.delete")}</button></td>
         </tr>`).join("")}
       </tbody></table>`;

  return `
    <div class="propfirm-card" data-account-id="${a.id}">
      <div class="propfirm-card-header">
        <div>
          <div class="propfirm-card-title">${a.firm_name || t("propfirm.firmName")} <span class="propfirm-card-sub">— ${a.name}</span></div>
        </div>
        <span class="propfirm-status-badge ${f.status}">${t("propfirm.status." + f.status)}</span>
      </div>
      <div class="propfirm-stats">
        <div class="propfirm-stat"><div class="propfirm-stat-label">${t("propfirm.totalSpent")}</div><div class="propfirm-stat-value">${fmt(f.total_spent)}</div></div>
        <div class="propfirm-stat"><div class="propfirm-stat-label">${t("propfirm.totalReceived")}</div><div class="propfirm-stat-value">${fmt(f.total_received)}</div></div>
        <div class="propfirm-stat"><div class="propfirm-stat-label">${t("propfirm.net")}</div><div class="propfirm-stat-value ${netCls}">${fmt(f.net)}</div></div>
        <div class="propfirm-stat"><div class="propfirm-stat-label">${t("propfirm.tradingPnl")}</div><div class="propfirm-stat-value ${tradingCls}">${fmt(f.trading_pnl)}</div></div>
      </div>
      <div class="propfirm-events-title">${t("propfirm.events")}</div>
      <div class="table-wrap">${eventsHtml}</div>
      <div class="propfirm-add-event-form">
        <label>${t("propfirm.eventType")}
          <select class="prop-new-type">
            ${PROP_EVENT_TYPES.map(ty => `<option value="${ty}">${t("propfirm.type." + ty)}</option>`).join("")}
          </select>
        </label>
        <label>${t("propfirm.eventDate")} <input type="date" class="prop-new-date"></label>
        <label>${t("propfirm.amount")} <input type="number" step="any" class="prop-new-amount"></label>
        <label>${t("propfirm.label")} <input type="text" class="prop-new-label" placeholder="${t("propfirm.labelPlaceholder")}"></label>
        <button type="button" class="btn primary prop-add-event" data-account-id="${a.id}">${t("propfirm.addEvent")}</button>
      </div>
    </div>`;
}

function wirePropFirmCardEvents(firms) {
  document.querySelectorAll(".prop-add-event").forEach(btn => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".propfirm-card");
      const date = card.querySelector(".prop-new-date").value;
      if (!date) { alert(t("propfirm.eventDate") + " ?"); return; }
      const payload = {
        account_id: parseInt(btn.dataset.accountId),
        event_type: card.querySelector(".prop-new-type").value,
        event_date: date,
        amount: card.querySelector(".prop-new-amount").value ? parseFloat(card.querySelector(".prop-new-amount").value) : null,
        label: card.querySelector(".prop-new-label").value.trim() || null,
      };
      await fetch(`${API}/api/prop-events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      loadPropFirms();
    });
  });
  document.querySelectorAll(".prop-event-delete").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(t("propfirm.confirmDeleteEvent"))) return;
      await fetch(`${API}/api/prop-events/${btn.dataset.id}`, { method: "DELETE" });
      loadPropFirms();
    });
  });
}

function renderCategoriesTable() {
  const tbody = document.querySelector("#categories-table tbody");
  tbody.innerHTML = "";
  for (const cat of allTagCategories) {
    const tr = document.createElement("tr");
    const tagsHtml = cat.tags.map(tg => `
      <span class="tag-chip">
        <span class="tag-chip-dot" style="background:${cat.color}"></span>
        ${tg.name}
        <button type="button" class="tag-chip-remove" data-tag-id="${tg.id}" title="${t("tags.confirmDeleteTag")}">&times;</button>
      </span>
    `).join("");
    tr.innerHTML = `
      <td><input type="text" class="cat-name" data-id="${cat.id}" value="${cat.name}"></td>
      <td><input type="color" class="cat-color" data-id="${cat.id}" value="${cat.color}"></td>
      <td class="cat-tags-cell">${tagsHtml}<button type="button" class="tag-add-inline" data-category-id="${cat.id}">+ ${t("tags.tags")}</button></td>
      <td class="acc-actions">
        <button class="btn cat-save" data-id="${cat.id}">${t("form.save")}</button>
        <button class="btn danger cat-delete" data-id="${cat.id}">${t("account.delete")}</button>
      </td>
    `;
    tbody.appendChild(tr);
  }

  tbody.querySelectorAll(".cat-save").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const name = tbody.querySelector(`.cat-name[data-id="${id}"]`).value.trim();
      if (!name) { alert(t("tags.categoryNameRequired")); return; }
      const color = tbody.querySelector(`.cat-color[data-id="${id}"]`).value;
      await fetch(`${API}/api/tag-categories/${id}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, color }),
      });
      await loadTagCategories();
    });
  });
  tbody.querySelectorAll(".cat-delete").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(t("tags.confirmDeleteCategory"))) return;
      await fetch(`${API}/api/tag-categories/${btn.dataset.id}`, { method: "DELETE" });
      await loadTagCategories();
    });
  });
  tbody.querySelectorAll(".tag-chip-remove").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(t("tags.confirmDeleteTag"))) return;
      await fetch(`${API}/api/tags/${btn.dataset.tagId}`, { method: "DELETE" });
      await loadTagCategories();
    });
  });
  tbody.querySelectorAll(".tag-add-inline").forEach(btn => {
    btn.addEventListener("click", async () => {
      const name = prompt(t("tags.newTagPrompt"));
      if (!name || !name.trim()) return;
      await fetch(`${API}/api/tags`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: parseInt(btn.dataset.categoryId), name: name.trim() }),
      });
      await loadTagCategories();
    });
  });
}

document.getElementById("add-category-btn").addEventListener("click", async () => {
  const name = document.getElementById("cat-name-new").value.trim();
  if (!name) { alert(t("tags.categoryNameRequired")); return; }
  const color = document.getElementById("cat-color-new").value;
  await fetch(`${API}/api/tag-categories`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, color }),
  });
  document.getElementById("category-form").reset();
  document.getElementById("cat-color-new").value = "#4d8dff";
  await loadTagCategories();
});

document.getElementById("add-account-btn").addEventListener("click", async () => {
  const name = document.getElementById("acc-name").value.trim();
  if (!name) { alert(t("account.nameRequired")); return; }
  const payload = {
    name,
    initial_balance: parseFloat(document.getElementById("acc-initial-balance").value || 0),
    initial_balance_date: document.getElementById("acc-initial-date").value || null,
    is_prop_firm: document.getElementById("acc-is-propfirm").checked,
    firm_name: document.getElementById("acc-firm-name").value.trim() || null,
  };
  await fetch(`${API}/api/accounts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  document.getElementById("account-form").reset();
  await loadAccountsList();
  renderAccountsTable();
  loadDashboard();
});

document.getElementById("lang-select").addEventListener("change", async e => {
  LANG = e.target.value;
  await fetch(`${API}/api/settings`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language: LANG }),
  });
  applyStaticTranslations();
  applyTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  updateDateFilterLabel();
  updateAccountFilterLabel();
  loadDashboard();
  loadTrades();
  loadAccount();
  loadImportLog();
  if (document.getElementById("tab-analyses").classList.contains("active")) renderAnalysisCalendar();
});

document.getElementById("add-cashflow-btn").addEventListener("click", async () => {
  const amount = parseFloat(document.getElementById("cf-amount").value);
  const date = document.getElementById("cf-date").value;
  if (!amount || !date) { alert(t("alert.amountDateRequired")); return; }
  const payload = {
    account_id: parseInt(document.getElementById("cf-account").value),
    type: document.getElementById("cf-type").value,
    amount: amount,
    date: date,
    note: document.getElementById("cf-note").value.trim() || null,
  };
  await fetch(`${API}/api/cashflows`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  document.getElementById("cf-amount").value = "";
  document.getElementById("cf-note").value = "";
  loadAccount();
  loadDashboard();
});

// ---------- Import log ----------
async function loadImportLog() {
  const res = await fetch(`${API}/api/imports`);
  const batches = await res.json();
  const tbody = document.querySelector("#import-log-table tbody");
  tbody.innerHTML = "";
  for (const b of batches) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${fmtDate(b.imported_at)}</td>
      <td>${b.account_name ?? "-"}</td>
      <td>${b.filename ?? "-"}</td>
      <td>${b.trades_inserted}</td>
      <td>${b.trades_skipped}</td>
      <td><button class="btn danger batch-delete" data-id="${b.id}">${t("import.undo")}</button></td>
    `;
    tbody.appendChild(tr);
  }
  document.querySelectorAll(".batch-delete").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(t("confirm.deleteBatch"))) return;
      await fetch(`${API}/api/imports/${btn.dataset.id}`, { method: "DELETE" });
      loadImportLog();
      loadTrades();
      loadDashboard();
    });
  });
}

// ---------- CSV / MT5 Import ----------
let csvPreviewTrades = [];

function importPlatform() {
  return document.getElementById("csv-platform").value;
}

function applyImportPlatform() {
  const platform = importPlatform();
  const fileInput = document.getElementById("csv-file");
  const description = document.getElementById("import-description");
  if (platform === "mt5") {
    fileInput.accept = ".xlsx";
    description.dataset.i18n = "import.descriptionMt5";
  } else {
    fileInput.accept = ".csv";
    description.dataset.i18n = "import.descriptionTradingview";
  }
  description.innerHTML = t(description.dataset.i18n);
  fileInput.value = "";
  document.getElementById("csv-preview-panel").style.display = "none";
}

document.getElementById("csv-platform").addEventListener("change", applyImportPlatform);

document.getElementById("csv-preview-btn").addEventListener("click", async () => {
  const fileInput = document.getElementById("csv-file");
  if (!fileInput.files.length) { alert(t("alert.noFileSelected")); return; }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  fd.append("account_id", document.getElementById("csv-account").value);

  const warningsEl = document.getElementById("csv-warnings");
  warningsEl.innerHTML = "";

  const endpoint = importPlatform() === "mt5" ? "mt5" : "csv";
  const res = await fetch(`${API}/api/import/${endpoint}/preview`, { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.json();
    warningsEl.innerHTML = `<p class="neg">${err.detail}</p>`;
    return;
  }
  const data = await res.json();
  csvPreviewTrades = data.trades;

  if (data.warnings.length) {
    warningsEl.innerHTML = data.warnings.map(w => `<p class="muted">⚠️ ${w}</p>`).join("");
  }

  const panel = document.getElementById("csv-preview-panel");
  panel.style.display = "block";
  document.getElementById("csv-summary").textContent =
    t("import.summary", { n: data.trades.length, d: data.duplicates });

  const tbody = document.querySelector("#csv-preview-table tbody");
  tbody.innerHTML = "";
  data.trades.forEach((tr_, i) => {
    const tr = document.createElement("tr");
    const pnlClass = tr_.pnl_usd != null ? (tr_.pnl_usd >= 0 ? "pos" : "neg") : (tr_.pnl_native >= 0 ? "pos" : "neg");
    const pnlDisplay = tr_.pnl_usd != null ? fmt(tr_.pnl_usd) + " USD" : fmt(tr_.pnl_native) + " " + (tr_.quote_currency || "");
    const sideLabel = tr_.side === "long" ? t("form.long") : t("form.short");
    tr.innerHTML = `
      <td><input type="checkbox" class="csv-row-check" data-idx="${i}" ${tr_.already_imported ? "" : "checked"}></td>
      <td>${tr_.symbol}</td>
      <td><span class="badge ${tr_.side}">${sideLabel}</span></td>
      <td>${fmt(tr_.quantity, 0)}</td>
      <td>${fmt(tr_.entry_price, 5)}</td>
      <td>${fmt(tr_.exit_price, 5)}</td>
      <td>${fmtDate(tr_.entry_time)}</td>
      <td>${fmtDate(tr_.exit_time)}</td>
      <td class="${pnlClass}">${pnlDisplay}${tr_.already_imported ? " (" + t("import.alreadyImported") + ")" : ""}</td>
    `;
    if (tr_.already_imported) tr.style.opacity = "0.5";
    tbody.appendChild(tr);
  });
});

document.getElementById("csv-select-all").addEventListener("change", e => {
  document.querySelectorAll(".csv-row-check").forEach(cb => cb.checked = e.target.checked);
});

document.getElementById("csv-commit-btn").addEventListener("click", async () => {
  const selected = [];
  document.querySelectorAll(".csv-row-check:checked").forEach(cb => {
    selected.push(csvPreviewTrades[parseInt(cb.dataset.idx)]);
  });
  if (selected.length === 0) { alert(t("alert.noTradeSelected")); return; }

  const filename = document.getElementById("csv-file").files[0]?.name ?? null;
  const accountId = parseInt(document.getElementById("csv-account").value);
  const endpoint = importPlatform() === "mt5" ? "mt5" : "csv";
  const res = await fetch(`${API}/api/import/${endpoint}/commit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trades: selected, filename: filename, account_id: accountId }),
  });
  const result = await res.json();
  alert(t("alert.importResult", { inserted: result.inserted, skipped: result.skipped }));
  document.getElementById("csv-preview-panel").style.display = "none";
  document.getElementById("csv-file").value = "";
  loadImportLog();
  loadDashboard();
});

// ---------- Init ----------
async function initApp() {
  try {
    const res = await fetch(`${API}/api/settings`);
    const settings = await res.json();
    LANG = settings.language || "fr";
  } catch (e) {
    LANG = "fr";
  }
  document.getElementById("lang-select").value = LANG;
  applyStaticTranslations();
  await loadAccountsList();
  await loadTagCategories();
  await loadStrategies();
  applyImportPlatform();
  updateDateFilterLabel();
  updateAccountFilterLabel();
  updateTagsFilterLabel();
  loadDashboard();
  loadTrades();
}
initApp();
