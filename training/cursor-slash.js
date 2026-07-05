/** Slash commands in composer — Cursor-style /new /mode /reindex … */
(function () {
  const COMMANDS = [
    { cmd: 'new', label: '新对话', desc: '清空并开始新会话', run: () => window.__junoNewChat?.() },
    { cmd: 'clear', label: '清空上下文', desc: '移除 @ 附加文件', run: () => window.__junoClearContext?.() },
    { cmd: 'reindex', label: '重建索引', desc: '@codebase 检索索引', async: true, run: async () => {
      window.__junoToast?.('正在重建索引…');
      await fetch('/api/index/rebuild', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      window.__junoToast?.('索引重建完成');
      window.__junoRefreshStatus?.();
    }},
    { cmd: 'sync', label: '同步知识库', desc: '拉取远程知识', async: true, run: async () => {
      window.__junoToast?.('同步中…');
      await fetch('/api/sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      window.__junoToast?.('知识库已同步');
    }},
    { cmd: 'mode', label: '切换模式', desc: 'mode agent|chat|plan|ask', run: (arg) => {
      const m = (arg || 'agent').toLowerCase();
      if (window.__junoApplyChatMode) window.__junoApplyChatMode(m);
      else window.__junoToast?.('模式：' + m);
    }},
    { cmd: 'explorer', label: '文件树', desc: '打开/关闭资源管理器', run: () => window.JunoExplorer?.toggle() },
    { cmd: 'mcp', label: 'MCP 服务器', desc: '查看入站 MCP', run: () => window.JunoMcpModal?.open() },
    { cmd: 'help', label: '帮助', desc: '列出斜杠命令', run: () => window.__junoToast?.('/new /clear /reindex /sync /mode /explorer /mcp') },
  ];

  const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;');

  function initSlashMenu() {
    const input = document.getElementById('input');
    const menu = document.getElementById('slash-menu');
    if (!input || !menu) return;

    let activeIdx = 0;
    let visible = [];

    function filter(q) {
      const qq = (q || '').toLowerCase().trim();
      visible = COMMANDS.filter(c => !qq || c.cmd.startsWith(qq) || c.label.includes(qq));
      activeIdx = visible.length ? 0 : -1;
      render();
    }

    function render() {
      if (!visible.length) { menu.classList.remove('show'); return; }
      menu.innerHTML = visible.map((c, i) =>
        `<div class="slash-item${i === activeIdx ? ' active' : ''}" data-idx="${i}">
          <span class="slash-cmd">/${esc(c.cmd)}</span>
          <span class="slash-label">${esc(c.label)}</span>
          <small>${esc(c.desc)}</small>
        </div>`
      ).join('');
      menu.classList.add('show');
    }

    async function exec(item, arg) {
      input.value = '';
      menu.classList.remove('show');
      try {
        if (item.async) await item.run(arg);
        else item.run(arg);
      } catch (e) {
        window.__junoToast?.('命令失败：' + e.message);
      }
    }

    input.addEventListener('input', () => {
      const val = input.value;
      if (!val.startsWith('/')) { menu.classList.remove('show'); return; }
      const rest = val.slice(1);
      const sp = rest.indexOf(' ');
      const cmdPart = sp >= 0 ? rest.slice(0, sp) : rest;
      if (sp >= 0 && cmdPart) {
        menu.classList.remove('show');
        return;
      }
      filter(cmdPart);
    });

    input.addEventListener('keydown', async e => {
      if (!menu.classList.contains('show')) {
        if (e.key === 'Enter' && input.value.startsWith('/')) {
          const parts = input.value.slice(1).trim().split(/\s+/);
          const item = COMMANDS.find(c => c.cmd === (parts[0] || '').toLowerCase());
          if (item) {
            e.preventDefault();
            await exec(item, parts.slice(1).join(' '));
          }
        }
        return;
      }
      if (e.key === 'ArrowDown') { e.preventDefault(); activeIdx = Math.min(activeIdx + 1, visible.length - 1); render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); render(); }
      else if (e.key === 'Enter' && activeIdx >= 0) {
        e.preventDefault();
        const parts = input.value.slice(1).trim().split(/\s+/);
        await exec(visible[activeIdx], parts.slice(1).join(' '));
      } else if (e.key === 'Escape') menu.classList.remove('show');
    });

    menu.addEventListener('click', async e => {
      const el = e.target.closest('.slash-item');
      if (!el) return;
      const item = visible[parseInt(el.dataset.idx, 10)];
      const parts = input.value.slice(1).trim().split(/\s+/);
      await exec(item, parts.slice(1).join(' '));
    });

    document.addEventListener('click', e => {
      if (!menu.contains(e.target) && e.target !== input) menu.classList.remove('show');
    });
  }

  window.JunoSlash = { init: initSlashMenu, commands: COMMANDS };

  document.addEventListener('DOMContentLoaded', initSlashMenu);
})();
