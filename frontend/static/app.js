/* TrendScope Dashboard */
const API = window.location.origin;
const TOKEN_KEY = 'ts_token';
const TENANT_KEY = 'ts_tenant';

function getToken() { return sessionStorage.getItem(TOKEN_KEY); }
function setToken(t) { sessionStorage.setItem(TOKEN_KEY, t); }
function clearAuth() { sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(TENANT_KEY); }
function getTenant() {
  try { return JSON.parse(sessionStorage.getItem(TENANT_KEY) || 'null'); } catch (e) { return null; }
}
function setTenant(t) { sessionStorage.setItem(TENANT_KEY, JSON.stringify(t)); }
function hasFull() {
  const t = getTenant();
  if (t === null) return false;
  const ents = t.entitlements || [];
  return ents.includes('trendscope:full') || ents.includes('trendscope:enterprise');
}
function hasEnterprise() {
  const t = getTenant();
  if (t === null) return false;
  return (t.entitlements || []).includes('trendscope:enterprise');
}

async function apiFetch(path, opts) {
  if (opts === undefined) opts = {};
  const token = getToken();
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const resp = await fetch(API + path, Object.assign({}, opts, { headers }));
  if (resp.status === 401) { clearAuth(); showView('login'); throw new Error('Unauthorized'); }
  return resp;
}
async function apiGet(path) {
  const resp = await apiFetch(path);
  if (resp.ok === false) throw new Error(await resp.text());
  return resp.json();
}
async function apiPost(path, body) {
  const resp = await apiFetch(path, { method: 'POST', body: JSON.stringify(body) });
  if (resp.ok === false) throw new Error(await resp.text());
  return resp.json();
}
async function apiDelete(path) {
  const resp = await apiFetch(path, { method: 'DELETE' });
  if (resp.ok === false) throw new Error(await resp.text());
  return resp.json();
}

function showView(name) {
  document.querySelectorAll('.view').forEach(function(v) { v.classList.add('hidden'); });
  const el = document.getElementById(name + '-view');
  if (el) el.classList.remove('hidden');
}

function showPage(name) {
  document.querySelectorAll('.page').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.nav-link').forEach(function(b) {
    b.classList.remove('active');
    b.removeAttribute('aria-current');
  });
  const page = document.getElementById('page-' + name);
  if (page) page.classList.add('active');
  const btn = document.querySelector('.nav-link[data-page="' + name + '"]');
  if (btn) { btn.classList.add('active'); btn.setAttribute('aria-current', 'page'); }
}
// ── Auth flows ────────────────────────────────────────────────────────────────

function signalClass(s) {
  if (s === null || s === undefined || s === '') return 'signal-hold';
  const m = s.toLowerCase().replace(/_/g, '-');
  return 'signal-' + m;
}
function signalLabel(s) {
  if (s === null || s === undefined || s === '') return 'Hold';
  const words = s.replace(/_/g, ' ').split(' ');
  return words.map(function(w) { return w.charAt(0).toUpperCase() + w.slice(1); }).join(' ');
}
function velArrow(v) {
  if (v === null || v === undefined) return '';
  if (v > 0.1) return '<span class="velocity up" aria-label="rising">&#8593;</span>';
  if (v < -0.1) return '<span class="velocity down" aria-label="falling">&#8595;</span>';
  return '<span class="velocity flat" aria-label="stable">&#8594;</span>';
}
function statusBadge(s) {
  return '<span class="badge badge-status-' + (s||'unknown').toLowerCase() + '">' + (s||'unknown') + '</span>';
}
function catBadge(c) {
  return '<span class="badge badge-cat">' + (c||'') + '</span>';
}
function scoreBar(score) {
  const pct = Math.round((score||0) * 100);
  const cls = pct >= 80 ? 'high' : pct >= 50 ? 'mid' : 'low';
  return '<div class="score-bar" title="Score: ' + pct + '%"><div class="score-fill score-fill-' + cls + '" style="width:' + pct + '%"></div></div>';
}

