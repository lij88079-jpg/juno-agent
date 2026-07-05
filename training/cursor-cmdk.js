/** Cmd+K inline edit — AgentZ / Cursor inline edit pattern */
(function () {
  'use strict';

  class CmdKModal {
    constructor() {
      this.modal = document.getElementById('cmdk-modal');
      this.input = document.getElementById('cmdk-input');
      this.fileEl = document.getElementById('cmdk-file');
      this.selectionEl = document.getElementById('cmdk-selection');
      this.path = '';
      this.selection = '';
      this.bind();
    }

    bind() {
      document.getElementById('cmdk-close')?.addEventListener('click', () => this.close());
      this.modal?.addEventListener('click', e => { if (e.target === this.modal) this.close(); });
      document.getElementById('cmdk-submit')?.addEventListener('click', () => this.submit());
      this.input?.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.submit(); }
        if (e.key === 'Escape') this.close();
      });
      document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          this.open();
        }
      });
    }

    async open(opts = {}) {
      this.path = opts.path || '';
      this.selection = opts.selection || '';
      if (!this.path) {
        try {
          const ctx = await fetch('/api/context/status').then(x => x.json());
          this.path = ctx.active_file || (ctx.open_files?.[0]?.path) || '';
          this.selection = ctx.selection || this.selection;
        } catch (_) {}
      }
      if (this.fileEl) this.fileEl.textContent = this.path || '（未指定文件，将仅按指令回复）';
      if (this.selectionEl) {
        this.selectionEl.textContent = this.selection ? this.selection.slice(0, 400) : '（无选区 · 可编辑整个文件或输入指令）';
        this.selectionEl.style.display = this.selection ? 'block' : 'none';
      }
      this.modal?.classList.add('show');
      this.input?.focus();
    }

    close() {
      this.modal?.classList.remove('show');
      if (this.input) this.input.value = '';
    }

    async submit() {
      const instruction = (this.input?.value || '').trim();
      if (!instruction) return;
      const sid = window.__junoSessionId;
      window.__junoToast?.('Inline edit 执行中…');
      try {
        const r = await fetch('/api/inline-edit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sid,
            path: this.path,
            selection: this.selection,
            instruction,
          }),
        }).then(x => x.json());
        if (r.ok) {
          window.__junoToast?.('Inline edit 完成 · ' + (r.path || ''));
          window.JunoCursorUI?.reviewBar?.loadFromServer();
          if (r.path) window.JunoCursorUI?.diffEditor?.show(r.path);
          this.close();
        } else window.__junoToast?.(r.error || '失败');
      } catch (e) {
        window.__junoToast?.(e.message);
      }
    }
  }

  window.JunoCmdK = { CmdKModal };
})();
