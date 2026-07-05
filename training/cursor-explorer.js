/** File explorer panel — Cursor-style workspace tree */
(function () {
  const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  function icon(type) {
    if (type === 'dir') return '<span class="ex-icon ex-dir">▸</span>';
    return '<span class="ex-icon ex-file">·</span>';
  }

  class ExplorerPanel {
    constructor() {
      this.panel = document.getElementById('explorer-panel');
      this.treeEl = document.getElementById('explorer-tree');
      this.open = false;
      if (!this.panel || !this.treeEl) return;
      this.bind();
    }

    bind() {
      document.getElementById('btn-rail-explorer')?.addEventListener('click', () => this.toggle());
      document.getElementById('explorer-refresh')?.addEventListener('click', () => this.load());
      this.treeEl.addEventListener('click', e => this.onClick(e));
      this.treeEl.addEventListener('dragstart', e => {
        const node = e.target.closest('.ex-node');
        if (!node) return;
        const p = node.dataset.path;
        if (!p) return;
        e.dataTransfer.setData('application/juno-path', p);
        e.dataTransfer.setData('text/juno-path', p);
        e.dataTransfer.effectAllowed = 'copy';
      });
    }

    toggle(force) {
      this.open = typeof force === 'boolean' ? force : !this.open;
      this.panel?.classList.toggle('open', this.open);
      document.getElementById('app-root')?.classList.toggle('explorer-open', this.open);
      document.getElementById('btn-rail-explorer')?.classList.toggle('active', this.open);
      if (this.open) this.load();
    }

    async load(path) {
      if (!this.treeEl) return;
      this.treeEl.innerHTML = '<div class="ex-loading">加载中…</div>';
      try {
        const qs = path ? '?path=' + encodeURIComponent(path) + '&depth=2' : '?depth=2';
        const r = await fetch('/api/tools/tree' + qs).then(x => x.json());
        if (!r.ok && r.error) {
          this.treeEl.innerHTML = `<div class="ex-empty">${esc(r.error)}</div>`;
          return;
        }
        this.treeEl.innerHTML = this.renderNodes(r.children || [], 0);
      } catch (e) {
        this.treeEl.innerHTML = `<div class="ex-empty">${esc(e.message)}</div>`;
      }
    }

    renderNodes(nodes, depth) {
      if (!nodes?.length) return '<div class="ex-empty">空目录</div>';
      return '<ul class="ex-list">' + nodes.map(n => this.renderNode(n, depth)).join('') + '</ul>';
    }

    renderNode(n, depth) {
      const hasKids = n.type === 'dir' && n.children?.length;
      const expanded = depth < 1 && hasKids;
      const kids = hasKids
        ? `<div class="ex-children${expanded ? ' open' : ''}">${this.renderNodes(n.children, depth + 1)}</div>`
        : '';
      return `<li class="ex-node" data-path="${esc(n.path)}" data-type="${esc(n.type)}" draggable="true">
        ${icon(n.type)}<span class="ex-name" title="${esc(n.path)}">${esc(n.name)}</span>
        ${kids}
      </li>`;
    }

    onClick(e) {
      const nameEl = e.target.closest('.ex-name');
      const node = e.target.closest('.ex-node');
      if (!node) return;
      const path = node.dataset.path;
      const type = node.dataset.type;
      const childWrap = node.querySelector(':scope > .ex-children');

      if (e.target.closest('.ex-icon') && childWrap) {
        childWrap.classList.toggle('open');
        return;
      }

      if (type === 'dir') {
        childWrap?.classList.toggle('open');
        return;
      }

      if (type === 'file') {
        this.attachFile(path, node.querySelector('.ex-name')?.textContent || path);
        return;
      }

      if (nameEl && !childWrap) {
        this.load(path);
      } else if (childWrap) {
        childWrap.classList.toggle('open');
      }
    }

    attachFile(path, label) {
      const add = window.__junoAddContextPath;
      if (typeof add === 'function') {
        add({ path, label, kind: 'file' });
        window.__junoToast?.('@' + label + ' 已附加');
        return;
      }
      window.__junoToast?.('已选文件：' + label);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    window.JunoExplorer = new ExplorerPanel();
  });
})();
