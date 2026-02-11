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
    this._historyData = null;
    this._historyLoading = false;
    this._toolAnalytics = null;
    this._historyPage = 0;
    this._autoRefreshEnabled = true;
    this._autoRefreshInterval = 30;
    this._autoRefreshTimer = null;
    this._boundVisibilityHandler = null;
    this._promptData = null;
    this._promptLoading = false;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._fetchData();
      this._subscribe();
      const stored = localStorage.getItem("smart_assist_auto_refresh");
      this._autoRefreshEnabled = stored !== "false";
      const storedInterval = localStorage.getItem("smart_assist_auto_refresh_interval");
      if (storedInterval) this._autoRefreshInterval = parseInt(storedInterval, 10) || 30;
      if (this._autoRefreshEnabled) this._startAutoRefresh();
    }
  }

  set narrow(val) { this._narrow = val; this._render(); }
  set panel(val) { this._panel = val; }
  set route(val) { this._route = val; }

  connectedCallback() {
    this._render();
    this._boundVisibilityHandler = () => this._handleVisibilityChange();
    document.addEventListener("visibilitychange", this._boundVisibilityHandler);
  }

  disconnectedCallback() {
    this._stopAutoRefresh();
    if (this._boundVisibilityHandler) {
      document.removeEventListener("visibilitychange", this._boundVisibilityHandler);
      this._boundVisibilityHandler = null;
    }
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
    // Also refresh history data if on history tab
    if (this._activeTab === "history") {
      this._loadHistory();
    }
  }

  async _subscribe() {
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (data) => { this._data = Object.assign(this._data || {}, data); this._render(); },
        { type: "smart_assist/subscribe" }
      );
    } catch (err) {
      console.warn("Smart Assist: Could not subscribe to updates:", err);
    }
  }

  _startAutoRefresh() {
    this._stopAutoRefresh();
    this._autoRefreshTimer = setInterval(() => {
      this._fetchData();
    }, this._autoRefreshInterval * 1000);
  }

  _stopAutoRefresh() {
    if (this._autoRefreshTimer) {
      clearInterval(this._autoRefreshTimer);
      this._autoRefreshTimer = null;
    }
  }

  _toggleAutoRefresh() {
    this._autoRefreshEnabled = !this._autoRefreshEnabled;
    localStorage.setItem("smart_assist_auto_refresh", String(this._autoRefreshEnabled));
    if (this._autoRefreshEnabled) {
      this._startAutoRefresh();
    } else {
      this._stopAutoRefresh();
    }
    this._render();
  }

  _setAutoRefreshInterval(seconds) {
    this._autoRefreshInterval = seconds;
    localStorage.setItem("smart_assist_auto_refresh_interval", String(seconds));
    if (this._autoRefreshEnabled) {
      this._startAutoRefresh();
    }
    this._render();
  }

  _handleVisibilityChange() {
    if (document.hidden) {
      this._stopAutoRefresh();
    } else if (this._autoRefreshEnabled) {
      this._fetchData();
      this._startAutoRefresh();
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
    // Preserve scroll position across re-renders (prevents jump-to-top on auto-refresh)
    const prevScrollY = window.scrollY;
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
    // Restore scroll position after DOM update
    requestAnimationFrame(() => { window.scrollTo(0, prevScrollY); });
  }

  _renderDashboard() {
    const agents = this._data.agents || {};
    const agentIds = Object.keys(agents);

    // Header
    let html = '<div class="header"><h1>Smart Assist</h1><div class="header-actions">'
      + '<button class="refresh-btn" id="refresh-btn" title="Jetzt aktualisieren">'
      + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;">'
      + '<path d="M23 4v6h-6M1 20v-6h6"/>'
      + '<path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>'
      + '</svg>'
      + '</button>'
      + '<div class="auto-refresh-control">'
      + '<button class="refresh-btn auto-refresh-toggle ' + (this._autoRefreshEnabled ? 'active' : '') + '" id="auto-refresh-btn" title="Auto-Refresh ' + (this._autoRefreshEnabled ? 'deaktivieren' : 'aktivieren') + '">'
      + (this._autoRefreshEnabled ? '<span class="pulse-dot"></span>' : '')
      + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;">'
      + '<path d="M23 4v6h-6M1 20v-6h6"/>'
      + '<path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>'
      + '</svg>'
      + '</button>'
      + '<select class="auto-refresh-select" id="auto-refresh-interval" title="Auto-Refresh Intervall">'
      + '<option value="5"' + (this._autoRefreshInterval === 5 ? ' selected' : '') + '>5s</option>'
      + '<option value="10"' + (this._autoRefreshInterval === 10 ? ' selected' : '') + '>10s</option>'
      + '<option value="30"' + (this._autoRefreshInterval === 30 ? ' selected' : '') + '>30s</option>'
      + '<option value="60"' + (this._autoRefreshInterval === 60 ? ' selected' : '') + '>60s</option>'
      + '</select></div>'
      + '</div></div>';

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
      + '<button class="tab-btn ' + (this._activeTab === "history" ? "active" : "") + '" data-tab="history">History</button>'
      + '<button class="tab-btn ' + (this._activeTab === "prompt" ? "active" : "") + '" data-tab="prompt">Prompt</button>'
      + '</div>';

    // Tab content
    if (this._activeTab === "overview") {
      html += this._renderOverviewTab(agents);
    } else if (this._activeTab === "memory") {
      html += this._renderMemoryTab();
    } else if (this._activeTab === "calendar") {
      html += this._renderCalendarTab();
    } else if (this._activeTab === "history") {
      html += this._renderHistoryTab();
    } else if (this._activeTab === "prompt") {
      html += this._renderPromptTab();
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

        // Action buttons
        const actions = '<div class="user-actions">'
          + '<button class="icon-btn rename-user-btn" data-user="' + this._esc(uid) + '" title="Rename user">&#9998;</button>'
          + (userIds.length > 1 ? '<button class="icon-btn merge-user-btn" data-user="' + this._esc(uid) + '" title="Merge into another user">&#8644;</button>' : '')
          + '</div>';

        rows += '<tr class="memory-user-row" data-user="' + this._esc(uid) + '">'
          + '<td><strong>' + this._esc(u.display_name || uid) + '</strong><div style="font-size:11px;color:var(--sa-text-secondary);">' + this._esc(uid) + '</div></td>'
          + '<td>' + (u.memory_count || 0) + '</td>'
          + '<td>' + (catTags || '-') + '</td>'
          + '<td style="font-size:12px;color:var(--sa-text-secondary);">' + (u.first_interaction ? new Date(u.first_interaction).toLocaleDateString() : '-') + '</td>'
          + '<td class="actions-cell">' + actions + '</td>'
          + '</tr>';
        if (this._memoryExpanded === uid) {
          rows += '<tr><td colspan="5" style="padding:0;">' + this._renderMemoryDetails(uid) + '</td></tr>';
        }
      }
      html += '<div class="card"><h3>User Profiles</h3>'
        + '<table><thead><tr><th>User</th><th>Memories</th><th>Categories</th><th>First Seen</th><th style="width:80px;">Actions</th></tr></thead>'
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

  _renderHistoryTab() {
    let html = '';

    // Tool Analytics Section
    if (this._toolAnalytics && this._toolAnalytics.tools) {
      const tools = this._toolAnalytics.tools;
      const summary = this._toolAnalytics.summary || {};

      // Summary cards
      html += '<div class="overview-grid">'
        + '<div class="metric-card"><div class="label">Logged Requests</div><div class="value">'
        + this._fmt(summary.total_requests || 0) + '</div></div>'
        + '<div class="metric-card"><div class="label">Avg Response</div><div class="value">'
        + Math.round(summary.avg_response_time_ms || 0) + '</div><div class="sub">ms</div></div>'
        + '<div class="metric-card"><div class="label">Avg Tokens</div><div class="value">'
        + this._fmt(summary.avg_tokens_per_request || 0) + '</div><div class="sub">per request</div></div>'
        + '<div class="metric-card"><div class="label">Tool Calls</div><div class="value">'
        + this._fmt(summary.total_tool_calls || 0) + '</div></div>'
        + '</div>';

      // Tool analytics table
      if (tools.length > 0) {
        let rows = '';
        for (const t of tools) {
          const srClass = this._successColor(t.success_rate || 100);
          rows += '<tr>'
            + '<td><strong>' + this._esc(t.name) + '</strong></td>'
            + '<td>' + (t.total_calls || 0) + '</td>'
            + '<td class="' + srClass + '">'
            + (t.success_rate || 100).toFixed(1) + '%</td>'
            + '<td>' + Math.round(t.average_execution_time_ms || 0) + ' ms</td>'
            + '<td style="font-size:12px;color:var(--sa-text-secondary);">'
            + (t.last_used ? new Date(t.last_used).toLocaleString() : '-') + '</td>'
            + '</tr>';
        }
        html += '<div class="card"><h3>Tool Usage Analytics</h3>'
          + '<table><thead><tr><th>Tool</th><th>Calls</th>'
          + '<th>Success Rate</th><th>Avg Time</th><th>Last Used</th></tr></thead>'
          + '<tbody>' + rows + '</tbody></table></div>';
      }
    }

    // Request History Table
    html += '<div class="card"><h3>Request History</h3>';

    if (this._historyLoading) {
      html += '<div class="loading">Loading history...</div>';
    } else if (!this._historyData || !this._historyData.entries || this._historyData.entries.length === 0) {
      html += '<div style="color:var(--sa-text-secondary);font-size:14px;padding:20px 0;">No request history yet. Entries will appear here as conversations are processed.</div>';
    } else {
      const entries = this._historyData.entries;
      const total = this._historyData.total || 0;

      let rows = '';
      for (const e of entries) {
        const time = e.timestamp ? new Date(e.timestamp).toLocaleString() : '-';
        const tokens = (e.prompt_tokens || 0) + (e.completion_tokens || 0);
        const toolNames = (e.tools_used || []).map(function(t) { return t.name; }).join(', ') || '-';
        const statusCls = e.success ? 'success' : 'error';
        const statusLabel = e.success ? 'OK' : 'Error';

        rows += '<tr>'
          + '<td style="white-space:nowrap;font-size:12px;">' + time + '</td>'
          + '<td>' + this._esc(e.agent_name || '-') + '</td>'
          + '<td>' + this._esc(e.user_id || '-') + '</td>'
          + '<td title="' + this._esc(e.input_text || '') + '">'
          + this._esc((e.input_text || '').substring(0, 60))
          + ((e.input_text || '').length > 60 ? '...' : '') + '</td>'
          + '<td>' + this._fmt(tokens) + '</td>'
          + '<td>' + Math.round(e.response_time_ms || 0) + '</td>'
          + '<td title="' + this._esc(toolNames) + '">'
          + this._esc(toolNames.substring(0, 30))
          + (toolNames.length > 30 ? '...' : '') + '</td>'
          + '<td><span class="cal-status ' + statusCls + '">' + statusLabel + '</span></td>'
          + '</tr>';
      }

      html += '<table><thead><tr>'
        + '<th>Time</th><th>Agent</th><th>User</th>'
        + '<th>Input</th><th>Tokens</th><th>Time (ms)</th>'
        + '<th>Tools</th><th>Status</th>'
        + '</tr></thead><tbody>' + rows + '</tbody></table>';

      // Pagination
      const pageSize = 50;
      const currentPage = this._historyPage || 0;
      const totalPages = Math.ceil(total / pageSize);
      if (totalPages > 1) {
        html += '<div class="history-pagination">'
          + '<button class="refresh-btn history-prev" '
          + (currentPage <= 0 ? 'disabled' : '') + '>Previous</button>'
          + '<span>' + (currentPage + 1) + ' / ' + totalPages + '</span>'
          + '<button class="refresh-btn history-next" '
          + (currentPage >= totalPages - 1 ? 'disabled' : '') + '>Next</button>'
          + '</div>';
      }
    }

    // Clear history button
    html += '<div style="margin-top:12px;text-align:right;">'
      + '<button class="refresh-btn" id="clear-history-btn">'
      + 'Clear History</button></div>';
    html += '</div>';

    return html;
  }

  async _loadHistory() {
    this._historyLoading = true;
    this._render();
    try {
      const agentId = this._selectedAgent || undefined;
      const offset = (this._historyPage || 0) * 50;
      const [historyResult, analyticsResult] = await Promise.all([
        this._hass.callWS({
          type: "smart_assist/request_history",
          agent_id: agentId,
          limit: 50,
          offset: offset,
        }),
        this._hass.callWS({
          type: "smart_assist/tool_analytics",
          agent_id: agentId,
        }),
      ]);
      this._historyData = historyResult;
      this._toolAnalytics = analyticsResult;
    } catch (err) {
      console.error("Failed to load history:", err);
    }
    this._historyLoading = false;
    this._render();
  }

  async _loadPrompt() {
    this._promptLoading = true;
    this._render();
    try {
      const agentId = this._selectedAgent || undefined;
      const result = await this._hass.callWS({
        type: "smart_assist/system_prompt",
        agent_id: agentId,
      });
      this._promptData = result;
    } catch (err) {
      console.error("Failed to load system prompt:", err);
      this._promptData = null;
    }
    this._promptLoading = false;
    this._render();
  }

  _renderPromptTab() {
    let html = '';

    if (this._promptLoading) {
      return '<div class="loading">Loading system prompt...</div>';
    }

    if (!this._promptData) {
      return '<div class="loading">Select an agent and switch to this tab to load the prompt.</div>';
    }

    const prompt = this._promptData;

    // Agent name header
    if (prompt.agent_name) {
      html += '<div class="overview-grid">'
        + '<div class="metric-card"><div class="label">Agent</div>'
        + '<div class="value" style="font-size:20px;">' + this._esc(prompt.agent_name) + '</div></div>'
        + '<div class="metric-card"><div class="label">System Prompt Length</div>'
        + '<div class="value">' + this._fmt(prompt.system_prompt ? prompt.system_prompt.length : 0) + '</div>'
        + '<div class="sub">characters</div></div>'
        + '<div class="metric-card"><div class="label">User Prompt Length</div>'
        + '<div class="value">' + this._fmt(prompt.user_prompt ? prompt.user_prompt.length : 0) + '</div>'
        + '<div class="sub">characters</div></div>'
        + '</div>';
    }

    // System prompt display
    html += '<div class="card"><h3>System Prompt (Technical)</h3>'
      + '<div class="prompt-preview">' + this._formatPrompt(prompt.system_prompt || '(not yet built)') + '</div>'
      + '</div>';

    // User system prompt display
    html += '<div class="card"><h3>User System Prompt (Custom Instructions)</h3>'
      + '<div class="prompt-preview">' + this._formatPrompt(prompt.user_prompt || '(none configured)') + '</div>'
      + '</div>';

    return html;
  }

  _formatPrompt(text) {
    if (!text) return '';
    const escaped = this._esc(text);
    const formatted = escaped
      .replace(/^## (.+)$/gm, '<div class="prompt-section-header">$1</div>')
      .replace(/\n/g, '<br>');
    return formatted;
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

  _renderMemoryDetails(userId) {
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
      const date = m.created_at ? new Date(m.created_at).toLocaleDateString() : (m.created ? new Date(m.created).toLocaleDateString() : "");
      entries += '<div class="memory-entry">'
        + '<span class="memory-category ' + this._esc(cat) + '">' + this._esc(cat) + '</span>'
        + '<span class="memory-content">' + this._esc(m.content || "") + '</span>'
        + '<span style="margin-left:auto;display:flex;align-items:center;gap:6px;">'
        + '<span style="font-size:11px;color:var(--sa-text-secondary);white-space:nowrap;">' + date + '</span>'
        + '<button class="icon-btn delete-memory-btn" data-user="' + this._esc(userId) + '" data-memory="' + this._esc(m.id) + '" title="Delete memory">&times;</button>'
        + '</span></div>';
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

    const autoRefreshBtn = root.getElementById("auto-refresh-btn");
    if (autoRefreshBtn) autoRefreshBtn.addEventListener("click", () => this._toggleAutoRefresh());

    const autoRefreshSelect = root.getElementById("auto-refresh-interval");
    if (autoRefreshSelect) autoRefreshSelect.addEventListener("change", (e) => {
      this._setAutoRefreshInterval(parseInt(e.target.value, 10));
    });

    const retryBtn = root.getElementById("retry-btn");
    if (retryBtn) retryBtn.addEventListener("click", () => this._fetchData());

    root.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._activeTab = btn.dataset.tab;
        if (btn.dataset.tab === "history") {
          this._loadHistory();
        }
        if (btn.dataset.tab === "prompt") {
          this._loadPrompt();
        }
        this._render();
      });
    });

    root.querySelectorAll(".agent-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._selectedAgent = btn.dataset.agent;
        if (this._activeTab === "prompt") {
          this._loadPrompt();
        }
        this._render();
      });
    });

    root.querySelectorAll(".memory-user-row").forEach((row) => {
      row.addEventListener("click", (e) => {
        // Don't toggle when clicking action buttons
        if (e.target.closest(".icon-btn")) return;
        this._toggleMemory(row.dataset.user);
      });
    });

    // Rename user buttons
    root.querySelectorAll(".rename-user-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._renameUser(btn.dataset.user);
      });
    });

    // Merge user buttons
    root.querySelectorAll(".merge-user-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._mergeUser(btn.dataset.user);
      });
    });

    // Delete memory buttons
    root.querySelectorAll(".delete-memory-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._deleteMemory(btn.dataset.user, btn.dataset.memory);
      });
    });

    // History pagination
    const prevBtn = root.querySelector(".history-prev");
    if (prevBtn) prevBtn.addEventListener("click", () => {
      this._historyPage = Math.max(0, (this._historyPage || 0) - 1);
      this._loadHistory();
    });
    const nextBtn = root.querySelector(".history-next");
    if (nextBtn) nextBtn.addEventListener("click", () => {
      this._historyPage = (this._historyPage || 0) + 1;
      this._loadHistory();
    });

    // Clear history
    const clearBtn = root.getElementById("clear-history-btn");
    if (clearBtn) clearBtn.addEventListener("click", async () => {
      if (!confirm("Clear all request history? This cannot be undone.")) return;
      try {
        await this._hass.callWS({
          type: "smart_assist/request_history_clear",
          agent_id: this._selectedAgent || undefined,
        });
        this._historyData = null;
        this._toolAnalytics = null;
        this._historyPage = 0;
        await this._loadHistory();
      } catch (err) {
        alert("Failed to clear history: " + (err.message || err));
      }
    });
  }

  async _renameUser(userId) {
    const memory = this._data ? this._data.memory : null;
    const users = memory ? (memory.users || {}) : {};
    const user = users[userId];
    const currentName = user ? (user.display_name || userId) : userId;

    const newName = prompt("Rename user '" + currentName + "':", currentName);
    if (!newName || newName === currentName) return;

    try {
      await this._hass.callWS({
        type: "smart_assist/memory_rename_user",
        user_id: userId,
        display_name: newName,
      });
      await this._fetchData();
    } catch (err) {
      alert("Failed to rename user: " + (err.message || err));
    }
  }

  async _mergeUser(sourceUserId) {
    const memory = this._data ? this._data.memory : null;
    const users = memory ? (memory.users || {}) : {};
    const userIds = Object.keys(users).filter(function(id) { return id !== sourceUserId; });

    if (userIds.length === 0) {
      alert("No other users to merge into.");
      return;
    }

    const sourceName = users[sourceUserId] ? (users[sourceUserId].display_name || sourceUserId) : sourceUserId;
    const options = userIds.map(function(id) {
      const name = users[id] ? (users[id].display_name || id) : id;
      return name + " (" + id + ")";
    });

    const choice = prompt(
      "Merge all memories from '" + sourceName + "' into which user?\n\n"
      + options.map(function(o, i) { return (i + 1) + ". " + o; }).join("\n")
      + "\n\nEnter number (1-" + options.length + "):"
    );

    if (!choice) return;
    const idx = parseInt(choice, 10) - 1;
    if (isNaN(idx) || idx < 0 || idx >= userIds.length) {
      alert("Invalid selection.");
      return;
    }

    const targetUserId = userIds[idx];
    const targetName = users[targetUserId] ? (users[targetUserId].display_name || targetUserId) : targetUserId;

    if (!confirm("Merge '" + sourceName + "' into '" + targetName + "'?\n\nThis will move all memories and delete the source user profile. This cannot be undone.")) {
      return;
    }

    try {
      const result = await this._hass.callWS({
        type: "smart_assist/memory_merge_users",
        source_user_id: sourceUserId,
        target_user_id: targetUserId,
      });
      alert(result.message || "Users merged successfully.");
      this._memoryExpanded = null;
      this._memoryDetails = null;
      await this._fetchData();
    } catch (err) {
      alert("Failed to merge users: " + (err.message || err));
    }
  }

  async _deleteMemory(userId, memoryId) {
    if (!confirm("Delete this memory? This cannot be undone.")) return;

    try {
      await this._hass.callWS({
        type: "smart_assist/memory_delete",
        user_id: userId,
        memory_id: memoryId,
      });
      // Refresh memory details
      await this._toggleMemory(userId);
      if (this._memoryExpanded !== userId) {
        // Re-expand if it collapsed
        await this._toggleMemory(userId);
      }
      await this._fetchData();
    } catch (err) {
      alert("Failed to delete memory: " + (err.message || err));
    }
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
      + ".card{background:var(--sa-card-bg);border-radius:var(--sa-border-radius);padding:20px;box-shadow:var(--ha-card-box-shadow,0 2px 6px rgba(0,0,0,0.1));margin-bottom:16px;}"
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
      + ".memory-content{flex:1;}"
      + ".memory-category{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500;white-space:nowrap;flex-shrink:0;}"
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
      // Action buttons
      + ".user-actions{display:flex;gap:4px;}"
      + ".actions-cell{text-align:right;}"
      + ".icon-btn{background:none;border:1px solid var(--sa-divider);border-radius:6px;width:28px;height:28px;cursor:pointer;font-size:14px;color:var(--sa-text-secondary);display:inline-flex;align-items:center;justify-content:center;transition:all 0.15s;padding:0;line-height:1;}"
      + ".icon-btn:hover{border-color:var(--sa-primary);color:var(--sa-primary);background:color-mix(in srgb,var(--sa-primary) 8%,transparent);}"
      + ".delete-memory-btn:hover{border-color:var(--sa-error);color:var(--sa-error);background:color-mix(in srgb,var(--sa-error) 8%,transparent);}"
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
      + ".sub{font-size:11px;color:var(--sa-text-secondary);margin-top:4px;}"
      // History pagination
      + ".history-pagination{display:flex;align-items:center;justify-content:center;gap:16px;margin-top:12px;font-size:13px;color:var(--sa-text-secondary);}"
      + ".history-pagination button:disabled{opacity:0.4;cursor:not-allowed;}"
      + ".auto-refresh-control{display:flex;align-items:center;gap:4px;}"
      + ".auto-refresh-toggle.active{border-color:var(--sa-success);color:var(--sa-success);}"
      + ".auto-refresh-select{background:var(--sa-card-bg);border:1px solid var(--sa-divider);border-radius:20px;padding:5px 8px;color:var(--sa-text);font-size:12px;cursor:pointer;outline:none;}"
      + ".auto-refresh-select:focus{border-color:var(--sa-primary);}"
      + ".pulse-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--sa-success);margin-right:4px;animation:pulse 1.5s infinite;}"
      + "@keyframes pulse{0%,100%{opacity:1;}50%{opacity:0.3;}}"
      + ".prompt-preview{font-family:'Roboto Mono',monospace;font-size:13px;line-height:1.6;white-space:pre-wrap;word-wrap:break-word;background:var(--primary-background-color,#fafafa);border:1px solid var(--sa-divider);border-radius:8px;padding:16px;max-height:600px;overflow-y:auto;color:var(--sa-text);}"
      + ".prompt-section-header{font-weight:700;color:var(--sa-primary);font-size:14px;margin:12px 0 4px 0;padding:4px 0;border-bottom:1px solid var(--sa-divider);}";
  }
}

customElements.define("smart-assist-panel", SmartAssistPanel);
