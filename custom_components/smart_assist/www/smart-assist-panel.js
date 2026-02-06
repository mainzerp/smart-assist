/**
 * Smart Assist Dashboard Panel
 *
 * Vanilla Web Component for Home Assistant sidebar.
 * Two tabs: Overview (metrics, tokens, cache, tools) and Memory (user browser).
 */

class SmartAssistPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._selectedAgent = null;
    this._activeTab = "overview";
    this._loading = true;
    this._error = null;
    this._memoryExpanded = null;
    this._memoryDetails = null;
    this._unsub = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._fetchData();
      this._subscribe();
    }
  }

  set narrow(val) { this._narrow = val; this._render(); }
  set panel(val) { this._panel = val; }
  set route(val) { this._route = val; }

  connectedCallback() { this._render(); }

  disconnectedCallback() {
    if (this._unsub) {
      try { this._unsub(); } catch (_) {}
      this._unsub = null;
    }
  }

  async _fetchData() {
    this._loading = true;
    this._error = null;
    this._render();
    try {
      const result = await this._hass.callWS({ type: "smart_assist/dashboard_data" });
      this._data = result;
      if (!this._selectedAgent && result.agents) {
        const ids = Object.keys(result.agents);
        if (ids.length > 0) this._selectedAgent = ids[0];
      }
    } catch (err) {
      this._error = err.message || "Failed to load dashboard data";
    }
    this._loading = false;
    this._render();
  }

  async _subscribe() {
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (data) => { this._data = data; this._render(); },
        { type: "smart_assist/subscribe" }
      );
    } catch (err) {
      console.warn("Smart Assist: Could not subscribe to updates:", err);
    }
  }

  async _toggleMemory(userId) {
    if (this._memoryExpanded === userId) {
      this._memoryExpanded = null;
      this._render();
      return;
    }
    try {
      const details = await this._hass.callWS({
        type: "smart_assist/memory_details",
        user_id: userId,
      });
      this._memoryDetails = details;
      this._memoryExpanded = userId;
    } catch (err) {
      console.error("Failed to load memory details:", err);
    }
    this._render();
  }

  _fmt(num) {
    if (num === undefined || num === null) return "0";
    if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
    if (num >= 1000) return (num / 1000).toFixed(1) + "K";
    return Math.round(num).toString();
  }

  _successColor(rate) {
    if (rate >= 95) return "success";
    if (rate >= 90) return "warning";
    return "error";
  }

  _cacheColor(rate) {
    if (rate >= 80) return "success";
    if (rate >= 50) return "warning";
    return "error";
  }

  _esc(str) {
    if (!str) return "";
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }

  _getAggregateMetrics() {
    if (!this._data || !this._data.agents) return null;
    const agents = Object.values(this._data.agents);
    if (agents.length === 0) return null;
    const agg = {
      total_requests: 0, successful_requests: 0, failed_requests: 0,
      total_prompt_tokens: 0, total_completion_tokens: 0,
      cache_hits: 0, cache_misses: 0, cached_tokens: 0,
      empty_responses: 0, stream_timeouts: 0, total_retries: 0,
    };
    let totalRT = 0;
    for (const a of agents) {
      const m = a.metrics || {};
      agg.total_requests += m.total_requests || 0;
      agg.successful_requests += m.successful_requests || 0;
      agg.failed_requests += m.failed_requests || 0;
      agg.total_prompt_tokens += m.total_prompt_tokens || 0;
      agg.total_completion_tokens += m.total_completion_tokens || 0;
      agg.cache_hits += m.cache_hits || 0;
      agg.cache_misses += m.cache_misses || 0;
      agg.cached_tokens += m.cached_tokens || 0;
      agg.empty_responses += m.empty_responses || 0;
      agg.stream_timeouts += m.stream_timeouts || 0;
      agg.total_retries += m.total_retries || 0;
      totalRT += (m.average_response_time_ms || 0) * (m.successful_requests || 0);
    }
    agg.success_rate = agg.total_requests > 0
      ? (agg.successful_requests / agg.total_requests) * 100 : 100;
    agg.average_response_time_ms = agg.successful_requests > 0
      ? totalRT / agg.successful_requests : 0;
    agg.cache_hit_rate = (agg.cache_hits + agg.cache_misses) > 0
      ? (agg.cache_hits / (agg.cache_hits + agg.cache_misses)) * 100 : 0;
    return agg;
  }

  _render() {
    if (!this.shadowRoot) return;
    let content = "";
    if (this._loading) {
      content = '<div class="loading">Loading Smart Assist Dashboard...</div>';
    } else if (this._error) {
      content = '<div class="error-msg">' + this._esc(this._error) + '<br><br><button class="refresh-btn" id="retry-btn">Retry</button></div>';
    } else if (!this._data) {
      content = '<div class="loading">No data available</div>';
    } else {
      content = this._renderDashboard();
    }
    this.shadowRoot.innerHTML = "<style>" + this._getStyles() + "</style>" + content;
    this._attachEvents();
  }

  _renderDashboard() {
    const agents = this._data.agents || {};
    const agentIds = Object.keys(agents);

    // Header
    let html = '<div class="header"><h1>Smart Assist</h1><div class="header-actions"><button class="refresh-btn" id="refresh-btn">Refresh</button></div></div>';

    // Agent selector (if multiple)
    if (agentIds.length > 1) {
      html += '<div class="agent-selector">';
      for (const id of agentIds) {
        const active = this._selectedAgent === id ? "active" : "";
        html += '<button class="agent-tab ' + active + '" data-agent="' + this._esc(id) + '">' + this._esc(agents[id].name) + '</button>';
      }
      html += '</div>';
    }

    // Tab bar
    html += '<div class="tab-bar">'
      + '<button class="tab-btn ' + (this._activeTab === "overview" ? "active" : "") + '" data-tab="overview">Overview</button>'
      + '<button class="tab-btn ' + (this._activeTab === "memory" ? "active" : "") + '" data-tab="memory">Memory</button>'
      + '<button class="tab-btn ' + (this._activeTab === "calendar" ? "active" : "") + '" data-tab="calendar">Calendar</button>'
      + '</div>';

    // Tab content
    if (this._activeTab === "overview") {
      html += this._renderOverviewTab(agents);
    } else if (this._activeTab === "memory") {
      html += this._renderMemoryTab();
    } else if (this._activeTab === "calendar") {
      html += this._renderCalendarTab();
    }

    return html;
  }

  _renderOverviewTab(agents) {
    const agent = this._selectedAgent ? agents[this._selectedAgent] : null;
    const metrics = agent ? (agent.metrics || {}) : this._getAggregateMetrics();
    let html = "";

    // Overview cards
    if (metrics) {
      const sr = metrics.success_rate ?? 100;
      const chr = metrics.cache_hit_rate ?? 0;
      const totalTokens = (metrics.total_prompt_tokens || 0) + (metrics.total_completion_tokens || 0);
      html += '<div class="overview-grid">'
        + '<div class="metric-card"><div class="label">Total Requests</div><div class="value">' + this._fmt(metrics.total_requests || 0) + '</div><div class="sub">' + (metrics.failed_requests || 0) + ' failed</div></div>'
        + '<div class="metric-card"><div class="label">Success Rate</div><div class="value ' + this._successColor(sr) + '">' + sr.toFixed(1) + '%</div><div class="sub">' + (metrics.total_retries || 0) + ' retries</div></div>'
        + '<div class="metric-card"><div class="label">Avg Response</div><div class="value">' + Math.round(metrics.average_response_time_ms || 0) + '</div><div class="sub">milliseconds</div></div>'
        + '<div class="metric-card"><div class="label">Total Tokens</div><div class="value">' + this._fmt(totalTokens) + '</div><div class="sub">' + this._fmt(metrics.total_prompt_tokens || 0) + ' prompt / ' + this._fmt(metrics.total_completion_tokens || 0) + ' completion</div></div>'
        + '<div class="metric-card"><div class="label">Cache Hit Rate</div><div class="value ' + this._cacheColor(chr) + '">' + chr.toFixed(1) + '%</div><div class="sub">' + this._fmt(metrics.cached_tokens || 0) + ' tokens cached</div></div>'
        + '</div>';
    }

    // Content grid
    html += '<div class="content-grid">';
    html += this._renderTokenCard(metrics);
    html += this._renderCacheCard(metrics, agent);
    html += this._renderToolsCard(agent);
    html += '</div>';

    return html;
  }

  _renderMemoryTab() {
    const memory = this._data ? this._data.memory : null;
    if (!memory) return '<div class="loading">No memory data available</div>';

    const users = memory.users || {};
    const userIds = Object.keys(users);

    // Summary cards
    let html = '<div class="overview-grid">'
      + '<div class="metric-card"><div class="label">Total Users</div><div class="value">' + (memory.total_users || 0) + '</div></div>'
      + '<div class="metric-card"><div class="label">Total Memories</div><div class="value">' + (memory.total_memories || 0) + '</div></div>'
      + '<div class="metric-card"><div class="label">Global Memories</div><div class="value">' + (memory.global_memories || 0) + '</div></div>'
      + '</div>';

    // User table
    if (userIds.length > 0) {
      let rows = "";
      for (const uid of userIds) {
        const u = users[uid];
        const cats = u.categories || {};
        const catTags = Object.entries(cats).map(function(e) {
          return '<span class="memory-category ' + e[0] + '">' + e[0] + ': ' + e[1] + '</span>';
        }).join(" ");
        rows += '<tr class="memory-user-row" data-user="' + this._esc(uid) + '">'
          + '<td><strong>' + this._esc(u.display_name || uid) + '</strong></td>'
          + '<td>' + (u.memory_count || 0) + '</td>'
          + '<td>' + (catTags || '-') + '</td>'
          + '<td style="font-size:12px;color:var(--sa-text-secondary);">' + (u.first_interaction ? new Date(u.first_interaction).toLocaleDateString() : '-') + '</td>'
          + '</tr>';
        if (this._memoryExpanded === uid) {
          rows += '<tr><td colspan="4" style="padding:0;">' + this._renderMemoryDetails() + '</td></tr>';
        }
      }
      html += '<div class="card"><h3>User Profiles</h3>'
        + '<table><thead><tr><th>User</th><th>Memories</th><th>Categories</th><th>First Seen</th></tr></thead>'
        + '<tbody>' + rows + '</tbody></table></div>';
    } else {
      html += '<div class="card"><h3>User Profiles</h3><div style="color:var(--sa-text-secondary);font-size:14px;padding:20px 0;">No user profiles yet. Memories will appear here once users interact with the assistant.</div></div>';
    }

    return html;
  }

  _renderCalendarTab() {
    const cal = this._data ? this._data.calendar : null;
    if (!cal || !cal.enabled) {
      return '<div class="loading">Calendar context is disabled. Enable it in the agent configuration to see upcoming events.</div>';
    }

    const events = cal.events || [];
    const calendars = cal.calendars || 0;

    // Count by status
    let pending = 0, announced = 0, passed = 0;
    for (const e of events) {
      if (e.status === "pending") pending++;
      else if (e.status === "announced") announced++;
      else if (e.status === "passed") passed++;
    }

    // Summary cards
    let html = '<div class="overview-grid">'
      + '<div class="metric-card"><div class="label">Upcoming Events</div><div class="value">' + events.length + '</div><div class="sub">next 28 hours</div></div>'
      + '<div class="metric-card"><div class="label">Calendars</div><div class="value">' + calendars + '</div><div class="sub">entities tracked</div></div>'
      + '<div class="metric-card"><div class="label">Pending</div><div class="value warning">' + pending + '</div><div class="sub">awaiting reminder</div></div>'
      + '<div class="metric-card"><div class="label">Announced</div><div class="value success">' + announced + '</div><div class="sub">reminder delivered</div></div>'
      + '</div>';

    // Events table
    if (events.length > 0) {
      let rows = "";
      for (const ev of events) {
        const startStr = this._fmtEventTime(ev.start);
        const endStr = this._fmtEventTime(ev.end);
        const timeRange = endStr ? (startStr + " - " + endStr) : startStr;
        const statusCls = ev.status || "upcoming";
        const statusLabel = statusCls.charAt(0).toUpperCase() + statusCls.slice(1);
        const loc = ev.location ? '<div style="font-size:11px;color:var(--sa-text-secondary);">' + this._esc(ev.location) + '</div>' : '';
        rows += '<tr>'
          + '<td style="white-space:nowrap;">' + timeRange + '</td>'
          + '<td><strong>' + this._esc(ev.summary) + '</strong>' + loc + '</td>'
          + '<td>' + this._esc(ev.owner) + '</td>'
          + '<td><span class="cal-status ' + statusCls + '">' + statusLabel + '</span></td>'
          + '</tr>';
      }
      html += '<div class="card"><h3>Events (next 28h)</h3>'
        + '<table><thead><tr><th>Time</th><th>Event</th><th>Owner</th><th>Status</th></tr></thead>'
        + '<tbody>' + rows + '</tbody></table></div>';
    } else {
      html += '<div class="card"><h3>Events</h3><div style="color:var(--sa-text-secondary);font-size:14px;padding:20px 0;">No upcoming events in the next 28 hours.</div></div>';
    }

    return html;
  }

  _fmtEventTime(timeStr) {
    if (!timeStr) return "";
    try {
      if (timeStr.indexOf("T") !== -1) {
        const d = new Date(timeStr);
        return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      }
      // All-day event (date only)
      const d = new Date(timeStr + "T00:00:00");
      return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    } catch (_) {
      return timeStr;
    }
  }

  _renderTokenCard(metrics) {
    if (!metrics) return "";
    const prompt = metrics.total_prompt_tokens || 0;
    const completion = metrics.total_completion_tokens || 0;
    const cached = metrics.cached_tokens || 0;
    const total = prompt + completion;
    const maxVal = Math.max(prompt, completion, cached, 1);

    let sub = "";
    if (total > 0) {
      sub = '<div class="sub" style="margin-top:12px;text-align:center;">Cache saved ~' + ((cached / Math.max(prompt, 1)) * 100).toFixed(0) + '% of prompt tokens</div>';
    }

    return '<div class="card"><h3>Token Usage</h3>'
      + '<div class="bar-row"><div class="bar-label">Prompt</div><div class="bar-track"><div class="bar-fill prompt" style="width:' + ((prompt / maxVal) * 100) + '%"></div></div><div class="bar-value">' + this._fmt(prompt) + '</div></div>'
      + '<div class="bar-row"><div class="bar-label">Completion</div><div class="bar-track"><div class="bar-fill completion" style="width:' + ((completion / maxVal) * 100) + '%"></div></div><div class="bar-value">' + this._fmt(completion) + '</div></div>'
      + '<div class="bar-row"><div class="bar-label">Cached</div><div class="bar-track"><div class="bar-fill cached" style="width:' + ((cached / maxVal) * 100) + '%"></div></div><div class="bar-value">' + this._fmt(cached) + '</div></div>'
      + sub + '</div>';
  }

  _renderCacheCard(metrics, agent) {
    if (!metrics) return "";
    const warming = agent ? agent.cache_warming : null;
    const hits = metrics.cache_hits || 0;
    const misses = metrics.cache_misses || 0;
    const rate = (hits + misses) > 0 ? ((hits / (hits + misses)) * 100).toFixed(1) : "0.0";

    let warmingHtml = "";
    if (warming) {
      const statusClass = warming.status || "inactive";
      const statusText = warming.status === "active" ? "Cache Warming Active"
        : warming.status === "warming" ? "Warming..." : "Cache Warming Inactive";
      warmingHtml = '<div class="warming-status ' + statusClass + '"><span>' + statusText + '</span></div>';
      if (warming.last_warmup) {
        warmingHtml += '<div class="warming-detail">Last: ' + new Date(warming.last_warmup).toLocaleString() + ' | Count: ' + (warming.warmup_count || 0) + ' | Failures: ' + (warming.warmup_failures || 0) + '</div>';
      }
    } else {
      warmingHtml = '<div class="warming-status inactive">Cache Warming Disabled</div>';
    }

    let extraHtml = "";
    if (metrics.empty_responses || metrics.stream_timeouts) {
      extraHtml = '<div style="margin-top:12px;font-size:12px;color:var(--sa-text-secondary);">Empty responses: ' + (metrics.empty_responses || 0) + ' | Stream timeouts: ' + (metrics.stream_timeouts || 0) + '</div>';
    }

    return '<div class="card"><h3>Cache Performance</h3>'
      + '<div style="display:flex;justify-content:space-around;margin-bottom:16px;">'
      + '<div style="text-align:center;"><div style="font-size:32px;font-weight:500;color:var(--sa-success);">' + hits + '</div><div style="font-size:12px;color:var(--sa-text-secondary);">Hits</div></div>'
      + '<div style="text-align:center;"><div style="font-size:32px;font-weight:500;color:var(--sa-error);">' + misses + '</div><div style="font-size:12px;color:var(--sa-text-secondary);">Misses</div></div>'
      + '<div style="text-align:center;"><div style="font-size:32px;font-weight:500;color:var(--sa-primary);">' + rate + '%</div><div style="font-size:12px;color:var(--sa-text-secondary);">Hit Rate</div></div>'
      + '</div>' + warmingHtml + extraHtml + '</div>';
  }

  _renderToolsCard(agent) {
    if (!agent || !agent.tools || agent.tools.length === 0) return "";
    let tags = "";
    for (const t of agent.tools) {
      tags += '<span class="tool-tag">' + this._esc(t) + '</span>';
    }
    return '<div class="card"><h3>Registered Tools (' + agent.tools.length + ')</h3><div class="tools-grid">' + tags + '</div></div>';
  }

  _renderMemoryDetails() {
    const details = this._memoryDetails;
    if (!details || !details.memories) return "";
    const memories = details.memories;
    if (memories.length === 0) {
      return '<div class="memory-detail" style="color:var(--sa-text-secondary);">No memories stored.</div>';
    }
    let entries = "";
    const shown = memories.slice(0, 30);
    for (const m of shown) {
      const cat = m.category || "unknown";
      const date = m.created ? new Date(m.created).toLocaleDateString() : "";
      entries += '<div class="memory-entry">'
        + '<span class="memory-category ' + this._esc(cat) + '">' + this._esc(cat) + '</span>'
        + this._esc(m.content || "")
        + '<span style="float:right;font-size:11px;color:var(--sa-text-secondary);">' + date + '</span></div>';
    }
    if (memories.length > 30) {
      entries += '<div style="text-align:center;padding:8px;color:var(--sa-text-secondary);font-size:12px;">... and ' + (memories.length - 30) + ' more</div>';
    }
    return '<div class="memory-detail">' + entries + '</div>';
  }

  _attachEvents() {
    const root = this.shadowRoot;
    if (!root) return;

    const refreshBtn = root.getElementById("refresh-btn");
    if (refreshBtn) refreshBtn.addEventListener("click", () => this._fetchData());

    const retryBtn = root.getElementById("retry-btn");
    if (retryBtn) retryBtn.addEventListener("click", () => this._fetchData());

    root.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._activeTab = btn.dataset.tab;
        this._render();
      });
    });

    root.querySelectorAll(".agent-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._selectedAgent = btn.dataset.agent;
        this._render();
      });
    });

    root.querySelectorAll(".memory-user-row").forEach((row) => {
      row.addEventListener("click", () => {
        this._toggleMemory(row.dataset.user);
      });
    });
  }

  _getStyles() {
    return ":host{"
      + "display:block;padding:16px;"
      + "--sa-card-bg:var(--ha-card-background,var(--card-background-color,#fff));"
      + "--sa-primary:var(--primary-color,#03a9f4);"
      + "--sa-text:var(--primary-text-color,#212121);"
      + "--sa-text-secondary:var(--secondary-text-color,#727272);"
      + "--sa-divider:var(--divider-color,#e0e0e0);"
      + "--sa-success:var(--label-badge-green,#4caf50);"
      + "--sa-warning:var(--label-badge-yellow,#ff9800);"
      + "--sa-error:var(--label-badge-red,#f44336);"
      + "--sa-border-radius:var(--ha-card-border-radius,12px);"
      + "font-family:var(--paper-font-body1_-_font-family,'Roboto',sans-serif);"
      + "color:var(--sa-text);"
      + "background:var(--primary-background-color,#fafafa);"
      + "min-height:100vh;box-sizing:border-box;"
      + "}"
      + ".header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:12px;}"
      + ".header h1{margin:0;font-size:24px;font-weight:400;color:var(--sa-text);}"
      + ".header-actions{display:flex;gap:8px;align-items:center;}"
      // Tab bar
      + ".tab-bar{display:flex;gap:0;margin-bottom:24px;border-bottom:2px solid var(--sa-divider);}"
      + ".tab-btn{padding:10px 20px;border:none;background:none;color:var(--sa-text-secondary);cursor:pointer;font-size:14px;font-weight:500;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all 0.2s;}"
      + ".tab-btn:hover{color:var(--sa-text);}"
      + ".tab-btn.active{color:var(--sa-primary);border-bottom-color:var(--sa-primary);}"
      // Agent selector
      + ".agent-selector{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;}"
      + ".agent-tab{padding:8px 16px;border-radius:20px;border:1px solid var(--sa-divider);background:var(--sa-card-bg);color:var(--sa-text);cursor:pointer;font-size:14px;transition:all 0.2s;}"
      + ".agent-tab:hover{border-color:var(--sa-primary);}"
      + ".agent-tab.active{background:var(--sa-primary);color:#fff;border-color:var(--sa-primary);}"
      // Overview grid
      + ".overview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px;}"
      + ".metric-card{background:var(--sa-card-bg);border-radius:var(--sa-border-radius);padding:20px;box-shadow:var(--ha-card-box-shadow,0 2px 6px rgba(0,0,0,0.1));text-align:center;}"
      + ".metric-card .label{font-size:12px;color:var(--sa-text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;}"
      + ".metric-card .value{font-size:28px;font-weight:500;color:var(--sa-text);}"
      + ".metric-card .value.success{color:var(--sa-success);}"
      + ".metric-card .value.warning{color:var(--sa-warning);}"
      + ".metric-card .value.error{color:var(--sa-error);}"
      + ".metric-card .sub{font-size:11px;color:var(--sa-text-secondary);margin-top:4px;}"
      // Content grid
      + ".content-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;}"
      + ".card{background:var(--sa-card-bg);border-radius:var(--sa-border-radius);padding:20px;box-shadow:var(--ha-card-box-shadow,0 2px 6px rgba(0,0,0,0.1));}"
      + ".card h3{margin:0 0 16px 0;font-size:16px;font-weight:500;color:var(--sa-text);}"
      // Bar chart
      + ".bar-row{display:flex;align-items:center;margin-bottom:8px;gap:8px;}"
      + ".bar-label{font-size:13px;color:var(--sa-text-secondary);min-width:100px;text-align:right;}"
      + ".bar-track{flex:1;height:18px;background:var(--sa-divider);border-radius:9px;overflow:hidden;}"
      + ".bar-fill{height:100%;border-radius:9px;transition:width 0.5s ease;}"
      + ".bar-fill.prompt{background:var(--sa-primary);}"
      + ".bar-fill.completion{background:var(--sa-success);}"
      + ".bar-fill.cached{background:var(--sa-warning);}"
      + ".bar-value{font-size:12px;color:var(--sa-text-secondary);min-width:70px;}"
      // Table
      + "table{width:100%;border-collapse:collapse;font-size:13px;}"
      + "th{text-align:left;padding:8px 12px;color:var(--sa-text-secondary);font-weight:500;border-bottom:2px solid var(--sa-divider);font-size:12px;text-transform:uppercase;letter-spacing:0.3px;}"
      + "td{padding:8px 12px;border-bottom:1px solid var(--sa-divider);color:var(--sa-text);}"
      + "tr:last-child td{border-bottom:none;}"
      // Tools
      + ".tools-grid{display:flex;flex-wrap:wrap;gap:6px;}"
      + ".tool-tag{padding:4px 10px;border-radius:12px;background:color-mix(in srgb,var(--sa-primary) 15%,transparent);color:var(--sa-primary);font-size:12px;font-weight:500;}"
      // Memory
      + ".memory-user-row{cursor:pointer;}"
      + ".memory-user-row:hover td{background:color-mix(in srgb,var(--sa-primary) 5%,transparent);}"
      + ".memory-detail{padding:16px;background:color-mix(in srgb,var(--sa-primary) 5%,transparent);border-radius:8px;margin:8px 0;}"
      + ".memory-entry{padding:8px 0;border-bottom:1px solid var(--sa-divider);font-size:13px;display:flex;align-items:baseline;gap:8px;}"
      + ".memory-entry:last-child{border-bottom:none;}"
      + ".memory-category{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500;white-space:nowrap;}"
      + ".memory-category.preference{background:#e3f2fd;color:#1565c0;}"
      + ".memory-category.named_entity{background:#f3e5f5;color:#7b1fa2;}"
      + ".memory-category.pattern{background:#fff3e0;color:#e65100;}"
      + ".memory-category.instruction{background:#e8f5e9;color:#2e7d32;}"
      + ".memory-category.fact{background:#fce4ec;color:#c62828;}"
      // Calendar status badges
      + ".cal-status{display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:500;white-space:nowrap;}"
      + ".cal-status.upcoming{background:#e3f2fd;color:#1565c0;}"
      + ".cal-status.pending{background:#fff3e0;color:#e65100;}"
      + ".cal-status.announced{background:#e8f5e9;color:#2e7d32;}"
      + ".cal-status.passed{background:#f5f5f5;color:#9e9e9e;}"
      // Cache warming
      + ".warming-status{display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:8px;font-size:13px;}"
      + ".warming-status.active{background:color-mix(in srgb,var(--sa-success) 15%,transparent);color:var(--sa-success);}"
      + ".warming-status.warming{background:color-mix(in srgb,var(--sa-warning) 15%,transparent);color:var(--sa-warning);}"
      + ".warming-status.inactive{background:color-mix(in srgb,var(--sa-divider) 50%,transparent);color:var(--sa-text-secondary);}"
      + ".warming-detail{color:var(--sa-text-secondary);font-size:12px;margin-top:4px;}"
      // Buttons
      + ".refresh-btn{background:none;border:1px solid var(--sa-divider);border-radius:20px;padding:6px 14px;color:var(--sa-text);cursor:pointer;font-size:13px;display:flex;align-items:center;gap:4px;transition:border-color 0.2s;}"
      + ".refresh-btn:hover{border-color:var(--sa-primary);color:var(--sa-primary);}"
      // States
      + ".loading,.error-msg{text-align:center;padding:60px 20px;color:var(--sa-text-secondary);font-size:16px;}"
      + ".error-msg{color:var(--sa-error);}"
      + ".sub{font-size:11px;color:var(--sa-text-secondary);margin-top:4px;}";
  }
}

customElements.define("smart-assist-panel", SmartAssistPanel);