function setHTML(id, html) { const el = document.getElementById(id); if (el) el.innerHTML = html; }
function showError(id, msg) {
  const el = document.getElementById(id);
  if (el) { el.textContent = msg; el.style.display = 'block'; }
}
function clearError(id) {
  const el = document.getElementById(id);
  if (el) { el.textContent = ''; el.style.display = ''; }
}
function loading(id) { setHTML(id, '<div class="loading"><span class="spinner"></span> Loading...</div>'); }
function emptyState(id, msg) { setHTML(id, '<div class="empty-state">' + (msg||'No data available.') + '</div>'); }
function errorState(id, msg) { setHTML(id, '<div class="error-state"><span class="error-icon">!</span> ' + (msg||'Failed to load.') + '</div>'); }
function upgradePrompt(id, feature) {
  setHTML(id, '<div class="upgrade-prompt"><p>' + feature + ' requires a Pro plan.</p><button class="btn-primary" onclick="showPage(&apos;billing&apos;)">Upgrade</button></div>');
}

async function doLogin(e) {
  e.preventDefault();
  clearError('login-error');
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  const btn = document.getElementById('login-btn');
  btn.disabled = true; btn.textContent = 'Signing in...';
  try {
    // JWT passthrough for dev
    if (password.startsWith('ey') && password.split('.').length === 3) {
      const resp = await fetch(API + '/v1/stats', {
        headers: { Authorization: 'Bearer ' + password }
      });
      if (resp.ok) {
        setToken(password);
        setTenant({ username: email, plan: 'dev', entitlements: ['trendscope:basic','trendscope:full','trendscope:enterprise'] });
        enterDashboard();
        return;
      }
    }
    const zuul = window.ZUULTIMATE_URL || 'http://localhost:8000';
    const resp = await fetch(zuul + '/v1/identity/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    if (resp.ok === false) {
      const data = await resp.json().catch(function() { return {}; });
      showError('login-error', data.detail || 'Login failed');
      return;
    }
    const data = await resp.json();
    setToken(data.access_token);
    const validate = await fetch(API + '/v1/stats', {
      headers: { Authorization: 'Bearer ' + data.access_token }
    });
    if (validate.ok === false) { showError('login-error', 'Account lacks Trendscope access'); return; }
    const tenantResp = await fetch(zuul + '/v1/identity/auth/validate', {
      headers: { Authorization: 'Bearer ' + data.access_token }
    });
    if (tenantResp.ok) setTenant(await tenantResp.json());
    enterDashboard();
  } catch (err) {
    showError('login-error', err.message || 'Network error');
  } finally {
    btn.disabled = false; btn.textContent = 'Sign In';
  }
}

async function doRegister(e) {
  e.preventDefault();
  clearError('register-error');
  const name = document.getElementById('reg-name').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  const btn = document.getElementById('register-btn');
  btn.disabled = true; btn.textContent = 'Creating account...';
  try {
    const zuul = window.ZUULTIMATE_URL || 'http://localhost:8000';
    const resp = await fetch(zuul + '/v1/identity/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: name, email, password })
    });
    if (resp.ok === false) {
      const data = await resp.json().catch(function() { return {}; });
      showError('register-error', data.detail || 'Registration failed');
      return;
    }
    // Auto-login
    const loginResp = await fetch(zuul + '/v1/identity/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    if (loginResp.ok) {
      const loginData = await loginResp.json();
      setToken(loginData.access_token);
      const tenantResp = await fetch(zuul + '/v1/identity/auth/validate', {
        headers: { Authorization: 'Bearer ' + loginData.access_token }
      });
      if (tenantResp.ok) setTenant(await tenantResp.json());
    }
    enterDashboard();
  } catch (err) {
    showError('register-error', err.message || 'Network error');
  } finally {
    btn.disabled = false; btn.textContent = 'Create Account';
  }
}

function enterDashboard() {
  showView('dashboard');
  const tenant = getTenant();
  const plan = (tenant && tenant.plan) ? tenant.plan : 'starter';
  const el = document.getElementById('plan-badge');
  if (el) el.textContent = plan.charAt(0).toUpperCase() + plan.slice(1);
  const user = document.getElementById('header-user');
  if (user) user.textContent = (tenant && tenant.username) ? tenant.username : (tenant && tenant.email) ? tenant.email : '';
  showPage('trends');
  loadTrends();
}

function doLogout() {
  clearAuth();
  showView('login');
  document.getElementById('login-email').value = '';
  document.getElementById('login-password').value = '';
}
// ── Trends page ───────────────────────────────────────────────────────────────

