#!/usr/bin/env python3
import argparse
import hmac
import html
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PRESETS = [
    ("qwen3:8b", "Qwen 3 8B — lebih ringan untuk runner 16 GB"),
    ("qwen3:14b", "Qwen 3 14B — lebih berat / lebih lambat"),
    ("qwen2.5:14b", "Qwen 2.5 14B"),
    ("qwen2.5-coder:7b", "Qwen 2.5 Coder 7B"),
    ("qwen2.5-coder:14b", "Qwen 2.5 Coder 14B — berat"),
    ("custom_ollama", "Custom Ollama model"),
    ("custom_gguf", "Custom GGUF URL (termasuk Abliterated)"),
]

CSS = r"""
:root {
  color-scheme: dark;
  --bg: #0b0d10;
  --card: #151922;
  --field: #0f131a;
  --text: #f4f6fb;
  --muted: #a7afbd;
  --border: #2a3140;
  --accent: #ffffff;
}
* { box-sizing: border-box; }
body {
  margin: 0; min-height: 100vh; display: grid; place-items: center;
  background: radial-gradient(circle at top, #1b2230 0, var(--bg) 45%);
  color: var(--text); font-family: system-ui, -apple-system, Segoe UI, sans-serif;
  padding: 20px;
}
.card {
  width: min(100%, 560px); background: rgba(21,25,34,.96);
  border: 1px solid var(--border); border-radius: 22px;
  padding: 24px; box-shadow: 0 24px 70px rgba(0,0,0,.35);
}
h1 { margin: 0 0 7px; font-size: 27px; }
p { color: var(--muted); line-height: 1.5; }
label { display:block; margin: 17px 0 7px; font-weight: 650; }
select,input {
  width:100%; padding: 14px; border-radius: 13px; border:1px solid var(--border);
  background: var(--field); color: var(--text); font-size: 16px; outline:none;
}
button {
  width:100%; margin-top: 21px; padding: 15px; border:0; border-radius: 14px;
  font-size:16px; font-weight:800; cursor:pointer; background: var(--accent); color:#08090b;
}
.note {
  margin-top:16px; padding:13px 14px; border:1px solid var(--border);
  border-radius:13px; color:var(--muted); font-size:14px;
}
.bad { color:#ff9d9d; }
.good { color:#9cf5b0; }
.spinner {
  width:36px; height:36px; border:4px solid #313949; border-top-color:#fff;
  border-radius:50%; animation:spin .9s linear infinite; margin:20px auto;
}
@keyframes spin { to { transform:rotate(360deg); } }
code { color:#fff; }
"""

