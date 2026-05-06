import os
import time
import json
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv
import MetaTrader5 as mt5

load_dotenv()

LOGIN    = int(os.getenv("LOGIN"))
PASSWORD = os.getenv("PASSWORD")
SERVER   = os.getenv("SERVER")

SYMBOLS = [
    "EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD",
    "EURGBP","EURJPY","EURCHF","EURAUD","EURCAD","EURNZD",
    "GBPJPY","GBPCHF","GBPAUD","GBPCAD","GBPNZD",
    "AUDJPY","AUDCHF","AUDCAD","AUDNZD",
    "CADJPY","CADCHF","CHFJPY","NZDJPY","NZDCAD",
]

FAST_MA     = 10
SLOW_MA     = 30
VOLUME      = 0.01
CLOSE_HOURS = 4
TIMEFRAME   = mt5.TIMEFRAME_M5
STEP        = timedelta(minutes=5)

DATA_DIR  = "M:/Projects/trading_losos/data"
DATA_FILE = f"{DATA_DIR}/live_data.json"


def get_rates(symbol, sim_time, count=100):
    rates = mt5.copy_rates_from(symbol, TIMEFRAME, sim_time, count)
    if rates is None or len(rates) == 0:
        return None
    return pd.DataFrame(rates)


def get_signal(symbol, sim_time):
    df = get_rates(symbol, sim_time, 100)
    if df is None or len(df) < SLOW_MA + 1:
        return None
    fast = df["close"].rolling(FAST_MA).mean()
    slow = df["close"].rolling(SLOW_MA).mean()
    crossed_up   = fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]
    crossed_down = fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]
    return "BUY" if crossed_up else "SELL" if crossed_down else None


def get_close_price(symbol, sim_time):
    df = get_rates(symbol, sim_time, 1)
    return float(df["close"].iloc[0]) if df is not None else None


def calc_pnl(symbol, order_type, open_price, close_price):
    """P&L in USD for 0.01 lot. Handles JPY cross-rate correctly."""
    delta = close_price - open_price if order_type == "BUY" else open_price - close_price

    # Pip size varies by pair
    if "JPY" in symbol:
        pips = delta * 100        # 1 pip = 0.01 for JPY pairs
    else:
        pips = delta * 10_000     # 1 pip = 0.0001 for standard pairs

    # USD value per pip at 0.01 lot
    # For USD-quote pairs (EURUSD, GBPUSD…): $0.10/pip
    # For USD-base pairs (USDJPY, USDCHF…): $0.10/pip ÷ close_price * pip_size
    # For cross pairs: simplified as $0.10/pip (acceptable for simulation)
    if symbol.startswith("USD"):
        if "JPY" in symbol:
            pip_value = 0.10 / close_price * 100
        else:
            pip_value = 0.10 / close_price
    else:
        pip_value = 0.10

    return round(pips * pip_value, 4)


def save_data(sim_time, profits, history, trades, open_positions, progress):
    payload = {
        "timestamp":      sim_time.timestamp(),
        "profits":        profits,
        "history":        history,
        "trades":         trades,         # list of closed trade dicts
        "open_positions": open_positions, # symbol → position dict with unrealized_pnl
        "symbols":        SYMBOLS,
        "progress":       progress,
    }
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    for attempt in range(3):
        try:
            os.replace(tmp, DATA_FILE)
            return
        except OSError:
            if attempt < 2:
                time.sleep(0.1)
            else:
                with open(DATA_FILE, "w") as f:
                    json.dump(payload, f)


