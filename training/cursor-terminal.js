/** Terminal panel — integrated shell output (no external CMD window) */
(function () {
  'use strict';

  const esc = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  class TerminalPanel {
    constructor() {
      this.panel = document.getElementById('terminal-panel');
      this.body = document.getElementById('terminal-body');
      this.lines = [];
      this.maxLines = 200;
      this.liveJobs = new Map();
    }

    toggle() {
      if (!this.panel) return;
      this.panel.classList.toggle('open');
      const open = this.panel.classList.contains('open');
      document.getElementById('btn-rail-terminal')?.classList.toggle('active', open);
      if (open && !this.lines.length && !this.liveJobs.size && this.body) {
        this.body.innerHTML = '<p class="term-empty" style="color:#858585;margin:0">暂无 shell 输出。Agent 执行 run_shell 后会自动显示。</p>';
      }
    }

    open() {
      this.panel?.classList.add('open');
      document.getElementById('btn-rail-terminal')?.classList.add('active');
    }

    close() {
      this.panel?.classList.remove('open');
      document.getElementById('btn-rail-terminal')?.classList.remove('active');
    }

    push(cmd, out, ok, meta) {
      if (!this.body) return;
      const ts = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      this.lines.push({ ts, cmd, out, ok, meta: meta || null });
      if (this.lines.length > this.maxLines) this.lines.shift();
      this.render();
      this.open();
    }

    startLiveJob(jobId, cmd) {
      if (!jobId || this.liveJobs.has(jobId)) return;
      const ts = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const block = { ts, cmd, out: '▶ 启动中…\n', ok: true, live: true, jobId, offset: 0 };
      this.lines.push(block);
      if (this.lines.length > this.maxLines) this.lines.shift();
      this.render();
      this.open();

      const poll = async () => {
        try {
          const r = await fetch('/api/terminal/job?id=' + encodeURIComponent(jobId) + '&offset=' + block.offset).then(x => x.json());
          if (!r.ok) return;
          if (r.output) {
            block.out += r.output;
            block.offset = r.next_offset ?? block.offset;
            this.render();
          }
          if (r.done) {
            block.live = false;
            block.ok = (r.code === 0 || r.code == null);
            if (r.code != null) block.out += `\n[进程结束 code=${r.code}]\n`;
            clearInterval(timer);
            this.liveJobs.delete(jobId);
            this.render();
          }
        } catch (_) {}
      };
      const timer = setInterval(poll, 450);
      poll();
      this.liveJobs.set(jobId, timer);
    }

    pushFromTool(ev) {
      const r = ev.result || {};
      const cmd = r.command || ev.args?.command || ev.label || ev.name || 'shell';
      if (r.background && r.job_id) {
        this.startLiveJob(r.job_id, cmd);
        return;
      }
      const out = (r.stdout || r.output || '') + (r.stderr ? '\n' + r.stderr : '') || (r.error || '');
      if (!out.trim()) return;
      this.push(cmd, out.slice(0, 8000), ev.ok !== false);
    }

    render() {
      if (!this.body) return;
      this.body.innerHTML = this.lines.map(l =>
        `<div class="term-block${l.ok === false ? ' error' : ''}${l.live ? ' live' : ''}">
          <div class="term-head"><span class="term-ts">${esc(l.ts)}</span><span class="term-cmd">${esc(l.cmd)}</span>${l.live ? '<span class="term-live-dot">●</span>' : ''}</div>
          <pre class="term-out">${esc(l.out)}</pre>
        </div>`
      ).join('');
      this.body.scrollTop = this.body.scrollHeight;
    }

    clear() {
      this.lines = [];
      for (const t of this.liveJobs.values()) clearInterval(t);
      this.liveJobs.clear();
      this.render();
    }
  }

  window.JunoTerminal = { TerminalPanel };
})();