let allTrends = [];

async function loadTrends() {
  loading('trends-stats');
  loading('trends-list');
  try {
    const [trendsData, statsData] = await Promise.all([
      apiGet('/v1/trends?limit=100'),
      apiGet('/v1/stats')
    ]);
    allTrends = trendsData.trends || trendsData || [];
    renderTrendStats(statsData);
    filterTrends();
  } catch (err) {
    errorState('trends-list', err.message);
    setHTML('trends-stats', '');
  }
}

function renderTrendStats(stats) {
  const db = stats.database || {};
  const total = db.total_trends || 0;
  const cats = db.categories || {};
  const catCount = Object.keys(cats).length;
  const analysis = stats.analysis || {};
  const signals = analysis.signals || {};
  const strongBuy = signals.strong_buy || 0;
  setHTML('trends-stats', [
    '<div class="stat-card"><div class="stat-val">' + total + '</div><div class="stat-label">Total Trends</div></div>',
    '<div class="stat-card"><div class="stat-val">' + catCount + '</div><div class="stat-label">Categories</div></div>',
    '<div class="stat-card"><div class="stat-val">' + strongBuy + '</div><div class="stat-label">Strong Buy</div></div>'
  ].join(''));
}

function renderTrends(trends) {
  if (!trends.length) { emptyState('trends-list', 'No trends match your filters.'); return; }
  setHTML('trends-list', trends.map(t => {
    const pct = Math.round((t.score || 0) * 100);
    return '<div class="trend-card">' +
      '<div class="trend-card-header">' +
        '<span class="trend-name">' + escapeHtml(t.name) + '</span>' +
        '<span class="' + signalClass(t.signal) + ' badge">' + signalLabel(t.signal) + '</span>' +
      '</div>' +
      '<p class="trend-desc">' + escapeHtml(t.description || '') + '</p>' +
      '<div class="trend-meta">' +
        statusBadge(t.status) + ' ' + catBadge(t.category) +
        ' <span class="trend-score">Score: ' + pct + '%</span>' +
        ' ' + velArrow(t.velocity) +
      '</div>' +
      scoreBar(t.score) +
    '</div>';
  }).join(''));
}

function filterTrends() {
  const q = (document.getElementById('trend-search').value || '').toLowerCase();
  const cat = document.getElementById('category-filter').value;
  const sort = document.getElementById('sort-filter').value;
  let filtered = allTrends.slice();
  if (q) filtered = filtered.filter(t =>
    (t.name||'').toLowerCase().includes(q) ||
    (t.description||'').toLowerCase().includes(q) ||
    (t.keywords||[]).some(k => k.toLowerCase().includes(q))
  );
  if (cat) filtered = filtered.filter(t => t.category === cat);
  if (sort === 'velocity') filtered.sort((a,b) => (b.velocity||0) - (a.velocity||0));
  else if (sort === 'status') filtered.sort((a,b) => (a.status||'').localeCompare(b.status||''));
  else filtered.sort((a,b) => (b.score||0) - (a.score||0));
  renderTrends(filtered);
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(String(str)));
  return div.innerHTML;
}
// ── Opportunities page ────────────────────────────────────────────────────────

async function loadOpportunities() {
  loading('opportunities-list');
  if (!hasFull()) { upgradePrompt('opportunities-list', 'Opportunities'); return; }
  try {
    const data = await apiGet('/v1/opportunities');
    const items = data.opportunities || data || [];
    if (!items.length) { emptyState('opportunities-list', 'No opportunities detected.'); return; }
    setHTML('opportunities-list', items.map(o => {
      const score = Math.round((o.opportunity_score || o.score || 0) * 100);
      return '<div class="opportunity-card">' +
        '<div class="opportunity-header">' +
          '<span class="opportunity-name">' + escapeHtml(o.name || o.trend_name || '') + '</span>' +
          '<span class="opportunity-score">' + score + '%</span>' +
        '</div>' +
        '<p class="opportunity-why">' + escapeHtml(o.rationale || o.description || '') + '</p>' +
        '<div class="opportunity-meta">' +
          '<span class="badge badge-urgency-' + (o.urgency || 'medium').toLowerCase() + '">' + (o.urgency || 'Medium') + '</span>' +
          ' <span class="opp-cat">' + escapeHtml(o.category || '') + '</span>' +
        '</div>' +
      '</div>';
    }).join(''));
  } catch (err) {
    errorState('opportunities-list', err.message);
  }
}

