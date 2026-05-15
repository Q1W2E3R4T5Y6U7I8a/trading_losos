import json
import os
import queue
import socketserver
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


PORT = 8766
DATA_DIR = os.getenv("TRADING_DATA_DIR", "M:/Projects/trading_losos/data")
MA_FILE = f"{DATA_DIR}/live_data.json"
RSI_FILE = f"{DATA_DIR}/rsi_live_data.json"
SESSION_FILE = f"{DATA_DIR}/session_data.json"
TMPL_FILE = os.getenv("TRADING_VIEWER_TEMPLATE", "M:/Projects/trading_losos/src/components/viewer_template.html")

FILES = {
    "ma": MA_FILE,
    "rsi": RSI_FILE,
    "session": SESSION_FILE,
}

clients = []
lock = threading.Lock()
latest = {}
template = ""
current = "ma"


def load_template():
    global template
    with open(TMPL_FILE, "r", encoding="utf-8") as f:
        template = f.read()


def event_bytes(data):
    return ("data: " + json.dumps(data) + "\n\n").encode("utf-8")


def broadcast(data):
    global latest
    latest = data or {}
    msg = event_bytes(latest)
    with lock:
        for q in list(clients):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


def data_file():
    return FILES.get(current, MA_FILE)


def read_payload(path, strategy):
    if not os.path.exists(path):
        return {
            "timestamp": time.time(),
            "symbols": [],
            "profits": {},
            "history": {},
            "trades": [],
            "open_positions": {},
            "progress": 0,
            "_strategy": strategy,
        }
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["_strategy"] = strategy
    data.setdefault("symbols", [])
    data.setdefault("profits", {})
    data.setdefault("history", {})
    data.setdefault("trades", [])
    data.setdefault("open_positions", {})
    data.setdefault("progress", 0)
    data.setdefault("timestamp", time.time())
    return data


def status():
    return {
        "current": current,
        "ma_available": os.path.exists(MA_FILE),
        "rsi_available": os.path.exists(RSI_FILE),
        "session_available": os.path.exists(SESSION_FILE),
    }


def switch(strategy):
    global current
    if strategy not in FILES:
        return False
    current = strategy
    broadcast(read_payload(data_file(), current))
    print(f"\nSWITCH {current.upper()} {data_file()}")
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = template.replace("{{DATA_JSON}}", json.dumps(latest))
            self.ok("text/html; charset=utf-8", html.encode("utf-8"))
            return
        if self.path == "/data":
            self.ok("application/json", json.dumps(latest).encode("utf-8"))
            return
        if self.path == "/strategy":
            self.ok("application/json", json.dumps(status()).encode("utf-8"))
            return
        if self.path == "/events":
            self.events()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/switch":
            self.send_response(404)
            self.end_headers()
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(size) or b"{}")
            strategy = body.get("strategy")
        except Exception:
            strategy = None
        if switch(strategy):
            self.ok("application/json", json.dumps({"ok": True, "strategy": strategy}).encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()

    def ok(self, content_type, body):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = queue.Queue(maxsize=30)
        with lock:
            clients.append(q)
        try:
            self.wfile.write(event_bytes(latest))
            self.wfile.flush()
        except Exception:
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
        except Exception:
            pass
        finally:
            with lock:
                if q in clients:
                    clients.remove(q)


class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def watch():
    last_path = None
    last_mtime = 0
    while True:
        try:
            path = data_file()
            if path != last_path:
                last_path = path
                last_mtime = 0
            if os.path.exists(path):
                mtime = os.path.getmtime(path)
                if mtime > last_mtime:
                    last_mtime = mtime
                    data = read_payload(path, current)
                    broadcast(data)
                    line(data)
        except Exception as e:
            print(f"\nwatch error {e}")
        time.sleep(0.4)


def line(data):
    total = sum(float(v or 0) for v in data.get("profits", {}).values())
    opened = len(data.get("open_positions", {}))
    shown = len(data.get("symbols", []))
    pct = float(data.get("progress", 0) or 0) * 100
    stamp = datetime.fromtimestamp(data.get("timestamp", time.time())).strftime("%H:%M:%S")
    print(f"\r{stamp} {current.upper()} TOTAL {total:+.2f} OPEN {opened} SYMBOLS {shown} {pct:.1f}%", end="", flush=True)


def first_strategy():
    for name, path in FILES.items():
        if os.path.exists(path):
            return name
    return "ma"


def start_browser(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    global current
    load_template()
    current = first_strategy()
    broadcast(read_payload(data_file(), current))
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    server = Server(("", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"\nVIEWER {url}")
    print(f"MA {MA_FILE}")
    print(f"RSI {RSI_FILE}")
    print(f"SESSION {SESSION_FILE}")
    threading.Timer(1, start_browser, args=[url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nVIEWER STOPPED")


if __name__ == "__main__":
    main()
