import json
import os
import time
from datetime import datetime, timedelta

import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv


load_dotenv()

LOGIN = int(os.getenv("LOGIN", "0"))
PASSWORD = os.getenv("PASSWORD")
SERVER = os.getenv("SERVER")

SESSIONS = {
    "ASIA": {
        "open": 0,
        "close": 1,
        "symbols": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY"],
    },
    "EUROPE": {
        "open": 8,
        "close": 9,
        "symbols": [
            "GBPUSD", "EURGBP", "GBPJPY", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
            "EURUSD", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
        ],
    },
    "US": {
        "open": 13,
        "close": 14,
        "symbols": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"],
    },
}

SYMBOLS = sorted({symbol for cfg in SESSIONS.values() for symbol in cfg["symbols"]})
ENTRY = 0.382
VOLUME = 0.01
CLOSE_BEFORE = 30
TIMEFRAME = mt5.TIMEFRAME_M5
MAX_SPREAD = 50
SLIPPAGE = 10
MAGIC = 123459

DATA_DIR = os.getenv("TRADING_DATA_DIR", "M:/Projects/trading_losos/data")
DATA_FILE = f"{DATA_DIR}/session_data.json"


def now():
    return datetime.utcnow()


def ts(dt):
    return dt.timestamp()


def session_now(dt):
    hour = dt.hour + dt.minute / 60
    for name, cfg in SESSIONS.items():
        if cfg["open"] <= hour < cfg["close"]:
            return name, cfg
    return None, None


def window(dt, cfg):
    start = dt.replace(hour=cfg["open"], minute=0, second=0, microsecond=0)
    end = dt.replace(hour=cfg["close"], minute=0, second=0, microsecond=0)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def rates_range(symbol, start, end):
    raw = mt5.copy_rates_range(symbol, TIMEFRAME, start, end)
    if raw is None or len(raw) == 0:
        return None
    return pd.DataFrame(raw)


def limit_price(symbol, start):
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None or info.spread > MAX_SPREAD:
        return None
    df = rates_range(symbol, start, now())
    if df is None or len(df) < 2:
        return None
    high = float(df["high"].max())
    low = float(df["low"].min())
    move = high - low
    if move <= 0:
        return None
    price = high - (move * ENTRY)
    return round(price, 5), round(move, 5)


def place(symbol, session, price):
    info = mt5.symbol_info(symbol)
    if info is None or info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        return None
    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": VOLUME,
        "type": mt5.ORDER_TYPE_BUY_LIMIT,
        "price": price,
        "slippage": SLIPPAGE,
        "magic": MAGIC,
        "comment": f"SESSION_{session}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        text = getattr(result, "comment", mt5.last_error())
        print(f"\n{symbol} ORDER FAILED {text}")
        return None
    print(f"\n{symbol} ORDER {result.order} {price:.5f}")
    return result


def positions():
    raw = mt5.positions_get()
    out = {}
    if not raw:
        return out
    for p in raw:
        if getattr(p, "magic", None) != MAGIC:
            continue
        if p.symbol not in SYMBOLS:
            continue
        out[p.symbol] = {
            "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
            "ticket": p.ticket,
            "volume": p.volume,
            "open_price": p.price_open,
            "open_time": datetime.utcfromtimestamp(p.time),
            "current_pnl": float(p.profit),
        }
    return out


def orders():
    raw = mt5.orders_get()
    out = {}
    if not raw:
        return out
    for order in raw:
        if getattr(order, "magic", None) != MAGIC:
            continue
        if order.symbol in SYMBOLS:
            out[order.symbol] = {"ticket": order.ticket, "price": order.price_open}
    return out


def close(symbol, pos):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": pos["volume"],
        "type": mt5.ORDER_TYPE_SELL,
        "position": pos["ticket"],
        "price": tick.bid,
        "slippage": SLIPPAGE,
        "magic": MAGIC,
        "comment": "SESSION_CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        text = getattr(result, "comment", mt5.last_error())
        print(f"\n{symbol} CLOSE FAILED {text}")
        return None
    print(f"\n{symbol} CLOSE {pos['ticket']} {result.price:.5f}")
    return result


def cancel(ticket):
    result = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
    return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE


def pnl(ticket):
    open_pos = mt5.positions_get(ticket=ticket)
    if open_pos:
        return float(open_pos[0].profit)
    deals = mt5.history_deals_get(position=ticket)
    if not deals:
        return 0.0
    return float(sum(d.profit + d.swap + d.commission for d in deals))


def history_from(trades):
    out = {}
    totals = {}
    for trade in sorted(trades, key=lambda x: x["close_time"]):
        sym = trade["symbol"]
        totals[sym] = totals.get(sym, 0.0) + trade["pnl"]
        out.setdefault(sym, []).append([trade["close_time"], round(totals[sym], 4)])
    return out