// ── Intelligence page ──────────────────────────────────────────────────────────

async function loadIntelligence() {
  loading('intelligence-content');
  if (!hasFull()) { upgradePrompt('intelligence-content', 'Intelligence Report'); return; }
  try {
    const [intel, signals] = await Promise.allSettled([
      apiGet('/v1/intelligence'),
      apiGet('/v1/signals')
    ]);
    const intelData = intel.status === 'fulfilled' ? intel.value : null;
    const signalsData = signals.status === 'fulfilled' ? signals.value : null;

    let html = '';

    if (intelData) {
      html += '<section class="intel-section">';
      html += '<h3 class="intel-title">Market Summary</h3>';
      html += '<p class="intel-body">' + escapeHtml(intelData.summary || intelData.narrative || 'No summary available.') + '</p>';
      if (intelData.top_categories && intelData.top_categories.length) {
        html += '<div class="intel-tags">' + intelData.top_categories.map(c =>
          '<span class="badge badge-cat">' + escapeHtml(c) + '</span>'
        ).join(' ') + '</div>';
      }
      html += '</section>';
    }

    if (signalsData) {
      const sigs = signalsData.signals || signalsData || [];
      if (sigs.length) {
        html += '<section class="intel-section">';
        html += '<h3 class="intel-title">Active Signals</h3>';
        html += '<div class="signal-grid">' + sigs.slice(0,12).map(s => {
          return '<div class="signal-card ' + signalClass(s.signal) + '">' +
            '<div class="signal-name">' + escapeHtml(s.name || s.trend_name || '') + '</div>' +
            '<div class="signal-badge">' + signalLabel(s.signal) + '</div>' +
            '<div class="signal-score">' + Math.round((s.score||0)*100) + '%</div>' +
          '</div>';
        }).join('') + '</div>';
        html += '</section>';
      }
    }

    if (!html) html = '<div class="empty-state">No intelligence data available.</div>';
    setHTML('intelligence-content', html);
  } catch (err) {
    errorState('intelligence-content', err.message);
  }
}
// ── Drift Alerts page ─────────────────────────────────────────────────────────

async function loadDrift() {
  if (!hasFull()) {
    upgradePrompt('subtab-drifts', 'Drift Alerts');
    upgradePrompt('subtab-anomalies', 'Anomaly Detection');
    upgradePrompt('subtab-alert-rules', 'Alert Rules');
    return;
  }
  loadDriftTab('drifts');
}

async function loadDriftTab(tab) {
  if (tab === 'drifts') {
    loading('subtab-drifts');
    try {
      const data = await apiGet('/v1/drifts');
      const items = data.drifts || data || [];
      if (!items.length) { emptyState('subtab-drifts', 'No drift events detected.'); return; }
      setHTML('subtab-drifts', items.map(d => {
        return '<div class="drift-card">' +
          '<div class="drift-header">' +
            '<span class="drift-name">' + escapeHtml(d.trend_name || d.name || '') + '</span>' +
            '<span class="badge badge-status-' + (d.direction||'unknown').toLowerCase() + '">' + (d.direction||'drift') + '</span>' +
          '</div>' +
          '<div class="drift-meta">' +
            '<span>Magnitude: ' + ((d.magnitude||0)*100).toFixed(1) + '%</span>' +
            (d.detected_at ? ' <span class="drift-date">' + new Date(d.detected_at).toLocaleDateString() + '</span>' : '') +
          '</div>' +
          (d.description ? '<p class="drift-desc">' + escapeHtml(d.description) + '</p>' : '') +
        '</div>';
      }).join(''));
    } catch (err) {
      errorState('subtab-drifts', err.message);
    }
  } else if (tab === 'anomalies') {
    loading('subtab-anomalies');
    try {
      const data = await apiGet('/v1/anomalies');
      const items = data.anomalies || [];
      if (!items.length) { emptyState('subtab-anomalies', 'No anomalies detected.'); return; }
      setHTML('subtab-anomalies', items.map(a => {
        return '<div class="anomaly-card">' +
          '<div class="anomaly-header">' +
            '<span class="anomaly-name">' + escapeHtml(a.trend_name || '') + '</span>' +
            '<span class="badge badge-urgency-' + (a.severity||'low').toLowerCase() + '">' + (a.severity||'low') + '</span>' +
          '</div>' +
          '<div class="anomaly-meta">' +
            escapeHtml(a.anomaly_type || '') +
            ' | Value: ' + (a.value||0).toFixed(2) +
            ' | Deviation: ' + (a.deviation||0).toFixed(2) + 'σ' +
          '</div>' +
        '</div>';
      }).join(''));
    } catch (err) {
      errorState('subtab-anomalies', err.message);
    }
  } else if (tab === 'alert-rules') {
    loadAlertRules();
  }
}

