"""
LAN File Manager Server
-----------------------
A full file-manager experience in the browser — search, folder navigation,
grid/list view, sort, drag-and-drop upload, delete, rename, and inline preview.
Supports HTTP + optional HTTPS (auto self-signed cert).

Usage:
    python lan_server.py                   # HTTP only, port 8000
    python lan_server.py --https           # HTTP (8000) + HTTPS (8443)
    python lan_server.py --https-only      # HTTPS only on 8443
    python lan_server.py --port 9000       # custom port
    python lan_server.py --dir /my/folder  # share a specific folder

Access from LAN peers:  http://<HOST_IP>:8000
"""

import argparse, html, json, mimetypes, os, shutil, socket, ssl, sys
import threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── Globals ───────────────────────────────────────────────────────────────────
SHARED_DIR   = Path("/home/nilesh/Downloads")
UPLOAD_DIR   = SHARED_DIR / "uploads"
_HTTP_PORT   = 8000
_HTTPS_PORT  = None

def ensure_dirs():
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except: return "127.0.0.1"

def human_size(n):
    for u in ("B","KB","MB","GB"):
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def safe_path(rel):
    name = urllib.parse.unquote(rel.lstrip("/"))
    target = (SHARED_DIR / name).resolve()
    try:
        target.relative_to(SHARED_DIR.resolve()); return target
    except ValueError: return None

def file_meta(p: Path):
    st   = p.stat()
    ext  = p.suffix.lower().lstrip(".")
    mime = mimetypes.guess_type(p.name)[0] or ""
    return {
        "name":     p.name,
        "rel":      str(p.relative_to(SHARED_DIR)),
        "size":     st.st_size,
        "size_h":   human_size(st.st_size),
        "mtime":    int(st.st_mtime),
        "mtime_h":  time.strftime("%d %b %Y, %H:%M", time.localtime(st.st_mtime)),
        "is_dir":   p.is_dir(),
        "ext":      ext,
        "mime":     mime,
        "previewable": mime.startswith(("image/","video/","audio/","text/")) or ext in ("pdf",),
    }

def list_dir(rel_dir=""):
    base = safe_path(rel_dir) if rel_dir else SHARED_DIR.resolve()
    if base is None or not base.is_dir(): return []
    items = []
    for p in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try: items.append(file_meta(p))
        except: pass
    return items

