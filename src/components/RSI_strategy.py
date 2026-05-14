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
CLOSE_HOURS  = 4        # Close after 4 REAL hours
TIMEFRAME    = mt5.TIMEFRAME_M5

DATA_DIR  = "M:/Projects/trading_losos/data"
DATA_FILE = f"{DATA_DIR}/rsi_live_data.json"

# Safety settings for REAL trading
MAX_SPREAD = 50
SLIPPAGE = 10
MAGIC_NUMBER = 123458


def get_rates(symbol, count=100):
    """Get latest rates from MT5"""
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, count)
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


def get_signal(symbol):
    """Returns BUY if RSI < 15, SELL if RSI > 85, else None"""
    df = get_rates(symbol, 100)
    if df is None or len(df) < RSI_PERIOD + 5:
        return None, None
    
    rsi = calculate_rsi(df["close"], RSI_PERIOD)
    current_rsi = rsi.iloc[-1]
    
    if current_rsi < RSI_OVERSOLD:
        return "BUY", round(current_rsi, 1)
    elif current_rsi > RSI_OVERBOUGHT:
        return "SELL", round(current_rsi, 1)
    return None, None


def get_current_price(symbol):
    """Get current bid/ask prices"""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None, None
    return tick.ask, tick.bid


def check_spread(symbol):
    """Check if spread is acceptable"""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return False
    spread = symbol_info.spread
    if spread > MAX_SPREAD:
        print(f"  ⚠️ {symbol}: Spread too high ({spread} > {MAX_SPREAD})")
        return False
    return True


def place_order(symbol, order_type, volume, rsi_value):
    """Place REAL order on MT5"""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None or symbol_info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        return None, None
    
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None, None
    
    if order_type == "BUY":
        price = tick.ask
        order_type_mt5 = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        order_type_mt5 = mt5.ORDER_TYPE_SELL
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type_mt5,
        "price": price,
        "slippage": SLIPPAGE,
        "magic": MAGIC_NUMBER,
        "comment": f"RSI_{RSI_PERIOD}_{rsi_value}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    print(f"  📝 {symbol}: {order_type} (RSI: {rsi_value}) at {price:.5f}...")
    result = mt5.order_send(request)
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"  ❌ {symbol}: Order failed - {result.comment}")
        return None, None
    
    print(f"  ✅ {symbol}: {order_type} order placed! Ticket: {result.order}")
    return result, result.order


def close_position(symbol, position_ticket, volume, order_type):
    """Close an existing position"""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, None
    
    if order_type == "BUY":
        price = tick.bid
        close_type = mt5.ORDER_TYPE_SELL
    else:
        price = tick.ask
        close_type = mt5.ORDER_TYPE_BUY
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": close_type,
        "position": position_ticket,
        "price": price,
        "slippage": SLIPPAGE,
        "magic": MAGIC_NUMBER,
        "comment": "Close_RSI_trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"  ❌ {symbol}: Close failed - {result.comment}")
        return False, result
    
    print(f"  ✅ {symbol}: Position {position_ticket} closed")
    return True, result


def get_position_pnl(ticket):
    """Get actual P&L from MT5"""
    positions = mt5.positions_get(ticket=ticket)
    if positions and len(positions) > 0:
        return positions[0].profit
    
    # Check closed positions in history
    deals = mt5.history_deals_get(position=ticket)
    if deals and len(deals) > 0:
        return sum(deal.profit + deal.swap + deal.commission for deal in deals)
    
    return 0.0


def get_live_positions():
    """Get open positions from MT5"""
    positions = mt5.positions_get(magic=MAGIC_NUMBER)
    if positions is None:
        return {}
    
    live_positions = {}
    for pos in positions:
        open_time = datetime.utcfromtimestamp(pos.time)
        if open_time > datetime.utcnow():
            print(f"  ⚠️ Skipping {pos.symbol} position with future open_time")
            continue
        live_positions[pos.symbol] = {
            "ticket": pos.ticket,
            "type": "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL",
            "volume": pos.volume,
            "open_price": pos.price_open,
            "open_time": open_time,
            "current_pnl": pos.profit,
        }
    return live_positions


def save_data(timestamp, profits, history, trades, open_positions):
    """Save data for visualization"""
    payload = {
        "timestamp": timestamp.timestamp(),
        "profits": profits,
        "history": history,
        "trades": trades,
        "open_positions": open_positions,
        "symbols": SYMBOLS,
        "progress": 0.5,
    }
    
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, DATA_FILE)


