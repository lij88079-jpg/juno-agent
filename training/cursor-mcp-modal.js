/** MCP server list modal — inbound servers + tools */
(function () {
  const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;');

  const McpModal = {
    modal: null,
    body: null,

    init() {
      this.modal = document.getElementById('mcp-modal');
      this.body = document.getElementById('mcp-modal-body');
      document.getElementById('mcp-modal-close')?.addEventListener('click', () => this.close());
      this.modal?.addEventListener('click', e => {
        if (e.target === this.modal) this.close();
      });
    },

    async open() {
      if (!this.modal) return;
      this.modal.classList.add('show');
      await this.refresh();
    },

    close() {
      this.modal?.classList.remove('show');
    },

    async refresh() {
      if (!this.body) return;
      this.body.innerHTML = '<p class="muted">加载 MCP 服务器…</p>';
      try {
        const r = await fetch('/api/mcp/servers').then(x => x.json());
        const servers = r.servers || [];
        if (!servers.length) {
          this.body.innerHTML = '<p class="muted">暂无启用的 MCP 服务器。编辑 <code>config/mcp-inbound.json</code> 或合并 Cursor <code>~/.cursor/mcp.json</code>。</p>';
          return;
        }
        this.body.innerHTML = servers.map(s => `
          <div class="mcp-card">
            <div class="mcp-card-head"><strong>${esc(s.label || s.id)}</strong><span class="mcp-id">${esc(s.id)}</span></div>
            <div class="mcp-tools">${(s.tools || []).map(t => `<span class="mcp-tool-pill">${esc(t)}</span>`).join('') || '<span class="muted">无工具或未连接</span>'}</div>
          </div>
        `).join('');
      } catch (e) {
        this.body.innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`;
      }
    },
  };

  document.addEventListener('DOMContentLoaded', () => {
    McpModal.init();
    window.JunoMcpModal = McpModal;
    const badge = document.getElementById('mcp-badge');
    if (badge) {
      badge.style.cursor = 'pointer';
      badge.title = 'MCP 服务器';
      badge.addEventListener('click', () => McpModal.open());
    }
  });
})();
