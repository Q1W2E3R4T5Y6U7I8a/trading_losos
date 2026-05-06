import json
import os
import queue
import socketserver
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT      = 8765
DATA_FILE = "M:/Projects/trading_losos/data/live_data.json"
TMPL_FILE = "M:/Projects/trading_losos/src/components/viewer_template.html"

# Shared state
_clients: list[queue.Queue] = []
_lock      = threading.Lock()
_latest:   dict = {}
_template:  str = ""

def load_template():
    global _template
    with open(TMPL_FILE, "r", encoding="utf-8") as f:
        _template = f.read()

def broadcast(data: dict):
    global _latest
    _latest = data
    msg = ("data: " + json.dumps(data) + "\n\n").encode()
    with _lock:
        for q in list(_clients):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            # Inject live data into template
            html = _template.replace("{{DATA_JSON}}", json.dumps(_latest))
            self._ok("text/html; charset=utf-8", html.encode())

        elif self.path == "/data":
            self._ok("application/json", json.dumps(_latest).encode())

        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            q = queue.Queue(maxsize=20)
            with _lock:
                _clients.append(q)

            # Send current state immediately
            if _latest:
                try:
                    self.wfile.write(("data: " + json.dumps(_latest) + "\n\n").encode())
                    self.wfile.flush()
                except:
                    pass

            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                        self.wfile.write(msg)
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except:
                pass
            finally:
                with _lock:
                    if q in _clients:
                        _clients.remove(q)

        else:
            self.send_response(404)
            self.end_headers()

    def _ok(self, content_type: str, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True

def watch_file():
    last_mtime = 0.0
    while True:
        try:
            if os.path.exists(DATA_FILE):
                mtime = os.path.getmtime(DATA_FILE)
                if mtime > last_mtime:
                    last_mtime = mtime
                    with open(DATA_FILE, "r") as f:
                        data = json.load(f)
                    broadcast(data)
                    total = sum(data.get("profits", {}).values())
                    ts = datetime.fromtimestamp(data["timestamp"]).strftime("%H:%M:%S")
                    pct = data.get("progress", 0) * 100
                    print(f"\r  [{ts}]  TOTAL: ${total:+.2f}  |  {pct:.1f}%  |  open: {len(data.get('open_positions', {}))}   ", end="", flush=True)
        except Exception as e:
            print(f"\n  watch error: {e}")
        time.sleep(0.4)

def main():
    load_template()
    threading.Thread(target=watch_file, daemon=True).start()
    
    server = ThreadedHTTPServer(("", PORT), Handler)
    url = f"http://localhost:{PORT}"
    
    print(f"  3D VIEWER  →  {url}")
    print(f"  data file  →  {DATA_FILE}\n")
    
    threading.Timer(1.0, webbrowser.open, args=[url]).start()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  VIEWER STOPPED")
        server.server_close()

if __name__ == "__main__":
    main()