def main():
    print("=" * 70)
    print("  RSI STRATEGY // REAL TIME TRADING")
    print(f"  Settings: BUY when RSI < {RSI_OVERSOLD} | SELL when RSI > {RSI_OVERBOUGHT}")
    print(f"  Period: {RSI_PERIOD} | Volume: {VOLUME} lots | Auto-close: {CLOSE_HOURS}h")
    print("=" * 70)
    
    # Initialize MT5
    print("\n  Connecting to MetaTrader 5...")
    if not mt5.initialize():
        print("  ❌ MT5 initialization failed")
        return
    
    if not mt5.login(LOGIN, password=PASSWORD, server=SERVER):
        print(f"  ❌ Login failed: {mt5.last_error()}")
        mt5.shutdown()
        return
    
    print("  ✅ MT5 connected!\n")
    
    account_info = mt5.account_info()
    if account_info:
        print(f"  Account: {account_info.login} | Balance: ${account_info.balance:.2f}")
    
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Load existing positions
    positions = {}
    live_positions = get_live_positions()
    for symbol, pos in live_positions.items():
        if symbol in SYMBOLS:
            positions[symbol] = {
                "type": pos["type"],
                "open_price": pos["open_price"],
                "open_time": pos["open_time"],
                "close_time": pos["open_time"] + timedelta(hours=CLOSE_HOURS),
                "ticket": pos["ticket"],
                "volume": pos["volume"],
            }
            print(f"  📌 Loaded existing {symbol} {pos['type']} position")
    
    # State tracking
    cumulative_pnl = {s: 0.0 for s in SYMBOLS}
    trade_history = {s: [] for s in SYMBOLS}
    closed_trades = []
    last_signal_time = {}
    start_time = datetime.utcnow()
    
    print(f"\n  🚀 Real-time RSI Strategy running...")
    print(f"  📊 Will close positions after {CLOSE_HOURS} hours\n")
    print("  " + "-" * 66)
    
    while True:
        try:
            now = datetime.utcnow()
            
            # Check each symbol
            for symbol in SYMBOLS:
                # ── CLOSE EXPIRED POSITIONS (after 4 REAL hours) ────────────
                if symbol in positions:
                    pos = positions[symbol]
                    
                    if now >= pos["close_time"]:
                        success, result = close_position(
                            symbol, pos["ticket"], pos["volume"], pos["type"]
                        )
                        
                        if success:
                            # Get REAL P&L from MT5
                            actual_pnl = get_position_pnl(pos["ticket"])
                            cumulative_pnl[symbol] += actual_pnl
                            
                            closed_trades.append({
                                "symbol": symbol,
                                "type": pos["type"],
                                "open_time": pos["open_time"].timestamp(),
                                "close_time": now.timestamp(),
                                "open_price": pos["open_price"],
                                "close_price": result.price if result else 0,
                                "pnl": actual_pnl,
                            })
                            
                            trade_history[symbol].append(
                                (now.timestamp(), round(cumulative_pnl[symbol], 4))
                            )
                            
                            print(f"\n  📊 CLOSE {symbol}: {pos['type']} | PnL = ${actual_pnl:+.2f} | Total: ${cumulative_pnl[symbol]:+.2f}")
                        
                        del positions[symbol]
                
                # ── CHECK FOR NEW RSI SIGNALS ──────────────────────────────
                if symbol not in positions:
                    # Rate limit: check every 60 seconds
                    last = last_signal_time.get(symbol, datetime.min)
                    if (now - last).total_seconds() < 60:
                        continue
                    
                    # Check spread
                    if not check_spread(symbol):
                        continue
                    
                    # Get RSI signal
                    signal, rsi_value = get_signal(symbol)
                    
                    if signal:
                        # Place order
                        result, ticket = place_order(symbol, signal, VOLUME, rsi_value)
                        
                        if result and ticket:
                            positions[symbol] = {
                                "type": signal,
                                "open_price": result.price,
                                "open_time": now,
                                "close_time": now + timedelta(hours=CLOSE_HOURS),
                                "ticket": ticket,
                                "volume": VOLUME,
                            }
                            
                            trade_history[symbol].append(
                                (now.timestamp(), round(cumulative_pnl[symbol], 4))
                            )
                            
                            last_signal_time[symbol] = now
                            print(f"\n  🚀 OPEN  {symbol}: {signal} at {result.price:.5f} | RSI: {rsi_value} | Ticket: {ticket}")
                            print(f"  ⏰ Will close at: {(now + timedelta(hours=CLOSE_HOURS)).strftime('%H:%M:%S')}")
            
            # ── UPDATE VISUALIZATION ───────────────────────────────────────
            live_profits = {}
            open_positions_viz = {}
            
            for symbol in SYMBOLS:
                if symbol in positions:
                    pos = positions[symbol]
                    current_pnl = get_position_pnl(pos["ticket"])
                    live_profits[symbol] = round(cumulative_pnl[symbol] + current_pnl, 4)
                    open_positions_viz[symbol] = {
                        "type": pos["type"],
                        "open_time": pos["open_time"].timestamp(),
                        "close_time": pos["close_time"].timestamp(),
                        "open_price": pos["open_price"],
                        "unrealized_pnl": round(current_pnl, 4),
                    }
                else:
                    live_profits[symbol] = round(cumulative_pnl[symbol], 4)
            
            save_data(now, live_profits, trade_history, closed_trades[-200:], open_positions_viz)
            
            # ── CONSOLE DISPLAY ────────────────────────────────────────────
            total_realized = sum(cumulative_pnl.values())
            total_unrealized = sum([get_position_pnl(p["ticket"]) for p in positions.values()])
            
            # Get current RSI for display
            sample_symbol = SYMBOLS[0]
            df_sample = get_rates(sample_symbol, 50)
            sample_rsi = "---"
            if df_sample is not None:
                rsi_val = calculate_rsi(df_sample["close"], RSI_PERIOD)
                sample_rsi = f"{rsi_val.iloc[-1]:.1f}"
            
            print(f"\r  [{now.strftime('%H:%M:%S')}]  Realized: ${total_realized:+7.2f}  |  Unrealized: ${total_unrealized:+7.2f}  |  Open: {len(positions):2}  |  Closed: {len(closed_trades):3}  |  RSI({sample_symbol}): {sample_rsi}", end="")
            
            # Wait 1 second before next check
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n\n  🛑 RSI Strategy stopping...")
            break
        except Exception as e:
            print(f"\n  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)
    
    # Close all remaining positions
    if positions:
        print("\n  Closing remaining positions...")
        for symbol, pos in positions.items():
            close_position(symbol, pos["ticket"], pos["volume"], pos["type"])
            time.sleep(0.5)
    
    mt5.shutdown()
    print("\n  ✅ MT5 disconnected")
    print("=" * 70)


if __name__ == "__main__":
    main()