// ── Alert Rules ──────────────────────────────────────────────────────────────

async function loadAlertRules() {
  loading('subtab-alert-rules');
  try {
    const data = await apiGet('/v1/alerts');
    const rules = data.rules || [];
    let html = '<div class="alert-rules-header"><h4>Alert Rules</h4></div>';
    html += '<div class="alert-rules-form">';
    html += '<h4>Create Alert Rule</h4>';
    html += '<input type="text" id="alert-name" class="input" placeholder="Rule name" />';
    html += '<input type="url" id="alert-webhook" class="input" placeholder="Webhook URL (https://...)" />';
    html += '<input type="text" id="alert-secret" class="input" placeholder="Webhook secret (optional)" />';
    html += '<div class="alert-conditions">';
    html += '<label>Conditions:</label>';
    html += '<div><label><input type="checkbox" id="cond-strong-buy" /> Strong Buy signal</label></div>';
    html += '<div><label><input type="checkbox" id="cond-high-drift" /> High drift detected</label></div>';
    html += '</div>';
    html += '<button class="btn-primary btn-sm" onclick="createAlertRule()">Create Rule</button>';
    html += '<div id="alert-form-error" class="form-error"></div>';
    html += '</div>';
    if (rules.length) {
      html += '<div class="alert-rules-list">';
      html += rules.map(r => {
        return '<div class="alert-rule-card">' +
          '<div class="alert-rule-header">' +
            '<span class="alert-rule-name">' + escapeHtml(r.name) + '</span>' +
            '<span class="badge ' + (r.active ? 'badge-status-growing' : 'badge-status-declining') + '">' + (r.active ? 'active' : 'paused') + '</span>' +
          '</div>' +
          '<div class="alert-rule-meta">' + escapeHtml(r.webhook_url||'') + '</div>' +
          '<button class="btn-secondary btn-xs" onclick="deleteAlertRule(' + "'" + r.id + "'" + ')">Delete</button>' +
        '</div>';
      }).join('');
      html += '</div>';
    } else {
      html += '<div class="empty-state">No alert rules configured.</div>';
    }
    setHTML('subtab-alert-rules', html);
  } catch (err) {
    errorState('subtab-alert-rules', err.message);
  }
}

async function createAlertRule() {
  const name = (document.getElementById('alert-name')||{}).value || '';
  const webhook = (document.getElementById('alert-webhook')||{}).value || '';
  const secret = (document.getElementById('alert-secret')||{}).value || '';
  const condStrongBuy = (document.getElementById('cond-strong-buy')||{}).checked;
  const condHighDrift = (document.getElementById('cond-high-drift')||{}).checked;
  if (!name || !webhook) {
    showError('alert-form-error', 'Name and webhook URL are required.');
    return;
  }
  const conditions = {};
  if (condStrongBuy) conditions.signal = 'strong_buy';
  if (condHighDrift) conditions.drift_magnitude_min = 0.5;
  try {
    await apiPost('/v1/alerts', { name, webhook_url: webhook, webhook_secret: secret, conditions });
    loadAlertRules();
  } catch (err) {
    showError('alert-form-error', err.message);
  }
}

async function deleteAlertRule(id) {
  if (!confirm('Delete this alert rule?')) return;
  try {
    await apiDelete('/v1/alerts/' + id);
    loadAlertRules();
  } catch (err) {
    alert('Failed to delete: ' + err.message);
  }
}
// ── Settings page ─────────────────────────────────────────────────────────────

