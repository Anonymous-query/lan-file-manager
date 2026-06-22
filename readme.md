# 📡 LAN File Manager

A **zero-dependency** browser-based file manager that runs on your laptop and lets anyone on the same Wi-Fi network browse, download, upload, rename, delete, and preview files — no installation needed on the peer devices.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔍 **Live search** | Filter files instantly as you type |
| 📂 **Folder navigation** | Browse into subfolders with breadcrumb trail |
| ⊞ **Grid / ☰ List view** | Toggle between icon grid and detailed list |
| 🔃 **Sort** | By name, size, date, or file type |
| 👁 **Inline preview** | Images, video, audio, PDF, and text files |
| ⬇ **Download** | Single file or multi-select batch download |
| ⬆ **Drag & drop upload** | Upload multiple files with a progress bar |
| ✏️ **Rename** | Inline rename without leaving the page |
| 🗑 **Delete** | Single or multi-select batch delete |
| 🖱 **Context menu** | Right-click any file for quick actions |
| 🔒 **HTTPS support** | Auto-generates a self-signed cert via OpenSSL |
| 🛡 **Path traversal safe** | Peers cannot escape the shared directory |

---

## 🚀 Quick Start

```bash
# Clone the repo
git clone https://github.com/your-username/lan-file-manager.git
cd lan-file-manager

# Run (Python 3.10+ required, no pip install needed)
python lan_server.py
```

Open the printed URL on any device on the same Wi-Fi:

```
http://192.168.x.x:8000
```

Drop files into the `shared_files/` folder on the host — they appear instantly for all peers.

---

## 📦 Requirements

- **Python 3.10+** (uses the `X | Y` union type hint syntax)
- **No third-party packages** — pure standard library (`http.server`, `ssl`, `json`, `pathlib`, `threading`)
- **OpenSSL** (optional, only needed for HTTPS mode — pre-installed on macOS/Linux)

---

## 🖥 Usage

```bash
python lan_server.py [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--port` | `8000` | HTTP port |
| `--https` | off | Run HTTP + HTTPS simultaneously |
| `--https-only` | off | HTTPS only (no plain HTTP) |
| `--https-port` | `8443` | HTTPS port |
| `--cert` | auto | Path to your own `.crt` file |
| `--key` | auto | Path to your own `.key` file |
| `--dir` | `./shared_files` | Folder to share |

### Examples

```bash
# HTTP only (default)
python lan_server.py

# HTTP + HTTPS with auto-generated self-signed cert
python lan_server.py --https

# HTTPS only on a custom port
python lan_server.py --https-only --https-port 9443

# Share a specific folder
python lan_server.py --dir /home/nilesh/Documents

# Bring your own certificate
python lan_server.py --https --cert server.crt --key server.key

# Custom HTTP port
python lan_server.py --port 9000
```

---

## 📁 Directory Structure

```
lan-file-manager/
├── lan_server.py        # The entire server — one file
├── shared_files/        # Auto-created; put files here to share them
│   └── uploads/         # Auto-created; incoming uploads land here
└── README.md
```

> All files placed in `shared_files/` (including subfolders) are immediately visible in the browser UI. Uploads from peers go into `shared_files/uploads/` by default, or into the folder currently open in the browser.

---

## 🔒 HTTPS & Self-Signed Certificates

When you run with `--https`, the server auto-generates a temporary self-signed certificate using `openssl`. Peer browsers will show a security warning — this is expected for LAN self-signed certs.

**To proceed in the browser:**
- Chrome / Edge: click **Advanced → Proceed to \<IP\> (unsafe)**
- Firefox: click **Advanced → Accept the Risk and Continue**
- Safari: click **Show Details → visit this website**

The warning goes away if you install your own cert from a local CA (e.g. [mkcert](https://github.com/FiloSottile/mkcert)).

### Why HTTPS?

Some browsers (especially on Android and iOS) default to `https://` and send a TLS handshake to a plain HTTP server, which produces garbled `400 Bad request version` errors in the logs. Running with `--https` or `--https-only` fixes this entirely.

---

## 🌐 Browser UI

### File manager view
- **Grid view** — icon cards with hover actions (download, preview, delete)
- **List view** — table rows with name, size, date, and action buttons
- **Breadcrumb** — click any segment to navigate up the folder tree
- **Stats bar** — live count of folders, files, and total size

### Search & sort
- Type in the search box to filter files in real time
- Sort dropdown: Name ↑↓ / Size ↑↓ / Newest or Oldest first / Type

### Multi-select
- `Ctrl+Click` (Windows/Linux) or `Cmd+Click` (Mac) to select multiple files
- A selection bar appears at the bottom with **Download all** and **Delete all**

### Previewer
Supported inline previews (no download required):

| Type | Formats |
|---|---|
| Image | jpg, jpeg, png, gif, webp, svg, bmp |
| Video | mp4, mkv, avi, mov, webm |
| Audio | mp3, wav, ogg, flac, aac, m4a |
| Document | pdf |
| Text / Code | txt, md, py, js, html, css, json, xml, sh, … |

### Upload
- Drag files onto the drop zone, or click **Browse files**
- Multiple files upload sequentially with a progress bar
- Files land in `shared_files/uploads/` or the currently open subfolder

---

## 🛡 Security Notes

- **Path traversal protection** — all file paths are resolved and validated to stay inside `shared_files/`. A peer cannot request `../../etc/passwd` or any path outside the shared root.
- **Filename sanitisation** — only the `name` component of any uploaded path is used; directory parts are stripped.
- **Upload collision handling** — if a file with the same name already exists, a numeric suffix is appended (`file_1.txt`, `file_2.txt`, …) instead of silently overwriting.
- **No authentication** — this server is designed for **trusted local networks only**. Do not expose it to the internet or untrusted networks.

---

## 🔧 Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `400 Bad request version` + garbled bytes in logs | Peer connected via HTTPS to plain HTTP | Run with `--https` flag |
| Peer can't reach the server | Firewall blocking the port | Allow port 8000 (or your custom port) in the host firewall |
| `openssl: command not found` | OpenSSL not installed | Install it, or supply `--cert` / `--key` manually |
| Browser says "Not secure" on HTTPS | Self-signed cert | Click Advanced → Proceed (expected on LAN) |
| Upload fails silently | File too large for browser timeout | Upload smaller batches |
| `python: command not found` | Python not on PATH | Use `python3 lan_server.py` |

---

## 📄 License

MIT — do whatever you want with it.

---

## 🙌 Contributing

Pull requests welcome. To keep things simple, the goal is to stay **single-file, zero-dependency**. Feature ideas:

- [ ] Password protection (HTTP Basic Auth)
- [ ] Create new folder from the UI
- [ ] Move / copy files between folders
- [ ] QR code on startup for easy mobile access
- [ ] Dark mode toggle
- [ ] ZIP download of entire folder

---

*Built with Python's standard library — no Flask, no FastAPI, no Node.js required.*