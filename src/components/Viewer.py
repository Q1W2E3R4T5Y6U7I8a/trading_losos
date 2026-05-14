import json
import os
import queue
import socketserver
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8765
DATA_DIR = "M:/Projects/trading_losos/data"
MA_DATA_FILE = f"{DATA_DIR}/live_data.json"
RSI_DATA_FILE = f"{DATA_DIR}/rsi_live_data.json"
TMPL_FILE = "M:/Projects/trading_losos/src/components/viewer_template.html"

# Shared state
_clients: list[queue.Queue] = []
_lock = threading.Lock()
_latest: dict = {}
_template: str = ""
_current_strategy: str = "ma"
_current_data_file: str = MA_DATA_FILE

# Track which symbols belong to which strategy (based on magic number)
# You can manually specify or auto-detect
MA_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "CADJPY", "CADCHF", "CHFJPY", "NZDJPY", "NZDCAD",
]

RSI_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "CADJPY", "CADCHF", "CHFJPY", "NZDJPY", "NZDCAD",
]


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


def filter_data_by_strategy(data: dict, strategy: str) -> dict:
    """Filter the data to only show trades from the selected strategy"""
    if data is None or "symbols" not in data:
        return data
    
    # Determine which symbols to keep
    allowed_symbols = MA_SYMBOLS if strategy == "ma" else RSI_SYMBOLS
    
    # Create filtered copy
    filtered_data = data.copy()
    
    # Filter symbols list
    filtered_data["symbols"] = [s for s in data["symbols"] if s in allowed_symbols]
    
    # Filter profits
    if "profits" in filtered_data:
        filtered_data["profits"] = {k: v for k, v in data["profits"].items() if k in allowed_symbols}
    
    # Filter history
    if "history" in filtered_data:
        filtered_data["history"] = {k: v for k, v in data["history"].items() if k in allowed_symbols}
    
    # Filter open positions
    if "open_positions" in filtered_data:
        filtered_data["open_positions"] = {k: v for k, v in data["open_positions"].items() if k in allowed_symbols}
    
    # Filter trades
    if "trades" in filtered_data:
        filtered_data["trades"] = [t for t in data["trades"] if t.get("symbol") in allowed_symbols]
    
    return filtered_data


def switch_strategy(strategy: str):
    """Switch between MA and RSI strategies"""
    global _current_strategy, _current_data_file, _latest
    _current_strategy = strategy
    _current_data_file = MA_DATA_FILE if strategy == "ma" else RSI_DATA_FILE
    print(f"\n  🔄 Switched to {strategy.upper()} strategy")
    print(f"  📁 Reading from: {_current_data_file}")
    
    # Force reload of latest data
    if os.path.exists(_current_data_file):
        try:
            with open(_current_data_file, "r") as f:
                raw_data = json.load(f)
            # Filter the data to only show this strategy's symbols
            _latest = filter_data_by_strategy(raw_data, strategy)
            broadcast(_latest)
        except Exception as e:
            print(f"  Error loading {strategy} data: {e}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = _template.replace("{{DATA_JSON}}", json.dumps(_latest))
            self._ok("text/html; charset=utf-8", html.encode())

        elif self.path == "/data":
            self._ok("application/json", json.dumps(_latest).encode())

        elif self.path == "/strategy":
            info = {
                "current": _current_strategy,
                "ma_available": os.path.exists(MA_DATA_FILE),
                "rsi_available": os.path.exists(RSI_DATA_FILE),
            }
            self._ok("application/json", json.dumps(info).encode())

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

    def do_POST(self):
        if self.path == "/switch":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = json.loads(self.rfile.read(content_length))
            strategy = post_data.get('strategy', 'ma')
            if strategy in ['ma', 'rsi']:
                switch_strategy(strategy)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "strategy": strategy}).encode())
            else:
                self.send_response(400)
                self.end_headers()
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
    """Watch the currently selected data file and filter by strategy"""
    last_mtime = 0.0
    last_file = None
    
    while True:
        try:
            current_file = _current_data_file
            
            if os.path.exists(current_file):
                mtime = os.path.getmtime(current_file)
                if mtime > last_mtime or current_file != last_file:
                    last_mtime = mtime
                    last_file = current_file
                    with open(current_file, "r") as f:
                        raw_data = json.load(f)
                    # Apply strategy filtering
                    filtered_data = filter_data_by_strategy(raw_data, _current_strategy)
                    broadcast(filtered_data)
                    
                    total = sum(filtered_data.get("profits", {}).values())
                    ts = datetime.fromtimestamp(filtered_data["timestamp"]).strftime("%H:%M:%S")
                    pct = filtered_data.get("progress", 0) * 100
                    strategy_indicator = "📈 MA" if _current_strategy == "ma" else "📉 RSI"
                    symbols_shown = len(filtered_data.get("symbols", []))
                    print(f"\r  [{ts}] {strategy_indicator}  TOTAL: ${total:+.2f}  |  {pct:.1f}%  |  open: {len(filtered_data.get('open_positions', {}))}  |  showing: {symbols_shown}/27", end="", flush=True)
        except Exception as e:
            print(f"\n  watch error: {e}")
        time.sleep(0.4)


def main():
    load_template()
    
    if os.path.exists(MA_DATA_FILE):
        switch_strategy("ma")
    elif os.path.exists(RSI_DATA_FILE):
        switch_strategy("rsi")
    
    threading.Thread(target=watch_file, daemon=True).start()
    
    server = ThreadedHTTPServer(("", PORT), Handler)
    url = f"http://localhost:{PORT}"
    
    print(f"\n  🚀 3D VIEWER  →  {url}")
    print(f"  📁 MA data  →  {MA_DATA_FILE}")
    print(f"  📁 RSI data →  {RSI_DATA_FILE}")
    print(f"  🎮 Buttons show ONLY the selected strategy's trades\n")
    
    threading.Timer(1.0, webbrowser.open, args=[url]).start()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n  VIEWER STOPPED")
        server.server_close()


if __name__ == "__main__":
    main()