async function loadSettings() {
  const container = document.getElementById('settings-content');
  if (!container) return;
  const tenant = getTenant();
  const token = getToken();
  let html = '<div class="settings-section">';
  html += '<h3>Account</h3>';
  html += '<div class="settings-field"><label>Username</label><span>' + escapeHtml((tenant && tenant.username) || 'Unknown') + '</span></div>';
  html += '<div class="settings-field"><label>Email</label><span>' + escapeHtml((tenant && tenant.email) || '') + '</span></div>';
  html += '<div class="settings-field"><label>Plan</label><span class="plan-badge">' + escapeHtml((tenant && tenant.plan) || 'starter') + '</span></div>';
  html += '</div>';

  html += '<div class="settings-section">';
  html += '<h3>API Token</h3>';
  html += '<div class="settings-field token-field">';
  html += '<input type="password" id="token-input" class="input input-mono" value="' + escapeHtml(token||'') + '" readonly />';
  html += '<button class="btn-secondary btn-sm" onclick="toggleTokenVisibility()">Show</button>';
  html += '<button class="btn-secondary btn-sm" onclick="copyToken()">Copy</button>';
  html += '</div>';
  html += '<p class="settings-hint">Use this Bearer token with the TrendScope API.</p>';
  html += '</div>';

  if (hasFull()) {
    html += '<div class="settings-section">';
    html += '<h3>Data</h3>';
    html += '<button class="btn-secondary" onclick="refreshData()">Refresh Trends Data</button>';
    html += '<div id="refresh-status" class="settings-hint"></div>';
    html += '</div>';
  }

  html += '<div class="settings-section">';
  html += '<h3>Entitlements</h3>';
  const ents = (tenant && tenant.entitlements) || [];
  if (ents.length) {
    html += '<div class="entitlements-list">' + ents.map(e =>
      '<span class="badge badge-status-growing">' + escapeHtml(e) + '</span>'
    ).join(' ') + '</div>';
  } else {
    html += '<p class="settings-hint">No entitlements found.</p>';
  }
  html += '</div>';

  container.innerHTML = html;
}

function toggleTokenVisibility() {
  const input = document.getElementById('token-input');
  if (!input) return;
  input.type = input.type === 'password' ? 'text' : 'password';
  const btn = input.nextElementSibling;
  if (btn) btn.textContent = input.type === 'password' ? 'Show' : 'Hide';
}

function copyToken() {
  const input = document.getElementById('token-input');
  if (!input) return;
  navigator.clipboard.writeText(input.value).then(() => {
    const btn = input.nextElementSibling.nextElementSibling;
    if (btn) { btn.textContent = 'Copied!'; setTimeout(() => { btn.textContent = 'Copy'; }, 1500); }
  }).catch(() => {
    input.select();
    document.execCommand('copy');
  });
}

async function refreshData() {
  const status = document.getElementById('refresh-status');
  if (status) status.textContent = 'Refreshing...';
  try {
    const data = await apiPost('/v1/refresh', {});
    if (status) status.textContent = 'Refreshed: ' + (data.new_trends || 0) + ' new trends.';
    loadTrends();
  } catch (err) {
    if (status) status.textContent = 'Failed: ' + err.message;
  }
}

// ── Billing page ───────────────────────────────────────────────────────────────