def generate_self_signed_cert(ip):
    import subprocess, tempfile, os
    tmp  = tempfile.mkdtemp()
    cert = os.path.join(tmp, "server.crt")
    key  = os.path.join(tmp, "server.key")
    cmd  = ["openssl","req","-x509","-newkey","rsa:2048","-keyout",key,"-out",cert,
            "-days","365","-nodes","-subj",f"/CN={ip}",
            "-addext",f"subjectAltName=IP:{ip},IP:127.0.0.1"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print("  ✗ openssl error:", r.stderr.decode()); sys.exit(1)
    print(f"  ✓ Self-signed cert: {cert}")
    return cert, key

# ── Full HTML page ─────────────────────────────────────────────────────────────
def render_page(host_ip, http_port, https_port):
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LAN File Manager</title>
<style>
:root {
  --bg: #f0f2f5; --surface: #ffffff; --border: #e2e5ea;
  --text: #1a1a2e; --muted: #6b7280; --accent: #4f46e5;
  --accent-light: #eef2ff; --danger: #dc2626; --danger-light: #fef2f2;
  --success: #16a34a; --success-light: #f0fdf4;
  --warn: #d97706; --warn-light: #fffbeb;
  --radius: 10px; --shadow: 0 1px 3px rgba(0,0,0,.08);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     background:var(--bg);color:var(--text);font-size:14px;min-height:100vh}
/* ── Header ── */
header{background:var(--surface);border-bottom:1px solid var(--border);
       padding:0 24px;height:56px;display:flex;align-items:center;gap:12px;
       position:sticky;top:0;z-index:100}
.logo{font-size:20px}
header h1{font-size:16px;font-weight:700;flex:1}
.pill{font-size:11px;padding:2px 9px;border-radius:99px;font-weight:600}
.pill-green{background:#dcfce7;color:#15803d}
.pill-blue{background:#dbeafe;color:#1d4ed8}
/* ── Toolbar ── */
.toolbar{display:flex;align-items:center;gap:8px;padding:16px 24px;flex-wrap:wrap}
.search-wrap{position:relative;flex:1;min-width:200px;max-width:360px}
.search-wrap input{width:100%;padding:7px 12px 7px 34px;border:1px solid var(--border);
  border-radius:8px;font-size:13px;background:var(--surface);outline:none}
.search-wrap input:focus{border-color:var(--accent)}
.search-icon{position:absolute;left:10px;top:50%;transform:translateY(-50%);
  color:var(--muted);font-size:15px;pointer-events:none}
.btn{padding:7px 14px;border:1px solid var(--border);border-radius:8px;
     background:var(--surface);cursor:pointer;font-size:12px;font-weight:500;
     display:inline-flex;align-items:center;gap:5px;transition:background .15s}
.btn:hover{background:#f3f4f6}
.btn-accent{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn-accent:hover{background:#4338ca}
.btn-danger{color:var(--danger);border-color:#fca5a5}
.btn-danger:hover{background:var(--danger-light)}
.sort-select{padding:7px 10px;border:1px solid var(--border);border-radius:8px;
  font-size:12px;background:var(--surface);cursor:pointer}
.view-toggle{display:flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.view-btn{padding:6px 10px;background:var(--surface);border:none;cursor:pointer;font-size:14px}
.view-btn.active{background:var(--accent-light);color:var(--accent)}
/* ── Breadcrumb ── */
.breadcrumb{padding:0 24px 12px;display:flex;align-items:center;gap:4px;
  font-size:12px;color:var(--muted);flex-wrap:wrap}
.breadcrumb a{color:var(--accent);text-decoration:none}
.breadcrumb a:hover{text-decoration:underline}
.breadcrumb span{color:var(--muted)}
/* ── Stats bar ── */
.stats-bar{padding:0 24px 14px;display:flex;gap:16px;font-size:12px;color:var(--muted)}
.stats-bar b{color:var(--text)}
/* ── Drop zone ── */
.dropzone{margin:0 24px 16px;border:2px dashed var(--border);border-radius:var(--radius);
  padding:20px;text-align:center;transition:all .2s;background:var(--surface)}
.dropzone.drag-over{border-color:var(--accent);background:var(--accent-light)}
.dropzone p{color:var(--muted);font-size:13px;margin-bottom:10px}
.dropzone input[type=file]{display:none}
.progress-bar{height:4px;background:#e5e7eb;border-radius:2px;margin-top:10px;display:none}
.progress-fill{height:100%;background:var(--accent);border-radius:2px;width:0%;transition:width .3s}
/* ── Grid view ── */
#file-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
  gap:12px;padding:0 24px 24px}
.file-card{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:14px 10px;text-align:center;
  cursor:pointer;transition:box-shadow .15s,border-color .15s;position:relative}
.file-card:hover{box-shadow:0 4px 12px rgba(0,0,0,.1);border-color:#c7d2fe}
.file-card.selected{border-color:var(--accent);background:var(--accent-light)}
.file-icon{font-size:36px;margin-bottom:8px;line-height:1}
.file-card .fname{font-size:12px;font-weight:500;word-break:break-word;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.file-card .fmeta{font-size:11px;color:var(--muted);margin-top:4px}
.file-card .card-actions{display:none;position:absolute;top:6px;right:6px;gap:3px}
.file-card:hover .card-actions{display:flex}
.icon-btn{width:24px;height:24px;border:1px solid var(--border);border-radius:5px;
  background:var(--surface);cursor:pointer;font-size:12px;display:flex;
  align-items:center;justify-content:center}
.icon-btn:hover{background:#f3f4f6}
/* ── List view ── */
#file-list{display:none;padding:0 24px 24px}
.list-header{display:grid;grid-template-columns:1fr 90px 140px 110px;
  gap:8px;padding:6px 12px;font-size:11px;font-weight:600;
  color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.file-row{display:grid;grid-template-columns:1fr 90px 140px 110px;
  gap:8px;align-items:center;padding:8px 12px;background:var(--surface);
  border:1px solid var(--border);border-radius:8px;margin-bottom:4px;
  cursor:pointer;transition:background .1s}
.file-row:hover{background:#f9fafb}
.file-row.selected{background:var(--accent-light);border-color:var(--accent)}
.row-name{display:flex;align-items:center;gap:8px;font-weight:500;font-size:13px;min-width:0}
.row-name span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row-size{font-size:12px;color:var(--muted);text-align:right}
.row-date{font-size:12px;color:var(--muted)}
.row-actions{display:flex;gap:4px;justify-content:flex-end}
/* ── Empty state ── */
.empty-state{text-align:center;padding:60px 24px;color:var(--muted)}
.empty-state .big{font-size:48px;margin-bottom:12px}
.empty-state p{font-size:14px}
/* ── Context menu ── */
.ctx-menu{position:fixed;background:var(--surface);border:1px solid var(--border);
  border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.12);
  padding:6px;min-width:160px;z-index:999;display:none}
.ctx-menu.show{display:block}
.ctx-item{padding:7px 12px;border-radius:6px;cursor:pointer;display:flex;
  align-items:center;gap:8px;font-size:13px}
.ctx-item:hover{background:#f3f4f6}
.ctx-item.danger{color:var(--danger)}
.ctx-item.danger:hover{background:var(--danger-light)}
.ctx-sep{height:1px;background:var(--border);margin:4px 0}
/* ── Preview modal ── */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:200;
  display:none;align-items:center;justify-content:center;padding:20px}
.modal-bg.show{display:flex}
.modal{background:var(--surface);border-radius:14px;max-width:90vw;max-height:90vh;
  overflow:hidden;display:flex;flex-direction:column;min-width:320px}
.modal-head{padding:14px 18px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:10px}
.modal-head h3{flex:1;font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.modal-body{padding:16px;overflow:auto;flex:1;display:flex;align-items:center;justify-content:center}
.modal-body img,.modal-body video,.modal-body audio{max-width:100%;max-height:70vh;border-radius:8px}
.modal-body pre{font-family:monospace;font-size:12px;white-space:pre-wrap;
  word-break:break-all;background:#f9fafb;padding:14px;border-radius:8px;max-height:60vh;overflow:auto}
.modal-foot{padding:12px 18px;border-top:1px solid var(--border);display:flex;gap:8px;justify-content:flex-end}
/* ── Rename input ── */
.rename-input{font-size:12px;padding:2px 6px;border:1px solid var(--accent);
  border-radius:4px;width:100%;font-family:inherit}
/* ── Toast ── */
#toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
  background:#1a1a2e;color:#fff;padding:9px 18px;border-radius:99px;
  font-size:13px;font-weight:500;z-index:300;opacity:0;
  transition:opacity .25s;pointer-events:none}
#toast.show{opacity:1}
/* ── Selection bar ── */
#sel-bar{display:none;position:sticky;bottom:0;background:var(--accent);
  color:#fff;padding:10px 24px;display:none;align-items:center;gap:12px;font-size:13px}
#sel-bar.show{display:flex}
#sel-bar .sb-actions{display:flex;gap:8px;margin-left:auto}
.sb-btn{padding:5px 14px;border-radius:6px;border:1px solid rgba(255,255,255,.4);
  background:transparent;color:#fff;cursor:pointer;font-size:12px}
.sb-btn:hover{background:rgba(255,255,255,.2)}
</style>
</head>
<body>

<header>
  <span class="logo">📡</span>
  <h1>LAN File Manager</h1>
  <span class="pill pill-green" id="status-pill">● Online</span>
  <span class="pill pill-blue" id="port-pill">PORT ___</span>
</header>

<div class="toolbar">
  <div class="search-wrap">
    <span class="search-icon">🔍</span>
    <input type="text" id="search" placeholder="Search files..." oninput="filterFiles()">
  </div>
  <select class="sort-select" id="sort-sel" onchange="applySort()">
    <option value="name-asc">Name ↑</option>
    <option value="name-desc">Name ↓</option>
    <option value="size-desc">Size ↓</option>
    <option value="size-asc">Size ↑</option>
    <option value="date-desc">Newest first</option>
    <option value="date-asc">Oldest first</option>
    <option value="type-asc">Type</option>
  </select>
  <div class="view-toggle">
    <button class="view-btn active" id="grid-btn" onclick="setView('grid')" title="Grid view">⊞</button>
    <button class="view-btn" id="list-btn" onclick="setView('list')" title="List view">☰</button>
  </div>
  <button class="btn btn-accent" onclick="document.getElementById('up-file').click()">
    ⬆ Upload
  </button>
  <button class="btn" onclick="loadDir(currentDir)">↻ Refresh</button>
</div>

<div class="breadcrumb" id="breadcrumb">
  <a href="#" onclick="loadDir('')">🏠 Home</a>
</div>

<div class="stats-bar" id="stats-bar">
  <span>Loading…</span>
</div>

<!-- Drop zone -->
<div class="dropzone" id="dropzone">
  <p>📂 Drag & drop files here to upload</p>
  <label class="btn" style="cursor:pointer">
    📁 Browse files
    <input type="file" id="up-file" multiple onchange="handleFileSelect(this.files)">
  </label>
  <div class="progress-bar" id="progress-bar">
    <div class="progress-fill" id="progress-fill"></div>
  </div>
  <div id="up-status" style="font-size:12px;color:var(--muted);margin-top:6px"></div>
</div>

<!-- Grid view -->
<div id="file-grid"></div>

<!-- List view -->
<div id="file-list">
  <div class="list-header">
    <div>Name</div><div style="text-align:right">Size</div>
    <div>Modified</div><div>Actions</div>
  </div>
  <div id="list-body"></div>
</div>

<!-- Context menu -->
<div class="ctx-menu" id="ctx-menu">
  <div class="ctx-item" onclick="ctxDownload()">⬇ Download</div>
  <div class="ctx-item" onclick="ctxOpen()">👁 Preview</div>
  <div class="ctx-item" onclick="ctxRename()">✏️ Rename</div>
  <div class="ctx-sep"></div>
  <div class="ctx-item danger" onclick="ctxDelete()">🗑 Delete</div>
</div>

<!-- Preview modal -->
<div class="modal-bg" id="modal" onclick="closeModal(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <div class="modal-head">
      <h3 id="modal-title">Preview</h3>
      <button class="btn" onclick="closeModal()">✕</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
    <div class="modal-foot">
      <button class="btn btn-accent" id="modal-dl">⬇ Download</button>
      <button class="btn" onclick="closeModal()">Close</button>
    </div>
  </div>
</div>

<!-- Toast -->
<div id="toast"></div>

<!-- Selection bar -->
<div id="sel-bar">
  <span id="sel-count">0 selected</span>
  <div class="sb-actions">
    <button class="sb-btn" onclick="downloadSelected()">⬇ Download all</button>
    <button class="sb-btn" onclick="deleteSelected()">🗑 Delete all</button>
    <button class="sb-btn" onclick="clearSelection()">✕ Clear</button>
  </div>
</div>

<script>
const API = '';
let allFiles  = [];
let filtered  = [];
let currentDir = '';
let viewMode  = 'grid';
let ctxTarget = null;
let selected  = new Set();

// ── Boot ──────────────────────────────────────────────────────────────────────
(async () => {
  const info = await fetch('/api/info').then(r=>r.json());
  document.getElementById('port-pill').textContent = 'PORT ' + info.http_port;
  if (info.https_port)
    document.getElementById('status-pill').textContent = '🔒 HTTPS :' + info.https_port;
  loadDir('');
})();

// ── Load directory ────────────────────────────────────────────────────────────
async function loadDir(rel) {
  currentDir = rel;
  clearSelection();
  const enc = encodeURIComponent(rel);
  allFiles   = await fetch(`/api/list?dir=${enc}`).then(r=>r.json());
  updateBreadcrumb(rel);
  applySort();
}

function updateBreadcrumb(rel) {
  let html = `<a href="#" onclick="loadDir('')">🏠 Home</a>`;
  if (rel) {
    const parts = rel.split('/');
    parts.forEach((p,i) => {
      const path = parts.slice(0,i+1).join('/');
      html += ` <span>/</span> <a href="#" onclick="loadDir('${path}')">${esc(p)}</a>`;
    });
  }
  document.getElementById('breadcrumb').innerHTML = html;
}

// ── Sort & filter ─────────────────────────────────────────────────────────────
function applySort() {
  const q   = document.getElementById('search').value.toLowerCase();
  const key = document.getElementById('sort-sel').value;
  filtered  = allFiles.filter(f => f.name.toLowerCase().includes(q));
  const [field, dir] = key.split('-');
  filtered.sort((a,b) => {
    let va, vb;
    if (field==='name') { va=a.name.toLowerCase(); vb=b.name.toLowerCase(); }
    else if (field==='size') { va=a.size; vb=b.size; }
    else if (field==='date') { va=a.mtime; vb=b.mtime; }
    else if (field==='type') { va=a.ext; vb=b.ext; }
    if (va===vb) return 0;
    const cmp = va<vb ? -1 : 1;
    return dir==='asc' ? cmp : -cmp;
  });
  // dirs always first
  filtered.sort((a,b) => (b.is_dir - a.is_dir));
  render();
}

function filterFiles() { applySort(); }

// ── Render ────────────────────────────────────────────────────────────────────
function render() {
  updateStats();
  if (viewMode==='grid') renderGrid();
  else renderList();
}

function updateStats() {
  const dirs  = filtered.filter(f=>f.is_dir).length;
  const files = filtered.filter(f=>!f.is_dir).length;
  const total = filtered.reduce((s,f)=>s+(f.is_dir?0:f.size),0);
  document.getElementById('stats-bar').innerHTML =
    `<span><b>${dirs}</b> folders</span>
     <span><b>${files}</b> files</span>
     <span>Total: <b>${humanSize(total)}</b></span>`;
}

function fileIcon(f) {
  if (f.is_dir) return '📁';
  const e = f.ext;
  if (['jpg','jpeg','png','gif','webp','svg','bmp','ico'].includes(e)) return '🖼️';
  if (['mp4','mkv','avi','mov','webm','flv'].includes(e)) return '🎬';
  if (['mp3','wav','ogg','flac','aac','m4a'].includes(e)) return '🎵';
  if (['pdf'].includes(e)) return '📕';
  if (['doc','docx'].includes(e)) return '📝';
  if (['xls','xlsx','csv'].includes(e)) return '📊';
  if (['ppt','pptx'].includes(e)) return '📋';
  if (['zip','rar','7z','tar','gz'].includes(e)) return '🗜️';
  if (['py','js','ts','html','css','json','xml','sh','c','cpp','java','go','rs'].includes(e)) return '💻';
  if (['txt','md','log'].includes(e)) return '📄';
  return '📄';
}

function renderGrid() {
  document.getElementById('file-grid').style.display = '';
  document.getElementById('file-list').style.display = 'none';
  const grid = document.getElementById('file-grid');
  if (!filtered.length) { grid.innerHTML = emptyHTML(); return; }
  grid.innerHTML = filtered.map(f => {
    const sel = selected.has(f.rel) ? 'selected' : '';
    return `<div class="file-card ${sel}" data-rel="${esc(f.rel)}"
        onclick="cardClick(event,'${esc(f.rel)}')"
        ondblclick="openItem('${esc(f.rel)}')"
        oncontextmenu="showCtx(event,'${esc(f.rel)}')">
      <div class="card-actions">
        ${f.is_dir?'':`<button class="icon-btn" title="Download" onclick="event.stopPropagation();dlFile('${esc(f.rel)}')">⬇</button>`}
        ${f.previewable?`<button class="icon-btn" title="Preview" onclick="event.stopPropagation();previewFile('${esc(f.rel)}','${esc(f.name)}','${esc(f.mime)}')">👁</button>`:''}
        <button class="icon-btn" title="Delete" onclick="event.stopPropagation();deleteFile('${esc(f.rel)}','${esc(f.name)}')">🗑</button>
      </div>
      <div class="file-icon">${fileIcon(f)}</div>
      <div class="fname" id="fname-${esc(f.rel.replace(/\//g,'_'))}">${esc(f.name)}</div>
      <div class="fmeta">${f.is_dir ? 'Folder' : f.size_h}</div>
      <div class="fmeta" style="font-size:10px">${f.mtime_h}</div>
    </div>`;
  }).join('');
}

function renderList() {
  document.getElementById('file-grid').style.display = 'none';
  document.getElementById('file-list').style.display = '';
  const body = document.getElementById('list-body');
  if (!filtered.length) { body.innerHTML = emptyHTML(); return; }
  body.innerHTML = filtered.map(f => {
    const sel = selected.has(f.rel) ? 'selected' : '';
    return `<div class="file-row ${sel}" data-rel="${esc(f.rel)}"
        onclick="cardClick(event,'${esc(f.rel)}')"
        ondblclick="openItem('${esc(f.rel)}')"
        oncontextmenu="showCtx(event,'${esc(f.rel)}')">
      <div class="row-name">
        <span style="font-size:18px">${fileIcon(f)}</span>
        <span>${esc(f.name)}</span>
      </div>
      <div class="row-size">${f.is_dir ? '—' : f.size_h}</div>
      <div class="row-date">${f.mtime_h}</div>
      <div class="row-actions">
        ${f.is_dir?'':`<button class="btn" onclick="event.stopPropagation();dlFile('${esc(f.rel)}')">⬇</button>`}
        ${f.previewable?`<button class="btn" onclick="event.stopPropagation();previewFile('${esc(f.rel)}','${esc(f.name)}','${esc(f.mime)}')">👁</button>`:''}
        <button class="btn" onclick="event.stopPropagation();startRename('${esc(f.rel)}','${esc(f.name)}')">✏️</button>
        <button class="btn btn-danger" onclick="event.stopPropagation();deleteFile('${esc(f.rel)}','${esc(f.name)}')">🗑</button>
      </div>
    </div>`;
  }).join('');
}

function emptyHTML() {
  const q = document.getElementById('search').value;
  return `<div class="empty-state">
    <div class="big">${q ? '🔍' : '📂'}</div>
    <p>${q ? `No files matching "<b>${esc(q)}</b>"` : 'This folder is empty'}</p>
  </div>`;
}

// ── Selection ─────────────────────────────────────────────────────────────────
function cardClick(e, rel) {
  if (e.ctrlKey || e.metaKey || e.shiftKey) {
    selected.has(rel) ? selected.delete(rel) : selected.add(rel);
    updateSelBar();
    render();
  }
}
function clearSelection() { selected.clear(); updateSelBar(); }
function updateSelBar() {
  const bar = document.getElementById('sel-bar');
  if (selected.size) {
    bar.classList.add('show');
    document.getElementById('sel-count').textContent = selected.size + ' selected';
  } else {
    bar.classList.remove('show');
  }
}
function downloadSelected() {
  selected.forEach(rel => dlFile(rel));
  toast('Downloads started');
}
async function deleteSelected() {
  if (!confirm(`Delete ${selected.size} item(s)?`)) return;
  for (const rel of selected) {
    await fetch('/api/delete', {method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({rel})});
  }
  toast(`Deleted ${selected.size} items`);
  clearSelection();
  loadDir(currentDir);
}

// ── Open item ─────────────────────────────────────────────────────────────────
function openItem(rel) {
  const f = allFiles.find(x=>x.rel===rel);
  if (!f) return;
  if (f.is_dir) { loadDir(rel); return; }
  if (f.previewable) previewFile(rel, f.name, f.mime);
  else dlFile(rel);
}

// ── Download ──────────────────────────────────────────────────────────────────
function dlFile(rel) {
  const a = document.createElement('a');
  a.href = '/download/' + encodeURIComponent(rel);
  a.download = rel.split('/').pop();
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function deleteFile(rel, name) {
  if (!confirm(`Delete "${name}"?`)) return;
  const r = await fetch('/api/delete', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({rel})});
  const d = await r.json();
  if (d.ok) { toast('Deleted ' + name); loadDir(currentDir); }
  else toast('Error: ' + d.error, true);
}

// ── Rename ────────────────────────────────────────────────────────────────────
function startRename(rel, name) {
  const id   = 'fname-' + rel.replace(/\//g,'_');
  const span = document.getElementById(id);
  if (!span) { promptRename(rel, name); return; }
  span.innerHTML = `<input class="rename-input" value="${esc(name)}"
    onblur="doRename('${esc(rel)}',this.value)"
    onkeydown="if(event.key==='Enter')this.blur();if(event.key==='Escape')loadDir(currentDir)">`;
  span.querySelector('input').select();
}
function promptRename(rel, name) {
  const newName = prompt('New name:', name);
  if (newName && newName !== name) doRename(rel, newName);
}
async function doRename(rel, newName) {
  const r = await fetch('/api/rename', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({rel, new_name:newName})});
  const d = await r.json();
  if (d.ok) { toast('Renamed to ' + newName); loadDir(currentDir); }
  else { toast('Error: ' + d.error, true); loadDir(currentDir); }
}

// ── Preview modal ─────────────────────────────────────────────────────────────
function previewFile(rel, name, mime) {
  const url = '/download/' + encodeURIComponent(rel);
  document.getElementById('modal-title').textContent = name;
  document.getElementById('modal-dl').onclick = () => dlFile(rel);
  const body = document.getElementById('modal-body');
  if (mime.startsWith('image/'))
    body.innerHTML = `<img src="${url}" alt="${esc(name)}">`;
  else if (mime.startsWith('video/'))
    body.innerHTML = `<video controls src="${url}"></video>`;
  else if (mime.startsWith('audio/'))
    body.innerHTML = `<audio controls src="${url}" style="width:100%"></audio>`;
  else if (mime==='application/pdf')
    body.innerHTML = `<iframe src="${url}" style="width:100%;height:65vh;border:none;border-radius:8px"></iframe>`;
  else
    fetch(url).then(r=>r.text()).then(t=>{
      body.innerHTML = `<pre>${esc(t.slice(0,8000))}${t.length>8000?'\n…(truncated)':''}</pre>`;
    });
  document.getElementById('modal').classList.add('show');
}
function closeModal(e) {
  if (!e || e.target===document.getElementById('modal'))
    document.getElementById('modal').classList.remove('show');
}

// ── Context menu ──────────────────────────────────────────────────────────────
function showCtx(e, rel) {
  e.preventDefault(); e.stopPropagation();
  ctxTarget = allFiles.find(f=>f.rel===rel);
  const menu = document.getElementById('ctx-menu');
  menu.style.left = e.clientX + 'px';
  menu.style.top  = e.clientY + 'px';
  menu.classList.add('show');
}
function hideCtx() { document.getElementById('ctx-menu').classList.remove('show'); }
function ctxDownload() { if(ctxTarget && !ctxTarget.is_dir) dlFile(ctxTarget.rel); hideCtx(); }
function ctxOpen()     { if(ctxTarget) openItem(ctxTarget.rel); hideCtx(); }
function ctxRename()   { if(ctxTarget) startRename(ctxTarget.rel,ctxTarget.name); hideCtx(); }
function ctxDelete()   { if(ctxTarget) deleteFile(ctxTarget.rel,ctxTarget.name); hideCtx(); }
document.addEventListener('click', hideCtx);
document.addEventListener('keydown', e=>{ if(e.key==='Escape'){ hideCtx(); closeModal(); }});

// ── Upload ────────────────────────────────────────────────────────────────────
async function handleFileSelect(files) {
  if (!files.length) return;
  const bar  = document.getElementById('progress-bar');
  const fill = document.getElementById('progress-fill');
  const stat = document.getElementById('up-status');
  bar.style.display = 'block';
  let done = 0;
  for (const file of files) {
    stat.textContent = `Uploading ${file.name}…`;
    const fd = new FormData();
    fd.append('file', file);
    if (currentDir) fd.append('dir', currentDir);
    await fetch('/upload', {method:'POST', body: fd});
    done++;
    fill.style.width = Math.round(done/files.length*100) + '%';
  }
  stat.textContent = `✓ ${done} file(s) uploaded`;
  setTimeout(()=>{ bar.style.display='none'; fill.style.width='0%'; stat.textContent=''; },2500);
  toast(`Uploaded ${done} file(s)`);
  loadDir(currentDir);
}

// Drag & drop
const dz = document.getElementById('dropzone');
dz.addEventListener('dragover', e=>{ e.preventDefault(); dz.classList.add('drag-over'); });
dz.addEventListener('dragleave', ()=> dz.classList.remove('drag-over'));
dz.addEventListener('drop', e=>{
  e.preventDefault(); dz.classList.remove('drag-over');
  handleFileSelect(e.dataTransfer.files);
});

// ── View toggle ───────────────────────────────────────────────────────────────
function setView(v) {
  viewMode = v;
  document.getElementById('grid-btn').classList.toggle('active', v==='grid');
  document.getElementById('list-btn').classList.toggle('active', v==='list');
  render();
}

// ── Utils ─────────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function humanSize(n) {
  for (const u of ['B','KB','MB','GB']) { if (n<1024) return n.toFixed(1)+' '+u; n/=1024; }
  return n.toFixed(1)+' TB';
}
let toastTimer;
function toast(msg, err=false) {
  const t = document.getElementById('toast');
  t.textContent = (err ? '⚠ ' : '✓ ') + msg;
  t.style.background = err ? '#dc2626' : '#1a1a2e';
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>t.classList.remove('show'), 2800);
}
</script>
</body>
</html>
"""

# ── API helpers ───────────────────────────────────────────────────────────────
def json_response(handler, data, code=200):
    body = json.dumps(data).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

def html_response(handler, body, code=200):
    enc = body.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(enc)))
    handler.end_headers()
    handler.wfile.write(enc)

# ── Request handler ───────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        proto = "HTTPS" if getattr(self.server, 'is_https', False) else "HTTP "
        print(f"  [{proto}] [{self.client_address[0]}] {fmt % args}")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        qs     = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            ip   = get_local_ip()
            html_response(self, render_page(ip, _HTTP_PORT, _HTTPS_PORT))

        elif path == "/api/info":
            json_response(self, {"http_port": _HTTP_PORT, "https_port": _HTTPS_PORT})

        elif path == "/api/list":
            rel = qs.get("dir", [""])[0]
            json_response(self, list_dir(rel))

        elif path.startswith("/download/"):
            rel       = urllib.parse.unquote(path[len("/download/"):])
            file_path = safe_path(rel)
            if file_path is None or not file_path.exists():
                html_response(self, "<h2>404 — Not found</h2>", 404); return
            if file_path.is_dir():
                html_response(self, "<h2>400 — Cannot download a folder</h2>", 400); return
            self._serve_file(file_path)

        else:
            html_response(self, "<h2>404 — Not found</h2>", 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path

        if path == "/upload":
            self._handle_upload()

        elif path == "/api/delete":
            length = int(self.headers.get("Content-Length", 0))
            data   = json.loads(self.rfile.read(length))
            rel    = data.get("rel", "")
            target = safe_path(rel)
            if not target or not target.exists():
                json_response(self, {"ok": False, "error": "Not found"}, 404); return
            try:
                if target.is_dir(): shutil.rmtree(target)
                else: target.unlink()
                print(f"  🗑 Deleted: {target}")
                json_response(self, {"ok": True})
            except Exception as e:
                json_response(self, {"ok": False, "error": str(e)}, 500)

        elif path == "/api/rename":
            length = int(self.headers.get("Content-Length", 0))
            data   = json.loads(self.rfile.read(length))
            rel    = data.get("rel", "")
            new_name = Path(data.get("new_name", "")).name  # strip directory part
            target = safe_path(rel)
            if not target or not target.exists():
                json_response(self, {"ok": False, "error": "Not found"}, 404); return
            dest = target.parent / new_name
            try:
                target.rename(dest)
                print(f"  ✏️  Renamed: {target.name} → {new_name}")
                json_response(self, {"ok": True})
            except Exception as e:
                json_response(self, {"ok": False, "error": str(e)}, 500)

        else:
            html_response(self, "<h2>405 — Method not allowed</h2>", 405)

    def _handle_upload(self):
        ct = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ct:
            html_response(self, "<h2>400 — Expected multipart</h2>", 400); return

        boundary = None
        for part in ct.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip().encode(); break
        if not boundary:
            html_response(self, "<h2>400 — No boundary</h2>", 400); return

        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        fields = self._parse_multipart_all(body, boundary)
        subdir = fields.get("dir", "")
        if subdir:
            dest_dir = safe_path(subdir)
            if dest_dir is None or not dest_dir.is_dir():
                dest_dir = UPLOAD_DIR
        else:
            dest_dir = UPLOAD_DIR

        filename = fields.get("__filename__")
        file_data = fields.get("__file__")
        if not filename or file_data is None:
            html_response(self, "<h2>400 — No file</h2>", 400); return

        safe_name = Path(filename).name
        dest = dest_dir / safe_name
        counter = 1
        stem, suf = Path(safe_name).stem, Path(safe_name).suffix
        while dest.exists():
            dest = dest_dir / f"{stem}_{counter}{suf}"; counter += 1

        dest.write_bytes(file_data)
        print(f"  ✓ Upload: {dest}  ({human_size(len(file_data))})")
        # Return 200 JSON (XHR upload)
        json_response(self, {"ok": True, "name": dest.name})

    def _serve_file(self, path: Path):
        mime, _ = mimetypes.guess_type(path.name)
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _parse_multipart_all(body: bytes, boundary: bytes) -> dict:
        result = {}
        delimiter = b"--" + boundary
        for part in body.split(delimiter)[1:]:
            if part in (b"--\r\n", b"--"): break
            if b"\r\n\r\n" not in part: continue
            hdr_raw, _, content = part.partition(b"\r\n\r\n")
            content = content.rstrip(b"\r\n")
            hdrs = hdr_raw.decode(errors="replace")
            # field name
            field_name = None
            for line in hdrs.splitlines():
                if "name=" in line:
                    field_name = line.split("name=")[-1].strip().strip('"').split('"')[0]
                    break
            if field_name is None: continue
            if "filename=" in hdrs:
                fn = None
                for line in hdrs.splitlines():
                    if "filename=" in line:
                        fn = line.split("filename=")[-1].strip().strip('"'); break
                result["__filename__"] = fn
                result["__file__"]     = content
            else:
                result[field_name] = content.decode(errors="replace")
        return result

# ── Server factory ────────────────────────────────────────────────────────────
class TaggedHTTPServer(HTTPServer):
    def __init__(self, *args, is_https=False, **kwargs):
        self.is_https = is_https
        super().__init__(*args, **kwargs)

def make_http_server(port):
    return TaggedHTTPServer(("0.0.0.0", port), Handler, is_https=False)

def make_https_server(port, cert, key):
    srv = TaggedHTTPServer(("0.0.0.0", port), Handler, is_https=True)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv

# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    global _HTTP_PORT, _HTTPS_PORT, SHARED_DIR, UPLOAD_DIR

    p = argparse.ArgumentParser(description="LAN File Manager")
    p.add_argument("--port",       type=int, default=8000)
    p.add_argument("--https-port", type=int, default=8443)
    p.add_argument("--https",      action="store_true")
    p.add_argument("--https-only", action="store_true")
    p.add_argument("--cert",       default=None)
    p.add_argument("--key",        default=None)
    p.add_argument("--dir",        default=None)
    args = p.parse_args()

    if args.dir:
        SHARED_DIR = Path(args.dir)
        UPLOAD_DIR = SHARED_DIR / "uploads"
    ensure_dirs()

    ip = get_local_ip()
    want_https = args.https or args.https_only
    cert_path, key_path = args.cert, args.key
    if want_https and (not cert_path or not key_path):
        cert_path, key_path = generate_self_signed_cert(ip)

    _HTTP_PORT  = args.port
    _HTTPS_PORT = args.https_port if want_https else None

    servers = []
    if not args.https_only: servers.append(make_http_server(args.port))
    if want_https:          servers.append(make_https_server(args.https_port, cert_path, key_path))

    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  📡  LAN File Manager                           │")
    if not args.https_only:
        print(f"  │  HTTP  ▶  http://{ip}:{args.port:<5}               │")
    if want_https:
        print(f"  │  HTTPS ▶  https://{ip}:{args.https_port:<5}             │")
        print("  │  (click 'Advanced → Proceed' for self-signed)   │")
    print(f"  │  Folder : {str(SHARED_DIR):<38}│")
    print("  │  Ctrl+C to stop                                 │")
    print("  └─────────────────────────────────────────────────┘")
    print()

    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for t in threads: t.start()
    try:
        for t in threads: t.join()
    except KeyboardInterrupt:
        print("\n  Stopping…")
        for s in servers: s.shutdown()
        print("  Done.")

if __name__ == "__main__":
    main()