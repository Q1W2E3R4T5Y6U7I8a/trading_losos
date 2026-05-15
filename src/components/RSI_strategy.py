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

SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "CADJPY", "CADCHF", "CHFJPY", "NZDJPY", "NZDCAD",
]

PERIOD = 14
LOW = 15
HIGH = 85
VOLUME = 0.01
CLOSE_HOURS = 4
TIMEFRAME = mt5.TIMEFRAME_M5
MAX_SPREAD = 50
SLIPPAGE = 10
MAGIC = 123460

DATA_DIR = os.getenv("TRADING_DATA_DIR", "M:/Projects/trading_losos/data")
DATA_FILE = f"{DATA_DIR}/rsi_live_data.json"


def now():
    return datetime.utcnow()


def rates(symbol, count=100):
    raw = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, count)
    if raw is None or len(raw) == 0:
        return None
    return pd.DataFrame(raw)


def rsi(prices):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(PERIOD).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def signal(symbol):
    info = mt5.symbol_info(symbol)
    if info is None or info.spread > MAX_SPREAD:
        return None, None
    df = rates(symbol, PERIOD + 20)
    if df is None or len(df) < PERIOD + 1:
        return None, None
    value = rsi(df["close"]).iloc[-1]
    if pd.isna(value):
        return None, None
    value = round(float(value), 1)
    if value < LOW:
        return "BUY", value
    if value > HIGH:
        return "SELL", value
    return None, value


def send(symbol, side, value):
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None or info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        return None
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if side == "BUY" else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": VOLUME,
        "type": order_type,
        "price": price,
        "slippage": SLIPPAGE,
        "magic": MAGIC,
        "comment": f"RSI_{PERIOD}_{value}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        text = getattr(result, "comment", mt5.last_error())
        print(f"\n{symbol} OPEN FAILED {text}")
        return None
    print(f"\n{symbol} OPEN {side} {result.order} {result.price:.5f} RSI {value}")
    return result


def close(symbol, pos):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    side = pos["type"]
    order_type = mt5.ORDER_TYPE_SELL if side == "BUY" else mt5.ORDER_TYPE_BUY
    price = tick.bid if side == "BUY" else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": pos["volume"],
        "type": order_type,
        "position": pos["ticket"],
        "price": price,
        "slippage": SLIPPAGE,
        "magic": MAGIC,
        "comment": "RSI_CLOSE",
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


def pnl(ticket):
    open_pos = mt5.positions_get(ticket=ticket)
    if open_pos:
        return float(open_pos[0].profit)
    deals = mt5.history_deals_get(position=ticket)
    if not deals:
        return 0.0
    return float(sum(d.profit + d.swap + d.commission for d in deals))


def live_positions():
    raw = mt5.positions_get()
    out = {}
    if not raw:
        return out
    for p in raw:
        if getattr(p, "magic", None) != MAGIC:
            continue
        if p.symbol not in SYMBOLS:
            continue
        opened = datetime.utcfromtimestamp(p.time)
        out[p.symbol] = {
            "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
            "ticket": p.ticket,
            "volume": p.volume,
            "open_price": p.price_open,
            "open_time": opened,
            "close_time": opened + timedelta(hours=CLOSE_HOURS),
        }
    return out


def ts(dt):
    return dt.timestamp()


def write_json(dt, realized, history, trades, positions):
    profits = {}
    visible = {}
    for symbol in SYMBOLS:
        if symbol in positions:
            p = positions[symbol]
            u = pnl(p["ticket"])
            profits[symbol] = round(realized[symbol] + u, 4)
            visible[symbol] = {
                "type": p["type"],
                "open_time": ts(p["open_time"]),
                "close_time": ts(p["close_time"]),
                "open_price": p["open_price"],
                "unrealized_pnl": round(u, 4),
            }
        else:
            profits[symbol] = round(realized[symbol], 4)
    os.makedirs(DATA_DIR, exist_ok=True)
    body = {
        "timestamp": ts(dt),
        "profits": profits,
        "history": history,
        "trades": trades[-200:],
        "open_positions": visible,
        "symbols": SYMBOLS,
        "progress": 0.5,
        "_strategy": "rsi",
    }
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
        print(f"RSI CONNECTED {acc.login} BALANCE {acc.balance:.2f}")
    return True


def open_trade(symbol, side, value, positions, history, realized, dt):
    result = send(symbol, side, value)
    if result is None:
        return
    positions[symbol] = {
        "type": side,
        "ticket": result.order,
        "volume": VOLUME,
        "open_price": result.price,
        "open_time": dt,
        "close_time": dt + timedelta(hours=CLOSE_HOURS),
    }
    history[symbol].append([ts(dt), round(realized[symbol], 4)])


def close_trade(symbol, pos, realized, history, trades, positions, dt):
    result = close(symbol, pos)
    if result is None:
        return
    value = pnl(pos["ticket"])
    realized[symbol] += value
    trades.append({
        "symbol": symbol,
        "type": pos["type"],
        "open_time": ts(pos["open_time"]),
        "close_time": ts(dt),
        "open_price": pos["open_price"],
        "close_price": result.price,
        "pnl": value,
    })
    history[symbol].append([ts(dt), round(realized[symbol], 4)])
    positions.pop(symbol, None)


def sample_text():
    df = rates(SYMBOLS[0], 50)
    if df is None:
        return "---"
    value = rsi(df.close).iloc[-1]
    return "---" if pd.isna(value) else f"{value:.1f}"


def loop():
    positions = live_positions()
    realized = {s: 0.0 for s in SYMBOLS}
    history = {s: [] for s in SYMBOLS}
    trades = []
    checked = {}
    print("RSI RUNNING")
    while True:
        dt = now()
        for symbol in SYMBOLS:
            if symbol in positions and dt >= positions[symbol]["close_time"]:
                close_trade(symbol, positions[symbol], realized, history, trades, positions, dt)
            if symbol not in positions:
                last = checked.get(symbol, datetime.min)
                if (dt - last).total_seconds() >= 60:
                    checked[symbol] = dt
                    side, value = signal(symbol)
                    if side:
                        open_trade(symbol, side, value, positions, history, realized, dt)
        write_json(dt, realized, history, trades, positions)
        rp = sum(realized.values())
        up = sum(pnl(p["ticket"]) for p in positions.values())
        print(f"\r{dt:%H:%M:%S} RSI R {rp:+.2f} U {up:+.2f} O {len(positions)} T {len(trades)} V {sample_text()}", end="")
        time.sleep(1)


def shutdown():
    mt5.shutdown()
    print("\nRSI STOPPED")


def main():
    print("RSI STRATEGY")
    print(f"{PERIOD} {LOW}/{HIGH} VOLUME {VOLUME} CLOSE {CLOSE_HOURS}H")
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