def main():
    print("  MA STRATEGY  //  connecting to MT5...")
    if not mt5.initialize():
        print("  MT5 init failed"); return
    if not mt5.login(LOGIN, password=PASSWORD, server=SERVER):
        print("  Login failed"); mt5.shutdown(); return
    print("  MT5 connected\n")

    os.makedirs(DATA_DIR, exist_ok=True)

    sim_start   = datetime.now() - timedelta(hours=24)
    current_sim = sim_start

    positions       = {}
    cumulative_pnl  = {s: 0.0 for s in SYMBOLS}
    trade_history   = {s: []  for s in SYMBOLS}   # (timestamp, cumulative_pnl) checkpoints
    closed_trades   = []                            # detailed trade log
    last_candle     = {}

    print(f"  SIM START : {sim_start.strftime('%Y-%m-%d %H:%M')}")
    print(f"  DATA FILE : {DATA_FILE}\n")

    while True:
        try:
            now = datetime.now()

            while current_sim <= now:
                for symbol in SYMBOLS:
                    pos = positions.get(symbol)

                    # ── Close expired positions ──────────────────────────────
                    if pos and current_sim >= pos["close_time"]:
                        close_price = get_close_price(symbol, pos["close_time"])
                        if close_price is None:
                            close_price = pos["open_price"]

                        pnl = calc_pnl(symbol, pos["type"], pos["open_price"], close_price)
                        cumulative_pnl[symbol] += pnl

                        # Record CLOSE checkpoint in equity curve
                        trade_history[symbol].append(
                            (pos["close_time"].timestamp(), round(cumulative_pnl[symbol], 4))
                        )

                        # Detailed trade record
                        closed_trades.append({
                            "symbol":      symbol,
                            "type":        pos["type"],
                            "open_time":   pos["open_time"].timestamp(),
                            "close_time":  pos["close_time"].timestamp(),
                            "open_price":  pos["open_price"],
                            "close_price": close_price,
                            "pnl":         pnl,
                        })

                        print(f"  CLOSE  {symbol:8s} {pos['type']:4s}  pnl={'+' if pnl>=0 else ''}{pnl:.2f}")
                        del positions[symbol]
                        pos = None

                    # ── Open new positions ───────────────────────────────────
                    if pos is None:
                        signal = get_signal(symbol, current_sim)
                        if signal:
                            rates = mt5.copy_rates_from(symbol, TIMEFRAME, current_sim, 1)
                            if rates is not None and len(rates) > 0:
                                candle_time = rates[0]["time"]
                                if last_candle.get(symbol) != candle_time:
                                    price = get_close_price(symbol, current_sim)
                                    if price:
                                        positions[symbol] = {
                                            "type":       signal,
                                            "open_price": price,
                                            "open_time":  current_sim,
                                            "close_time": current_sim + timedelta(hours=CLOSE_HOURS),
                                        }
                                        last_candle[symbol] = candle_time

                                        # Record OPEN checkpoint (equity baseline before trade resolves)
                                        trade_history[symbol].append(
                                            (current_sim.timestamp(), round(cumulative_pnl[symbol], 4))
                                        )
                                        print(f"  OPEN   {symbol:8s} {signal:4s}  @ {price:.5f}  [{current_sim.strftime('%H:%M')}]")

                # ── Snapshot: live P&L including unrealized ──────────────────
                live_profits    = {}
                open_positions  = {}
                for symbol in SYMBOLS:
                    pos = positions.get(symbol)
                    if pos:
                        cur = get_close_price(symbol, current_sim) or pos["open_price"]
                        unreal = calc_pnl(symbol, pos["type"], pos["open_price"], cur)
                        live_profits[symbol] = round(cumulative_pnl[symbol] + unreal, 4)
                        open_positions[symbol] = {
                            "type":          pos["type"],
                            "open_time":     pos["open_time"].timestamp(),
                            "close_time":    pos["close_time"].timestamp(),
                            "open_price":    pos["open_price"],
                            "unrealized_pnl": round(unreal, 4),
                        }
                    else:
                        live_profits[symbol] = round(cumulative_pnl[symbol], 4)

                progress = (current_sim - sim_start).total_seconds() / 86_400
                save_data(current_sim, live_profits, trade_history,
                          closed_trades[-200:],  # keep last 200 trades
                          open_positions, progress)

                current_sim += STEP

            total = sum(cumulative_pnl.values())
            print(f"\r  SIM {current_sim.strftime('%H:%M:%S')}  |  TOTAL: {'+' if total>=0 else ''}{total:.2f}  |  OPEN: {len(positions)}", end="")
            time.sleep(1)

        except KeyboardInterrupt:
            print("\n\n  STRATEGY STOPPED"); break
        except Exception as e:
            print(f"\n  ERR: {e}"); time.sleep(1)

    mt5.shutdown()


if __name__ == "__main__":
    main()