/**
 * Smart Assist Dashboard Panel
 *
 * A custom sidebar panel for Home Assistant that displays
 * metrics, memory, and configuration for Smart Assist agents.
 *
 * Uses Lit 3.x for reactive rendering with HA theme integration.
 */

const LitImport = (() => {
  // Use HA's built-in Lit if available, otherwise define minimal helpers
  if (window.LitElement) {
    return {
      LitElement: window.LitElement,
      html: window.litHtml || window.html,
      css: window.litCss || window.css,
    };
  }
  // Fallback: will be overridden once HA loads
  return { LitElement: HTMLElement, html: String.raw, css: String.raw };
})();

class SmartAssistPanel extends (LitImport.LitElement || HTMLElement) {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      panel: { type: Object },
      route: { type: Object },
      _data: { type: Object, state: true },
      _selectedAgent: { type: String, state: true },
      _loading: { type: Boolean, state: true },
      _error: { type: String, state: true },
      _memoryExpanded: { type: String, state: true },
      _subscriptionId: { type: Number, state: true },
    };
  }

  static get styles() {
    // Use css tagged template if available, otherwise raw string
    const cssTag = (window.litCss || window.css || String.raw);
    return cssTag`
      :host {
        display: block;
        padding: 16px;
        --sa-card-bg: var(--ha-card-background, var(--card-background-color, #fff));
        --sa-primary: var(--primary-color, #03a9f4);
        --sa-text: var(--primary-text-color, #212121);
        --sa-text-secondary: var(--secondary-text-color, #727272);
        --sa-divider: var(--divider-color, #e0e0e0);
        --sa-success: var(--label-badge-green, #4caf50);
        --sa-warning: var(--label-badge-yellow, #ff9800);
        --sa-error: var(--label-badge-red, #f44336);
        --sa-border-radius: var(--ha-card-border-radius, 12px);
        font-family: var(--paper-font-body1_-_font-family, "Roboto", sans-serif);
        color: var(--sa-text);
        background: var(--primary-background-color, #fafafa);
        min-height: 100vh;
        box-sizing: border-box;
      }

      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 24px;
        flex-wrap: wrap;
        gap: 12px;
      }

      .header h1 {
        margin: 0;
        font-size: 24px;
        font-weight: 400;
        color: var(--sa-text);
      }

      .header-actions {
        display: flex;
        gap: 8px;
        align-items: center;
      }

      .agent-selector {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 20px;
      }

      .agent-tab {
        padding: 8px 16px;
        border-radius: 20px;
        border: 1px solid var(--sa-divider);
        background: var(--sa-card-bg);
        color: var(--sa-text);
        cursor: pointer;
        font-size: 14px;
        transition: all 0.2s;
      }

      .agent-tab:hover {
        border-color: var(--sa-primary);
      }

      .agent-tab.active {
        background: var(--sa-primary);
        color: #fff;
        border-color: var(--sa-primary);
      }

      .overview-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 16px;
        margin-bottom: 24px;
      }

      .metric-card {
        background: var(--sa-card-bg);
        border-radius: var(--sa-border-radius);
        padding: 20px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
        text-align: center;
      }

      .metric-card .label {
        font-size: 12px;
        color: var(--sa-text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 8px;
      }

      .metric-card .value {
        font-size: 28px;
        font-weight: 500;
        color: var(--sa-text);
      }

      .metric-card .value.success { color: var(--sa-success); }
      .metric-card .value.warning { color: var(--sa-warning); }
      .metric-card .value.error { color: var(--sa-error); }

      .metric-card .sub {
        font-size: 11px;
        color: var(--sa-text-secondary);
        margin-top: 4px;
      }

      .section {
        margin-bottom: 24px;
      }

      .section-title {
        font-size: 18px;
        font-weight: 500;
        margin-bottom: 12px;
        color: var(--sa-text);
      }

      .content-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
        gap: 16px;
      }

      .card {
        background: var(--sa-card-bg);
        border-radius: var(--sa-border-radius);
        padding: 20px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
      }

      .card h3 {
        margin: 0 0 16px 0;
        font-size: 16px;
        font-weight: 500;
        color: var(--sa-text);
      }

      /* Gauge */
      .gauge-container {
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 16px 0;
      }

      .gauge {
        width: 120px;
        height: 120px;
        border-radius: 50%;
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .gauge .gauge-value {
        font-size: 24px;
        font-weight: 500;
        z-index: 1;
      }

      /* Bar chart */
      .bar-row {
        display: flex;
        align-items: center;
        margin-bottom: 8px;
        gap: 8px;
      }

      .bar-label {
        font-size: 13px;
        color: var(--sa-text-secondary);
        min-width: 100px;
        text-align: right;
      }

      .bar-track {
        flex: 1;
        height: 18px;
        background: var(--sa-divider);
        border-radius: 9px;
        overflow: hidden;
        position: relative;
      }

      .bar-fill {
        height: 100%;
        border-radius: 9px;
        transition: width 0.5s ease;
      }

      .bar-fill.prompt { background: var(--sa-primary); }
      .bar-fill.completion { background: var(--sa-success); }
      .bar-fill.cached { background: var(--sa-warning); }

      .bar-value {
        font-size: 12px;
        color: var(--sa-text-secondary);
        min-width: 70px;
      }

      /* Table */
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }

      th {
        text-align: left;
        padding: 8px 12px;
        color: var(--sa-text-secondary);
        font-weight: 500;
        border-bottom: 2px solid var(--sa-divider);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.3px;
      }

      td {
        padding: 8px 12px;
        border-bottom: 1px solid var(--sa-divider);
        color: var(--sa-text);
      }

      tr:last-child td {
        border-bottom: none;
      }

      /* Tools tags */
      .tools-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }

      .tool-tag {
        padding: 4px 10px;
        border-radius: 12px;
        background: color-mix(in srgb, var(--sa-primary) 15%, transparent);
        color: var(--sa-primary);
        font-size: 12px;
        font-weight: 500;
      }

      /* Features */
      .feature-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
        gap: 8px;
      }

      .feature-item {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
      }

      .feature-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
      }

      .feature-dot.on { background: var(--sa-success); }
      .feature-dot.off { background: var(--sa-divider); }

      /* Memory user row */
      .memory-user-row {
        cursor: pointer;
      }

      .memory-user-row:hover td {
        background: color-mix(in srgb, var(--sa-primary) 5%, transparent);
      }

      .memory-detail {
        padding: 12px;
        background: color-mix(in srgb, var(--sa-primary) 5%, transparent);
        border-radius: 8px;
        margin-top: 8px;
      }

      .memory-entry {
        padding: 6px 0;
        border-bottom: 1px solid var(--sa-divider);
        font-size: 13px;
      }

      .memory-entry:last-child {
        border-bottom: none;
      }

      .memory-category {
        display: inline-block;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 500;
        margin-right: 6px;
      }

      .memory-category.preference { background: #e3f2fd; color: #1565c0; }
      .memory-category.named_entity { background: #f3e5f5; color: #7b1fa2; }
      .memory-category.pattern { background: #fff3e0; color: #e65100; }
      .memory-category.instruction { background: #e8f5e9; color: #2e7d32; }
      .memory-category.fact { background: #fce4ec; color: #c62828; }

      /* Cache warming status */
      .warming-status {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        border-radius: 8px;
        font-size: 13px;
      }

      .warming-status.active {
        background: color-mix(in srgb, var(--sa-success) 15%, transparent);
        color: var(--sa-success);
      }

      .warming-status.warming {
        background: color-mix(in srgb, var(--sa-warning) 15%, transparent);
        color: var(--sa-warning);
      }

      .warming-status.inactive {
        background: color-mix(in srgb, var(--sa-divider) 50%, transparent);
        color: var(--sa-text-secondary);
      }

      .warming-detail {
        color: var(--sa-text-secondary);
        font-size: 12px;
        margin-top: 4px;
      }

      /* Refresh button */
      .refresh-btn {
        background: none;
        border: 1px solid var(--sa-divider);
        border-radius: 20px;
        padding: 6px 14px;
        color: var(--sa-text);
        cursor: pointer;
        font-size: 13px;
        display: flex;
        align-items: center;
        gap: 4px;
        transition: border-color 0.2s;
      }

      .refresh-btn:hover {
        border-color: var(--sa-primary);
        color: var(--sa-primary);
      }

      /* Loading / Error */
      .loading, .error-msg {
        text-align: center;
        padding: 60px 20px;
        color: var(--sa-text-secondary);
        font-size: 16px;
      }

      .error-msg { color: var(--sa-error); }

      /* Narrow mode */
      :host([narrow]) .overview-grid {
        grid-template-columns: repeat(2, 1fr);
      }

      :host([narrow]) .content-grid {
        grid-template-columns: 1fr;
      }

      :host([narrow]) .header h1 {
        font-size: 20px;
      }
    `;
  }

  constructor() {
    super();
    this._data = null;
    this._selectedAgent = null;
    this._loading = true;
    this._error = null;
    this._memoryExpanded = null;
    this._subscriptionId = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this._fetchData();
    this._subscribe();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsubscribe();
  }

  async _fetchData() {
    this._loading = true;
    this._error = null;
    try {
      const result = await this.hass.callWS({ type: "smart_assist/dashboard_data" });
      this._data = result;

      // Auto-select first agent if none selected
      if (!this._selectedAgent && result.agents) {
        const agentIds = Object.keys(result.agents);
        if (agentIds.length > 0) {
          this._selectedAgent = agentIds[0];
        }
      }
    } catch (err) {
      this._error = err.message || "Failed to load dashboard data";
      console.error("Smart Assist Dashboard error:", err);
    }
    this._loading = false;
  }

  async _subscribe() {
    try {
      this._subscriptionId = await this.hass.connection.subscribeMessage(
        (data) => {
          this._data = data;
        },
        { type: "smart_assist/subscribe" }
      );
    } catch (err) {
      console.warn("Smart Assist: Could not subscribe to updates:", err);
    }
  }

  _unsubscribe() {
    if (this._subscriptionId) {
      try {
        this._subscriptionId();
      } catch (_) {
        // Ignore errors during unsubscribe
      }
      this._subscriptionId = null;
    }
  }

  _selectAgent(agentId) {
    this._selectedAgent = agentId;
  }

  _formatNumber(num) {
    if (num === undefined || num === null) return "0";
    if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
    if (num >= 1000) return (num / 1000).toFixed(1) + "K";
    return Math.round(num).toString();
  }

  _getSuccessColor(rate) {
    if (rate >= 95) return "success";
    if (rate >= 90) return "warning";
    return "error";
  }

  _getCacheColor(rate) {
    if (rate >= 80) return "success";
    if (rate >= 50) return "warning";
    return "error";
  }

  _getAgentMetrics() {
    if (!this._data || !this._selectedAgent) return null;
    const agent = this._data.agents[this._selectedAgent];
    return agent ? agent.metrics : null;
  }

  _getAgent() {
    if (!this._data || !this._selectedAgent) return null;
    return this._data.agents[this._selectedAgent];
  }

  _getAggregateMetrics() {
    if (!this._data || !this._data.agents) return null;
    const agents = Object.values(this._data.agents);
    if (agents.length === 0) return null;

    const agg = {
      total_requests: 0,
      successful_requests: 0,
      failed_requests: 0,
      total_prompt_tokens: 0,
      total_completion_tokens: 0,
      average_response_time_ms: 0,
      cache_hits: 0,
      cache_misses: 0,
      cached_tokens: 0,
      empty_responses: 0,
      stream_timeouts: 0,
      total_retries: 0,
    };

    let totalResponseTime = 0;
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
      totalResponseTime += (m.average_response_time_ms || 0) * (m.successful_requests || 0);
    }

    agg.success_rate = agg.total_requests > 0
      ? (agg.successful_requests / agg.total_requests) * 100 : 100;
    agg.average_response_time_ms = agg.successful_requests > 0
      ? totalResponseTime / agg.successful_requests : 0;
    agg.cache_hit_rate = (agg.cache_hits + agg.cache_misses) > 0
      ? (agg.cache_hits / (agg.cache_hits + agg.cache_misses)) * 100 : 0;

    return agg;
  }

  render() {
    const h = (window.litHtml || window.html || String.raw);

    if (this._loading) {
      return h`<div class="loading">Loading Smart Assist Dashboard...</div>`;
    }

    if (this._error) {
      return h`
        <div class="error-msg">
          ${this._error}
          <br><br>
          <button class="refresh-btn" @click=${() => this._fetchData()}>Retry</button>
        </div>
      `;
    }

    if (!this._data) {
      return h`<div class="loading">No data available</div>`;
    }

    const agents = this._data.agents || {};
    const agentIds = Object.keys(agents);
    const metrics = this._selectedAgent ? (agents[this._selectedAgent]?.metrics || {}) : this._getAggregateMetrics();
    const agent = this._getAgent();

    return h`
      <div class="header">
        <h1>Smart Assist</h1>
        <div class="header-actions">
          <button class="refresh-btn" @click=${() => this._fetchData()}>
            Refresh
          </button>
        </div>
      </div>

      ${agentIds.length > 1 ? h`
        <div class="agent-selector">
          ${agentIds.map(id => h`
            <button
              class="agent-tab ${this._selectedAgent === id ? 'active' : ''}"
              @click=${() => this._selectAgent(id)}
            >
              ${agents[id].name}
            </button>
          `)}
        </div>
      ` : ''}

      ${this._renderOverviewCards(metrics)}

      <div class="content-grid">
        ${this._renderTokenCard(metrics)}
        ${this._renderCacheCard(metrics, agent)}
        ${this._renderToolsCard(agent)}
        ${this._renderFeaturesCard(agent)}
        ${this._renderMemoryCard()}
        ${this._renderConfigCard(agent)}
      </div>
    `;
  }

  _renderOverviewCards(metrics) {
    const h = (window.litHtml || window.html || String.raw);
    if (!metrics) return '';

    const successRate = metrics.success_rate ?? 100;
    const cacheHitRate = metrics.cache_hit_rate ?? 0;
    const totalTokens = (metrics.total_prompt_tokens || 0) + (metrics.total_completion_tokens || 0);

    return h`
      <div class="overview-grid">
        <div class="metric-card">
          <div class="label">Total Requests</div>
          <div class="value">${this._formatNumber(metrics.total_requests || 0)}</div>
          <div class="sub">${metrics.failed_requests || 0} failed</div>
        </div>

        <div class="metric-card">
          <div class="label">Success Rate</div>
          <div class="value ${this._getSuccessColor(successRate)}">
            ${successRate.toFixed(1)}%
          </div>
          <div class="sub">${metrics.total_retries || 0} retries</div>
        </div>

        <div class="metric-card">
          <div class="label">Avg Response</div>
          <div class="value">${Math.round(metrics.average_response_time_ms || 0)}</div>
          <div class="sub">milliseconds</div>
        </div>

        <div class="metric-card">
          <div class="label">Total Tokens</div>
          <div class="value">${this._formatNumber(totalTokens)}</div>
          <div class="sub">${this._formatNumber(metrics.total_prompt_tokens || 0)} prompt / ${this._formatNumber(metrics.total_completion_tokens || 0)} completion</div>
        </div>

        <div class="metric-card">
          <div class="label">Cache Hit Rate</div>
          <div class="value ${this._getCacheColor(cacheHitRate)}">
            ${cacheHitRate.toFixed(1)}%
          </div>
          <div class="sub">${this._formatNumber(metrics.cached_tokens || 0)} tokens cached</div>
        </div>
      </div>
    `;
  }

  _renderTokenCard(metrics) {
    const h = (window.litHtml || window.html || String.raw);
    if (!metrics) return '';

    const prompt = metrics.total_prompt_tokens || 0;
    const completion = metrics.total_completion_tokens || 0;
    const cached = metrics.cached_tokens || 0;
    const total = prompt + completion;
    const maxVal = Math.max(prompt, completion, cached, 1);

    return h`
      <div class="card">
        <h3>Token Usage</h3>
        <div class="bar-row">
          <div class="bar-label">Prompt</div>
          <div class="bar-track">
            <div class="bar-fill prompt" style="width: ${(prompt / maxVal) * 100}%"></div>
          </div>
          <div class="bar-value">${this._formatNumber(prompt)}</div>
        </div>
        <div class="bar-row">
          <div class="bar-label">Completion</div>
          <div class="bar-track">
            <div class="bar-fill completion" style="width: ${(completion / maxVal) * 100}%"></div>
          </div>
          <div class="bar-value">${this._formatNumber(completion)}</div>
        </div>
        <div class="bar-row">
          <div class="bar-label">Cached</div>
          <div class="bar-track">
            <div class="bar-fill cached" style="width: ${(cached / maxVal) * 100}%"></div>
          </div>
          <div class="bar-value">${this._formatNumber(cached)}</div>
        </div>
        ${total > 0 ? h`
          <div class="sub" style="margin-top: 12px; text-align: center;">
            Cache saved ~${((cached / Math.max(prompt, 1)) * 100).toFixed(0)}% of prompt tokens
          </div>
        ` : ''}
      </div>
    `;
  }

  _renderCacheCard(metrics, agent) {
    const h = (window.litHtml || window.html || String.raw);
    if (!metrics) return '';

    const warming = agent?.cache_warming;
    const hits = metrics.cache_hits || 0;
    const misses = metrics.cache_misses || 0;
    const rate = (hits + misses) > 0 ? ((hits / (hits + misses)) * 100).toFixed(1) : "0.0";

    return h`
      <div class="card">
        <h3>Cache Performance</h3>

        <div style="display: flex; justify-content: space-around; margin-bottom: 16px;">
          <div style="text-align: center;">
            <div style="font-size: 32px; font-weight: 500; color: var(--sa-success);">${hits}</div>
            <div style="font-size: 12px; color: var(--sa-text-secondary);">Hits</div>
          </div>
          <div style="text-align: center;">
            <div style="font-size: 32px; font-weight: 500; color: var(--sa-error);">${misses}</div>
            <div style="font-size: 12px; color: var(--sa-text-secondary);">Misses</div>
          </div>
          <div style="text-align: center;">
            <div style="font-size: 32px; font-weight: 500; color: var(--sa-primary);">${rate}%</div>
            <div style="font-size: 12px; color: var(--sa-text-secondary);">Hit Rate</div>
          </div>
        </div>

        ${warming ? h`
          <div class="warming-status ${warming.status || 'inactive'}">
            <span>${warming.status === 'active' ? 'Cache Warming Active' : warming.status === 'warming' ? 'Warming...' : 'Cache Warming Inactive'}</span>
          </div>
          ${warming.last_warmup ? h`
            <div class="warming-detail">
              Last: ${new Date(warming.last_warmup).toLocaleString()} |
              Count: ${warming.warmup_count || 0} |
              Failures: ${warming.warmup_failures || 0}
            </div>
          ` : ''}
        ` : h`
          <div class="warming-status inactive">Cache Warming Disabled</div>
        `}

        ${(metrics.empty_responses || metrics.stream_timeouts) ? h`
          <div style="margin-top: 12px; font-size: 12px; color: var(--sa-text-secondary);">
            Empty responses: ${metrics.empty_responses || 0} |
            Stream timeouts: ${metrics.stream_timeouts || 0}
          </div>
        ` : ''}
      </div>
    `;
  }

  _renderToolsCard(agent) {
    const h = (window.litHtml || window.html || String.raw);
    if (!agent || !agent.tools || agent.tools.length === 0) return '';

    return h`
      <div class="card">
        <h3>Registered Tools (${agent.tools.length})</h3>
        <div class="tools-grid">
          ${agent.tools.map(t => h`<span class="tool-tag">${t}</span>`)}
        </div>
      </div>
    `;
  }

  _renderFeaturesCard(agent) {
    const h = (window.litHtml || window.html || String.raw);
    if (!agent || !agent.features) return '';

    const features = agent.features;
    const featureLabels = {
      memory: "Memory",
      web_search: "Web Search",
      calendar_context: "Calendar",
      prompt_caching: "Prompt Caching",
      cache_warming: "Cache Warming",
      clean_responses: "Clean Responses",
      ask_followup: "Follow-up",
      presence_heuristic: "Presence Heuristic",
    };

    return h`
      <div class="card">
        <h3>Features</h3>
        <div class="feature-grid">
          ${Object.entries(features).map(([key, val]) => h`
            <div class="feature-item">
              <span class="feature-dot ${val ? 'on' : 'off'}"></span>
              <span>${featureLabels[key] || key}</span>
            </div>
          `)}
        </div>
      </div>
    `;
  }

  _renderMemoryCard() {
    const h = (window.litHtml || window.html || String.raw);
    const memory = this._data?.memory;
    if (!memory) return '';

    const users = memory.users || {};
    const userIds = Object.keys(users);

    return h`
      <div class="card">
        <h3>Memory (${memory.total_memories || 0} total, ${memory.total_users || 0} users)</h3>

        ${memory.global_memories > 0 ? h`
          <div style="margin-bottom: 12px; font-size: 13px; color: var(--sa-text-secondary);">
            ${memory.global_memories} global memories
          </div>
        ` : ''}

        ${userIds.length > 0 ? h`
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Memories</th>
                <th>Categories</th>
              </tr>
            </thead>
            <tbody>
              ${userIds.map(uid => {
                const u = users[uid];
                const cats = u.categories || {};
                const catStr = Object.entries(cats)
                  .map(([c, n]) => `${c}: ${n}`)
                  .join(", ");
                return h`
                  <tr class="memory-user-row" @click=${() => this._toggleMemory(uid)}>
                    <td>${u.display_name || uid}</td>
                    <td>${u.memory_count || 0}</td>
                    <td style="font-size: 12px;">${catStr || '-'}</td>
                  </tr>
                  ${this._memoryExpanded === uid ? h`
                    <tr>
                      <td colspan="3" style="padding: 0;">
                        ${this._renderMemoryDetails(uid)}
                      </td>
                    </tr>
                  ` : ''}
                `;
              })}
            </tbody>
          </table>
        ` : h`
          <div style="color: var(--sa-text-secondary); font-size: 13px;">
            No user profiles yet.
          </div>
        `}
      </div>
    `;
  }

  async _toggleMemory(userId) {
    if (this._memoryExpanded === userId) {
      this._memoryExpanded = null;
      return;
    }

    try {
      const details = await this.hass.callWS({
        type: "smart_assist/memory_details",
        user_id: userId,
      });
      this._memoryDetails = details;
      this._memoryExpanded = userId;
    } catch (err) {
      console.error("Failed to load memory details:", err);
    }
  }

  _renderMemoryDetails(userId) {
    const h = (window.litHtml || window.html || String.raw);
    const details = this._memoryDetails;
    if (!details || !details.memories) return '';

    const memories = details.memories;
    if (memories.length === 0) {
      return h`<div class="memory-detail" style="color: var(--sa-text-secondary);">No memories stored.</div>`;
    }

    return h`
      <div class="memory-detail">
        ${memories.slice(0, 20).map(m => h`
          <div class="memory-entry">
            <span class="memory-category ${m.category || ''}">${m.category || 'unknown'}</span>
            ${m.content || ''}
            <span style="float: right; font-size: 11px; color: var(--sa-text-secondary);">
              ${m.created ? new Date(m.created).toLocaleDateString() : ''}
            </span>
          </div>
        `)}
        ${memories.length > 20 ? h`
          <div style="text-align: center; padding: 8px; color: var(--sa-text-secondary); font-size: 12px;">
            ... and ${memories.length - 20} more
          </div>
        ` : ''}
      </div>
    `;
  }

  _renderConfigCard(agent) {
    const h = (window.litHtml || window.html || String.raw);
    if (!agent) return '';

    return h`
      <div class="card">
        <h3>Configuration</h3>
        <table>
          <tbody>
            <tr><td style="color: var(--sa-text-secondary);">Model</td><td>${agent.model}</td></tr>
            <tr><td style="color: var(--sa-text-secondary);">LLM Provider</td><td>${agent.llm_provider}</td></tr>
            <tr><td style="color: var(--sa-text-secondary);">Provider</td><td>${agent.provider}</td></tr>
            <tr><td style="color: var(--sa-text-secondary);">Temperature</td><td>${agent.temperature}</td></tr>
            <tr><td style="color: var(--sa-text-secondary);">Max Tokens</td><td>${agent.max_tokens}</td></tr>
          </tbody>
        </table>
      </div>
    `;
  }
}

customElements.define("smart-assist-panel", SmartAssistPanel);
