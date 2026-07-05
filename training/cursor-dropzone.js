/** Drag & drop — Cursor/VS Code composer pattern (window + composer + textarea) */
(function () {
  let inited = false;
  let dragActive = false;
  let hideTimer = null;

  const TEXT_EXT = new Set([
    '.txt', '.md', '.json', '.py', '.ts', '.tsx', '.js', '.jsx', '.html', '.htm',
    '.css', '.scss', '.csv', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.log',
    '.vue', '.sql', '.rs', '.go', '.java', '.c', '.cpp', '.h', '.xml', '.env', '.sh',
  ]);

  function isFileDrag(e) {
    const dt = e.dataTransfer;
    if (!dt) return false;
    const types = dt.types ? [...dt.types] : [];
    if (types.includes('Files')) return true;
    if (types.includes('application/juno-path') || types.includes('text/juno-path')) return true;
    if (dt.items?.length) {
      for (const it of dt.items) {
        if (it.kind === 'file') return true;
      }
    }
    return false;
  }

  function entryToFile(entry) {
    return new Promise((resolve, reject) => entry.file(resolve, reject));
  }

  async function walkDirectory(entry, prefix, out, depth) {
    if (depth > 8 || out.length > 120) return;
    const reader = entry.createReader();
    const readEntries = () => new Promise((res, rej) => reader.readEntries(res, rej));
    let batch = await readEntries();
    while (batch.length) {
      for (const ent of batch) {
        if (out.length > 120) return;
        if (ent.isFile) {
          const f = await entryToFile(ent);
          const rel = prefix ? prefix + '/' + ent.name : ent.name;
          try { Object.defineProperty(f, 'webkitRelativePath', { value: rel, configurable: true }); } catch (_) {}
          out.push(f);
        } else if (ent.isDirectory) {
          await walkDirectory(ent, prefix ? prefix + '/' + ent.name : ent.name, out, depth + 1);
        }
      }
      batch = await readEntries();
    }
  }

  async function collectFromDataTransfer(dt) {
    const files = [];
    let rootFolder = '';
    const items = dt.items ? [...dt.items] : [];

    for (const item of items) {
      if (item.kind !== 'file') continue;
      const entry = item.webkitGetAsEntry?.();
      if (!entry) continue;
      if (entry.isDirectory) {
        rootFolder = entry.name;
        await walkDirectory(entry, entry.name, files, 0);
      } else if (entry.isFile) {
        files.push(await entryToFile(entry));
      }
    }

    if (!files.length && dt.files?.length) {
      for (const f of dt.files) files.push(f);
    }
    if (!rootFolder && files[0]?.webkitRelativePath?.includes('/')) {
      rootFolder = files[0].webkitRelativePath.split('/')[0];
    }
    return { files, rootFolder };
  }

  function showOverlay() {
    dragActive = true;
    clearTimeout(hideTimer);
    const o = document.getElementById('drop-overlay');
    if (o) {
      o.classList.add('show');
      o.setAttribute('aria-hidden', 'false');
    }
  }

  function hideOverlay() {
    dragActive = false;
    const o = document.getElementById('drop-overlay');
    if (o) {
      o.classList.remove('show');
      o.setAttribute('aria-hidden', 'true');
    }
  }

  function onDragEnter(e) {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    showOverlay();
  }

  function onDragOver(e) {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    showOverlay();
  }

  function onDragLeave(e) {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      if (!dragActive) return;
      hideOverlay();
    }, 120);
  }

  async function onDrop(e) {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragActive = false;
    hideOverlay();
    await handleDrop(e);
  }

  function bindDropTarget(el) {
    if (!el || el.dataset.junoDropBound) return;
    el.dataset.junoDropBound = '1';
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(ev => {
      el.addEventListener(ev, ev === 'drop' ? onDrop : ev === 'dragleave' ? onDragLeave : ev === 'dragover' ? onDragOver : onDragEnter, false);
    });
  }

  async function handleDrop(e) {
    const dt = e.dataTransfer;
    if (!dt) return;

    const junoPath = dt.getData('application/juno-path') || dt.getData('text/juno-path');
    if (junoPath) {
      await attachPath(junoPath);
      return;
    }

    try {
      const { files, rootFolder } = await collectFromDataTransfer(dt);
      if (files.length) {
        if (rootFolder && (files.length > 1 || files[0]?.webkitRelativePath?.includes('/'))) {
          await window.__junoUploadFolderFiles?.(files, rootFolder);
        } else {
          await window.__junoUploadFiles?.(files);
        }
        return;
      }
    } catch (err) {
      window.__junoToast?.('拖放失败：' + err.message);
    }

    const text = (dt.getData('text/plain') || dt.getData('text/uri-list') || '').trim();
    const pathMatch = text.match(/[A-Za-z]:[\\\/][^\s*<>|"]+/);
    if (pathMatch) await attachPath(pathMatch[0].replace(/\//g, '\\'));
  }

  function isAbsPath(s) {
    return !!s && /^[A-Za-z]:[\\/]/.test(s);
  }

  async function attachPath(pathStr) {
    if (window.__junoAttachWorkspacePath) {
      await window.__junoAttachWorkspacePath(pathStr);
    } else if (window.__junoAddContextPath) {
      const label = pathStr.replace(/\\/g, '/').split('/').pop() || pathStr;
      window.__junoAddContextPath({ path: pathStr, label, kind: 'folder' });
      window.__junoToast?.('已附加 @' + label);
    }
  }

  function initPathPaste() {
    const input = document.getElementById('input');
    if (!input || input.dataset.junoPasteBound) return;
    input.dataset.junoPasteBound = '1';
    input.addEventListener('paste', async e => {
      const text = e.clipboardData?.getData('text/plain')?.trim();
      if (!isAbsPath(text)) return;
      e.preventDefault();
      input.value = input.value.replace(text, '').trim();
      await attachPath(text);
    });
    input.addEventListener('drop', onDrop);
    input.addEventListener('dragover', onDragOver);
  }

  function init() {
    if (inited) return;
    inited = true;

    bindDropTarget(window);
    bindDropTarget(document.body);
    bindDropTarget(document.getElementById('drop-overlay'));
    bindDropTarget(document.querySelector('.composer'));
    bindDropTarget(document.querySelector('.composer-box'));
    bindDropTarget(document.querySelector('.composer-inner'));
    bindDropTarget(document.querySelector('.messages-wrap'));
    bindDropTarget(document.querySelector('.chat-panel'));
    bindDropTarget(document.getElementById('input'));

    initPathPaste();
  }

  window.JunoDropzone = { init, handleDrop, attachPath };

  // Auto-init when chat handlers registered (inline script calls init again at end)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      if (window.__junoUploadFiles) init();
    });
  }
})();