def write_json(dt, trades, active, pending, start, end):
    profits = {}
    for trade in trades:
        profits[trade["symbol"]] = profits.get(trade["symbol"], 0.0) + trade["pnl"]
    for sym, pos in active.items():
        profits[sym] = profits.get(sym, 0.0) + pos["current_pnl"]
    visible = {}
    close_at = end - timedelta(minutes=CLOSE_BEFORE) if end else dt
    for sym, pos in active.items():
        visible[sym] = {
            "type": pos["type"],
            "open_price": pos["open_price"],
            "open_time": ts(pos["open_time"]),
            "close_time": ts(close_at),
            "unrealized_pnl": round(pos["current_pnl"], 4),
        }
    progress = 0.0
    if start and end:
        total = (end - start).total_seconds()
        progress = max(0.0, min(1.0, (dt - start).total_seconds() / total)) if total else 0.0
    body = {
        "timestamp": ts(dt),
        "symbols": SYMBOLS,
        "profits": {k: round(v, 4) for k, v in profits.items()},
        "history": history_from(trades),
        "trades": trades[-100:],
        "open_positions": visible,
        "pending_orders": pending,
        "progress": progress,
        "_strategy": "session",
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f)
    os.replace(tmp, DATA_FILE)


def connect():
    if not mt5.initialize():
        print("MT5 INIT FAILED")
        return False
    if not mt5.login(LOGIN, password=PASSWORD, server=SERVER):
        print(f"LOGIN FAILED {mt5.last_error()}")
        mt5.shutdown()
        return False
    acc = mt5.account_info()
    if acc:
        print(f"SESSION CONNECTED {acc.login} BALANCE {acc.balance:.2f}")
    return True


def place_orders(name, cfg, start, active, pending):
    count = 0
    for symbol in cfg["symbols"]:
        if symbol in active or symbol in pending:
            continue
        levels = limit_price(symbol, start)
        if levels is None:
            continue
        price, move = levels
        result = place(symbol, name, price)
        if result is not None:
            pending[symbol] = {"ticket": result.order, "price": price, "move": move}
            count += 1
    print(f"\n{name} ORDERS {count}")


def close_all(active, pending, trades, session, dt):
    for symbol, pos in list(active.items()):
        result = close(symbol, pos)
        if result is None:
            continue
        value = pnl(pos["ticket"])
        trades.append({
            "symbol": symbol,
            "type": pos["type"],
            "open_time": ts(pos["open_time"]),
            "close_time": ts(dt),
            "open_price": pos["open_price"],
            "close_price": result.price,
            "pnl": value,
            "session": session,
        })
        active.pop(symbol, None)
    for symbol, order in list(pending.items()):
        if cancel(order["ticket"]):
            pending.pop(symbol, None)


def sync(active, pending):
    fresh = positions()
    for symbol, pos in fresh.items():
        if symbol not in active:
            print(f"\n{symbol} FILLED {pos['open_price']:.5f}")
        active[symbol] = pos
        pending.pop(symbol, None)
    for symbol in list(active):
        if symbol not in fresh:
            active.pop(symbol, None)
    pending.clear()
    pending.update(orders())


def loop():
    active = positions()
    pending = orders()
    trades = []
    current = None
    start = None
    end = None
    placed = False
    print("SESSION RUNNING")
    while True:
        dt = now()
        name, cfg = session_now(dt)
        if name != current:
            current = name
            placed = False
            start, end = window(dt, cfg) if cfg else (None, None)
            if name:
                print(f"\n{name} {start:%H:%M}-{end:%H:%M}")
        if current and end and dt >= end - timedelta(minutes=CLOSE_BEFORE):
            close_all(active, pending, trades, current, dt)
            placed = True
        if current and start and end and not placed and start <= dt < start + timedelta(minutes=5):
            place_orders(current, SESSIONS[current], start, active, pending)
            placed = True
        if end and dt >= end:
            current = None
            start = None
            end = None
            placed = False
        sync(active, pending)
        write_json(dt, trades, active, pending, start, end)
        total = sum(p["current_pnl"] for p in active.values())
        status = current or "WAIT"
        print(f"\r{dt:%H:%M:%S} SESSION {status:<6} P {len(active)} Q {len(pending)} U {total:+.2f}", end="")
        time.sleep(2)


def shutdown():
    mt5.shutdown()
    print("\nSESSION STOPPED")


def main():
    print("SESSION STRATEGY")
    print(f"ENTRY {ENTRY} VOLUME {VOLUME} CLOSE {CLOSE_BEFORE}M")
    if not connect():
        return
    try:
        loop()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\nERROR {e}")
        time.sleep(5)
        raise
    finally:
        shutdown()


if __name__ == "__main__":
    main()
