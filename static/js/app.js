/* Harbor · 港股投研台 */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const FONT = '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif';
  const MONO = '"Segoe UI Variable Text","Segoe UI","PingFang SC","Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif';
  const PALETTES = {
    dark: {
      up: '#ff5d73', down: '#2ed3a1', accent: '#4ade80', cyan: '#38bdf8',
      gold: '#f5c45c', violet: '#a78bfa', text: '#e8eef9', muted: '#8b99af',
      dim: '#5d6b82', line: '#1b2940', grid: 'rgba(35,52,78,.45)',
      track: '#1a2840', panel: '#0d1524', tooltipBg: 'rgba(10,18,32,.97)',
      tooltipBorder: '#283a56', pointer: '#314763', tooltipText: '#c9d5e8',
    },
    light: {
      up: '#e5484d', down: '#0f9f6e', accent: '#0f9f6e', cyan: '#087fc0',
      gold: '#b7791f', violet: '#7554cf', text: '#101b2d', muted: '#52627a',
      dim: '#7d8ca2', line: '#dbe5f0', grid: 'rgba(16,27,45,.10)',
      track: '#e7eef6', panel: '#ffffff', tooltipBg: 'rgba(255,255,255,.98)',
      tooltipBorder: '#dbe5f0', pointer: '#b9c9db', tooltipText: '#1b2a3f',
    },
  };
  let storedTheme = 'dark';
  try { storedTheme = localStorage.getItem('harbor-theme') || 'dark'; } catch (_) {}
  document.documentElement.dataset.theme = storedTheme;
  let C = PALETTES[storedTheme] || PALETTES.dark;

  const SECTOR_NAMES = ['互联网平台', '硬科技/半导体', '医药生物', '金融', '地产/收租', '消费', '能源/资源', '汽车/工业', '电讯/公用'];
  const WATCH_KEY = 'harbor-watchlist';

  const state = {
    meta: null,
    view: 'overview',
    overview: null,
    buyback: null,
    short: null,
    signals: null,
    macro: null,
    stock: null,
    shareholders: null,
    screener: null,
    screenerRows: null,
    charts: {},
    flowRange: 120,
    bbChartRange: 60,
    bbPeriod: 20,
    bbSort: 'amount',
    shortChartRange: 52,
    shortPeriod: 4,
    shortSort: 'ratio',
    moverTab: 'gainers',
    stockRange: 250,
    stockCode: null,
    screenerPreset: 'all',
    syncTimer: null,
    syncRunning: false,
    searchTimer: null,
  };

  /* ---------------- utils ---------------- */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[m]));
  }
  function num(v, d = 2) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function int(v) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  }
  function pct(v, d = 2, sign = true) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    return (sign && v > 0 ? '+' : '') + Number(v).toFixed(d) + '%';
  }
  function money(v, d = 2) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    const a = Math.abs(v);
    if (a >= 1e12) return (v / 1e12).toFixed(d) + '万亿';
    if (a >= 1e8) return (v / 1e8).toFixed(d) + '亿';
    if (a >= 1e4) return (v / 1e4).toFixed(1) + '万';
    return num(v, 0);
  }
  function mcap(v) {
    if (v == null) return '—';
    if (Math.abs(v) >= 1e12) return (v / 1e12).toFixed(2) + '万亿';
    return (v / 1e8).toFixed(1) + '亿';
  }
  function yi(v, d = 2) {
    if (v == null) return '—';
    return (v / 1e8).toFixed(d);
  }
  function cls(v) {
    if (v == null || Math.abs(v) < 0.0001) return 'flat';
    return v > 0 ? 'up' : 'down';
  }
  function shortDate(d) { return d ? String(d).slice(5) : '—'; }
  function tag(text, tone = '') { return `<span class="tag ${tone}">${esc(text)}</span>`; }

  function sortableTable(table, colIdx, dir) {
    const tbody = table.tBodies && table.tBodies[0];
    if (!tbody) return;
    const rows = Array.from(tbody.rows);
    const cellVal = tr => {
      const cell = tr.cells[colIdx];
      if (!cell) return null;
      if (cell.dataset.v !== undefined) {
        const raw = cell.dataset.v;
        if (raw === '' || raw === 'null' || raw === 'undefined') return null;
        const n = Number(raw);
        return Number.isNaN(n) ? raw : n;
      }
      const txt = cell.textContent.trim();
      if (!txt || txt === '—') return null;
      const n = parseFloat(txt.replace(/,/g, '').replace(/[+%]/g, ''));
      return Number.isNaN(n) ? txt : n;
    };
    rows.sort((ra, rb) => {
      const a = cellVal(ra), b = cellVal(rb);
      if (a === null && b === null) return 0;
      if (a === null) return 1;
      if (b === null) return -1;
      if (typeof a === 'number' && typeof b === 'number') return dir === 'asc' ? a - b : b - a;
      return dir === 'asc' ? String(a).localeCompare(String(b), 'zh') : String(b).localeCompare(String(a), 'zh');
    });
    rows.forEach((r, i) => {
      tbody.appendChild(r);
      const rank = r.cells[0] && r.cells[0].querySelector('.rank-no');
      if (rank) rank.textContent = i + 1;
    });
  }
  function toast(msg, ms = 2600) {
    const el = $('#toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), ms);
  }
  function showError(msg) {
    const el = $('#errorBanner');
    el.hidden = false;
    el.textContent = msg;
  }
  function clearError() { $('#errorBanner').hidden = true; }

  /* ---------------- theme / watchlist / export ---------------- */
  function getWatch() {
    try {
      const v = JSON.parse(localStorage.getItem(WATCH_KEY) || '[]');
      return Array.isArray(v) ? v.filter(x => /^\d{5}$/.test(String(x))) : [];
    } catch (_) { return []; }
  }
  function updateWatchBadge() {
    const n = getWatch().length;
    const btn = $('#watchBtn');
    if (!btn) return;
    const badge = $('#watchCount');
    if (badge) badge.textContent = n ? n : '';
    btn.classList.toggle('has-items', n > 0);
  }
  function toggleWatch(code) {
    code = String(code).padStart(5, '0');
    const list = getWatch();
    const i = list.indexOf(code);
    if (i >= 0) list.splice(i, 1);
    else list.unshift(code);
    try { localStorage.setItem(WATCH_KEY, JSON.stringify(list)); } catch (_) {}
    updateWatchBadge();
    const btn = document.querySelector(`[data-star="${code}"]`);
    if (btn) btn.classList.toggle('on', list.includes(code));
    toast(i >= 0 ? `${code} 已移出自选` : `${code} 已加入自选`);
    if (!$('#watchDrawer').hidden) openWatchDrawer();
  }
  function closeWatchDrawer() {
    $('#watchDrawer').hidden = true;
    $('#watchMask').hidden = true;
  }
  async function openWatchDrawer() {
    const codes = getWatch();
    $('#watchMask').hidden = false;
    $('#watchDrawer').hidden = false;
    const body = $('#watchBody');
    if (!codes.length) {
      body.innerHTML = '<div class="watch-empty"><b>还没有自选股</b>在个股页点击星标，或在下方加入核心标的<br><button class="mini-btn" data-quick="00700">加入腾讯</button> <button class="mini-btn" data-quick="09992">加入泡泡玛特</button></div>';
      return;
    }
    body.innerHTML = '<div class="loading-panel">正在加载自选行情…</div>';
    try {
      const rows = await api('/api/watchlist?codes=' + codes.join(','));
      if (!rows.length) {
        body.innerHTML = '<div class="watch-empty"><b>自选暂无有效行情</b>可能已停牌或代码不在当前股票池</div>';
        return;
      }
      body.innerHTML = rows.map(r => `<div class="watch-item" data-wcode="${esc(r.code)}">
        <div>
          <div class="w-name">${esc(r.name)}<span class="w-code">${esc(r.code)}.HK</span></div>
          <div class="w-meta">${esc(r.sector)} · 回购占市值 ${num(r.buyback_cap, 1)}% · ${r.buyback_days} 天</div>
        </div>
        <div class="w-right">
          ${num(r.price, 2)}
          <div class="w-chg ${cls(r.change_pct)}">${pct(r.change_pct)}</div>
          <button class="w-del" data-unwatch="${esc(r.code)}" title="移出自选">移除</button>
        </div>
      </div>`).join('');
    } catch (err) {
      body.innerHTML = `<div class="watch-empty"><b>加载失败</b>${esc(err.message)}</div>`;
    }
  }
  function applyTheme(theme, rerender = true) {
    theme = theme === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    try { localStorage.setItem('harbor-theme', theme); } catch (_) {}
    C = PALETTES[theme];
    const use = $('#themeBtn')?.querySelector('use');
    if (use) use.setAttribute('href', theme === 'light' ? '#i-sun' : '#i-moon');
    if (rerender) rerenderCurrent();
  }
  function rerenderCurrent() {
    if (state.view === 'overview' && state.overview) renderOverview(state.overview);
    else if (state.view === 'buyback' && state.buyback) renderBuyback(state.buyback);
    else if (state.view === 'short' && state.short) renderShort(state.short);
    else if (state.view === 'signals' && state.signals) renderSignals(state.signals);
    else if (state.view === 'macro' && state.macro) renderMacro(state.macro);
    else if (state.view === 'stock' && state.stock) renderStock(state.stock);
    else if (state.view === 'screener' && state.screener) renderScreener(state.screener);
    setTimeout(resizeCharts, 70);
  }
  function csvDownload(filename, columns, rows) {
    const q = v => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
    const content = [columns.map(c => q(c.label)).join(','),
      ...rows.map(r => columns.map(c => q(typeof c.get === 'function' ? c.get(r) : r[c.key])).join(','))].join('\n');
    const blob = new Blob(['\ufeff' + content], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast(`已导出 ${rows.length} 行`);
  }

  async function api(path, options = {}) {
    const opt = Object.assign({ headers: { 'Content-Type': 'application/json' } }, options);
    const r = await fetch(path, opt);
    let j = null;
    try { j = await r.json(); } catch (_) { /* noop */ }
    if (!r.ok || !j || j.ok === false) throw new Error((j && j.error) || `请求失败 (${r.status})`);
    return j.data;
  }

  function chart(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    if (state.charts[id]) {
      try { state.charts[id].dispose(); } catch (_) {}
      delete state.charts[id];
    }
    const c = echarts.init(el, null, { renderer: 'canvas' });
    state.charts[id] = c;
    return c;
  }
  function resizeCharts() {
    Object.values(state.charts).forEach(c => { try { c.resize(); } catch (_) {} });
  }
  function tip(extra = {}) {
    return Object.assign({
      trigger: 'axis',
      backgroundColor: C.tooltipBg,
      borderColor: C.tooltipBorder,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: C.tooltipText, fontSize: 12, fontFamily: FONT },
      axisPointer: { lineStyle: { color: C.pointer, width: 1 } },
      extraCssText: 'border-radius:8px;box-shadow:0 12px 30px rgba(0,0,0,.18);',
    }, extra);
  }
  function axisX(data, showLabel = true) {
    return {
      type: 'category',
      data,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#23344e' } },
      axisTick: { show: false },
      axisLabel: {
        color: C.dim, fontSize: 11.5, fontFamily: MONO, show: showLabel, hideOverlap: true,
        formatter: v => /^\d{4}-\d{2}-\d{2}$/.test(v) ? v.slice(5) : v,
      },
      splitLine: { show: false },
    };
  }
  function axisY(extra = {}) {
    return Object.assign({
      type: 'value',
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: C.dim, fontSize: 12, fontFamily: MONO },
      splitLine: { lineStyle: { color: C.grid, type: 'dashed' } },
    }, extra);
  }
  const rgba = (hex, a) => {
    const h = hex.replace('#', '');
    const n = parseInt(h.length === 3 ? h.split('').map(x => x + x).join('') : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };

  /* ---------------- boot / sync ---------------- */
  async function init() {
    bindGlobal();
    const urlTheme = new URLSearchParams(location.search).get('theme');
    applyTheme(urlTheme === 'light' || urlTheme === 'dark' ? urlTheme : (document.documentElement.dataset.theme || 'dark'), false);
    updateWatchBadge();
    try {
      const meta = await api('/api/meta');
      state.meta = meta;
      applyMeta(meta);
      const s = await api('/api/sync/status');
      updateSyncButton(s);
      if (meta.needs_sync) {
        showBoot();
        pollSync('boot');
      } else {
        hideBoot();
        route();
        if (s.running) { showBanner(); pollSync('banner'); }
      }
    } catch (err) {
      hideBoot();
      showError(`无法连接后端服务：${err.message}`);
      $('.main').insertAdjacentHTML('beforeend', '<div class="panel empty"><b>后端未启动</b><span>请运行 python app.py 后刷新页面</span></div>');
    }
  }

  function applyMeta(meta) {
    const q = meta.quote_date ? shortDate(meta.quote_date) : '—';
    const b = meta.buyback_date ? shortDate(meta.buyback_date) : '—';
    const s = meta.short_date ? shortDate(meta.short_date) : '—';
    $('#sideDataStatus').textContent = `行情 ${q} · 回购 ${b} · 淡仓 ${s}`;
    const last = meta.last_sync;
    $('#footSync').textContent = last
      ? `同步 ${last.finished_at || '—'} · ${last.seconds || '—'}s`
      : '尚未同步';
    const foot = $('#syncMenuFoot');
    if (foot) foot.textContent = last ? `上次 ${last.finished_at || '—'} · ${last.seconds || '—'}s` : '尚无同步记录';
    const btn = $('#syncBtn');
    if (btn && !state.syncRunning) btn.title = last
      ? `上次同步 ${last.finished_at || ''} · ${last.seconds || ''}s`
      : '快速同步：行情 / 回购 / 指数 / 南向 / 淡仓';
    const pill = $('#marketPill');
    const ms = meta.market || {};
    pill.querySelector('span').textContent = ms.status || '—';
    pill.classList.toggle('live', ms.status === '盘中');
    pill.classList.toggle('closed', ms.status !== '盘中');
  }

  function showBoot() { $('#bootOverlay').hidden = false; }
  function hideBoot() { $('#bootOverlay').hidden = true; }
  function showBanner() { $('#syncBanner').hidden = false; }
  function hideBanner() { $('#syncBanner').hidden = true; }

  function syncProgressText(s) {
    const pct = Math.max(0, Math.min(100, s.percent || 0));
    const label = s.phase_label || (s.mode === 'full' ? '全量同步' : '同步');
    return { pct, label, eta: s.eta ? `约剩 ${s.eta}s` : '' };
  }

  function updateSyncButton(s) {
    const running = !!s.running;
    state.syncRunning = running;
    const btn = $('#syncBtn');
    const txt = $('#syncBtnText');
    const menuBtn = $('#syncMenuBtn');
    if (btn) { btn.classList.toggle('syncing', running); btn.disabled = running; }
    if (menuBtn) menuBtn.disabled = running;
    if (running) {
      const { pct, label, eta } = syncProgressText(s);
      if (txt) txt.textContent = `${label} ${pct}%`;
      if (btn) btn.title = `${label} · ${pct}%${eta ? ' · ' + eta : ''}`;
    } else {
      if (txt) txt.textContent = '同步';
      const last = s.last_sync || (state.meta && state.meta.last_sync);
      if (btn) btn.title = last
        ? `上次同步 ${last.finished_at || ''} · ${last.seconds || ''}s`
        : '快速同步：行情 / 回购 / 指数 / 南向 / 淡仓';
      const foot = $('#syncMenuFoot');
      if (foot) foot.textContent = last
        ? `上次 ${last.finished_at || '—'} · ${last.seconds || '—'}s`
        : '尚无同步记录';
    }
  }

  function resetDataCaches() {
    state.overview = null;
    state.buyback = null;
    state.short = null;
    state.signals = null;
    state.macro = null;
    state.screener = null;
    state.stock = null;
  }

  async function refreshAll() {
    try {
      const meta = await api('/api/meta');
      state.meta = meta;
      applyMeta(meta);
      resetDataCaches();
      const cur = state.view;
      if (cur === 'overview') await loadOverview();
      else if (cur === 'buyback') await loadBuyback();
      else if (cur === 'short') await loadShort();
      else if (cur === 'signals') await loadSignals();
      else if (cur === 'macro') await loadMacro();
      else if (cur === 'stock') await loadStock(state.stockCode || '00700');
      else if (cur === 'screener') await loadScreener(state.screenerPreset);
    } catch (err) {
      toast(err.message);
    }
  }

  async function pollSync(kind) {
    clearTimeout(state.syncTimer);
    try {
      const s = await api('/api/sync/status');
      const { pct, label, eta } = syncProgressText(s);
      updateSyncButton(s);
      if (kind === 'boot') {
        $('#bootBar').style.width = pct + '%';
        $('#bootPct').textContent = pct + '%';
        $('#bootMsg').textContent = `${label} · ${s.message || '正在同步公开数据…'}`;
        $('#bootCount').textContent = s.counts ? `回购 ${int(s.counts.buybacks)} · 行情 ${int(s.counts.quotes)}` : '';
      } else {
        showBanner();
        $('#syncBar').style.width = pct + '%';
        $('#syncPct').textContent = `${pct}%${eta ? ' · ' + eta : ''}`;
        $('#syncMessage').textContent = `${label} · ${s.message || '正在同步公开数据…'}`;
      }
      if (s.running) {
        state.syncTimer = setTimeout(() => pollSync(kind), 800);
        return;
      }
      if (kind === 'boot') {
        $('#bootBar').style.width = '100%';
        $('#bootPct').textContent = '100%';
        setTimeout(async () => {
          hideBoot();
          hideBanner();
          resetDataCaches();
          route();
          updateSyncButton(s);
          if (s.error) toast('同步完成，部分数据源失败', 3600);
        }, 400);
      } else {
        hideBanner();
        const last = s.last_sync || {};
        const okSteps = (last.steps || []).filter(x => x.status === 'ok').map(x => `${x.label} ${x.seconds}s`);
        const detail = okSteps.length ? ` · ${okSteps.join(' · ')}` : '';
        const warn = (last.warnings || []).length;
        toast(s.error ? '同步完成（部分数据源失败）'
          : `同步完成 · ${last.seconds || '—'}s${detail}${warn ? ` · ${warn} 项数据告警` : ''}`, 4200);
        await refreshAll();
        updateSyncButton(await api('/api/sync/status'));
      }
    } catch (err) {
      if (kind === 'boot') {
        $('#bootMsg').textContent = `同步状态读取失败：${err.message}`;
      } else {
        hideBanner();
        toast(err.message);
      }
      state.syncTimer = setTimeout(() => pollSync(kind), 2500);
    }
  }

  async function triggerSync(mode = 'quick') {
    const menu = $('#syncMenu');
    if (menu) menu.hidden = true;
    try {
      const s = await api('/api/sync/status');
      if (s.running) {
        updateSyncButton(s);
        showBanner();
        pollSync('banner');
        return;
      }
      const r = await api('/api/sync', { method: 'POST', body: JSON.stringify({ mode }) });
      if (r.started) {
        toast(mode === 'full' ? '已开始全量同步' : '已开始快速同步', 2000);
        showBanner();
        pollSync('banner');
      } else {
        toast(r.message || '同步任务已在运行');
      }
    } catch (err) { toast(err.message); }
  }

  /* ---------------- routing ---------------- */
  const TITLES = {
    overview: ['市场总览', 'MARKET COMMAND DECK'],
    buyback: ['回购雷达', 'REPURCHASE RADAR'],
    short: ['卖空透视', 'SHORT SELLING DECK'],
    signals: ['信号中心', 'SIGNAL CENTER'],
    macro: ['宏观环境', 'MACRO & LIQUIDITY'],
    stock: ['个股透视', 'SINGLE STOCK DECK'],
    screener: ['机会筛选', 'MULTI-FACTOR SCREENER'],
  };

  function goto(view, arg) {
    const hash = arg ? `${view}/${arg}` : view;
    if (location.hash.slice(1) === hash) route();
    else location.hash = hash;
  }

  function route() {
    const raw = location.hash.replace(/^#/, '') || 'overview';
    const [viewRaw, arg] = raw.split('/');
    const view = TITLES[viewRaw] ? viewRaw : 'overview';
    state.view = view;
    $$('.view').forEach(v => { v.hidden = v.id !== `view-${view}`; });
    $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
    const [title, sub] = TITLES[view];
    $('#pageTitle').textContent = title;
    $('#pageSub').textContent = sub;
    if (view === 'overview') loadOverview();
    else if (view === 'buyback') loadBuyback();
    else if (view === 'short') loadShort();
    else if (view === 'signals') loadSignals();
    else if (view === 'macro') loadMacro();
    else if (view === 'stock') loadStock(arg || state.stockCode || '00700');
    else if (view === 'screener') loadScreener(state.screenerPreset || 'all');
    setTimeout(resizeCharts, 80);
  }

  /* ---------------- overview ---------------- */
  async function loadOverview() {
    if (state.overview) { renderOverview(state.overview); return; }
    try {
      const d = await api('/api/overview');
      state.overview = d;
      renderOverview(d);
      clearError();
    } catch (err) {
      showError(`市场概览加载失败：${err.message}`);
    }
  }

  function renderOverview(d) {
    $('#overviewAsOf').textContent = `行情 ${d.as_of || '—'} · 回购 ${d.buyback_as_of || '—'}`;
    $('#buybackAsOf').textContent = d.buyback_as_of ? `截至 ${d.buyback_as_of}` : '';
    $('#breadthAsOf').textContent = d.as_of || '';
    renderTicker(d.indices);
    renderIndexCards(d.indices);
    renderNarrative(d.narrative);
    renderFlowChart(d);
    renderBuybackMini(d.buyback);
    renderBreadth(d.breadth);
    renderPeChart(d.breadth);
    renderSectorList(d.sectors);
    renderTopBuyback(d.buyback);
    renderMovers(d.movers);
    setTimeout(resizeCharts, 60);
  }

  function renderTicker(indices) {
    $('#tickerStrip').innerHTML = indices.map(i => `
      <div class="ticker"><span>${esc(i.short)}</span><b>${num(i.price, 2)}</b>
      <span class="${cls(i.change_pct)}">${pct(i.change_pct)}</span></div>`).join('');
  }

  function sparkline(values, positive, id = 0) {
    if (!values || values.length < 2) return '';
    const min = Math.min(...values), max = Math.max(...values);
    const span = max - min || 1;
    const pts = values.map((v, i) => [i / (values.length - 1) * 100, 30 - ((v - min) / span) * 26 + 2]);
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(' ');
    const area = `${line} L100,34 L0,34 Z`;
    const color = positive ? C.up : C.down;
    const aid = `sgA${id}`, lid = `sgL${id}`;
    return `<svg viewBox="0 0 100 34" preserveAspectRatio="none">
      <defs>
        <linearGradient id="${aid}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity=".26"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
        </linearGradient>
        <linearGradient id="${lid}" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="${color}" stop-opacity=".3"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="1"/>
        </linearGradient>
      </defs>
      <path class="spark-area" d="${area}" fill="url(#${aid})"></path>
      <path class="spark-line" pathLength="1" d="${line}" fill="none" stroke="url(#${lid})" stroke-width="1.8" vector-effect="non-scaling-stroke"></path>
    </svg>`;
  }

  function animateCount(el, target, decimals = 2) {
    if (!Number.isFinite(target)) return;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.textContent = num(target, decimals);
      return;
    }
    const dur = 620;
    const t0 = performance.now();
    const step = t => {
      const p = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      el.textContent = num(target * e, decimals);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function renderIndexCards(indices) {
    $('#indexCards').innerHTML = indices.map((i, idx) => {
      const tone = cls(i.change_pct);
      const up = (i.change_pct || 0) >= 0;
      const ma20 = i.ma20 ? num(i.ma20, 0) : '—';
      const trend = i.spark && i.spark.length > 1 && i.spark[i.spark.length - 1] >= i.spark[0];
      return `<div class="panel index-card ${tone}" style="--i:${idx}">
        <span class="ic-glow"></span>
        <div class="ic-top">
          <div class="ic-name"><i class="ic-live"></i><b>${esc(i.short)}</b><span class="ic-code">${esc(i.code)}</span></div>
          <span class="ic-date">${i.date ? shortDate(i.date) : ''}</span>
        </div>
        <div class="ic-main">
          <div class="ic-price" data-count="${i.price}">${num(i.price, 2)}</div>
          <div class="ic-pill ${tone}"><svg class="ic-arrow"><use href="${up ? '#i-up' : '#i-down'}"/></svg>${pct(i.change_pct, 2, true)}</div>
        </div>
        <div class="ic-sub ${tone}">${i.change == null ? '—' : (i.change > 0 ? '+' : '') + num(i.change, 2)}<em>今日变动</em></div>
        <div class="ic-spark">${sparkline(i.spark, trend, idx)}</div>
        <div class="ic-foot">
          <span>MA20 <b>${ma20}</b></span>
          <span>距高 <b>${pct(i.drawdown, 1, false)}</b></span>
          <span>波动 <b>${num(i.vol20, 1)}%</b></span>
        </div>
      </div>`;
    }).join('');
    $$('#indexCards .ic-price[data-count]').forEach(el => animateCount(el, Number(el.dataset.count), 2));
  }

  function renderNarrative(items) {
    const labels = ['指数与技术', '市场广度', '南向资金', '回购支撑', '行业结构'];
    $('#narrative').innerHTML = (items || []).map((t, i) => `
      <div class="narrative-item"><b><span class="n-dot"></span>${labels[i] || '观察'}</b>${esc(t)}</div>`).join('');
  }

  function renderFlowChart(d) {
    const n = state.flowRange;
    const hsi = (d.hsi_series || []).slice(-n);
    const sb = (d.southbound.series || []);
    const sbMap = new Map(sb.map(r => [r.date, r]));
    const dates = hsi.map(r => r.date);
    let cum = 0;
    const nets = dates.map(dt => {
      const r = sbMap.get(dt);
      const v = r && r.net != null ? r.net : null;
      if (v != null) cum += v;
      return v;
    });
    const cums = dates.map((dt, i) => {
      let s = 0;
      for (let j = 0; j <= i; j++) if (nets[j] != null) s += nets[j];
      return +s.toFixed(2);
    });
    const c = chart('chartFlow');
    if (!c) return;
    c.setOption({
      animationDuration: 500,
      grid: { left: 8, right: 14, top: 46, bottom: 6, containLabel: true },
      legend: { left: 'center', top: 2, itemGap: 14, itemWidth: 10, itemHeight: 6, textStyle: { color: C.muted, fontSize: 12 } },
      tooltip: tip({
        formatter: ps => {
          const i = ps[0].dataIndex;
          const net = nets[i];
          return `<div style="color:${C.muted};font-size:12px;margin-bottom:4px">${dates[i]}</div>
            <div style="font-family:${MONO}">恒指 <b style="color:${C.gold}">${num(hsi[i].close, 2)}</b></div>
            <div style="font-family:${MONO}">南向净买入 <b style="color:${net >= 0 ? C.up : C.down}">${net == null ? '—' : (net > 0 ? '+' : '') + num(net, 1) + ' 亿'}</b></div>
            <div style="font-family:${MONO}">区间累计 <b style="color:${C.cyan}">${cums[i] >= 0 ? '+' : ''}${num(cums[i], 1)} 亿</b></div>`;
        }
      }),
      xAxis: axisX(dates),
      yAxis: [
        axisY({ name: '恒指', nameTextStyle: { color: C.dim, fontSize: 11 }, axisLabel: { color: C.dim, fontSize: 12, formatter: v => (v / 1000).toFixed(1) + 'k' } }),
        axisY({ name: '亿港元', nameTextStyle: { color: C.dim, fontSize: 11 }, splitLine: { show: false }, axisLabel: { color: C.dim, fontSize: 12 } }),
      ],
      series: [
        {
          name: '南向净买入', type: 'bar', yAxisIndex: 1, data: nets, barWidth: '42%',
          itemStyle: { color: p => p.value >= 0 ? rgba(C.up, .55) : rgba(C.down, .55), borderRadius: 2 },
        },
        {
          name: '恒生指数', type: 'line', data: hsi.map(r => r.close), showSymbol: false, smooth: true,
          lineStyle: { color: C.gold, width: 1.6 },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: rgba(C.gold,.13) }, { offset: 1, color: rgba(C.gold,0) }]) },
        },
      ],
    });
    const sbData = d.southbound || {};
    $('#flowFoot').innerHTML = `
      <span>今日净买入 <b class="${cls(sbData.today)}">${sbData.today == null ? '—' : (sbData.today > 0 ? '+' : '') + num(sbData.today, 1) + ' 亿'}</b></span>
      <span>近5日 <b class="${cls(sbData.d5)}">${sbData.d5 == null ? '—' : (sbData.d5 > 0 ? '+' : '') + num(sbData.d5, 1) + ' 亿'}</b></span>
      <span>近20日 <b class="${cls(sbData.d20)}">${sbData.d20 == null ? '—' : (sbData.d20 > 0 ? '+' : '') + num(sbData.d20, 1) + ' 亿'}</b></span>
      <span>20日净买入天数 <b>${sbData.positive_days || 0}/20</b></span>`;
  }

  function renderBuybackMini(bb) {
    if (!bb) return;
    const rows = (bb.series || []).slice(-60);
    const dates = rows.map(r => r.date);
    const amounts = rows.map(r => +(r.amount / 1e8).toFixed(2));
    const ma = rows.map(r => r.ma20 == null ? null : +(r.ma20 / 1e8).toFixed(2));
    $('#buybackHero').innerHTML = `
      <div class="bh-main"><b>${num(bb.today_amount / 1e8, 2)}</b><span>亿港元</span>
        <small>最新回购日 ${bb.latest_date || '—'} · ${bb.today_companies || 0} 家公司</small></div>
      <div class="bh-side">近20日 <b>${num(bb.d20_amount / 1e8, 1)} 亿</b><br>
        占成交额 <b>${num(bb.ratio_bps, 1)} bp</b><br>
        环比 <b class="${cls(bb.d20_change)}">${pct(bb.d20_change, 1)}</b></div>`;
    const c = chart('chartBuybackMini');
    if (!c) return;
    c.setOption({
      animationDuration: 500,
      grid: { left: 6, right: 10, top: 20, bottom: 4, containLabel: true },
      tooltip: tip({
        formatter: ps => {
          const i = ps[0].dataIndex;
          return `<div style="font-size:12px;color:${C.muted};margin-bottom:3px">${dates[i]}</div>
            <div style="font-family:${MONO}">回购 <b style="color:${C.gold}">${num(amounts[i], 2)} 亿</b></div>
            <div style="font-family:${MONO}">公司 <b>${rows[i].companies || 0} 家</b></div>`;
        }
      }),
      xAxis: axisX(dates, false),
      yAxis: axisY({ splitNumber: 2, axisLabel: { color: C.dim, fontSize: 11 } }),
      series: [
        { type: 'bar', data: amounts, barWidth: '55%', itemStyle: { color: rgba(C.gold,.62), borderRadius: [2, 2, 0, 0] } },
        { type: 'line', data: ma, showSymbol: false, smooth: true, lineStyle: { color: C.cyan, width: 1.2 } },
      ],
    });
    $('#buybackFoot').innerHTML = `<span>20日均额 <b>${num(bb.avg20 / 1e8, 2)} 亿</b></span><span>前三贡献 <b>${num(bb.top3_share, 1)}%</b></span><span>年内累计 <b>${num(bb.ytd_amount / 1e8, 0)} 亿</b></span>`;
  }

  function renderBreadth(b) {
    const c = chart('chartBreadth');
    if (c) {
      c.setOption({
        animationDuration: 500,
        tooltip: tip({ trigger: 'item', formatter: p => `${p.name} <b style="font-family:${MONO}">${p.value}</b> 只 · ${p.percent}%` }),
        series: [{
          type: 'pie', radius: ['60%', '82%'], center: ['50%', '50%'], avoidLabelOverlap: true,
          label: { show: false }, labelLine: { show: false },
          itemStyle: { borderColor: C.panel, borderWidth: 2 },
          data: [
            { name: '上涨', value: b.up, itemStyle: { color: C.up } },
            { name: '平盘', value: b.flat, itemStyle: { color: '#3c4d66' } },
            { name: '下跌', value: b.down, itemStyle: { color: C.down } },
          ],
        }],
        title: {
          text: num(b.up_ratio, 0) + '%', subtext: '上涨占比',
          left: 'center', top: '35%',
          textStyle: { color: C.up, fontSize: 22, fontFamily: MONO, fontWeight: 500 },
          subtextStyle: { color: C.dim, fontSize: 11, fontFamily: FONT },
        },
      });
    }
    $('#breadthStats').innerHTML = `
      <div class="bs-row"><span>上涨</span><b class="up">${b.up}</b></div>
      <div class="bs-row"><span>下跌</span><b class="down">${b.down}</b></div>
      <div class="bs-row"><span>成交额</span><b>${money(b.turnover, 0)}</b></div>
      <div class="bs-row"><span>PE中位</span><b>${num(b.median_pe, 1)}</b></div>
      <div class="bs-row"><span>PB中位</span><b>${num(b.median_pb, 2)}</b></div>
      <div class="bs-row"><span>52周下半区</span><b>${num(b.below_mid52_ratio, 0)}%</b></div>
      <div class="bs-row"><span>样本（≥3亿）</span><b>${b.total}</b></div>
      <div class="bs-row"><span>停牌/无成交</span><b>${Math.max(0, b.total - b.active)}</b></div>`;
  }

  function renderPeChart(b) {
    const c = chart('chartPe');
    if (!c) return;
    const data = b.pe_dist || [];
    c.setOption({
      animationDuration: 500,
      grid: { left: 6, right: 22, top: 30, bottom: 6, containLabel: true },
      tooltip: tip({ formatter: ps => `${ps[0].name} 倍：<b style="font-family:${MONO}">${ps[0].value}</b> 只` }),
      xAxis: axisX(data.map(x => x.label), true),
      yAxis: axisY({ splitNumber: 2, axisLabel: { color: C.dim, fontSize: 11 } }),
      series: [{
        type: 'bar', data: data.map(x => x.count), barWidth: '48%',
        itemStyle: {
          borderRadius: [3, 3, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: rgba(C.cyan,.85) }, { offset: 1, color: rgba(C.cyan,.22) }]),
        },
        label: { show: true, position: 'top', color: C.dim, fontSize: 11, fontFamily: MONO },
      }],
    });
    $('#valuationStats').innerHTML = `
      <div class="ms-item"><span>PE中位</span><b>${num(b.median_pe, 1)}</b></div>
      <div class="ms-item"><span>PB中位</span><b>${num(b.median_pb, 2)}</b></div>
      <div class="ms-item"><span>股息中位</span><b>${num(b.median_div, 1)}%</b></div>`;
  }

  function renderSectorList(sectors) {
    const max = Math.max(...(sectors || []).map(s => Math.abs(s.change_pct || 0)), 0.1);
    $('#sectorList').innerHTML = (sectors || []).map(s => {
      const w = Math.abs(s.change_pct || 0) / max * 100;
      const color = (s.change_pct || 0) >= 0 ? C.up : C.down;
      const side = (s.change_pct || 0) >= 0 ? 'left:0' : 'right:0';
      return `<div class="sector-row" title="PE中位 ${num(s.median_pe, 1)} · 20日回购 ${num(s.buyback20 / 1e8, 1)}亿 · 回购占市值 ${num(s.buyback_yield, 2)}%">
        <span class="sector-name">${esc(s.name)}</span>
        <span class="sector-bar"><i style="${side};width:${w}%;background:${color}"></i></span>
        <span class="sector-val ${cls(s.change_pct)}">${pct(s.change_pct)}</span>
      </div>`;
    }).join('');
  }

  function renderTopBuyback(bb) {
    const rows = (bb && bb.top) || [];
    if (!rows.length) {
      $('#topBuybackTable').innerHTML = '<div class="empty"><b>暂无回购数据</b><span>等待同步港交所回购报告</span></div>';
      return;
    }
    $('#topBuybackTable').innerHTML = `<table class="data-table">
      <thead><tr><th class="l sortable">股票</th><th class="sortable">回购金额</th><th class="sortable">均价</th><th class="sortable">现价</th><th class="sortable">现价/均价</th><th class="sortable">占成交</th></tr></thead>
      <tbody>${rows.map(r => `<tr class="clickable" data-code="${esc(r.code)}">
        <td class="l"><div class="name">${esc(r.name)}</div><div class="code">${esc(r.code)}.HK · ${esc(r.sector)}</div></td>
        <td data-v="${r.amount}" class="em">${yi(r.amount)}亿</td>
        <td data-v="${r.vwap}">${num(r.vwap, 2)}</td>
        <td data-v="${r.price}">${num(r.price, 2)}</td>
        <td data-v="${r.premium}" class="${cls(r.premium)}">${pct(r.premium, 1)}</td>
        <td data-v="${r.turnover_pct}">${r.turnover_pct == null ? '—' : num(r.turnover_pct, 1) + '%'}</td>
      </tr>`).join('')}</tbody></table>`;
    $$('#topBuybackTable tr[data-code]').forEach(tr => tr.addEventListener('click', () => goto('stock', tr.dataset.code)));
  }

  function renderMovers(m) {
    const rows = (m && m[state.moverTab]) || [];
    $('#moversBody').innerHTML = rows.map((r, i) => {
      const isActive = state.moverTab === 'active';
      return `<div class="mover-row" data-code="${esc(r.code)}" style="cursor:pointer">
        <span class="m-over">${String(i + 1).padStart(2, '0')}</span>
        <span><span class="m-name">${esc(r.name)}</span><span class="m-code">${esc(r.code)}</span></span>
        <span class="m-price">${isActive ? money(r.amount, 1) : num(r.price, 2)}</span>
        <span class="m-chg ${cls(r.change_pct)}">${pct(r.change_pct)}</span>
      </div>`;
    }).join('') || '<div class="empty"><b>暂无数据</b></div>';
    $$('#moversBody .mover-row').forEach(row => row.addEventListener('click', () => goto('stock', row.dataset.code)));
    $$('#moverTabs button').forEach(b => b.classList.toggle('on', b.dataset.k === state.moverTab));
  }

  /* ---------------- macro & liquidity ---------------- */
  async function loadMacro() {
    if (state.macro) { renderMacro(state.macro); return; }
    $('#macroKpis').innerHTML = '<div class="panel loading-panel" style="grid-column:span 5">正在同步 HKMA / HKAB / FRED 宏观数据…</div>';
    try {
      const d = await api('/api/macro');
      state.macro = d;
      renderMacro(d);
      clearError();
    } catch (err) {
      showError(`宏观数据加载失败：${err.message}`);
    }
  }

  function renderMacro(d) {
    const s = d.snapshot || {};
    $('#macroAsOf').textContent = `HIBOR ${d.data_dates?.HIBOR_1M || '—'} · 美债 ${d.data_dates?.US10Y || '—'}`;
    $('#hiborAsOf').textContent = d.hibor_curve?.date || '—';
    $('#macroKpis').innerHTML = [
      kpi('HIBOR 1M', num(s.hibor_1m, 2), '%', `3M ${num(s.hibor_3m, 2)}% · O/N ${num(s.hibor_on, 2)}%`),
      kpi('港美利差', num(s.spread, 2), 'pp', `HIBOR − SOFR ${num(s.sofr, 2)}%`),
      kpi('美债 10Y', num(s.us10, 2), '%', `2Y ${num(s.us2, 2)}% · 30Y ${num(s.us30, 2)}%`),
      kpi('2s10s 曲线', num(s.curve, 2), 'pp', s.curve != null && s.curve >= 0 ? '正斜率' : '倒挂'),
      kpi('港股风险溢价', num(s.erp, 2), 'pp', `盈利收益率 ${num(s.earnings_yield, 1)}%`),
    ].join('');
    renderMacroLiquidity(d);
    renderYieldCurve(d);
    renderHsiUs(d);
    renderHiborCurve(d);
    renderMacroSignals(d.signals || []);
    $('#macroNarrative').innerHTML = (d.narrative || []).map((t, i) => {
      const warn = /弱方|流出|偏紧|高位|约束/.test(t);
      return `<div class="mn-item ${warn ? 'warn' : ''}">${esc(t)}</div>`;
    }).join('');
    setTimeout(resizeCharts, 60);
  }

  function timeAxisX() {
    return {
      type: 'time',
      axisLine: { lineStyle: { color: C.line } },
      axisTick: { show: false },
      axisLabel: { color: C.dim, fontSize: 12, fontFamily: MONO, hideOverlap: true },
      splitLine: { show: false },
    };
  }

  function renderMacroLiquidity(d) {
    const c = chart('chartMacroLiquidity');
    if (!c) return;
    const agg = (d.series?.agg || []).map(r => [r.date, r.value]);
    const us = (d.series?.us10 || []).slice(-380).map(r => [r.date, r.value]);
    c.setOption({
      animationDuration: 500,
      grid: { left: 8, right: 14, top: 46, bottom: 6, containLabel: true },
      legend: { left: 'center', top: 2, itemGap: 14, itemWidth: 10, itemHeight: 6, textStyle: { color: C.muted, fontSize: 12 } },
      tooltip: tip({ trigger: 'axis', formatter: ps => {
        const dt = ps[0]?.axisValue || '';
        return `<div style="font-size:12px;color:${C.muted};margin-bottom:4px">${String(dt).slice(0,10)}</div>` +
          ps.map(p => `<div style="font-family:${MONO}">${p.seriesName} <b style="color:${p.color}">${num(p.value?.[1], 2)}${p.seriesName.includes('总结余') ? ' 亿' : '%'}</b></div>`).join('');
      }}),
      xAxis: timeAxisX(),
      yAxis: [
        axisY({ name: '亿港元', nameTextStyle: { color: C.dim, fontSize: 11 } }),
        axisY({ name: '美债10Y %', nameTextStyle: { color: C.dim, fontSize: 11 }, splitLine: { show: false } }),
      ],
      series: [
        { name: '总结余', type: 'line', data: agg, showSymbol: false, smooth: true,
          lineStyle: { color: C.gold, width: 1.5 },
          areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1,[
            { offset: 0, color: rgba(C.gold,.16) }, { offset: 1, color: rgba(C.gold,0) }]) } },
        { name: '美债10Y', type: 'line', yAxisIndex: 1, data: us, showSymbol: false, smooth: true,
          lineStyle: { color: C.cyan, width: 1.4 } },
      ],
    });
    const s = d.snapshot || {};
    $('#macroLiquidityFoot').innerHTML = `
      <span>总结余 <b>${num((s.agg_balance || 0)/100, 0)} 亿</b></span>
      <span>近四年分位 <b>${num(s.agg_percentile, 0)}%</b></span>
      <span>HIBOR 1M <b>${num(s.hibor_1m, 2)}%</b></span>
      <span>HKMA 基准 <b>${num(s.base_rate, 2)}%</b></span>
      <span>SOFR <b>${num(s.sofr, 2)}%</b></span>`;
  }

  function renderYieldCurve(d) {
    const c = chart('chartYieldCurve');
    if (!c) return;
    const mk = (name, key, color) => ({ name, type: 'line', showSymbol: false, smooth: true,
      data: (d.series?.[key] || []).slice(-260).map(r => [r.date, r.value]),
      lineStyle: { color, width: 1.4 } });
    c.setOption({
      animationDuration: 400,
      grid: { left: 6, right: 14, top: 42, bottom: 6, containLabel: true },
      legend: { left: 'center', top: 2, itemGap: 14, itemWidth: 10, itemHeight: 6, textStyle: { color: C.muted, fontSize: 12 } },
      tooltip: tip({ trigger: 'axis', formatter: ps => `<div style="font-size:12px;color:${C.muted}">${String(ps[0]?.axisValue || '').slice(0,10)}</div>` +
        ps.map(p => `<div style="font-family:${MONO}">${p.seriesName} <b style="color:${p.color}">${num(p.value?.[1], 2)}%</b></div>`).join('') }),
      xAxis: timeAxisX(),
      yAxis: axisY({ axisLabel: { color: C.dim, fontSize: 11, formatter: v => v + '%' } }),
      series: [mk('2Y', 'us2', C.down), mk('10Y', 'us10', C.cyan), mk('30Y', 'us30', C.violet)],
    });
  }

  function renderHsiUs(d) {
    const c = chart('chartHsiUs');
    if (!c) return;
    const hsi = (d.series?.hsi || []).map(r => [r.date, r.value]);
    const us = (d.series?.us10 || []).slice(-260).map(r => [r.date, r.value]);
    c.setOption({
      animationDuration: 400,
      grid: { left: 8, right: 14, top: 40, bottom: 6, containLabel: true },
      tooltip: tip({ trigger: 'axis', formatter: ps => `<div style="font-size:12px;color:${C.muted}">${String(ps[0]?.axisValue || '').slice(0,10)}</div>` +
        ps.map(p => `<div style="font-family:${MONO}">${p.seriesName} <b style="color:${p.color}">${num(p.value?.[1], 2)}${p.seriesName === '恒指' ? '' : '%'}</b></div>`).join('') }),
      xAxis: timeAxisX(),
      yAxis: [
        axisY({ name: '恒指', nameTextStyle: { color: C.dim, fontSize: 11 }, axisLabel: { color: C.dim, fontSize: 11, formatter: v => (v/1000).toFixed(0)+'k' } }),
        axisY({ name: 'US10Y %', nameTextStyle: { color: C.dim, fontSize: 11 }, splitLine: { show: false }, axisLabel: { color: C.dim, fontSize: 11 } }),
      ],
      series: [
        { name: '恒指', type: 'line', data: hsi, showSymbol: false, smooth: true, lineStyle: { color: C.gold, width: 1.5 } },
        { name: '美债10Y', type: 'line', yAxisIndex: 1, data: us, showSymbol: false, smooth: true, lineStyle: { color: C.cyan, width: 1.3 } },
      ],
    });
  }

  function renderHiborCurve(d) {
    const c = chart('chartHiborCurve');
    if (!c) return;
    const vals = d.hibor_curve?.values || [];
    c.setOption({
      animationDuration: 400,
      grid: { left: 6, right: 22, top: 30, bottom: 6, containLabel: true },
      tooltip: tip({ trigger: 'axis', formatter: ps => `${ps[0]?.name} <b style="font-family:${MONO}">${num(ps[0]?.value, 3)}%</b>` }),
      xAxis: axisX(d.hibor_curve?.labels || [], true),
      yAxis: axisY({ axisLabel: { color: C.dim, fontSize: 11, formatter: v => v + '%' } }),
      series: [{ type: 'bar', data: vals, barWidth: '48%',
        itemStyle: { color: rgba(C.gold, .7), borderRadius: [3,3,0,0] },
        label: { show: true, position: 'top', color: C.dim, fontSize: 11, formatter: p => num(p.value, 2) + '%' } }],
    });
  }

  function macroSignalValue(s) {
    if (s.value == null) return '—';
    if (s.unit === '%') return num(s.value, 2) + '%';
    if (s.unit === 'pp') return (s.value > 0 ? '+' : '') + num(s.value, 2) + 'pp';
    if (s.unit === '亿') return (s.value > 0 ? '+' : '') + num(s.value, 1) + '亿';
    if (s.name.includes('USD/HKD')) return num(s.value, 4);
    return num(s.value, 2);
  }

  function macroSignalChange(s) {
    if (s.change == null) return '—';
    if (s.name.includes('HIBOR') || s.name.includes('美债') || s.name.includes('2s10s')) {
      return (s.change > 0 ? '+' : '') + num(s.change, 0) + 'bp';
    }
    if (s.name.includes('USD/HKD')) return (s.change > 0 ? '+' : '') + num(s.change * 10000, 1) + 'pips';
    return (s.change > 0 ? '+' : '') + num(s.change, 2);
  }

  function macroToneClass(tone) {
    if (/利多|宽松|平静|正常|流入|支撑|有吸引力|强方/.test(tone)) return 'green';
    if (/利空|偏紧|倒挂|恐慌|弱方|流出|偏贵/.test(tone)) return 'red';
    return 'blue';
  }

  function renderMacroSignals(signals) {
    $('#macroSignals').innerHTML = signals.map(s => `
      <div class="macro-signal-row">
        <span class="ms-name">${esc(s.name)}</span>
        <span class="ms-value">${macroSignalValue(s)}</span>
        <span class="ms-change">${macroSignalChange(s)}</span>
        <span class="ms-read">${tag(s.tone, macroToneClass(s.tone))}${esc(s.text)}</span>
      </div>`).join('');
  }

  /* ---------------- signal center ---------------- */
  async function loadSignals() {
    if (state.signals) { renderSignals(state.signals); return; }
    try {
      const d = await api('/api/signals');
      state.signals = d;
      renderSignals(d);
      clearError();
    } catch (err) {
      showError(`信号中心加载失败：${err.message}`);
    }
  }

  function signalTone(tone) {
    return ({ gold: C.gold, green: C.down, cyan: C.cyan, blue: C.cyan, purple: C.violet, red: C.up })[tone] || C.cyan;
  }

  function renderSignals(d) {
    const s = d.summary || {};
    $('#signalMonthlyAsOf').textContent = `截至 ${d.as_of || '—'}`;
    $('#signalKpis').innerHTML = [
      kpi('信号标的', int(s.signal_stocks), '只', '至少命中一类信号'),
      kpi('低于回购均价', int(s.below_vwap), '只', '现价低于公司回购成本'),
      kpi('持续回购', int(s.persistent), '只', '20日内回购≥10天'),
      kpi('高回购占市值', int(s.high_yield), '只', '近20日回购/市值≥1%'),
      kpi('近20日回购', num((s.d20_amount || 0) / 1e8, 1), '亿', `年内 ${num((s.ytd_amount || 0) / 1e8, 0)} 亿`),
    ].join('');
    renderMonthlyChart(d.monthly || []);
    renderSignalOverview(d.categories || []);
    renderSignalCards(d.categories || []);
    setTimeout(resizeCharts, 60);
  }

  function renderMonthlyChart(monthly) {
    const labels = monthly.map(m => m.month.slice(5) + '月');
    const amounts = monthly.map(m => +(m.amount / 1e8).toFixed(1));
    const companies = monthly.map(m => m.companies);
    const c = chart('chartMonthly');
    if (!c) return;
    c.setOption({
      animationDuration: 500,
      grid: { left: 8, right: 14, top: 46, bottom: 6, containLabel: true },
      legend: { left: 'center', top: 2, itemGap: 14, itemWidth: 10, itemHeight: 6, textStyle: { color: C.muted, fontSize: 12 } },
      tooltip: tip({
        formatter: ps => {
          const i = ps[0].dataIndex;
          return `<div style="font-size:12px;color:${C.muted};margin-bottom:4px">${monthly[i].month}</div>
            <div style="font-family:${MONO}">回购金额 <b style="color:${C.gold}">${num(amounts[i], 1)} 亿</b></div>
            <div style="font-family:${MONO}">参与公司 <b>${companies[i]} 家</b></div>`;
        }
      }),
      xAxis: axisX(labels),
      yAxis: [
        axisY({ name: '亿港元', nameTextStyle: { color: C.dim, fontSize: 11 } }),
        axisY({ name: '家', nameTextStyle: { color: C.dim, fontSize: 11 }, splitLine: { show: false } }),
      ],
      series: [
        { name: '回购金额', type: 'bar', data: amounts, barWidth: '46%',
          itemStyle: { color: rgba(C.gold, .72), borderRadius: [3, 3, 0, 0] } },
        { name: '参与公司', type: 'line', yAxisIndex: 1, data: companies, showSymbol: false, smooth: true,
          lineStyle: { color: C.cyan, width: 1.4 } },
      ],
    });
    const total = amounts.reduce((a, b) => a + b, 0);
    const peak = monthly.reduce((a, b) => (b.amount > (a.amount || 0) ? b : a), {});
    const nowMonth = monthly[monthly.length - 1];
    $('#monthlyFoot').innerHTML = `
      <span>累计 <b>${num(total, 0)} 亿</b></span>
      <span>峰值 <b>${peak.month || '—'} · ${num((peak.amount || 0) / 1e8, 1)} 亿</b></span>
      <span>本月 <b>${nowMonth ? num(nowMonth.amount / 1e8, 1) + ' 亿' : '—'}</b></span>`;
  }

  function renderSignalOverview(cats) {
    const max = Math.max(...cats.map(c => c.count), 1);
    $('#signalOverview').innerHTML = cats.map(c => `
      <div class="signal-row" data-target="sig-${esc(c.key)}" style="cursor:pointer">
        <span>${esc(c.name)}</span>
        <span class="bar"><i style="width:${c.count / max * 100}%;background:${signalTone(c.tone)}"></i></span>
        <b>${c.count}</b>
      </div>`).join('');
    $$('#signalOverview .signal-row').forEach(el => el.addEventListener('click', () => {
      document.getElementById(el.dataset.target)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }));
  }

  function signalKey(cat, r) {
    if (cat.key === 'high_dividend') return { label: '股息率', value: num(r.dividend_yield, 1) + '%' };
    if (cat.key === 'below_book') return { label: 'PB', value: num(r.pb, 2) };
    if (cat.key === 'low_52w' || cat.key === 'momentum') return { label: '52W位置', value: num(r.pos52, 0) + '%' };
    return { label: '折价', value: pct(r.premium, 1) };
  }

  function renderSignalCards(cats) {
    $('#signalGrid').innerHTML = cats.map((c, idx) => {
      const keyLabel = c.rows.length ? signalKey(c, c.rows[0]).label : '折价';
      return `
      <div class="panel span6 signal-card" id="sig-${esc(c.key)}">
        <div class="panel-head">
          <div><span class="eyebrow">SIGNAL ${String(idx + 1).padStart(2, '0')}</span>
            <h2>${esc(c.name)} <span class="signal-count">${c.count}</span></h2></div>
          <span class="tag ${c.tone === 'gold' ? 'gold' : c.tone === 'green' ? 'green' : 'blue'}">${c.count} 只命中</span>
        </div>
        <p class="signal-desc">${esc(c.desc)}</p>
        ${c.rows.length ? `<table class="data-table">
          <thead><tr><th class="l sortable">股票</th><th class="l sortable">行业</th><th class="sortable">现价</th><th class="sortable">涨跌</th><th class="sortable">回购占市值</th><th class="sortable">天数</th><th class="sortable">${keyLabel}</th></tr></thead>
          <tbody>${c.rows.map(r => {
            const key = signalKey(c, r);
            return `<tr class="clickable" data-code="${esc(r.code)}">
              <td class="l"><div class="name">${esc(r.name)}</div><div class="code">${esc(r.code)}.HK</div></td>
              <td class="l soft">${esc(r.sector)}</td>
              <td data-v="${r.price}">${num(r.price, 2)}</td>
              <td data-v="${r.change_pct}" class="${cls(r.change_pct)}">${pct(r.change_pct)}</td>
              <td data-v="${r.buyback_cap}" style="color:${C.gold}">${num(r.buyback_cap, 2)}%</td>
              <td data-v="${r.buyback_days}">${r.buyback_days}</td>
              <td style="color:${r.premium != null && r.premium < 0 ? C.gold : C.muted}">${key.value}</td>
            </tr>`;
          }).join('')}</tbody></table>`
          : '<div class="empty" style="padding:22px"><b>暂无标的</b></div>'}
      </div>`;
    }).join('');
    $$('#signalGrid tr[data-code]').forEach(tr => tr.addEventListener('click', () => goto('stock', tr.dataset.code)));
  }

  /* ---------------- buyback view ---------------- */
  async function loadBuyback() {
    try {
      const params = new URLSearchParams({
        period: String(state.bbPeriod),
        sort: state.bbSort,
        limit: '300',
        min_mcap: $('#bbMinMcap') ? ($('#bbMinMcap').value || '0') : '30',
      });
      const sector = $('#bbSector') ? $('#bbSector').value : '';
      if (sector) params.set('sector', sector);
      if ($('#bbBelowVwap') && $('#bbBelowVwap').checked) params.set('below_vwap', '1');
      if ($('#bbSearch') && $('#bbSearch').value.trim()) params.set('q', $('#bbSearch').value.trim());
      const d = await api('/api/buybacks?' + params.toString());
      state.buyback = d;
      renderBuyback(d);
      clearError();
    } catch (err) {
      showError(`回购数据加载失败：${err.message}`);
    }
  }

  function renderBuyback(d) {
    const m = d.market;
    const rows = d.table.rows;
    $('#bbMeta').textContent = d.table.start === d.table.end
      ? `最新交易日 ${d.table.end || '—'} · ${d.table.total} 只`
      : `${d.table.start || '—'} ~ ${d.table.end || '—'} · ${d.table.total} 只`;
    $('#buybackKpis').innerHTML = [
      kpi('最新回购额', num(m.today_amount / 1e8, 2), '亿港元', `${m.latest_date || '—'} · ${m.today_companies || 0} 家`),
      kpi('近20日累计', num(m.d20_amount / 1e8, 1), '亿港元', `${m.d20_companies || 0} 家公司参与`),
      kpi('年内累计', num(m.ytd_amount / 1e8, 0), '亿港元', `${m.ytd_companies || 0} 家公司`),
      kpi('20日回购/成交', num(m.ratio_bps, 1), 'bp', `环比 ${pct(m.d20_change, 1)}`),
      kpi('前三贡献度', num(m.top3_share, 1), '%', '最新一日 · 头部集中度'),
    ].join('');
    renderBuybackChart(m, state.bbChartRange);
    renderCalendar(d.calendar || []);
    fillSectorOptions(d.sectors || []);
    renderBuybackTable(rows);
    setTimeout(resizeCharts, 50);
  }

  function kpi(label, value, unit, sub) {
    return `<div class="kpi"><div class="k-label">${esc(label)}</div>
      <div class="k-value">${value}<small>${esc(unit)}</small></div>
      <div class="k-sub">${sub || ''}</div></div>`;
  }

  function fillSectorOptions(sectors) {
    const el = $('#bbSector');
    if (!el || el.dataset.filled) return;
    const names = sectors.map(s => s.name);
    el.innerHTML = '<option value="">全部行业</option>' + names.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
    el.dataset.filled = '1';
  }

  function ensureScreenerSectors() {
    const f = $('#fSector');
    if (!f || f.dataset.filled) return;
    const names = (state.overview?.sectors || []).map(s => s.name);
    const list = names.length ? names : SECTOR_NAMES;
    f.innerHTML = '<option value="">全部</option>' + list.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
    f.dataset.filled = '1';
  }

  function renderBuybackChart(m, n) {
    const rows = (m.series || []).slice(-n);
    const dates = rows.map(r => r.date);
    const amounts = rows.map(r => +(r.amount / 1e8).toFixed(2));
    const ma = rows.map(r => r.ma20 == null ? null : +(r.ma20 / 1e8).toFixed(2));
    const hsi = rows.map(r => r.hsi);
    const c = chart('chartBuyback');
    if (!c) return;
    c.setOption({
      animationDuration: 500,
      grid: { left: 8, right: 14, top: 46, bottom: 8, containLabel: true },
      legend: { left: 'center', top: 2, itemGap: 14, itemWidth: 10, itemHeight: 6, textStyle: { color: C.muted, fontSize: 12 } },
      tooltip: tip({
        formatter: ps => {
          const i = ps[0].dataIndex;
          return `<div style="font-size:12px;color:${C.muted};margin-bottom:4px">${dates[i]}</div>
            <div style="font-family:${MONO}">回购金额 <b style="color:${C.gold}">${num(amounts[i], 2)} 亿</b></div>
            <div style="font-family:${MONO}">参与公司 <b>${rows[i].companies || 0} 家</b></div>
            <div style="font-family:${MONO}">恒生指数 <b>${num(hsi[i], 0)}</b></div>`;
        }
      }),
      xAxis: axisX(dates),
      yAxis: [
        axisY({ name: '亿港元', nameTextStyle: { color: C.dim, fontSize: 11 } }),
        axisY({ name: '恒指', nameTextStyle: { color: C.dim, fontSize: 11 }, splitLine: { show: false }, axisLabel: { color: C.dim, fontSize: 12, formatter: v => (v / 1000).toFixed(1) + 'k' } }),
      ],
      series: [
        {
          name: '回购金额', type: 'bar', data: amounts, barWidth: '46%',
          itemStyle: {
            borderRadius: [2, 2, 0, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: rgba(C.gold,.85) }, { offset: 1, color: rgba(C.gold,.18) }]),
          },
        },
        { name: '20日均额', type: 'line', data: ma, showSymbol: false, smooth: true, lineStyle: { color: C.cyan, width: 1.4 } },
        { name: '恒生指数', type: 'line', yAxisIndex: 1, data: hsi, showSymbol: false, smooth: true, lineStyle: { color: 'rgba(232,238,249,.55)', width: 1.2, type: 'dashed' } },
      ],
    });
    const total = rows.reduce((s, r) => s + r.amount, 0);
    const peak = rows.reduce((a, b) => (b.amount > (a.amount || 0) ? b : a), {});
    $('#bbChartFoot').innerHTML = `
      <span>区间回购 <b>${num(total / 1e8, 1)} 亿</b></span>
      <span>日均 <b>${num(total / Math.max(rows.length, 1) / 1e8, 2)} 亿</b></span>
      <span>峰值 <b>${peak.date || '—'} · ${num((peak.amount || 0) / 1e8, 2)} 亿</b></span>
      <span>20日/成交 <b>${num(m.ratio_bps, 1)} bp</b></span>`;
  }

  function renderCalendar(rows) {
    const host = $('#bbCalendar');
    if (!rows || !rows.length) {
      host.innerHTML = '<div class="empty"><b>暂无日历数据</b></div>';
      return;
    }
    const max = Math.max(...rows.map(r => r.amount || 0), 1);
    const weeks = new Map();
    rows.forEach(r => {
      const dt = new Date(r.date + 'T00:00:00');
      const dow = (dt.getDay() + 6) % 7;
      const mon = new Date(dt);
      mon.setDate(dt.getDate() - dow);
      const key = `${mon.getFullYear()}-${String(mon.getMonth() + 1).padStart(2, '0')}-${String(mon.getDate()).padStart(2, '0')}`;
      if (!weeks.has(key)) weeks.set(key, []);
      weeks.get(key)[dow] = r;
    });
    const sorted = Array.from(weeks.entries()).sort((a, b) => a[0] < b[0] ? -1 : 1);
    let html = '';
    sorted.forEach(([week, arr]) => {
      for (let i = 0; i < 5; i++) {
        const r = arr[i];
        if (!r) { html += '<div class="cal-cell" style="opacity:.16"></div>'; continue; }
        const v = r.amount || 0;
        const lv = v <= 0 ? 0 : Math.min(4, 1 + Math.floor(v / max * 4));
        const title = `${r.date} · 回购 ${num(v / 1e8, 2)} 亿 · ${r.companies || 0} 家`;
        html += `<div class="cal-cell lv${lv}" title="${esc(title)}"></div>`;
      }
    });
    host.innerHTML = html;
    const last = rows[rows.length - 1];
    const avg20 = rows.slice(-20).reduce((s, r) => s + (r.amount || 0), 0) / Math.min(20, rows.length);
    const peak = rows.reduce((a, b) => (b.amount > (a.amount || 0) ? b : a), {});
    const covered = rows.filter(r => (r.companies || 0) > 0).length;
    $('#bbCalSide').innerHTML = `
      <div>最新一日<b>${num((last.amount || 0) / 1e8, 2)} 亿</b></div>
      <div>20日均值<b>${num(avg20 / 1e8, 2)} 亿</b></div>
      <div>区间峰值<b>${num((peak.amount || 0) / 1e8, 2)} 亿</b></div>
      <div>有回购交易日<b>${covered}/${rows.length}</b></div>`;
  }

  function renderBuybackTable(rows) {
    if (!rows || !rows.length) {
      $('#bbTable').innerHTML = '<div class="empty"><b>没有符合条件的回购标的</b><span>尝试放宽市值或行业条件</span></div>';
      return;
    }
    const ratioHead = state.bbPeriod === 1 ? '占当日成交' : '区间回购/成交';
    $('#bbTable').innerHTML = `<table class="data-table">
      <thead><tr>
        <th class="l">#</th><th class="l sortable">股票</th><th class="l sortable">行业</th>
        <th class="sortable">回购金额</th><th class="sortable">天数</th><th class="sortable">回购均价</th><th class="sortable">现价</th><th class="sortable">现价/均价</th>
        <th class="sortable" title="日K成交量 × 收盘价近似成交额">${ratioHead}</th><th class="sortable">回购占市值</th><th class="sortable">市值</th>
      </tr></thead>
      <tbody>${rows.map((r, i) => `<tr class="clickable" data-code="${esc(r.code)}">
        <td class="l"><span class="rank-no ${i < 3 ? 'top' : ''}">${i + 1}</span></td>
        <td class="l"><div class="name">${esc(r.name)}</div><div class="code">${esc(r.code)}.HK</div></td>
        <td class="l soft">${esc(r.sector)}</td>
        <td data-v="${r.amount}" class="em">${num(r.amount / 1e8, 2)}亿</td>
        <td data-v="${r.days}">${r.days}<span class="soft">${r.streak > 1 ? ' / 连' + r.streak : ''}</span></td>
        <td data-v="${r.vwap}">${num(r.vwap, 2)}</td>
        <td data-v="${r.price}">${num(r.price, 2)}</td>
        <td data-v="${r.premium}" class="${r.premium != null && r.premium < 0 ? 'em' : 'soft'}" title="负值代表现价低于回购均价">${pct(r.premium, 1)}</td>
        <td data-v="${r.turnover_pct}">${r.turnover_pct == null ? '<span class="soft">—</span>' : num(r.turnover_pct, 1) + '%'}</td>
        <td data-v="${r.yield_pct}">${r.yield_pct == null ? '<span class="soft">—</span>' : num(r.yield_pct, 2) + '%'}</td>
        <td data-v="${r.market_cap}">${mcap(r.market_cap)}</td>
      </tr>`).join('')}</tbody></table>`;
    $$('#bbTable tr[data-code]').forEach(tr => tr.addEventListener('click', () => goto('stock', tr.dataset.code)));
  }

  /* ---------------- short selling view ---------------- */
  async function loadShort() {
    try {
      const params = new URLSearchParams({
        period: String(state.shortPeriod),
        sort: state.shortSort,
        limit: '300',
        min_mcap: $('#shortMinMcap') ? ($('#shortMinMcap').value || '0') : '30',
        min_ratio: $('#shortMinRatio') ? ($('#shortMinRatio').value || '0') : '0',
      });
      const sector = $('#shortSector') ? $('#shortSector').value : '';
      if (sector) params.set('sector', sector);
      if ($('#shortHedge') && $('#shortHedge').checked) params.set('hedge', '1');
      if ($('#shortSearch') && $('#shortSearch').value.trim()) params.set('q', $('#shortSearch').value.trim());
      const d = await api('/api/shortsell?' + params.toString());
      state.short = d;
      renderShort(d);
      clearError();
    } catch (err) {
      showError(`卖空数据加载失败：${err.message}`);
    }
  }

  function renderShort(d) {
    const m = d.market || {};
    const rows = d.table.rows;
    $('#shortMeta').textContent = d.table.start === d.table.end
      ? `最新披露 ${d.table.end || '—'} · ${d.table.total} 只`
      : `${d.table.start || '—'} ~ ${d.table.end || '—'} · ${d.table.total} 只`;
    if (!m.has_data) {
      $('#shortKpis').innerHTML = '<div class="panel loading-panel" style="grid-column:span 5">暂无卖空数据，请先同步数据源。</div>';
      $('#chartShort').innerHTML = '';
      $('#hedgeList').innerHTML = '<div class="empty"><b>暂无数据</b></div>';
      $('#shortTable').innerHTML = '<div class="empty"><b>暂无卖空数据</b><span>同步后此处展示 SFC 每周淡仓持仓与个股卖空占市值比</span></div>';
      return;
    }
    $('#shortKpis').innerHTML = [
      kpi('淡仓占市值', num(m.today_pct, 2), '%', `${m.latest_date || '—'} · ${m.today_companies || 0} 只`),
      kpi('4周均占比', num(m.avg4_pct, 2), '%', `周环比 ${m.week_chg == null ? '—' : (m.week_chg > 0 ? '+' : '') + num(m.week_chg, 2) + 'pp'}`),
      kpi('区间历史分位', num(m.pct_percentile, 0), '%', `区间 ${num(m.min_pct, 2)}% ~ ${num(m.max_pct, 2)}%`),
      kpi('淡仓总市值', num(m.today_value / 1e8, 0), '亿港元', `覆盖市值 ${num((m.today_mcap || 0) / 1e8, 0)} 亿`),
      kpi('4周趋势', pct(m.change4, 1), '', '淡仓规模较前 4 周'),
    ].join('');
    renderShortChart(m, state.shortChartRange);
    renderHedgeList(d.hedge || []);
    fillShortSectors();
    renderShortTable(rows);
    setTimeout(resizeCharts, 50);
  }

  function fillShortSectors() {
    const el = $('#shortSector');
    if (!el || el.dataset.filled) return;
    el.innerHTML = '<option value="">全部行业</option>' + SECTOR_NAMES.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
    el.dataset.filled = '1';
  }

  function renderShortChart(m, n) {
    const rows = (m.series || []).slice(-n);
    const dates = rows.map(r => r.date);
    const values = rows.map(r => +((r.short_value || 0) / 1e8).toFixed(1));
    const ratio = rows.map(r => r.short_pct == null ? null : +r.short_pct.toFixed(2));
    const ma = rows.map(r => r.pct_ma4 == null ? null : +r.pct_ma4.toFixed(2));
    const hsi = rows.map(r => r.hsi);
    const c = chart('chartShort');
    if (!c) return;
    c.setOption({
      animationDuration: 500,
      grid: { left: 8, right: 14, top: 46, bottom: 8, containLabel: true },
      legend: { left: 'center', top: 2, itemGap: 14, itemWidth: 10, itemHeight: 6, textStyle: { color: C.muted, fontSize: 12 } },
      tooltip: tip({
        formatter: ps => {
          const i = ps[0].dataIndex;
          return `<div style="font-size:12px;color:${C.muted};margin-bottom:4px">${dates[i]}</div>
            <div style="font-family:${MONO}">淡仓市值 <b style="color:${C.up}">${num(values[i], 0)} 亿</b></div>
            <div style="font-family:${MONO}">占市值比 <b style="color:${C.gold}">${num(ratio[i], 2)}%</b></div>
            <div style="font-family:${MONO}">恒生指数 <b>${num(hsi[i], 0)}</b></div>`;
        }
      }),
      xAxis: axisX(dates),
      yAxis: [
        axisY({ name: '淡仓亿港元', nameTextStyle: { color: C.dim, fontSize: 11 } }),
        axisY({ name: '占市值 %', nameTextStyle: { color: C.dim, fontSize: 11 }, splitLine: { show: false }, axisLabel: { color: C.dim, fontSize: 12, formatter: v => v + '%' } }),
      ],
      series: [
        {
          name: '淡仓市值', type: 'bar', data: values, barWidth: '52%',
          itemStyle: {
            borderRadius: [2, 2, 0, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: rgba(C.up,.8) }, { offset: 1, color: rgba(C.up,.15) }]),
          },
        },
        { name: '占市值比', type: 'line', yAxisIndex: 1, data: ratio, showSymbol: false, smooth: true, lineStyle: { color: C.gold, width: 1.6 } },
        { name: '4周均比', type: 'line', yAxisIndex: 1, data: ma, showSymbol: false, smooth: true, lineStyle: { color: C.cyan, width: 1.2, type: 'dashed' } },
      ],
    });
    const latest = rows[rows.length - 1] || {};
    const peak = rows.reduce((a, b) => ((b.short_pct || 0) > (a.short_pct || 0) ? b : a), {});
    $('#shortChartFoot').innerHTML = `
      <span>最新淡仓 <b>${num((latest.short_value || 0) / 1e8, 0)} 亿</b></span>
      <span>占市值 <b>${num(latest.short_pct, 2)}%</b></span>
      <span>区间峰值 <b>${peak.date || '—'} · ${num(peak.short_pct, 2)}%</b></span>
      <span>4周均比 <b>${num(m.avg4_pct, 2)}%</b></span>`;
  }

  function renderHedgeList(rows) {
    const host = $('#hedgeList');
    if (!rows || !rows.length) {
      host.innerHTML = '<div class="empty"><b>暂无对冲标的</b><span>近 4 周同时满足回购与高淡仓占比的股票为空</span></div>';
      return;
    }
    host.innerHTML = rows.map(r => `
      <div class="hedge-item clickable" data-code="${esc(r.code)}">
        <div class="hg-left">
          <div class="hg-name">${esc(r.name)}<span class="hg-code">${esc(r.code)}</span></div>
          <div class="hg-meta">回购 <b class="em">${num(r.buyback_amount / 1e8, 2)}亿</b> · 淡仓 <b class="up">${num(r.short_value / 1e8, 2)}亿</b></div>
        </div>
        <div class="hg-right">
          <b class="hg-ratio">${num(r.short_pct, 1)}%</b>
          <span class="hg-sub">占市值比</span>
        </div>
      </div>`).join('');
    $$('#hedgeList [data-code]').forEach(el => el.addEventListener('click', () => goto('stock', el.dataset.code)));
  }

  function renderShortTable(rows) {
    if (!rows || !rows.length) {
      $('#shortTable').innerHTML = '<div class="empty"><b>没有符合条件的卖空标的</b><span>尝试放宽市值或淡仓占比条件</span></div>';
      return;
    }
    const wk = state.shortPeriod > 0 ? state.shortPeriod : '年';
    const chgHead = state.shortPeriod === 1 ? '周变化' : `较${wk}周前`;
    $('#shortTable').innerHTML = `<table class="data-table">
      <thead><tr>
        <th class="l">#</th><th class="l sortable">股票</th><th class="l sortable">行业</th>
        <th class="sortable" title="SFC 申报淡仓市值（港元）">淡仓市值</th><th class="sortable" title="淡仓市值 / 总市值">占市值比</th><th class="sortable">${chgHead}</th>
        <th class="sortable">回购金额</th><th class="sortable">现价</th><th class="sortable">涨跌</th><th class="sortable">市值</th>
      </tr></thead>
      <tbody>${rows.map((r, i) => `<tr class="clickable" data-code="${esc(r.code)}">
        <td class="l"><span class="rank-no ${i < 3 ? 'top' : ''}">${i + 1}</span></td>
        <td class="l"><div class="name">${esc(r.name)}${r.hedge ? ' <span class="tag gold">对冲</span>' : ''}</div><div class="code">${esc(r.code)}.HK</div></td>
        <td class="l soft">${esc(r.sector)}</td>
        <td data-v="${r.short_value}" class="up">${num(r.short_value / 1e8, 2)}亿</td>
        <td data-v="${r.short_pct}" class="em">${r.short_pct == null ? '<span class="soft">—</span>' : num(r.short_pct, 2) + '%'}</td>
        <td data-v="${r.chg_ratio}" class="${r.chg_ratio == null ? 'soft' : r.chg_ratio > 0 ? 'up' : 'down'}">${r.chg_ratio == null ? '—' : pct(r.chg_ratio, 1)}</td>
        <td data-v="${r.buyback_amount}" class="${r.buyback_amount > 0 ? 'em' : 'soft'}">${r.buyback_amount > 0 ? num(r.buyback_amount / 1e8, 2) + '亿' : '—'}</td>
        <td data-v="${r.price}">${num(r.price, 2)}</td>
        <td data-v="${r.change_pct}" class="${cls(r.change_pct)}">${pct(r.change_pct, 1)}</td>
        <td data-v="${r.market_cap}">${mcap(r.market_cap)}</td>
      </tr>`).join('')}</tbody></table>`;
    $$('#shortTable tr[data-code]').forEach(tr => tr.addEventListener('click', () => goto('stock', tr.dataset.code)));
  }

  /* ---------------- stock view ---------------- */
  async function loadStock(code) {
    code = String(code || '').replace(/\D/g, '').padStart(5, '0');
    if (state.stockCode === code && state.stock) {
      renderStock(state.stock);
      return;
    }
    state.stockCode = code;
    $('#stockContent').innerHTML = '<div class="panel loading-panel">正在加载个股数据…</div>';
    try {
      const d = await api('/api/stocks/' + code);
      state.stock = d;
      renderStock(d);
      clearError();
    } catch (err) {
      $('#stockContent').innerHTML = `<div class="panel empty"><b>加载失败</b><span>${esc(err.message)}</span></div>`;
    }
  }

  function renderStock(d) {
    const q = d.quote || {};
    const v = d.valuation || {};
    const f = d.fundamental || {};
    const t = d.tech || {};
    const tags = [];
    const d20 = d.buyback?.d20 || {};
    if (d20.days >= 10) tags.push('持续回购');
    else if (d20.days > 0) tags.push('回购中');
    if (d20.premium != null && d20.premium < -1) tags.push('低于回购均价');
    if (v.pe && v.pe > 0 && v.pe < 10) tags.push('低估值');
    if (v.pb && v.pb > 0 && v.pb < 1) tags.push('破净');
    if (v.dividend_yield && v.dividend_yield >= 5) tags.push('高股息');
    if (t.pos52 != null && t.pos52 < 30) tags.push('52周低位');
    if (f.roe && f.roe >= 15) tags.push('ROE优秀');
    tags.length = Math.min(tags.length, 4);
    const tone = cls(q.change_pct);
    const sector = (d.sector && d.sector !== '其他') ? d.sector : (d.industry || '其他');
    const pos = t.pos52;
    const peText = v.pe == null || v.pe === 0 ? '—' : v.pe < 0 ? '亏损' : num(v.pe, 1);
    const pbText = v.pb == null ? '—' : num(v.pb, 2);
    const divText = v.dividend_yield == null ? '—' : num(v.dividend_yield, 2) + '%';
    const roeText = f.roe == null ? '—' : num(f.roe, 1) + '%';
    const revText = f.revenue_growth == null ? '—' : pct(f.revenue_growth, 1);
    const profitText = f.profit_growth == null ? '—' : pct(f.profit_growth, 1);
    const watched = getWatch().includes(d.code);

    $('#stockContent').innerHTML = `
      <div class="panel">
        <div class="stock-head">
          <div class="sh-left">
            <div class="sh-name">
              <h2>${esc(d.name)} <span class="sh-code">${esc(d.code)}.HK</span></h2>
              <div class="sh-meta"><span>${esc(sector)}</span><span>·</span><span>港股</span>
                ${tags.map(x => tag(x, x.includes('回购') ? 'gold' : x.includes('低') || x.includes('破净') ? 'green' : 'blue')).join('')}
              </div>
            </div>
          </div>
          <div class="sh-right">
            <div class="sh-price">
              <b class="${tone}">${num(q.price, 2)}</b>
              <div class="chg ${tone}">${q.change == null ? '—' : (q.change > 0 ? '+' : '') + num(q.change, 2)} · ${pct(q.change_pct)}</div>
            </div>
            <button class="star-btn ${watched ? 'on' : ''}" data-star="${esc(d.code)}" title="${watched ? '移出自选' : '加入自选'}"><svg><use href="#i-star"/></svg></button>
            <button class="mini-btn" data-scroll="shareholderPanel">股东结构</button>
          </div>
        </div>
        <div class="stock-kpis">
          <div class="sk"><span>市盈率 TTM</span><b>${peText}</b><small>市场中位 ${num(v.market_pe, 1)}</small></div>
          <div class="sk"><span>市净率</span><b>${pbText}</b><small>市场中位 ${num(v.market_pb, 2)}</small></div>
          <div class="sk"><span>股息率</span><b>${divText}</b><small>市场中位 ${num(v.market_div, 2)}%</small></div>
          <div class="sk"><span>总市值</span><b>${mcap(q.market_cap)}</b><small>${esc(q.currency || 'HKD')}</small></div>
          <div class="sk"><span>ROE</span><b>${roeText}</b><small>股东权益回报率</small></div>
          <div class="sk"><span>营收环比 / 利润环比</span><b style="font-size:13px">${revText} / ${profitText}</b><small>滚动环比</small></div>
        </div>
        <div style="margin-top:12px" class="pos52"><i style="left:${Math.max(0, Math.min(100, pos || 0))}%"></i></div>
        <div class="pos52-l"><span>52W 低 ${num(t.low52, 2)}</span><span>当前处于 ${num(pos, 0)}% 位置</span><span>52W 高 ${num(t.high52, 2)}</span></div>
      </div>

      <div class="stock-grid">
        <div class="stock-left">
          <div class="panel">
            <div class="panel-head">
              <div><span class="eyebrow">PRICE ACTION</span><h2>价格结构</h2></div>
              <div class="seg" id="stockRange">
                <button data-n="90">3M</button><button data-n="250" class="on">1Y</button><button data-n="520">3Y</button>
              </div>
            </div>
            <div class="chart stock-chart" id="chartStock"></div>
            <div class="chart-foot">
              <span>MA20 <b>${num(t.ma20, 2)}</b></span><span>MA60 <b>${num(t.ma60, 2)}</b></span>
              <span>20日波动 <b>${num(t.vol20, 1)}%</b></span><span>一年最大回撤 <b>${num(t.max_drawdown1y, 1)}%</b></span>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head"><div><span class="eyebrow">REPURCHASE LEDGER</span><h2>回购明细</h2></div><span class="asof">${esc(d.buyback.history.currency)} · 最近 12 笔</span></div>
            ${historyTable(d.buyback.history)}
          </div>
        </div>

        <div class="stock-side">
          <div class="panel">
            <div class="panel-head"><div><span class="eyebrow">BUYBACK PROFILE</span><h2>回购画像</h2></div><span class="asof">${esc(d.buyback.d20.start || '')}</span></div>
            <div class="bb-profile">
              <div class="bp-item"><span>近20日回购</span><b>${num((d.buyback.d20.amount || 0) / 1e8, 2)} 亿</b></div>
              <div class="bp-item"><span>回购天数</span><b>${d.buyback.d20.days || 0} 天</b></div>
              <div class="bp-item"><span>20日回购均价</span><b>${num(d.buyback.d20.vwap, 2)}</b></div>
              <div class="bp-item"><span>现价 vs 均价</span><b class="${d.buyback.d20.premium != null && d.buyback.d20.premium < 0 ? 'em' : 'soft'}">${pct(d.buyback.d20.premium, 1)}</b></div>
              <div class="bp-item"><span>60日回购占市值</span><b>${num(d.buyback.d60.yield_pct, 2)}%</b></div>
              <div class="bp-item"><span>年内累计</span><b>${num((d.buyback.ytd.amount || 0) / 1e8, 1)} 亿</b></div>
            </div>
          </div>

          ${shortProfile(d.short)}

          <div class="panel">
            <div class="panel-head"><div><span class="eyebrow">RESEARCH NOTES</span><h2>投研结论</h2></div></div>
            ${(d.conclusions || []).map(c => `<div class="conclusion ${c.tone}">
              <span class="c-dot"></span><div><b>${esc(c.title)}</b>${esc(c.text)}</div></div>`).join('')}
          </div>
        </div>
      </div>

      <div class="panel holder-panel" id="shareholderPanel">
        <div class="panel-head">
          <div><span class="eyebrow">OWNERSHIP & DISCLOSURE</span><h2>股东结构与权益披露</h2></div>
          <div class="panel-tools">
            <button class="mini-btn" data-holder-refresh>刷新披露</button>
            <a class="mini-btn" id="diSource" href="#" target="_blank" rel="noopener">官方权益披露 ↗</a>
          </div>
        </div>
        <div id="shareholderBody" class="holder-body"><div class="loading-panel">正在加载 5%+ 股东与增减持披露…</div></div>
      </div>

      <div class="panel peers-panel">
        <div class="panel-head"><div><span class="eyebrow">PEERS</span><h2>同业对比</h2></div><span class="asof">${esc(d.sector || '')}</span></div>
        ${peersTable(d.peers)}
      </div>`;
    renderStockChart(d, state.stockRange);
    renderShortTrend(d.short);
    loadShareholders(d.code);
    setTimeout(resizeCharts, 60);
  }

  /* ---------------- shareholders ---------------- */
  async function loadShareholders(code, force = false) {
    const body = $('#shareholderBody');
    if (!body) return;
    if (!force && state.shareholders && state.shareholders.code === code) {
      renderShareholders(state.shareholders.data);
      return;
    }
    body.innerHTML = '<div class="loading-panel">正在加载 5%+ 股东与增减持披露…</div>';
    try {
      const data = await api(`/api/stocks/${code}/shareholders${force ? '?refresh=1' : ''}`);
      state.shareholders = { code, data };
      renderShareholders(data);
    } catch (err) {
      body.innerHTML = `<div class="empty"><b>暂无权益披露数据</b><span>${esc(err.message)}</span></div>`;
    }
  }

  function holderTone(type) {
    return ({ '外资机构': 'blue', '外资战略': 'gold', '主权基金': 'purple', '中资机构': 'red',
      '创始人/管理层': 'green', '个人/其他': '', '其他机构': '' })[type] || '';
  }

  function renderShareholders(d) {
    const body = $('#shareholderBody');
    if (!body) return;
    const src = $('#diSource');
    if (src && d.source_url) src.href = d.source_url;
    if (!d.holders || !d.holders.length) {
      body.innerHTML = `<div class="empty"><b>暂无 5%+ 权益披露</b><span>该标的可能没有达到披露门槛的股东，或披露数据暂不可用</span></div>`;
      return;
    }
    const s = d.summary || {};
    const fmtN = v => {
      if (v == null) return '—';
      const a = Math.abs(v);
      if (a >= 1e8) return (a / 1e8).toFixed(2) + '亿';
      if (a >= 1e4) return (a / 1e4).toFixed(1) + '万';
      return int(a);
    };
    const holders = (d.holders_unique || d.holders).slice(0, 5);
    const notices = (d.notices || []).slice(0, 8);
    const maxPct = Math.max(...holders.map(h => h.pct || 0), 1);
    const last = s.foreign_last;
    const netTone = v => (v == null ? 'soft' : v > 0 ? 'up' : v < 0 ? 'down' : 'soft');
    const netText = v => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '-' : ''}${fmtN(v)} 股`);
    const ribbon = [
      ['前五大合计', num(s.top5_pct, 2) + '%' + (s.overlap ? '*' : ''), C.gold, s.overlap ? '去重封顶' : '去重口径'],
      ['外资 / 战略', num(s.foreign_pct, 2) + '%', C.cyan, `近12月 ${netText(s.foreign_net_12m)}`],
      ['中资机构', num(s.china_pct, 2) + '%', C.up, `近12月 ${netText(s.china_net_12m)}`],
      ['创始人 / 管理层', num(s.founder_pct, 2) + '%', C.accent, '披露口径'],
      ['披露股东', String(s.holder_count || 0), C.violet, '5%+ 名单'],
    ];
    body.innerHTML = `
      <div class="holder-ribbon">
        ${ribbon.map(([label, value, color, sub], i) => {
          const tint = /^0(\.00)?%?$/.test(value) ? 'var(--dim)' : color;
          return `
          <div class="hrb" style="--accent:${tint};--i:${i}">
            <span class="hrb-label">${label}</span>
            <b class="hrb-value" style="color:${tint}">${value}</b>
            <span class="hrb-sub">${esc(sub)}</span>
          </div>`;
        }).join('')}
      </div>
      <div class="holder-main">
        <div class="holder-list-wrap">
          <div class="subhead">主要股东 <span>TOP 5 · 按份额去重</span></div>
          <div class="holder-list">
            ${holders.map((h, i) => {
              const tone = holderTone(h.holder_type);
              const col = { blue: C.cyan, gold: C.gold, purple: C.violet, red: C.up, green: C.accent }[tone] || C.accent;
              return `
              <div class="holder-row" style="--i:${i};--c:${col}">
                <span class="hr-rank">${String(i + 1).padStart(2, '0')}</span>
                <div class="hr-main">
                  <div class="hr-name">${esc(h.name)}<span class="hr-type ${tone}">${esc(h.holder_type || '—')}</span></div>
                  <div class="hr-bar"><i style="width:${Math.max(3, (h.pct || 0) / maxPct * 100)}%;background:linear-gradient(90deg,${rgba(col, .18)},${col});box-shadow:0 0 10px ${rgba(col, .3)}"></i></div>
                </div>
                <div class="hr-right">
                  <b class="hr-pct">${num(h.pct, 2)}%</b>
                  <span class="hr-date">更新 ${h.last_notice ? esc(String(h.last_notice).slice(5)) : '—'}</span>
                </div>
              </div>`;
            }).join('')}
          </div>
        </div>
        <div class="holder-side">
          <div class="subhead">类型分布 <span>披露口径</span></div>
          <div class="chart holder-pie" id="chartHolders"></div>
          <div class="holder-moves">
            <div class="hm-row"><span>外资近12月</span><b class="${netTone(s.foreign_net_12m)}">${netText(s.foreign_net_12m)}</b></div>
            <div class="hm-row"><span>中资近12月</span><b class="${netTone(s.china_net_12m)}">${netText(s.china_net_12m)}</b></div>
            <div class="hm-row"><span>最近外资动作</span><b class="soft">${last ? `${esc(last.name)} · ${esc(last.direction)}` : (s.foreign_signal === '无披露' ? '近12个月无披露' : '—')}</b></div>
          </div>
        </div>
      </div>
      <div class="subhead holder-disc-head">近期权益披露 <span>${d.notices ? d.notices.length : 0} 条 · 方向按持仓变化推断</span></div>
      ${notices.length ? `<div class="holder-timeline">
        ${notices.map((n, i) => `
          <div class="ht-row" style="--i:${i}">
            <span class="ht-date">${esc((n.date || '').slice(5) || '—')}</span>
            <span class="ht-dot ${n.direction === '增持' ? 'up' : n.direction === '减持' ? 'down' : ''}"></span>
            <div class="ht-main">
              <b>${esc(n.name)}</b>
              <span>${n.change_shares ? `${fmtN(Math.abs(n.change_shares))} 股 · ` : ''}变动后 ${num(n.after_pct, 2)}%</span>
            </div>
            <span class="ht-pill ${n.direction === '增持' ? 'up' : n.direction === '减持' ? 'down' : ''}">${esc(n.direction || '—')}</span>
          </div>`).join('')}
      </div>` : '<div class="empty" style="padding:18px"><span>近三年暂无权益披露变动</span></div>'}
      <div class="holder-note">来源：HKEX 权益披露（DION）· 覆盖 5%+ 大股东及董事；类型按名称规则推断，不等同于基金季报的全部持仓。${s.overlap ? '部分股东存在共同权益/多层披露，占比已按份额去重并封顶至 100%。' : ''}${d.error ? ' ' + esc(d.error) : ''}</div>`;
    renderHolderPie(d.holders_unique || d.holders);
    setTimeout(resizeCharts, 50);
  }

  function renderHolderPie(holders) {
    const c = chart('chartHolders');
    if (!c) return;
    const groups = {};
    holders.forEach(h => {
      if (!h.holder_type) return;
      groups[h.holder_type] = (groups[h.holder_type] || 0) + (h.pct || 0);
    });
    const colors = {
      '外资机构': C.cyan, '外资战略': C.gold, '主权基金': C.violet,
      '中资机构': C.up, '创始人/管理层': C.accent, '个人/其他': C.dim, '其他机构': C.muted,
    };
    const total = Object.values(groups).reduce((a, b) => a + b, 0) || 1;
    const data = Object.entries(groups).map(([name, value]) => ({
      name: `${name} ${(value / total * 100).toFixed(1)}%`,
      value,
      itemStyle: { color: colors[name] || C.muted },
    }));
    c.setOption({
      tooltip: tip({ trigger: 'item', formatter: p => `${p.name}<br><b style="font-family:${MONO}">${num(p.value, 2)}%</b>` }),
      legend: { bottom: 2, left: 'center', itemGap: 12, itemWidth: 9, itemHeight: 6, textStyle: { color: C.muted, fontSize: 11 } },
      series: [{
        type: 'pie', radius: ['48%', '70%'], center: ['50%', '46%'],
        avoidLabelOverlap: true,
        label: { show: false }, labelLine: { show: false },
        itemStyle: { borderColor: C.panel, borderWidth: 2 },
        data,
      }],
    }, true);
  }

  function shortProfile(s) {
    if (!s || !s.has_data) {
      return `<div class="panel">
        <div class="panel-head"><div><span class="eyebrow">SHORT INTEREST</span><h2>淡仓持仓</h2></div></div>
        <div class="empty" style="padding:18px"><b>暂无淡仓数据</b><span>该标的暂不在 SFC 申报淡仓名单内</span></div></div>`;
    }
    const rows = s.rows || [];
    const tone = s.trend != null && s.trend > 0 ? 'up' : 'down';
    const back = k => (rows.length > k ? rows[rows.length - 1 - k] : null);
    const chgFoot = (label, k) => {
      const base = back(k);
      const v = base && base.short_value && s.latest_value != null
        ? (s.latest_value / base.short_value - 1) * 100 : null;
      return `<span>${label} <b class="${v == null ? 'soft' : v > 0 ? 'up' : 'down'}">${v == null ? '—' : (v > 0 ? '+' : '') + num(v, 1) + '%'}</b></span>`;
    };
    return `<div class="panel short-panel">
      <div class="panel-head"><div><span class="eyebrow">SHORT INTEREST</span><h2>淡仓持仓</h2></div><span class="asof">周度 · ${esc(s.latest_date || '')}</span></div>
      <div class="bb-profile">
        <div class="bp-item"><span>淡仓占市值</span><b>${num(s.latest_pct, 2)}%</b></div>
        <div class="bp-item"><span>4周均占比</span><b>${num(s.avg4, 2)}%</b></div>
        <div class="bp-item"><span>较4周均值</span><b class="${tone}">${s.trend == null ? '—' : (s.trend > 0 ? '+' : '') + num(s.trend, 2) + 'pp'}</b></div>
        <div class="bp-item"><span>区间历史分位</span><b>${num(s.percentile, 0)}%</b></div>
        <div class="bp-item"><span>淡仓市值</span><b>${num((s.latest_value || 0) / 1e8, 1)}亿</b></div>
        <div class="bp-item"><span>回购−淡仓</span><b class="${s.net >= 0 ? 'em' : 'up'}">${num((s.net || 0) / 1e8, 2)}亿</b></div>
      </div>
      <div class="chart short-trend" id="chartStockShort"></div>
      <div class="short-foot">
        ${chgFoot('周变化', 1)}
        ${chgFoot('4周变化', 4)}
        ${chgFoot('13周变化', 13)}
      </div>
      ${s.hedge ? '<div class="tech-note"><span class="tag gold">多空对冲</span><span class="tag">公司回购承接淡仓抛压</span></div>' : ''}
    </div>`;
  }

  function renderShortTrend(s) {
    const c = chart('chartStockShort');
    if (!c || !s || !s.rows || !s.rows.length) return;
    const rows = s.rows.slice(-52);
    const dates = rows.map(r => r.date);
    const values = rows.map(r => +((r.short_value || 0) / 1e8).toFixed(2));
    const pcts = rows.map(r => r.short_pct);
    const ma4 = pcts.map((_, i) => {
      const w = pcts.slice(Math.max(0, i - 3), i + 1).filter(v => v != null);
      return w.length ? +(w.reduce((a, b) => a + b, 0) / w.length).toFixed(3) : null;
    });
    const grad = (color, top, bottom) => ({
      type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
      colorStops: [{ offset: 0, color: rgba(color, top) }, { offset: 1, color: rgba(color, bottom) }],
    });
    c.setOption({
      animationDuration: 650,
      grid: { left: 2, right: 4, top: 30, bottom: 4, containLabel: true },
      legend: { top: 2, left: 'center', itemGap: 10, itemWidth: 8, itemHeight: 5, textStyle: { color: C.muted, fontSize: 10.5 } },
      tooltip: tip({
        formatter: ps => {
          if (!ps.length) return '';
          const i = ps[0].dataIndex;
          return `<div style="font-size:11px;color:${C.muted};margin-bottom:3px">${dates[i]}</div>
            <div>淡仓市值 <b style="font-family:${MONO};color:${C.text}">${num(values[i], 2)} 亿</b></div>
            <div>淡仓占市值 <b style="font-family:${MONO};color:${C.gold}">${pcts[i] == null ? '—' : num(pcts[i], 2) + '%'}</b></div>`;
        },
      }),
      xAxis: {
        type: 'category', data: dates, boundaryGap: true,
        axisLine: { lineStyle: { color: '#23344e' } }, axisTick: { show: false },
        axisLabel: { color: C.dim, fontSize: 9.5, fontFamily: MONO, hideOverlap: true, formatter: v => String(v).slice(5) },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: 'value', scale: true,
          axisLabel: { color: C.dim, fontSize: 9.5, fontFamily: MONO, formatter: v => num(v, 0) },
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { lineStyle: { color: C.grid, type: 'dashed' } },
        },
        {
          type: 'value', scale: true,
          axisLabel: { color: C.dim, fontSize: 9.5, fontFamily: MONO, formatter: v => num(v, 1) },
          axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '淡仓市值(亿)', type: 'bar', data: values, barWidth: '52%',
          itemStyle: { borderRadius: [3, 3, 0, 0], color: grad(C.cyan, .58, .1) },
        },
        {
          name: '占市值比(%)', type: 'line', yAxisIndex: 1, data: pcts, showSymbol: false, smooth: true,
          itemStyle: { color: C.gold }, lineStyle: { color: C.gold, width: 1.6 }, areaStyle: { color: grad(C.gold, .14, 0) },
        },
        {
          name: '4周均', type: 'line', yAxisIndex: 1, data: ma4, showSymbol: false, smooth: true,
          itemStyle: { color: C.violet }, lineStyle: { color: C.violet, width: 1, type: 'dashed' },
        },
      ],
    }, true);
  }

  function historyTable(h) {
    const rows = [...(h.rows || [])].reverse().slice(0, 12);
    if (!rows.length) return '<div class="empty"><b>暂无回购记录</b><span>近两年未在港交所披露场内回购</span></div>';
    return `<table class="data-table"><thead><tr>
      <th class="l sortable">日期</th><th class="sortable">回购股数</th><th class="sortable">均价</th><th class="sortable">金额</th><th class="sortable">累计金额</th><th class="sortable">授权累计占比</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td class="l" data-v="${r.date}">${esc(r.date)}</td><td data-v="${r.shares}">${int(r.shares)}</td><td data-v="${r.vwap}">${num(r.vwap, 2)}</td>
        <td data-v="${r.amount}" class="em">${money(r.amount, 3)}</td><td data-v="${r.cum_amount}">${money(r.cum_amount, 2)}</td>
        <td data-v="${r.pct_issued}">${r.pct_issued == null ? '—' : num(r.pct_issued, 3) + '%'}</td>
      </tr>`).join('')}</tbody></table>`;
  }

  function peersTable(peers) {
    if (!peers || !peers.length) return '<div class="empty"><b>暂无同业样本</b><span>该标的暂未纳入核心观察池</span></div>';
    return `<table class="data-table"><thead><tr>
      <th class="l sortable">公司</th><th class="sortable">现价</th><th class="sortable">涨跌</th><th class="sortable">PE</th><th class="sortable">股息</th><th class="sortable">20日回购</th><th class="sortable">现价/均价</th>
      </tr></thead><tbody>${peers.map(p => `<tr class="clickable" data-code="${esc(p.code)}">
        <td class="l"><div class="name">${esc(p.name)}</div><div class="code">${esc(p.code)}.HK</div></td>
        <td data-v="${p.price}">${num(p.price, 2)}</td><td data-v="${p.change_pct}" class="${cls(p.change_pct)}">${pct(p.change_pct)}</td>
        <td data-v="${p.pe}">${p.pe == null || p.pe === 0 ? '—' : p.pe < 0 ? '亏损' : num(p.pe, 1)}</td>
        <td data-v="${p.dividend_yield}">${num(p.dividend_yield, 1)}%</td><td data-v="${p.buyback20}" class="em">${num((p.buyback20 || 0) / 1e8, 2)}亿</td>
        <td data-v="${p.premium}" class="${p.premium != null && p.premium < 0 ? 'em' : 'soft'}">${pct(p.premium, 1)}</td>
      </tr>`).join('')}</tbody></table>`;
  }

  function renderStockChart(d, n) {
    const c = chart('chartStock');
    if (!c) return;
    const chartData = d.chart || {};
    const allDates = chartData.dates || [];
    if (!allDates.length) {
      c.clear();
      return;
    }
    const start = Math.max(0, allDates.length - n);
    const dates = allDates.slice(start);
    const candles = (chartData.candles || []).slice(start);
    const volumes = (chartData.volume || []).slice(start);
    const ma20 = (chartData.ma20 || []).slice(start);
    const ma60 = (chartData.ma60 || []).slice(start);
    c.setOption({
      animation: false,
      legend: { top: 4, left: 'center', itemGap: 14, itemWidth: 10, itemHeight: 6, textStyle: { color: C.muted, fontSize: 12 } },
      tooltip: tip({
        trigger: 'axis',
        axisPointer: { type: 'cross', crossStyle: { color: '#314763' } },
        formatter: ps => {
          if (!ps.length) return '';
          const i = ps[0].dataIndex;
          const cd = candles[i] || [];
          let s = `<div style="font-size:12px;color:${C.muted};margin-bottom:4px">${dates[i]}</div>`;
          if (cd.length) s += `<div style="font-family:${MONO};line-height:1.7">开 <b>${num(cd[0], 2)}</b>　收 <b style="color:${cd[1] >= cd[0] ? C.up : C.down}">${num(cd[1], 2)}</b><br>高 <b>${num(cd[3], 2)}</b>　低 <b>${num(cd[2], 2)}</b></div>`;
          if (ma20[i] != null) s += `<div style="font-family:${MONO};color:${C.cyan};font-size:12px">MA20 ${num(ma20[i], 2)}</div>`;
          if (ma60[i] != null) s += `<div style="font-family:${MONO};color:#a78bfa;font-size:12px">MA60 ${num(ma60[i], 2)}</div>`;
          return s;
        }
      }),
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { left: 6, right: 30, top: 44, height: '60%', containLabel: true },
        { left: 6, right: 30, top: '80%', height: '12%', containLabel: true },
      ],
      xAxis: [
        { type: 'category', data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#23344e' } }, axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
        { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#23344e' } }, axisTick: { show: false }, axisLabel: { color: C.dim, fontSize: 12, hideOverlap: true, formatter: v => String(v).slice(5) }, splitLine: { show: false } },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: C.grid, type: 'dashed' } }, axisLabel: { color: C.dim, fontSize: 12, fontFamily: MONO }, axisLine: { show: false }, axisTick: { show: false } },
        { scale: true, gridIndex: 1, splitNumber: 1, splitLine: { show: false }, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false } },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 }],
      series: [
        {
          name: 'K线', type: 'candlestick', data: candles, barMaxWidth: 8,
          itemStyle: { color: C.up, color0: C.down, borderColor: C.up, borderColor0: C.down },
        },
        { name: 'MA20', type: 'line', data: ma20, showSymbol: false, smooth: true, lineStyle: { color: C.cyan, width: 1.2 }, connectNulls: false },
        { name: 'MA60', type: 'line', data: ma60, showSymbol: false, smooth: true, lineStyle: { color: C.violet, width: 1.1 }, connectNulls: false },
        {
          name: '成交额', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes, barWidth: '55%',
          itemStyle: { color: p => (candles[p.dataIndex] && candles[p.dataIndex][1] >= candles[p.dataIndex][0] ? rgba(C.up, .5) : rgba(C.down, .5)) },
        },
      ],
    }, true);
    $$('#stockRange button').forEach(b => b.classList.toggle('on', Number(b.dataset.n) === n));
  }

  /* ---------------- screener ---------------- */
  async function loadScreener(preset) {
    const p = preset || state.screenerPreset || 'all';
    state.screenerPreset = p;
    const params = new URLSearchParams({ preset: p, limit: '300' });
    const read = (id) => { const el = $(id); return el ? el.value.trim() : ''; };
    const map = {
      mcap_min: '#fMcap', pe_max: '#fPe', pb_max: '#fPb', div_min: '#fDiv',
      days_min: '#fDays', yield_min: '#fYield', roe_min: '#fRoe', pos_max: '#fPos',
      sector: '#fSector',
    };
    Object.entries(map).forEach(([k, sel]) => {
      const v = read(sel);
      if (v !== '' && v != null) params.set(k, v);
    });
    if ($('#fBelowVwap') && $('#fBelowVwap').checked) params.set('below_vwap', '1');
    try {
      const d = await api('/api/screener?' + params.toString());
      if ($('#fWatchOnly') && $('#fWatchOnly').checked) {
        const codes = getWatch();
        d.rows = codes.length ? await api('/api/watchlist?codes=' + codes.join(',')) : [];
        d.count = d.rows.length;
      }
      state.screener = d;
      state.screenerRows = d.rows;
      renderScreener(d);
      clearError();
    } catch (err) {
      showError(`筛选失败：${err.message}`);
    }
  }

  function resetFilterInputs(keepMcap = true) {
    ['#fPe', '#fPb', '#fDiv', '#fDays', '#fYield', '#fRoe', '#fPos'].forEach(id => { if ($(id)) $(id).value = ''; });
    if (!keepMcap && $('#fMcap')) $('#fMcap').value = 30;
    if ($('#fSector')) $('#fSector').value = '';
    if ($('#fBelowVwap')) $('#fBelowVwap').checked = false;
  }

  function renderScreener(d) {
    ensureScreenerSectors();
    const presetMeta = {
      all: ['全市场', '全部港股'],
      buyback_value: ['回购 + 低估值', 'PE≤20 · PB≤2.5'],
      persistent: ['持续回购', '20日内≥10天'],
      below_vwap: ['低于回购均价', '现价 < 公司回购成本'],
      dividend: ['高股息 + 回购', '股息率≥5%'],
      oversold: ['52周低位', '位置≤30% · 有回购'],
      quality: ['质量 + 回购', 'ROE≥10% · PE≤25'],
    };
    $('#presets').innerHTML = Object.entries(presetMeta).map(([k, v]) => `
      <button class="preset ${k === d.preset ? 'on' : ''}" data-preset="${k}">
        <em>${k === d.preset ? 'ACTIVE' : ''}</em><b>${v[0]}</b><span>${v[1]}</span>
      </button>`).join('');
    $$('#presets .preset').forEach(b => b.addEventListener('click', () => {
      resetFilterInputs(false);
      loadScreener(b.dataset.preset);
    }));

    $('#screenerSummary').innerHTML = `
      <span>命中 <b>${d.count}</b> 只</span><span>展示前 <b>${d.rows.length}</b> 只</span>
      <span>点击列头排序</span>`;
    if (!d.rows.length) {
      $('#screenerTable').innerHTML = '<div class="empty"><b>没有符合条件的标的</b><span>尝试放宽 PE/PB/回购天数条件</span></div>';
      return;
    }
    $('#screenerTable').innerHTML = `<table class="data-table">
      <thead><tr>
        <th class="l">#</th><th class="l sortable">股票</th><th class="l sortable">标签</th>
        <th class="sortable">现价</th><th class="sortable">涨跌</th><th class="sortable">PE</th><th class="sortable">PB</th><th class="sortable">股息率</th>
        <th class="sortable">回购占市值</th><th class="sortable">回购天数</th><th class="sortable">现价/均价</th><th class="sortable">市值</th><th class="sortable">52W位置</th>
      </tr></thead>
      <tbody>${d.rows.map((r, i) => `<tr class="clickable" data-code="${esc(r.code)}">
        <td class="l"><span class="rank-no ${i < 3 ? 'top' : ''}">${i + 1}</span></td>
        <td class="l"><div class="name">${esc(r.name)}</div><div class="code">${esc(r.code)}.HK · ${esc(r.sector)}</div></td>
        <td class="l">${(r.tags || []).map(t => tag(t, t.includes('回购') ? 'gold' : t.includes('低') || t.includes('破净') ? 'green' : t.includes('股息') ? 'blue' : '')).join('')}</td>
        <td data-v="${r.price}">${num(r.price, 2)}</td><td data-v="${r.change_pct}" class="${cls(r.change_pct)}">${pct(r.change_pct)}</td>
        <td data-v="${r.pe}">${r.pe == null || r.pe === 0 ? '—' : r.pe < 0 ? '亏损' : num(r.pe, 1)}</td>
        <td data-v="${r.pb}">${num(r.pb, 2)}</td><td data-v="${r.dividend_yield}">${num(r.dividend_yield, 2)}%</td>
        <td data-v="${r.buyback_cap}" class="em">${num(r.buyback_cap, 2)}%</td>
        <td data-v="${r.buyback_days}">${r.buyback_days}<span class="soft">${r.streak > 1 ? '/连' + r.streak : ''}</span></td>
        <td data-v="${r.premium}" class="${r.premium != null && r.premium < 0 ? 'em' : 'soft'}">${pct(r.premium, 1)}</td>
        <td data-v="${r.market_cap}">${mcap(r.market_cap)}</td>
        <td data-v="${r.pos52}">${num(r.pos52, 0)}%</td>
      </tr>`).join('')}</tbody></table>`;
    $$('#screenerTable tr[data-code]').forEach(tr => tr.addEventListener('click', () => goto('stock', tr.dataset.code)));
  }

  /* ---------------- search ---------------- */
  function bindStockSearch() {
    const input = $('#stockSearch');
    if (!input) return;
    input.addEventListener('input', () => {
      clearTimeout(state.searchTimer);
      const q = input.value.trim();
      if (!q) { $('#stockSuggest').hidden = true; return; }
      state.searchTimer = setTimeout(async () => {
        try {
          const rows = await api('/api/search?q=' + encodeURIComponent(q));
          const host = $('#stockSuggest');
          host.innerHTML = rows.map(r => `<div class="sug-item" data-code="${esc(r.code)}">
            <span class="sug-name">${esc(r.name)}</span><span class="sug-code">${esc(r.code)}.HK</span>
            <span class="sug-meta">${num(r.price, 2)} <em class="${cls(r.change_pct)}">${pct(r.change_pct)}</em></span>
          </div>`).join('') || '<div class="sug-item"><span class="sug-name">未找到匹配标的</span></div>';
          host.hidden = false;
          $$('#stockSuggest .sug-item[data-code]').forEach(el => el.addEventListener('click', () => {
            host.hidden = true;
            state.stock = null;
            goto('stock', el.dataset.code);
          }));
        } catch (_) {}
      }, 220);
    });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        const first = $('#stockSuggest .sug-item[data-code]');
        if (first) { state.stock = null; goto('stock', first.dataset.code); $('#stockSuggest').hidden = true; }
      }
    });
  }

  /* ---------------- about ---------------- */
  function openAbout() {
    const meta = state.meta || {};
    const sources = meta.sources || [];
    const credits = meta.credits || [];
    $('#aboutBody').innerHTML = `
      <h3>数据来源</h3>
      <div class="source-grid">${sources.map(s => `<div class="source-card"><b>${esc(s.name)}</b><span>${esc(s.detail)}</span></div>`).join('')}</div>
      <h3>回购口径</h3>
      <p>回购数据来自港交所每日《股份回购报告》（SRRPT*.xls）。市场总量采用 <code>Method = Exchange</code>（含 <code>Exchange (Note 1/2/3...)</code>）且以 <code>HKD</code> 计价的记录，按<strong>交易日期</strong>去重汇总；同一公司同日多渠道披露会分别保留。回购金额/成交额为估算值：用日 K 成交量 × 收盘价近似成交额，仅用于横向比较。</p>
      <p>金额与股数/价格明显矛盾（成交均价超出当日最低/最高价 ±20%）的披露会标记为异常并从统计中剔除；若金额为累计口径且可通过累计股数验证，则按当日股数折算。截至 2026-10-30，有效场内回购约 1,252 亿港元。</p>
      <p>最新回购日通常滞后行情一个交易日：例如 10 月 30 日收盘后，可看到 10 月 29 日的回购披露。</p>
      <h3>指标定义</h3>
      <ul>
        <li><strong>回购占市值</strong> = 区间回购金额 ÷ 当前总市值（不年化，避免短窗口失真）。</li>
        <li><strong>现价 / 回购均价</strong> = 现价 ÷ 区间加权平均回购价 − 1；负值表示现价低于公司回购成本。</li>
        <li><strong>52周位置</strong> = (现价 − 52周低) ÷ (52周高 − 52周低)。</li>
        <li><strong>RSI / MACD / Beta</strong>：RSI(14) 采用 Wilder 平滑；MACD 为 12/26/9 日 EMA；Beta 与相关性基于个股和恒指近 250 个交易日对数收益。</li>
      </ul>
      <h3>信号中心</h3>
      <p>基于近 20 日回购金额/天数、现价相对回购均价、股息率、52 周位置与 PB，生成 7 类信号；信号是筛选起点，不是买卖指令。</p>
      <h3>股东结构与权益披露</h3>
      <p>个股页的股东数据来自 HKEX 权益披露（DION）的 5%+ 大股东及董事披露，包含持股比例、最后披露日与近三年增减持记录。增减持方向由同一股东前后持仓变化推断；股东类型（外资机构、中资机构、创始人/管理层、主权基金、外资战略等）按名称规则推断，不是官方分类，也不等同于基金季报的全部持仓。</p>
      <h3>宏观与流动性</h3>
      <p>总结余、HIBOR、基准利率与兑换保证来自 HKMA/HKAB；美债 2Y/10Y/30Y、实际利率、SOFR、VIX 与 USD/HKD 来自 FRED，用于观察港元流动性与利率环境。</p>
      <h3>主题与自选</h3>
      <p>亮/暗主题与自选股保存在当前浏览器的 localStorage，不会上传；自选抽屉和筛选器“仅看自选”共用同一份列表。</p>
      <h3>开源方案与致谢</h3>
      ${credits.map(c => `<div class="credit-row"><b>${esc(c.name)}</b><em>${esc(c.license)}</em><span>${esc(c.use)}</span></div>`).join('')}
      <h3>已知限制</h3>
      <ul>
        <li>腾讯行情为公开接口，非交易所 Level-2；盘中数据可能延迟。</li>
        <li>东财批量行情在当前网络环境不可用，因此全市场估值来自腾讯快照，财务指标仅覆盖核心池与主要回购标的。</li>
        <li>港股财报口径差异较大，PE/PB 对亏损、一次性收益与不同币种敏感；PE=0 视为无有效数据，PE&lt;0 才视为亏损。</li>
        <li>全市场广度与估值中位数仅覆盖市值≥3亿港元的样本；52周高低与现价明显不一致的标的不会参与 52 周位置统计。</li>
        <li>回购披露存在滞后、补录与个别填报错误，最新一日数据可能不完整。</li>
      </ul>
      <div class="disclaimer">本工具仅用于研究辅助，不构成任何投资建议。数据可能存在延迟、缺失或错误，交易前请以港交所及券商终端为准。</div>`;
    $('#aboutModal').hidden = false;
  }

  /* ---------------- binding ---------------- */
  function bindGlobal() {
    $$('.nav-item').forEach(b => b.addEventListener('click', () => goto(b.dataset.view)));
    window.addEventListener('hashchange', route);
    window.addEventListener('resize', () => { clearTimeout(window._rz); window._rz = setTimeout(resizeCharts, 120); });
    document.addEventListener('click', e => {
      const th = e.target.closest('th.sortable');
      if (!th) return;
      const table = th.closest('table');
      if (!table) return;
      const idx = Array.from(th.parentNode.children).indexOf(th);
      const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
      th.parentNode.querySelectorAll('th').forEach(h => { delete h.dataset.dir; h.classList.remove('sorted'); });
      th.dataset.dir = dir;
      th.classList.add('sorted');
      sortableTable(table, idx, dir);
    });
    $('#syncBtn')?.addEventListener('click', () => triggerSync('quick'));
    $('#syncMenuBtn')?.addEventListener('click', e => {
      e.stopPropagation();
      const m = $('#syncMenu');
      if (m) m.hidden = !m.hidden;
    });
    $('#syncMenu')?.addEventListener('click', e => {
      const b = e.target.closest('[data-sync-mode]');
      if (!b) return;
      $('#syncMenu').hidden = true;
      triggerSync(b.dataset.syncMode);
    });
    document.addEventListener('click', e => {
      if (!e.target.closest('#syncControl')) {
        const m = $('#syncMenu');
        if (m) m.hidden = true;
      }
    });
    $('#themeBtn').addEventListener('click', () => applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'));
    $('#watchBtn').addEventListener('click', openWatchDrawer);
    $('#closeWatch').addEventListener('click', closeWatchDrawer);
    $('#watchMask').addEventListener('click', closeWatchDrawer);
    $('#watchBody').addEventListener('click', e => {
      const del = e.target.closest('[data-unwatch]');
      if (del) { e.stopPropagation(); toggleWatch(del.dataset.unwatch); return; }
      const quick = e.target.closest('[data-quick]');
      if (quick) { toggleWatch(quick.dataset.quick); openWatchDrawer(); return; }
      const item = e.target.closest('[data-wcode]');
      if (item) { closeWatchDrawer(); state.stock = null; goto('stock', item.dataset.wcode); }
    });
    $('#exportBuyback').addEventListener('click', () => {
      const rows = state.buyback?.table?.rows || [];
      csvDownload(`harbor_buyback_${new Date().toISOString().slice(0, 10)}.csv`, [
        { label: '代码', key: 'code' }, { label: '名称', key: 'name' }, { label: '行业', key: 'sector' },
        { label: '回购金额(HKD)', key: 'amount' }, { label: '回购均价', key: 'vwap' },
        { label: '现价', key: 'price' }, { label: '现价/均价(%)', key: 'premium' },
        { label: '回购天数', key: 'days' }, { label: '回购占市值(%)', key: 'yield_pct' },
        { label: '市值(HKD)', key: 'market_cap' },
      ], rows);
    });
    $('#exportScreener').addEventListener('click', () => {
      const rows = state.screenerRows || state.screener?.rows || [];
      csvDownload(`harbor_screener_${new Date().toISOString().slice(0, 10)}.csv`, [
        { label: '代码', key: 'code' }, { label: '名称', key: 'name' }, { label: '行业', key: 'sector' },
        { label: '现价', key: 'price' }, { label: '涨跌(%)', key: 'change_pct' },
        { label: 'PE', key: 'pe' }, { label: 'PB', key: 'pb' }, { label: '股息率(%)', key: 'dividend_yield' },
        { label: '回购占市值(%)', key: 'buyback_cap' }, { label: '回购天数', key: 'buyback_days' },
        { label: '现价/均价(%)', key: 'premium' }, { label: '市值(HKD)', key: 'market_cap' },
        { label: '52周位置(%)', key: 'pos52' },
      ], rows);
    });
    $('#fWatchOnly').addEventListener('change', () => loadScreener(state.screenerPreset));
    $('#aboutBtn').addEventListener('click', openAbout);
    $('#aboutBtn2')?.addEventListener('click', openAbout);
    $('#closeAbout').addEventListener('click', () => { $('#aboutModal').hidden = true; });
    $('#aboutModal').addEventListener('click', e => { if (e.target.id === 'aboutModal') $('#aboutModal').hidden = true; });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') { $('#aboutModal').hidden = true; $('#stockSuggest').hidden = true; closeWatchDrawer(); }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (state.view !== 'stock') goto('stock');
        setTimeout(() => $('#stockSearch')?.focus(), 80);
      }
    });
    $('#flowRange').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      state.flowRange = Number(b.dataset.n);
      $$('#flowRange button').forEach(x => x.classList.toggle('on', x === b));
      if (state.overview) renderFlowChart(state.overview);
    });
    $('#moverTabs').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      state.moverTab = b.dataset.k;
      if (state.overview) renderMovers(state.overview.movers);
    });
    $('#bbRange').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      state.bbChartRange = Number(b.dataset.n);
      $$('#bbRange button').forEach(x => x.classList.toggle('on', x === b));
      if (state.buyback) renderBuybackChart(state.buyback.market, state.bbChartRange);
    });
    $('#bbPeriod').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      state.bbPeriod = Number(b.dataset.p);
      $$('#bbPeriod button').forEach(x => x.classList.toggle('on', x === b));
      loadBuyback();
    });
    $('#bbSort').addEventListener('change', () => { state.bbSort = $('#bbSort').value; loadBuyback(); });
    $('#bbApply').addEventListener('click', loadBuyback);
    $('#bbBelowVwap').addEventListener('change', loadBuyback);
    $('#bbSector').addEventListener('change', loadBuyback);
    $('#bbMinMcap').addEventListener('change', loadBuyback);
    let bbTimer;
    $('#bbSearch').addEventListener('input', () => { clearTimeout(bbTimer); bbTimer = setTimeout(loadBuyback, 350); });
    $('#exportShort').addEventListener('click', () => {
      const rows = state.short?.table?.rows || [];
      csvDownload(`harbor_shortinterest_${new Date().toISOString().slice(0, 10)}.csv`, [
        { label: '代码', key: 'code' }, { label: '名称', key: 'name' }, { label: '行业', key: 'sector' },
        { label: '淡仓市值(HKD)', key: 'short_value' }, { label: '淡仓占市值比(%)', key: 'short_pct' },
        { label: '较期初变化(%)', key: 'chg_ratio' }, { label: '期初淡仓市值(HKD)', key: 'prev_value' },
        { label: '回购金额(HKD)', key: 'buyback_amount' }, { label: '现价', key: 'price' },
        { label: '涨跌(%)', key: 'change_pct' }, { label: '市值(HKD)', key: 'market_cap' },
      ], rows);
    });
    $('#shortRange').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      state.shortChartRange = Number(b.dataset.n);
      $$('#shortRange button').forEach(x => x.classList.toggle('on', x === b));
      if (state.short) renderShortChart(state.short.market, state.shortChartRange);
    });
    $('#shortPeriod').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      state.shortPeriod = Number(b.dataset.p);
      $$('#shortPeriod button').forEach(x => x.classList.toggle('on', x === b));
      loadShort();
    });
    $('#shortSort').addEventListener('change', () => { state.shortSort = $('#shortSort').value; loadShort(); });
    $('#shortApply').addEventListener('click', loadShort);
    $('#shortHedge').addEventListener('change', loadShort);
    $('#shortSector').addEventListener('change', loadShort);
    $('#shortMinMcap').addEventListener('change', loadShort);
    $('#shortMinRatio').addEventListener('change', loadShort);
    let shortTimer;
    $('#shortSearch').addEventListener('input', () => { clearTimeout(shortTimer); shortTimer = setTimeout(loadShort, 350); });
    $('#stockRange')?.addEventListener('click', () => {});
    document.addEventListener('click', e => {
      const star = e.target.closest('[data-star]');
      if (star) { e.stopPropagation(); toggleWatch(star.dataset.star); return; }
      const r = e.target.closest('#stockRange button');
      if (r && state.stock) {
        state.stockRange = Number(r.dataset.n);
        renderStockChart(state.stock, state.stockRange);
      }
      const quick = e.target.closest('#quickChips button');
      if (quick) { state.stock = null; goto('stock', quick.dataset.code); }
      const go = e.target.closest('[data-goto]');
      if (go) goto(go.dataset.goto);
      const scroll = e.target.closest('[data-scroll]');
      if (scroll) document.getElementById(scroll.dataset.scroll)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      const holderRefresh = e.target.closest('[data-holder-refresh]');
      if (holderRefresh && state.stockCode) { state.shareholders = null; loadShareholders(state.stockCode, true); }
      if (!e.target.closest('.stock-search')) $('#stockSuggest').hidden = true;
    });
    $('#stockContent').addEventListener('click', e => {
      const row = e.target.closest('tr[data-code]');
      if (row) { state.stock = null; goto('stock', row.dataset.code); }
    });
    $('#presets').addEventListener('click', () => {});
    $('#fApply').addEventListener('click', () => loadScreener(state.screenerPreset));
    $('#fReset').addEventListener('click', () => {
      ['#fMcap', '#fPe', '#fPb', '#fDiv', '#fDays', '#fYield', '#fRoe', '#fPos'].forEach(id => { if ($(id)) $(id).value = ''; });
      $('#fMcap').value = 30;
      $('#fSector').value = '';
      $('#fBelowVwap').checked = false;
      if ($('#fWatchOnly')) $('#fWatchOnly').checked = false;
      state.screenerPreset = 'all';
      loadScreener('all');
    });
    bindStockSearch();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
