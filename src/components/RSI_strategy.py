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

RSI_PERIOD   = 14
RSI_OVERSOLD = 15      # Buy when RSI < 15
RSI_OVERBOUGHT = 85    # Sell when RSI > 85
VOLUME       = 0.01
CLOSE_HOURS  = 4
TIMEFRAME    = mt5.TIMEFRAME_M5
STEP         = timedelta(minutes=5)

DATA_DIR  = "M:/Projects/trading_losos/data"
DATA_FILE = f"{DATA_DIR}/rsi_live_data.json"  # Different file name to avoid conflict


def get_rates(symbol, sim_time, count=100):
    rates = mt5.copy_rates_from(symbol, TIMEFRAME, sim_time, count)
    if rates is None or len(rates) == 0:
        return None
    return pd.DataFrame(rates)


def calculate_rsi(prices, period=14):
    """Calculate RSI from price series"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def get_signal(symbol, sim_time):
    """Returns BUY if RSI < 15, SELL if RSI > 85, else None"""
    df = get_rates(symbol, sim_time, 100)
    if df is None or len(df) < RSI_PERIOD + 5:
        return None
    
    rsi = calculate_rsi(df["close"], RSI_PERIOD)
    if rsi.iloc[-1] < RSI_OVERSOLD:
        return "BUY"
    elif rsi.iloc[-1] > RSI_OVERBOUGHT:
        return "SELL"
    return None


def get_close_price(symbol, sim_time):
    df = get_rates(symbol, sim_time, 1)
    return float(df["close"].iloc[0]) if df is not None else None


def calc_pnl(symbol, order_type, open_price, close_price):
    """P&L in USD for 0.01 lot. Handles JPY cross-rate correctly."""
    delta = close_price - open_price if order_type == "BUY" else open_price - close_price

    if "JPY" in symbol:
        pips = delta * 100
    else:
        pips = delta * 10_000

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
        "trades":         trades,
        "open_positions": open_positions,
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
    print("  RSI STRATEGY  //  connecting to MT5...")
    print("  RSI Settings: BUY when RSI < 15, SELL when RSI > 85")
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
    trade_history   = {s: []  for s in SYMBOLS}
    closed_trades   = []
    last_candle     = {}
    last_rsi_value  = {}  # Store last RSI for debugging

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

                        trade_history[symbol].append(
                            (pos["close_time"].timestamp(), round(cumulative_pnl[symbol], 4))
                        )

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

                    # ── Open new positions based on RSI ──────────────────────
                    if pos is None:
                        signal = get_signal(symbol, current_sim)
                        if signal:
                            rates = mt5.copy_rates_from(symbol, TIMEFRAME, current_sim, 1)
                            if rates is not None and len(rates) > 0:
                                candle_time = rates[0]["time"]
                                if last_candle.get(symbol) != candle_time:
                                    price = get_close_price(symbol, current_sim)
                                    if price:
                                        # Calculate current RSI for logging
                                        df = get_rates(symbol, current_sim, 100)
                                        if df is not None:
                                            rsi = calculate_rsi(df["close"], RSI_PERIOD)
                                            last_rsi_value[symbol] = round(rsi.iloc[-1], 1)
                                        
                                        positions[symbol] = {
                                            "type":       signal,
                                            "open_price": price,
                                            "open_time":  current_sim,
                                            "close_time": current_sim + timedelta(hours=CLOSE_HOURS),
                                        }
                                        last_candle[symbol] = candle_time

                                        trade_history[symbol].append(
                                            (current_sim.timestamp(), round(cumulative_pnl[symbol], 4))
                                        )
                                        
                                        rsi_info = f" (RSI: {last_rsi_value.get(symbol, '?')})"
                                        print(f"  OPEN   {symbol:8s} {signal:4s}  @ {price:.5f}  [{current_sim.strftime('%H:%M')}]{rsi_info}")

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
                          closed_trades[-200:],
                          open_positions, progress)

                current_sim += STEP

            total = sum(cumulative_pnl.values())
            print(f"\r  SIM {current_sim.strftime('%H:%M:%S')}  |  TOTAL: {'+' if total>=0 else ''}{total:.2f}  |  OPEN: {len(positions)}", end="")
            time.sleep(1)

        except KeyboardInterrupt:
            print("\n\n  RSI STRATEGY STOPPED"); break
        except Exception as e:
            print(f"\n  ERR: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

    mt5.shutdown()


if __name__ == "__main__":
    main()