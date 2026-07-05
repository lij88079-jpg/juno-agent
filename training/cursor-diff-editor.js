/** Monaco diff editor — Cursor native diff pattern (agent-trace + EditTool) */
(function () {
  'use strict';

  const MONACO_BASE = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs';
  let loadPromise = null;
  let diffEditor = null;

  function loadMonaco() {
    if (window.monaco) return Promise.resolve(window.monaco);
    if (loadPromise) return loadPromise;
    loadPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = MONACO_BASE + '/loader.js';
      s.onload = () => {
        window.require.config({ paths: { vs: MONACO_BASE } });
        window.require(['vs/editor/editor.main'], () => resolve(window.monaco));
      };
      s.onerror = reject;
      document.head.appendChild(s);
    });
    return loadPromise;
  }

  class DiffEditorPanel {
    constructor() {
      this.wrap = document.getElementById('diff-editor-wrap');
      this.container = document.getElementById('diff-editor-container');
      this.pathEl = document.getElementById('diff-editor-path');
      this.ready = false;
    }

    async show(path) {
      if (!this.wrap || !this.container) return;
      const sid = window.__junoSessionId;
      if (!sid || !path) return;
      this.wrap.classList.add('show');
      this.pathEl && (this.pathEl.textContent = path);
      try {
        const r = await fetch('/api/tools/diff-preview?session_id=' + encodeURIComponent(sid) + '&path=' + encodeURIComponent(path)).then(x => x.json());
        if (!r.ok) {
          this.container.innerHTML = '<p style="padding:1rem;color:#858585">' + (r.error || '无法加载 diff') + '</p>';
          return;
        }
        await loadMonaco();
        if (diffEditor) diffEditor.dispose();
        this.container.innerHTML = '';
        diffEditor = window.monaco.editor.createDiffEditor(this.container, {
          readOnly: true,
          renderSideBySide: true,
          automaticLayout: true,
          theme: 'vs-dark',
          fontSize: 12,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
        });
        const lang = r.language || 'plaintext';
        diffEditor.setModel({
          original: window.monaco.editor.createModel(r.original || '', lang),
          modified: window.monaco.editor.createModel(r.modified || '', lang),
        });
        this.ready = true;
      } catch (e) {
        this.container.innerHTML = '<p style="padding:1rem;color:#f48771">' + e.message + '</p>';
      }
    }

    hide() {
      this.wrap?.classList.remove('show');
    }
  }

  window.JunoDiffEditor = { DiffEditorPanel, loadMonaco };
})();