def page(title, body, refresh=None):
    meta = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{meta}<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><main class="card">{body}</main></body></html>""".encode()

class App:
    def __init__(self, selection, status, password):
        self.selection = selection
        self.status = status
        self.password = password

    def status_text(self):
        try:
            with open(self.status, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return "Sedang menyiapkan..."

    def selected(self):
        return os.path.exists(self.selection) and os.path.getsize(self.selection) > 0

    def save_selection(self, data):
        os.makedirs(os.path.dirname(self.selection), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="selection-", suffix=".json",
                                   dir=os.path.dirname(self.selection))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.selection)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

class Handler(BaseHTTPRequestHandler):
    app = None

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def send_html(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/health"):
            b = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return

        if self.app.selected():
            status = html.escape(self.app.status_text())
            body = f"""
              <h1>Local AI sedang disiapkan</h1>
              <div class="spinner"></div>
              <p class="good"><strong>{status}</strong></p>
              <p>Halaman ini refresh otomatis. Setelah siap, URL yang sama akan berubah menjadi Open WebUI.</p>
              <div class="note">Saat perpindahan launcher → Open WebUI, mungkin muncul 502 beberapa detik. Refresh saja.</div>
            """
            self.send_html(page("Preparing Local AI", body, refresh=5))
            return

        opts = "\n".join(
            f'<option value="{html.escape(v)}">{html.escape(label)}</option>'
            for v, label in PRESETS
        )
        body = f"""
          <h1>Local AI Launcher</h1>
          <p>Pilih model setelah GitHub runner sudah hidup. Hanya model yang dipilih yang akan didownload.</p>

          <form method="post" action="/select">
            <label>Password</label>
            <input type="password" name="password" autocomplete="current-password" required>

            <label>Model</label>
            <select name="preset" id="preset" onchange="toggleCustom()">{opts}</select>

            <div id="customBox" style="display:none">
              <label id="customLabel">Custom model</label>
              <input type="text" id="custom" name="custom"
                placeholder="contoh: modelname:tag atau https://.../model.gguf">
            </div>

            <label>Context length</label>
            <select name="context">
              <option value="4096">4096 — hemat RAM</option>
              <option value="8192" selected>8192 — balanced</option>
              <option value="16384">16384 — lebih berat</option>
            </select>

            <button type="submit">START AI</button>
          </form>

          <div class="note">
            Runner kamu punya sekitar 15 GiB RAM. Model 14B bisa berjalan sangat mepet dan jauh lebih lambat di CPU.
            Untuk Qwen 2.5 14B Abliterated milikmu, pilih <b>Custom GGUF URL</b> dan tempel direct URL file GGUF.
          </div>

          <script>
          function toggleCustom() {{
            const p = document.getElementById('preset').value;
            const box = document.getElementById('customBox');
            const label = document.getElementById('customLabel');
            const input = document.getElementById('custom');
            const custom = p === 'custom_ollama' || p === 'custom_gguf';
            box.style.display = custom ? 'block' : 'none';
            input.required = custom;
            label.textContent = p === 'custom_gguf' ? 'Direct GGUF URL' : 'Ollama model name';
          }}
          toggleCustom();
          </script>
        """
        self.send_html(page("Local AI Launcher", body))

    def do_POST(self):
        if self.path != "/select":
            self.send_error(404)
            return

        if self.app.selected():
            self.send_html(page("Already selected",
                "<h1>Model sudah dipilih</h1><p>Workflow sedang melanjutkan setup.</p>", refresh=4))
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length > 8192:
            self.send_error(413)
            return

        raw = self.rfile.read(length).decode("utf-8", "replace")
        q = parse_qs(raw)

        supplied = q.get("password", [""])[0]
        if not hmac.compare_digest(supplied, self.app.password):
            self.send_html(page("Wrong password",
                '<h1>Password salah</h1><p class="bad">Gunakan nilai repository secret LOCAL_AI_PASSWORD.</p>'),
                code=403)
            return

        preset = q.get("preset", [""])[0]
        custom = q.get("custom", [""])[0].strip()
        context_raw = q.get("context", ["8192"])[0]

        if context_raw not in {"4096", "8192", "16384"}:
            context_raw = "8192"

        preset_values = {v for v, _ in PRESETS}
        if preset not in preset_values:
            self.send_error(400, "Invalid preset")
            return

        if preset == "custom_ollama":
            if not custom or len(custom) > 240 or "\n" in custom or "\r" in custom:
                self.send_error(400, "Invalid Ollama model name")
                return
            kind, model = "ollama", custom

        elif preset == "custom_gguf":
            u = urlparse(custom)
            if u.scheme not in {"http", "https"} or not u.netloc or len(custom) > 2048:
                self.send_error(400, "Invalid GGUF URL")
                return
            kind, model = "gguf", custom

        else:
            kind, model = "ollama", preset

        data = {"kind": kind, "model": model, "context": int(context_raw)}
        self.app.save_selection(data)

        with open(self.app.status, "w", encoding="utf-8") as f:
            f.write(f"Pilihan diterima: {model}. Workflow melanjutkan setup...")

        body = f"""
          <h1>Pilihan diterima ✅</h1>
          <p><strong>{html.escape(model)}</strong></p>
          <div class="spinner"></div>
          <p>Workflow sekarang akan install Ollama, download model, lalu menyalakan Open WebUI.</p>
          <p>Jangan tutup GitHub Action. URL ini akan tetap sama.</p>
        """
        self.send_html(page("Selection received", body, refresh=5))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--selection", required=True)
    ap.add_argument("--status", required=True)
    args = ap.parse_args()

    password = os.environ.get("LAUNCH_PASSWORD", "")
    if not password:
        raise SystemExit("LAUNCH_PASSWORD is required")

    app = App(args.selection, args.status, password)
    Handler.app = app

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Launcher listening on http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
      
