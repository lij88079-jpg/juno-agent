/** Cursor-style UI v2 — Review bar, inline runs, edit tracking */
(function () {
  'use strict';

  const esc = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  function basename(p) {
    return String(p || '').replace(/\\/g, '/').split('/').pop() || p || 'file';
  }

  function formatToolDetail(ev) {
    const parts = [];
    if (ev.args && Object.keys(ev.args).length) {
      parts.push('args:\n' + JSON.stringify(ev.args, null, 2));
    }
    if (ev.result) {
      parts.push('result:\n' + JSON.stringify(ev.result, null, 2));
    }
    return parts.join('\n\n');
  }

  function formatDiff(result) {
    if (!result?.diff) return '';
    return result.diff.split('\n').map(line => {
      if (line.startsWith('-')) return `<span class="del">${esc(line)}</span>`;
      if (line.startsWith('+')) return `<span class="add">${esc(line)}</span>`;
      return esc(line);
    }).join('\n');
  }

  function isEditTool(name) {
    return ['str_replace', 'apply_patch', 'write_file'].includes(name);
  }

  function inlineRunPayload(ev) {
    const r = ev.result || {};
    const n = ev.name || '';
    if (n === 'run_shell' && (r.stdout || r.stderr || r.command)) {
      return { cmd: r.command || ev.args?.command || 'shell', out: (r.stdout || '') + (r.stderr ? '\n' + r.stderr : '') };
    }
    if (n === 'read_file' && r.content) {
      return { cmd: 'Read ' + basename(r.path || ev.args?.path), out: r.content };
    }
    if (ev.label && /verify|python|test/i.test(ev.label) && (r.stdout || r.output)) {
      return { cmd: ev.label, out: r.stdout || r.output || JSON.stringify(r) };
    }
    return null;
  }

  function createInlineRun(ev) {
    const payload = inlineRunPayload(ev);
    if (!payload) return null;
    const el = document.createElement('div');
    el.className = 'inline-run';
    el.innerHTML = `
      <div class="inline-run-head">
        <span class="run-icon">▸</span>
        <span class="run-cmd">${esc(payload.cmd)}</span>
        <span class="tool-chevron">▸</span>
      </div>
      <div class="inline-run-body">${esc(payload.out.slice(0, 2000))}${payload.out.length > 2000 ? '…' : ''}</div>`;
    el.querySelector('.inline-run-head').addEventListener('click', () => el.classList.toggle('open'));
    return el;
  }

  function formatHunkLines(hunk) {
    const oldP = (hunk.preview_old || '').split('\n').filter(Boolean);
    const newP = (hunk.preview_new || '').split('\n').filter(Boolean);
    const lines = [...oldP, ...newP];
    return lines.map(line => {
      if (line.startsWith('-')) return `<span class="del">${esc(line)}</span>`;
      if (line.startsWith('+')) return `<span class="add">${esc(line)}</span>`;
      return esc(line);
    }).join('\n');
  }

  function renderUnifiedHunk(hunk, baseLine) {
    const start = baseLine || hunk.old_start || 1;
    const oldL = (hunk.old_string || '').split('\n');
    const newL = (hunk.new_string || '').split('\n');
    let html = '';
    let ln = start;
    oldL.forEach(line => {
      html += `<div class="diff-line del"><span class="ln">${ln}</span><span class="code">${esc(line || ' ')}</span></div>`;
      ln++;
    });
    const newStart = hunk.new_start || start;
    let nln = newStart;
    newL.forEach(line => {
      html += `<div class="diff-line add"><span class="ln">${nln}</span><span class="code">${esc(line || ' ')}</span></div>`;
      nln++;
    });
    return html || formatHunkLines(hunk);
  }

  class SubagentPanel {
    constructor() {
      this.panel = document.getElementById('agents-drawer') || document.getElementById('subagent-panel');
      this.tabsEl = document.getElementById('agents-tabs') || document.getElementById('subagent-tabs');
      this.bodyEl = document.getElementById('agents-body') || document.getElementById('subagent-body');
      this.tasks = [];
      this.active = 0;
    }

    push(event) {
      const id = event.id || `sub-${this.tasks.length}`;
      const kind = event.kind || 'explore';
      const label = (event.label || 'Subagent').replace(/^Finished subagent ·\s*/i, '').replace(/^Subagent ·\s*/i, '').slice(0, 36) || kind;
      let existing = this.tasks.find(t => t.id === id);
      if (existing) {
        existing.label = label || existing.label;
        existing.done = event.state === 'done' || event.phase === 'done';
        if (event.trace?.length) existing.trace = event.trace;
        if (event.summary) existing.summary = event.summary;
      } else {
        existing = { id, label, kind, done: event.state === 'done', trace: event.trace || [], summary: event.summary || '' };
        this.tasks.push(existing);
        this.active = this.tasks.length - 1;
      }
      if (event.phase === 'start') existing.done = false;
      this.render();
      if (event.phase !== 'start') this.open();
    }

    addToolTrace(taskId, ev) {
      const t = this.tasks.find(x => x.id === taskId || x.id.startsWith(taskId));
      if (!t) return;
      t.trace.push(ev);
      if (this.active === this.tasks.indexOf(t)) this.renderBody();
    }

    open() {
      if (!this.tasks.length) this.render();
      this.panel?.classList.add('open');
      document.getElementById('btn-rail-subagent')?.classList.add('active');
      document.getElementById('agents-drawer')?.classList.add('open');
    }

    close() {
      this.panel?.classList.remove('open');
      document.getElementById('btn-rail-subagent')?.classList.remove('active');
      document.getElementById('agents-drawer')?.classList.remove('open');
    }

    toggle() {
      if (this.panel?.classList.contains('open')) this.close();
      else this.open();
    }

    render() {
      if (!this.tabsEl || !this.bodyEl) return;
      if (!this.tasks.length) {
        this.tabsEl.innerHTML = '';
        this.bodyEl.innerHTML = '<p class="agents-empty">暂无子代理任务。Agent 调用 <code>task</code> 工具后会在此显示。</p>';
        return;
      }
      this.tabsEl.innerHTML = this.tasks.map((t, i) =>
        `<button type="button" class="subagent-tab${i === this.active ? ' active' : ''}" data-i="${i}">${esc(t.kind)} · ${esc(t.label)}${t.done ? ' ✓' : ''}</button>`
      ).join('');
      this.tabsEl.querySelectorAll('.subagent-tab').forEach(btn => {
        btn.addEventListener('click', () => {
          this.active = parseInt(btn.dataset.i, 10);
          this.render();
        });
      });
      this.renderBody();
    }

    renderBody() {
      const t = this.tasks[this.active];
      if (!t || !this.bodyEl) return;
      let html = '';
      if (t.summary) html += `<div class="cursor-tool done"><span class="cursor-tool-icon">✓</span><span class="cursor-tool-label">${esc(t.summary.slice(0, 200))}</span></div>`;
      if (!t.trace.length && !t.summary) {
        this.bodyEl.innerHTML = `<div class="cursor-tool ${t.done ? 'done' : 'active'}"><span class="cursor-tool-icon">${t.done ? '✓' : '◐'}</span><span class="cursor-tool-label">${esc(t.label || 'Subagent')}</span></div>`;
        return;
      }
      html += t.trace.map(ev =>
        `<div class="cursor-tool ${ev.ok === false ? 'error' : 'done'}"><span class="cursor-tool-icon">◆</span><span class="cursor-tool-label">${esc(ev.label || ev.name || 'tool')}</span></div>`
      ).join('');
      this.bodyEl.innerHTML = html;
    }
  }

  class EditReviewBar {
    constructor() {
      this.bar = document.getElementById('review-bar');
      this.drawer = document.getElementById('review-drawer');
      this.filesEl = document.getElementById('review-files-count');
      this.listEl = document.getElementById('review-file-list');
      this.edits = new Map();
      this._activePath = '';
      this.bind();
    }

    bind() {
      document.getElementById('review-btn-open')?.addEventListener('click', () => this.openDrawer());
      document.getElementById('review-btn-undo')?.addEventListener('click', () => this.undoAll());
      document.getElementById('review-btn-keep')?.addEventListener('click', () => this.keepAll());
      document.getElementById('review-btn-review')?.addEventListener('click', () => this.openDrawer());
      document.getElementById('review-drawer-close')?.addEventListener('click', () => this.closeDrawer());
      this.drawer?.addEventListener('click', e => { if (e.target === this.drawer) this.closeDrawer(); });
      this.bar?.querySelector('.review-bar-files')?.addEventListener('click', () => this.openDrawer());
    }

    ingestTrace(trace) {
      if (!trace?.length) return;
      for (const ev of trace) {
        if (!isEditTool(ev.name)) continue;
        const p = ev.result?.path || ev.args?.path;
        if (!p) continue;
        const prev = this.edits.get(p);
        const hunks = ev.result?.hunks || prev?.hunks || [];
        this.edits.set(p, {
          path: p,
          name: basename(p),
          diff: ev.result?.diff || prev?.diff || '',
          hunks,
          tool: ev.name,
          ev,
        });
      }
      this.render();
    }

    async loadFromServer() {
      const sid = window.__junoSessionId;
      if (!sid) return;
      try {
        const r = await fetch('/api/session/edits?session_id=' + encodeURIComponent(sid)).then(x => x.json());
        for (const it of r.edits || []) {
          if (!it.path) continue;
          this.edits.set(it.path, {
            path: it.path,
            name: basename(it.path),
            diff: it.diff || '',
            hunks: it.hunks || [],
            tool: 'str_replace',
          });
        }
        this.render();
      } catch (_) {}
    }

    renderHunks(it) {
      const hunks = it.hunks || [];
      if (!hunks.length) {
        return it.diff ? `<div class="review-file-diff">${formatDiff({ diff: it.diff })}</div>` : `<div class="review-file-diff">${esc('（无 diff 预览）')}</div>`;
      }
      return hunks.map((h, idx) => {
        const st = h.status || 'pending';
        const baseLine = h.old_start || (idx * 10 + 1);
        return `<div class="hunk-block ${st}" data-hunk="${esc(h.id)}" data-path="${esc(it.path)}">
          <div class="hunk-head">
            <span>L${baseLine}${h.old_end ? '–' + h.old_end : ''} · ${esc(h.tag || 'edit')}</span>
            <span class="hunk-actions">
              ${st === 'pending' ? `<button type="button" class="reject" data-hunk="${esc(h.id)}" data-path="${esc(it.path)}">Reject</button>
              <button type="button" class="accept" data-hunk="${esc(h.id)}" data-path="${esc(it.path)}">Accept</button>` : `<span>${esc(st)}</span>`}
            </span>
          </div>
          <div class="inline-diff">${renderUnifiedHunk(h, baseLine)}</div>
        </div>`;
      }).join('');
    }

    ingestFromMessages(messages) {
      this.edits.clear();
      for (const m of messages || []) {
        if (m.trace) this.ingestTrace(m.trace);
      }
      this.render();
    }

    render() {
      const n = this.edits.size;
      if (!this.bar) return;
      this.bar.classList.toggle('show', n > 0);
      if (this.filesEl) this.filesEl.textContent = n + ' 个文件';
      if (!this.listEl) return;
      this.listEl.innerHTML = [...this.edits.values()].map(it => `
        <div class="review-file-item open${this._activePath === it.path ? ' selected' : ''}" data-path="${esc(it.path)}">
          <div class="review-file-head">
            <span>✎</span><span class="fname">${esc(it.name)}</span>
            <span class="review-file-actions">
              <button type="button" class="reject" data-path="${esc(it.path)}">Reject file</button>
              <button type="button" class="accept" data-path="${esc(it.path)}">Accept file</button>
            </span>
            <span class="tool-chevron">▸</span>
          </div>
          ${this.renderHunks(it)}
        </div>`).join('');
      this.listEl.querySelectorAll('.review-file-head .fname, .review-file-head .tool-chevron').forEach(h => {
        h.addEventListener('click', (e) => {
          if (e.target.closest('.review-file-actions')) return;
          const item = h.closest('.review-file-item');
          const p = item?.dataset.path;
          if (p) {
            this._activePath = p;
            window.JunoCursorUI?.diffEditor?.show(p);
            this.listEl.querySelectorAll('.review-file-item').forEach(el => el.classList.toggle('selected', el.dataset.path === p));
          }
          item?.classList.toggle('open');
        });
      });
      this.listEl.querySelectorAll('.review-file-actions .reject').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); this.rejectOne(btn.dataset.path); });
      });
      this.listEl.querySelectorAll('.review-file-actions .accept').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); this.acceptOne(btn.dataset.path); });
      });
      this.listEl.querySelectorAll('.hunk-head .reject').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); this.hunkAction(btn.dataset.path, btn.dataset.hunk, 'reject'); });
      });
      this.listEl.querySelectorAll('.hunk-head .accept').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); this.hunkAction(btn.dataset.path, btn.dataset.hunk, 'accept'); });
      });
    }

    async hunkAction(path, hunkId, action) {
      const sid = window.__junoSessionId;
      if (!sid || !path || !hunkId) return;
      const r = await fetch('/api/session/edits/hunk', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid, path, hunk_id: hunkId, action }),
      }).then(x => x.json());
      if (r.ok) {
        const it = this.edits.get(path);
        if (it?.hunks) {
          const h = it.hunks.find(x => x.id === hunkId);
          if (h) h.status = action === 'accept' ? 'accepted' : 'rejected';
        }
        this.render();
        window.__junoToast?.(`${action === 'accept' ? 'Accept' : 'Reject'} hunk · ${basename(path)}`);
        if (action === 'reject') await this.loadFromServer();
      } else window.__junoToast?.(r.error || 'hunk 操作失败');
    }

    async rejectOne(path) {
      const sid = window.__junoSessionId;
      if (!sid || !path) return;
      const r = await fetch('/api/session/edits/revert', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid, paths: [path] }),
      }).then(x => x.json());
      if (r.ok) {
        this.edits.delete(path);
        this.render();
        window.__junoToast?.('已 Reject · ' + basename(path));
      }
    }

    acceptOne(path) {
      this.edits.delete(path);
      this.render();
      window.__junoToast?.('已 Accept · ' + basename(path));
    }

    openDrawer() {
      this.drawer?.classList.add('show');
      const first = [...this.edits.values()][0];
      if (first?.path) {
        this._activePath = first.path;
        window.JunoCursorUI?.diffEditor?.show(first.path);
      }
    }
    closeDrawer() {
      this.drawer?.classList.remove('show');
    }

    async undoAll() {
      const sid = window.__junoSessionId;
      if (!sid) return;
      try {
        const r = await fetch('/api/session/edits/revert', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sid }),
        }).then(x => x.json());
        if (r.ok) {
          this.edits.clear();
          this.render();
          window.__junoToast?.('已还原 ' + (r.reverted?.length || 0) + ' 个文件');
        } else window.__junoToast?.(r.error || '还原失败');
      } catch (e) { window.__junoToast?.(e.message); }
    }

    async keepAll() {
      const sid = window.__junoSessionId;
      if (!sid) return;
      try {
        await fetch('/api/session/edits/keep', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sid }),
        });
        this.edits.clear();
        this.render();
        window.__junoToast?.('已保留全部修改');
      } catch (e) { window.__junoToast?.(e.message); }
    }
  }

  window.JunoCursorUI = {
    reviewBar: null,
    subagentPanel: null,
    diffEditor: null,
    terminal: null,
    cmdk: null,

    init() {
      this.reviewBar = new EditReviewBar();
      this.subagentPanel = new SubagentPanel();
      this.diffEditor = window.JunoDiffEditor ? new JunoDiffEditor.DiffEditorPanel() : null;
      this.terminal = window.JunoTerminal ? new JunoTerminal.TerminalPanel() : null;
      this.cmdk = window.JunoCmdK ? new JunoCmdK.CmdKModal() : null;
      this.initIconRail();
      window.__junoBindAllButtons?.();
      this.loadMcpBadge();
      this.loadOpenFilesBar();
      document.getElementById('agents-drawer-close')?.addEventListener('click', () => {
        this.subagentPanel?.close();
      });
      document.getElementById('diff-editor-close')?.addEventListener('click', () => this.diffEditor?.hide());
      document.getElementById('terminal-close')?.addEventListener('click', () => {
        document.getElementById('terminal-panel')?.classList.remove('open');
        document.getElementById('btn-rail-terminal')?.classList.remove('active');
      });
      document.getElementById('terminal-clear')?.addEventListener('click', () => this.terminal?.clear());
      document.addEventListener('click', (e) => {
        const app = document.getElementById('app-root');
        if (!app?.classList.contains('sidebar-open')) return;
        const sb = document.getElementById('sidebar');
        if (sb && !sb.contains(e.target)
          && !e.target.closest('#btn-rail-history')
          && !e.target.closest('#btn-panel-history')
          && !e.target.closest('#btn-panel-chat')
          && !e.target.closest('#btn-panel-title')) {
          window.__junoCloseSidebar?.();
        }
      });
    },

    initIconRail() {
      /* Rail buttons bound in chat.html bindAllButtons() */
    },

    async loadOpenFilesBar() {
      const bar = document.getElementById('open-files-bar');
      if (!bar) return;
      try {
        const ctx = await fetch('/api/context/status').then(x => x.json());
        const files = ctx.open_files || [];
        const active = ctx.active_file || '';
        if (!files.length && !active) {
          bar.classList.remove('show');
          bar.innerHTML = '';
          return;
        }
        const chips = [];
        if (active && !files.some(f => (f.path || f.name) === active)) {
          chips.push({ path: active, label: basename(active), active: true });
        }
        files.forEach(f => {
          const p = f.path || f.name || '';
          if (!p) return;
          chips.push({ path: p, label: basename(p), active: p === active });
        });
        bar.innerHTML = chips.map(c =>
          `<button type="button" class="open-file-chip${c.active ? ' active' : ''}" data-path="${esc(c.path)}" title="${esc(c.path)}">${esc(c.label)}</button>`
        ).join('');
        bar.classList.add('show');
        bar.querySelectorAll('.open-file-chip').forEach(btn => {
          btn.addEventListener('click', () => {
            const p = btn.dataset.path;
            if (p) {
              this.diffEditor?.show(p);
              this.reviewBar?.openDrawer();
            }
          });
        });
      } catch (_) {
        bar.classList.remove('show');
      }
    },

    async loadMcpBadge() {
      try {
        const r = await fetch('/api/mcp/servers').then(x => x.json());
        const names = (r.servers || []).map(s => s.id).join(', ');
        const el = document.getElementById('mcp-badge');
        if (el && names) {
          el.textContent = 'MCP: ' + names;
          el.classList.add('mcp-badge');
          if (!el.dataset.bound) {
            el.dataset.bound = '1';
            el.title = 'MCP 服务：' + names;
            el.addEventListener('click', () => window.__junoToast?.('MCP: ' + names));
          }
        }
      } catch (_) {}
    },

    onSubagent(event) {
      this.subagentPanel?.push(event);
    },

    enhanceToolEl(el, ev) {
      if (!el || el.dataset.enhanced) return;
      el.dataset.enhanced = '1';
      const chevron = document.createElement('span');
      chevron.className = 'tool-chevron';
      chevron.textContent = '▸';
      el.appendChild(chevron);

      const detail = document.createElement('div');
      detail.className = 'tool-detail';
      detail.textContent = formatToolDetail(ev);
      el.appendChild(detail);

      if (ev.result?.diff) {
        const diff = document.createElement('div');
        diff.className = 'tool-diff';
        diff.innerHTML = formatDiff(ev.result);
        detail.appendChild(diff);
      }

      el.addEventListener('click', (e) => {
        if (e.target.closest('.inline-run')) return;
        el.classList.toggle('expanded');
      });

      const run = createInlineRun(ev);
      if (run) el.after(run);

      if (ev.name === 'run_shell' || ev.result?.command) {
        window.JunoCursorUI.terminal?.pushFromTool(ev);
      }
    },

    replayTrace(msgBody, trace) {
      if (!trace?.length || !msgBody) return;
      const stack = document.createElement('div');
      stack.className = 'tool-stack trace-replay finished';
      let lastFinished = '';
      trace.forEach((ev, i) => {
        if (ev.label) lastFinished = ev.label;
        const el = document.createElement('div');
        el.className = 'cursor-tool ' + (ev.ok === false ? 'error' : 'done');
        el.dataset.toolId = ev.id || `replay-${i}`;
        el.innerHTML = `<span class="cursor-tool-icon">◆</span><span class="cursor-tool-label">${esc(ev.label || ev.name || 'tool')}</span><span class="cursor-tool-tag">${esc(ev.name || 'tool')}</span>`;
        stack.appendChild(el);
        window.JunoCursorUI.enhanceToolEl(el, ev);
      });
      const fin = document.createElement('div');
      fin.className = 'finished-line';
      fin.innerHTML = `<span class="fin-check">✓</span><span>Finished ${esc(lastFinished || 'task')}</span>`;
      const bubble = msgBody.querySelector('.bubble');
      msgBody.insertBefore(fin, bubble);
      msgBody.insertBefore(stack, fin);
    },

    onTraceDone(trace) {
      window.JunoCursorUI.reviewBar?.ingestTrace(trace);
    },

    onSessionMessages(messages) {
      window.JunoCursorUI.reviewBar?.ingestFromMessages(messages);
      window.JunoCursorUI.reviewBar?.loadFromServer();
      window.JunoCursorUI.loadOpenFilesBar?.();
    },

    highlightCodeBlocks(root) {
      if (!window.hljs) return;
      root.querySelectorAll('pre code').forEach(block => {
        try { window.hljs.highlightElement(block); } catch (_) {}
      });
    },

    linkCitations(root) {
      root.querySelectorAll('.bubble').forEach(bubble => {
        bubble.innerHTML = bubble.innerHTML.replace(
          /(`?)([\w./\\-]+):(\d+(?:-\d+)?)\1/g,
          (_, _q, path, lines) => `<span class="citation-link" data-path="${esc(path)}" data-line="${esc(lines)}">${esc(path)}:${esc(lines)}</span>`
        );
      });
    },

    async loadTodos() {
      const panel = document.getElementById('todo-inline');
      if (!panel) return;
      try {
        const r = await fetch('/api/todos').then(x => x.json());
        const todos = r.todos || [];
        if (!todos.length) { panel.classList.remove('show'); return; }
        panel.innerHTML = '<h4>Todos</h4><ul>' + todos.map(t =>
          `<li class="${t.done ? 'done' : ''}"><span>${t.done ? '✓' : '○'}</span> ${esc(t.content || '')}</li>`
        ).join('') + '</ul>';
        panel.classList.add('show');
      } catch (_) {}
    },
  };

  function initMentionPicker() {
    const input = document.getElementById('input');
    const menu = document.getElementById('mention-menu');
    if (!input || !menu) return;

    let items = [], activeIdx = -1, debounce = null, pickMode = 'files';
    const contextBar = document.getElementById('context-chips');
    const contextPaths = [];

    menu.innerHTML = '<div class="mention-tabs">'
      + '<button type="button" class="mention-tab active" data-m="files">@file</button>'
      + '<button type="button" class="mention-tab" data-m="codebase">@codebase</button>'
      + '<button type="button" class="mention-tab" data-m="rules">@Rules</button>'
      + '<button type="button" class="mention-tab" data-m="docs">@Docs</button>'
      + '<button type="button" class="mention-tab" data-m="folder">@Folder</button>'
      + '<button type="button" class="mention-tab" data-m="git">@Git</button>'
      + '</div><div id="mention-list"></div>';
    const listEl = document.getElementById('mention-list');
    menu.querySelectorAll('.mention-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        pickMode = tab.dataset.m || 'files';
        menu.querySelectorAll('.mention-tab').forEach(t => t.classList.toggle('active', t.dataset.m === pickMode));
        fetchItems(input.value.slice(input.value.lastIndexOf('@') + 1));
      });
    });

    function renderContextChips() {
      if (window.__junoRenderComposerPills) {
        window.__junoRenderComposerPills();
        return;
      }
      if (!contextBar) return;
      const kindIcon = k => ({ codebase: '⌕', rules: '§', docs: '◈', folder: '▤', git: '⎇', web: '◉' }[k] || '@');
      contextBar.innerHTML = contextPaths.map((p, i) =>
        `<span class="context-chip">${kindIcon(p.kind)}${esc(p.label)}<button type="button" data-i="${i}">×</button></span>`
      ).join('');
      contextBar.querySelectorAll('button').forEach(b => {
        b.onclick = () => { contextPaths.splice(+b.dataset.i, 1); renderContextChips(); };
      });
    }

    window.__junoContextPaths = () => contextPaths.slice();
    window.__junoRemoveContextPath = (i) => {
      if (i >= 0 && i < contextPaths.length) {
        contextPaths.splice(i, 1);
        renderContextChips();
      }
    };
    window.__junoClearContext = () => { contextPaths.length = 0; renderContextChips(); };
    window.__junoAddContextPath = (item) => {
      if (!item?.path) return;
      if (!contextPaths.some(c => c.path === item.path && c.kind === (item.kind || 'file'))) {
        contextPaths.push({ path: item.path, label: item.label || item.name || item.path, kind: item.kind || 'file', snippet: item.snippet });
      }
      renderContextChips();
    };

    async function fetchItems(q) {
      if (pickMode === 'codebase') {
        const r = await fetch('/api/index/search?q=' + encodeURIComponent(q || 'agent') + '&k=10').then(x => x.json()).catch(() => ({ hits: [] }));
        items = (r.hits || []).map(h => ({
          path: h.path, label: (h.path || '').split(/[/\\]/).pop() || h.path,
          name: h.path, kind: 'codebase', snippet: (h.text || '').slice(0, 72),
        }));
      } else if (pickMode === 'git') {
        const r = await fetch('/api/mention/sources?kind=git&limit=10').then(x => x.json()).catch(() => ({ items: [] }));
        const w = await fetch('/api/mention/sources?kind=web&limit=5').then(x => x.json()).catch(() => ({ items: [] }));
        items = [...(r.items || []), ...(w.items || [])];
      } else {
        const r = await fetch('/api/mention/sources?kind=' + encodeURIComponent(pickMode) + '&q=' + encodeURIComponent(q || '') + '&limit=40').then(x => x.json()).catch(() => ({ items: [] }));
        items = r.items || [];
      }
      activeIdx = items.length ? 0 : -1;
      renderMenu();
    }

    function renderMenu() {
      if (!items.length) { menu.classList.remove('show'); return; }
      listEl.innerHTML = items.map((it, i) =>
        `<div class="mention-item${i === activeIdx ? ' active' : ''}" data-idx="${i}">${esc(it.label || it.name)}<small>${esc(it.snippet || it.path || '')}</small></div>`
      ).join('');
      menu.classList.add('show');
    }

    function insertMention(it) {
      const val = input.value;
      const at = val.lastIndexOf('@');
      if (at >= 0) input.value = val.slice(0, at).trimEnd();
      if (!contextPaths.some(c => c.path === it.path && c.kind === (it.kind || 'file'))) {
        contextPaths.push({ path: it.path, label: it.label || it.name, kind: it.kind || 'file' });
      }
      renderContextChips();
      menu.classList.remove('show');
      input.focus();
    }

    listEl.addEventListener('click', e => {
      const el = e.target.closest('.mention-item');
      if (!el) return;
      insertMention(items[parseInt(el.dataset.idx, 10)]);
    });

    input.addEventListener('input', () => {
      const val = input.value;
      const at = val.lastIndexOf('@');
      if (at < 0 || at < val.length - 80) { menu.classList.remove('show'); return; }
      const q = val.slice(at + 1);
      if (/\s/.test(q)) { menu.classList.remove('show'); return; }
      if (q.toLowerCase().startsWith('codebase')) { pickMode = 'codebase'; menu.querySelector('[data-m=codebase]')?.click(); return; }
      if (q.toLowerCase().startsWith('rules')) { pickMode = 'rules'; menu.querySelector('[data-m=rules]')?.click(); return; }
      if (q.toLowerCase().startsWith('docs')) { pickMode = 'docs'; menu.querySelector('[data-m=docs]')?.click(); return; }
      if (q.toLowerCase().startsWith('folder')) { pickMode = 'folder'; menu.querySelector('[data-m=folder]')?.click(); return; }
      if (q.toLowerCase().startsWith('git')) { pickMode = 'git'; menu.querySelector('[data-m=git]')?.click(); return; }
      clearTimeout(debounce);
      debounce = setTimeout(() => fetchItems(q), 180);
    });

    input.addEventListener('keydown', e => {
      if (!menu.classList.contains('show')) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); activeIdx = Math.min(activeIdx + 1, items.length - 1); renderMenu(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); renderMenu(); }
      else if (e.key === 'Enter' && activeIdx >= 0) { e.preventDefault(); insertMention(items[activeIdx]); }
      else if (e.key === 'Escape') menu.classList.remove('show');
    });

    document.addEventListener('click', e => {
      if (!menu.contains(e.target) && e.target !== input) menu.classList.remove('show');
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    window.JunoCursorUI.init();
    initMentionPicker();
    window.JunoCursorUI.loadTodos();
    setInterval(() => window.JunoCursorUI.loadTodos(), 15000);
    document.body.classList.add('messages-dense');
    document.querySelector('.composer')?.classList.add('composer-v2');
  });
})();