function loadBilling() {
  const container = document.getElementById('billing-content');
  if (!container) return;
  const tenant = getTenant();
  const currentPlan = (tenant && tenant.plan) ? tenant.plan.toLowerCase() : 'starter';

  const plans = [
    {
      id: 'free',
      name: 'Free',
      price: '$0',
      features: [
        'Trend browsing (up to 50)',
        'Basic search & filters',
        'Stats overview',
        'API access (trendscope:basic)'
      ],
      cta: 'Current Plan',
      ctaDisabled: currentPlan === 'starter' || currentPlan === 'free'
    },
    {
      id: 'pro',
      name: 'Pro',
      price: '$19 / month',
      standardPrice: '$29',
      founderBadge: true,
      features: [
        'Everything in Free',
        'Opportunities detection',
        'Intelligence reports',
        'Drift & anomaly alerts',
        'Alert rule webhooks',
        'API access (trendscope:full)'
      ],
      cta: currentPlan === 'pro' ? 'Current Plan' : 'Upgrade to Pro',
      ctaDisabled: currentPlan === 'pro',
      highlight: true
    }
  ];

  let html = '<div class="billing-plans">';
  html += plans.map(p => {
    return '<div class="plan-card' + (p.highlight ? ' plan-card-highlight' : '') + (currentPlan === p.id ? ' plan-card-current' : '') + '">' +
      (p.founderBadge ? '<div class="plan-founder-badge">30% off \u2014 Founder Rate</div>' : '') +
      '<div class="plan-name">' + p.name + '</div>' +
      '<div class="plan-price">' + p.price + (p.standardPrice ? ' <span class="plan-strike">' + p.standardPrice + '</span>' : '') + '</div>' +
      '<ul class="plan-features">' +
        p.features.map(f => '<li>' + escapeHtml(f) + '</li>').join('') +
      '</ul>' +
      '<button class="btn-primary plan-btn" ' + (p.ctaDisabled ? 'disabled' : '') + ' onclick="handlePlanCta(\'' + p.id + '\')">' +
        p.cta +
      '</button>' +
      (p.founderBadge ? '<p class="plan-lock-note">Founder pricing locks in for life.</p>' : '') +
    '</div>';
  }).join('');
  html += '</div>';
  html += '<p class="billing-note">Payments processed via Stripe. Need help? Email <a href="mailto:billing@gozerai.com">billing@gozerai.com</a>.</p>';
  container.innerHTML = html;
}

function handlePlanCta(planId) {
  if (planId === 'free' || planId === 'starter') return;
  window.open('https://gozerai.com/pricing', '_blank');
}
// ── Sub-tab switcher ──────────────────────────────────────────────────────────

function switchSubTab(tabName) {
  document.querySelectorAll('#page-drift .sub-tab').forEach(t => {
    t.classList.remove('active');
    t.setAttribute('aria-selected', 'false');
  });
  document.querySelectorAll('#page-drift .sub-panel').forEach(p => p.classList.remove('active'));
  const activeTab = document.querySelector('#page-drift .sub-tab[data-subtab="' + tabName + '"]');
  if (activeTab) { activeTab.classList.add('active'); activeTab.setAttribute('aria-selected', 'true'); }
  const activePanel = document.getElementById('subtab-' + tabName);
  if (activePanel) activePanel.classList.add('active');
  loadDriftTab(tabName);
}

// ── Page load dispatcher ───────────────────────────────────────────────────────

function onPageChange(name) {
  switch (name) {
    case 'trends': loadTrends(); break;
    case 'opportunities': loadOpportunities(); break;
    case 'intelligence': loadIntelligence(); break;
    case 'drift': loadDrift(); break;
    case 'settings': loadSettings(); break;
    case 'billing': loadBilling(); break;
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────

function init() {
  // Auth links
  document.getElementById('show-register').addEventListener('click', e => {
    e.preventDefault(); clearError('login-error'); showView('register');
  });
  document.getElementById('show-login').addEventListener('click', e => {
    e.preventDefault(); clearError('register-error'); showView('login');
  });

  // Forms
  document.getElementById('login-form').addEventListener('submit', doLogin);
  document.getElementById('register-form').addEventListener('submit', doRegister);
  document.getElementById('logout-btn').addEventListener('click', doLogout);

  // Nav
  document.querySelectorAll('.nav-link').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      const page = btn.getAttribute('data-page');
      showPage(page);
      onPageChange(page);
    });
  });

  // Trend filters
  const searchEl = document.getElementById('trend-search');
  if (searchEl) searchEl.addEventListener('input', filterTrends);
  const catEl = document.getElementById('category-filter');
  if (catEl) catEl.addEventListener('change', filterTrends);
  const sortEl = document.getElementById('sort-filter');
  if (sortEl) sortEl.addEventListener('change', filterTrends);
  const refreshBtn = document.getElementById('refresh-btn');
  if (refreshBtn) refreshBtn.addEventListener('click', loadTrends);

  // Sub-tabs for drift page
  document.querySelectorAll('#page-drift .sub-tab').forEach(tab => {
    tab.addEventListener('click', () => switchSubTab(tab.getAttribute('data-subtab')));
  });

  // Check existing session
  if (getToken()) {
    enterDashboard();
  } else {
    showView('login');
  }
}

document.addEventListener('DOMContentLoaded', init);
