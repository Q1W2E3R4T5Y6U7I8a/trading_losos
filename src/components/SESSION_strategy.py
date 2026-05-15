# M:/Projects/trading_losos/src/components/SESSION_strategy.py

import os
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import MetaTrader5 as mt5

load_dotenv()

LOGIN    = int(os.getenv("LOGIN"))
PASSWORD = os.getenv("PASSWORD")
SERVER   = os.getenv("SERVER")

# ============================================================
# CORRECT SESSION CONFIGURATION
# ============================================================
SESSION_TIMES = {
    "ASIA": {
        "open": 0,      # 00:00 UTC (Tokyo open)
        "close": 9,     # 09:00 UTC (London open)
        "currency": "JPY",
        "symbols": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY"],
        "direction": "LONG",
        "description": "🇯🇵 Asia (00:00-09:00 UTC) - JPY pairs",
    },
    "EUROPE": {
        "open": 8,      # 08:00 UTC (London open)
        "close": 17,    # 17:00 UTC (US close)
        "currency": "GBP",  # Primary for first hour, but will trade both
        "symbols": ["GBPUSD", "EURGBP", "GBPJPY", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
                    "EURUSD", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD"],
        "direction": "LONG",
        "description": "🇪🇺 Europe (08:00-17:00 UTC) - GBP/EUR pairs",
    },
    "US": {
        "open": 13,     # 13:00 UTC (NY open)
        "close": 22,    # 22:00 UTC (NY close)
        "currency": "USD",
        "symbols": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"],
        "direction": "LONG",
        "description": "🇺🇸 US (13:00-22:00 UTC) - USD pairs",
    }
}

# We'll trade ONLY during the FIRST HOUR of each session (as you originally wanted)
# This catches the "session opening volatility"
TRADE_ONLY_FIRST_HOUR = True  # Set to False to trade entire session

# Trading parameters
VOLUME = 0.01
TIMEFRAME = mt5.TIMEFRAME_M5

# Fibonacci levels for limit orders
FIB_LEVELS = [0.382, 0.5, 0.618, 0.786]
ENTRY_RETRACEMENT = 0.382  # Enter at 38.2% retracement from session high

# Take profit levels (% of expected move)
TP_LEVELS = [0.382, 0.618, 1.0]

# Stop loss - ATR multiplier
ATR_MULTIPLIER_SL = 1.5

# Close positions 30 minutes after TRADING WINDOW ends
CLOSE_BUFFER_MINUTES = 30

DATA_DIR = "M:/Projects/trading_losos/data"
DATA_FILE = f"{DATA_DIR}/session_data.json"

# Safety settings
MAX_SPREAD = 50
SLIPPAGE = 10
MAGIC_NUMBER = 123459


def get_rates(symbol: str, count: int = 100) -> Optional[pd.DataFrame]:
    """Get latest rates from MT5"""
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, count)
    if rates is None or len(rates) == 0:
        return None
    return pd.DataFrame(rates)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate ATR for stop loss"""
    if df is None or len(df) < period + 1:
        return 0.002
    
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    return atr.iloc[-1]


def get_session_high_low(symbol: str, session_start: datetime, session_end: datetime) -> Tuple[float, float, float]:
    """
    Get high/low for the current session so far
    Returns: (session_high, session_low, current_price)
    """
    rates = mt5.copy_rates_range(symbol, TIMEFRAME, session_start, datetime.utcnow())
    
    if rates is None or len(rates) < 5:
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            current = tick.ask
            return current + 0.005, current - 0.005, current
        return 1.1000, 1.0900, 1.0950
    
    df = pd.DataFrame(rates)
    return df["high"].max(), df["low"].min(), df["close"].iloc[-1]


def calculate_limit_price(symbol: str, session_info: Dict, current_price: float, 
                          session_high: float, session_low: float) -> Optional[Dict]:
    """
    Calculate limit order price using Fibonacci retracement from session high
    For LONG positions: Buy at retracement from high
    """
    expected_move = session_high - session_low
    
    if expected_move <= 0:
        expected_move = 0.005  # Fallback 50 pips
    
    # Calculate limit price (buy at retracement from high)
    retracement_amount = expected_move * ENTRY_RETRACEMENT
    limit_price = session_high - retracement_amount
    
    # Ensure limit price is reasonable (not too far from current price)
    if abs(limit_price - current_price) > expected_move * 2:
        limit_price = current_price - (expected_move * 0.25)
    
    # Calculate stop loss (below session low or ATR-based)
    full_df = get_rates(symbol, 50)
    atr = calculate_atr(full_df) if full_df is not None else 0.002
    stop_loss = session_low - (atr * 0.5)
    
    # Alternative stop: recent swing low
    if stop_loss > limit_price - atr:
        stop_loss = limit_price - (atr * ATR_MULTIPLIER_SL)
    
    # Take profits
    tp1 = limit_price + (expected_move * 0.382)
    tp2 = limit_price + (expected_move * 0.618)
    tp3 = limit_price + expected_move
    
    return {
        "limit_price": round(limit_price, 5),
        "stop_loss": round(stop_loss, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "atr": round(atr, 5),
        "expected_move": round(expected_move, 5),
    }


def place_limit_order(symbol: str, session_name: str, prices: Dict) -> Tuple[Optional[any], Optional[int]]:
    """Place a BUY LIMIT order"""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None or symbol_info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        return None, None
    
    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": VOLUME,
        "type": mt5.ORDER_TYPE_BUY_LIMIT,
        "price": prices["limit_price"],
        "sl": prices["stop_loss"],
        "tp": prices["tp1"],
        "slippage": SLIPPAGE,
        "magic": MAGIC_NUMBER,
        "comment": f"{session_name}_FIB_{prices['limit_price']}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    print(f"  📝 {symbol}: BUY LIMIT at {prices['limit_price']:.5f} (SL: {prices['stop_loss']:.5f}, TP: {prices['tp1']:.5f})")
    result = mt5.order_send(request)
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"  ❌ {symbol}: Limit order failed - {result.comment}")
        return None, None
    
    print(f"  ✅ {symbol}: LIMIT order placed! Ticket: {result.order}")
    return result, result.order


def cancel_pending_order(ticket: int) -> bool:
    """Cancel a pending limit order"""
    request = {
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": ticket,
    }
    result = mt5.order_send(request)
    return result.retcode == mt5.TRADE_RETCODE_DONE


def get_pending_orders() -> Dict:
    """Get all pending limit orders for this strategy"""
    orders = mt5.orders_get(magic=MAGIC_NUMBER)
    if orders is None:
        return {}
    
    pending = {}
    for order in orders:
        pending[order.symbol] = {
            "ticket": order.ticket,
            "price": order.price_open,
            "sl": order.sl,
            "tp": order.tp,
        }
    return pending


def get_positions() -> Dict:
    """Get active positions from MT5"""
    positions = mt5.positions_get(magic=MAGIC_NUMBER)
    if positions is None:
        return {}
    
    active = {}
    for pos in positions:
        active[pos.symbol] = {
            "ticket": pos.ticket,
            "type": "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL",
            "volume": pos.volume,
            "open_price": pos.price_open,
            "open_time": datetime.fromtimestamp(pos.time),
            "current_pnl": pos.profit,
        }
    return active


def close_position(symbol: str, ticket: int, volume: float) -> bool:
    """Close an existing position"""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_SELL,  # Closing LONG position
        "position": ticket,
        "price": tick.bid,
        "slippage": SLIPPAGE,
        "magic": MAGIC_NUMBER,
        "comment": "SESSION_CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"  ❌ {symbol}: Close failed - {result.comment}")
        return False
    
    print(f"  ✅ {symbol}: Position closed")
    return True


def get_position_pnl(ticket: int) -> float:
    """Get actual P&L from MT5"""
    positions = mt5.positions_get(ticket=ticket)
    if positions and len(positions) > 0:
        return positions[0].profit
    
    deals = mt5.history_deals_get(position=ticket)
    if deals and len(deals) > 0:
        return sum(deal.profit + deal.swap + deal.commission for deal in deals)
    
    return 0.0


def get_active_session() -> Optional[Tuple[str, Dict]]:
    """Determine which session is currently active"""
    now = datetime.utcnow()
    current_hour = now.hour + now.minute / 60.0  # Float hour
    
    for session_name, session in SESSION_TIMES.items():
        if session["open"] <= current_hour < session["close"]:
            return session_name, session
    
    return None, None


def get_trading_window(session_name: str, session_info: Dict) -> Tuple[datetime, datetime]:
    """
    Get the trading window start/end times.
    If TRADE_ONLY_FIRST_HOUR is True, only trade the first hour of session.
    """
    now = datetime.utcnow()
    session_start = now.replace(hour=session_info["open"], minute=0, second=0, microsecond=0)
    
    if TRADE_ONLY_FIRST_HOUR:
        # Only trade the first hour of the session
        trading_end = session_start + timedelta(hours=1)
    else:
        # Trade entire session
        trading_end = now.replace(hour=session_info["close"], minute=0, second=0, microsecond=0)
    
    return session_start, trading_end


def save_data(timestamp: datetime, closed_trades: List, positions: Dict, pending: Dict, 
              session_info: Optional[Tuple[str, Dict]], trading_window: Tuple[datetime, datetime]):
    """Save data for visualization"""
    payload = {
        "timestamp": timestamp.timestamp(),
        "closed_trades": closed_trades[-100:],
        "open_positions": {s: {"type": p["type"], "open_price": p["open_price"], 
                               "open_time": p["open_time"].timestamp(), "pnl": p["current_pnl"]} 
                          for s, p in positions.items()},
        "pending_orders": pending,
        "active_session": session_info[0] if session_info else None,
        "trading_window_start": trading_window[0].timestamp() if trading_window else None,
        "trading_window_end": trading_window[1].timestamp() if trading_window else None,
        "trade_only_first_hour": TRADE_ONLY_FIRST_HOUR,
    }
    
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, DATA_FILE)


def main():
    print("=" * 70)
    print("  SESSION STRATEGY // CORRECT SESSION TIMES")
    print(f"  Trading only FIRST HOUR of each session: {TRADE_ONLY_FIRST_HOUR}")
    print("  Strategy: ALWAYS LONG on session-specific currencies")
    print("  Entry: LIMIT orders at 38.2% Fibonacci retracement")
    print(f"  Close: {CLOSE_BUFFER_MINUTES} minutes after trading window ends")
    print("=" * 70)
    
    print("\n  📅 SESSION SCHEDULE (UTC):")
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  ASIA    00:00 ─────── 09:00  (trade 00:00-01:00)│")
    print("  │  EUROPE  08:00 ─────── 17:00  (trade 08:00-09:00)│")
    print("  │  US      13:00 ─────── 22:00  (trade 13:00-14:00)│")
    print("  └─────────────────────────────────────────────────┘")
    
    # Initialize MT5
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
    active_positions = get_positions()
    pending_orders = get_pending_orders()
    
    print(f"\n  Loaded: {len(active_positions)} positions, {len(pending_orders)} pending orders\n")
    
    # State tracking
    closed_trades = []
    current_session = None
    trading_window_start = None
    trading_window_end = None
    orders_placed = False
    
    print("  🚀 Session Strategy running...")
    print("  ⏰ Waiting for next trading session...\n")
    
    while True:
        try:
            now = datetime.utcnow()
            session_name, session_info = get_active_session()
            
            # ── CLOSE POSITIONS AFTER TRADING WINDOW ──────────────────────
            if trading_window_end and now >= trading_window_end + timedelta(minutes=CLOSE_BUFFER_MINUTES):
                print(f"\n  📊 Closing all positions from {current_session} session...")
                
                for symbol, pos in list(active_positions.items()):
                    success = close_position(symbol, pos["ticket"], pos["volume"])
                    if success:
                        pnl = get_position_pnl(pos["ticket"])
                        closed_trades.append({
                            "symbol": symbol,
                            "type": pos["type"],
                            "open_time": pos["open_time"].timestamp(),
                            "close_time": now.timestamp(),
                            "pnl": pnl,
                            "session": current_session,
                        })
                        print(f"    {symbol}: PnL = ${pnl:+.2f}")
                        del active_positions[symbol]
                
                # Cancel any pending orders
                for symbol, order in list(pending_orders.items()):
                    cancel_pending_order(order["ticket"])
                    del pending_orders[symbol]
                
                current_session = None
                trading_window_start = None
                trading_window_end = None
                orders_placed = False
                print(f"  ✅ Cleanup complete\n")
            
            # ── NEW SESSION / TRADING WINDOW ──────────────────────────────
            if session_name and session_name != current_session:
                # Check if we're within the first hour of this session
                session_start, trading_end = get_trading_window(session_name, session_info)
                
                if session_start <= now < trading_end:
                    print(f"\n  🚀 {session_info['description']}")
                    print(f"  📈 Trading window: {session_start.strftime('%H:%M')} - {trading_end.strftime('%H:%M')} UTC")
                    print(f"  🎯 Direction: LONG on {session_info['currency']} pairs")
                    
                    current_session = session_name
                    trading_window_start = session_start
                    trading_window_end = trading_end
                    orders_placed = False
            
            # ── PLACE LIMIT ORDERS DURING TRADING WINDOW ──────────────────
            if (current_session and trading_window_start and trading_window_end and 
                trading_window_start <= now < trading_window_end and not orders_placed):
                
                session_info = SESSION_TIMES[current_session]
                orders_placed = True
                orders_count = 0
                
                for symbol in session_info["symbols"]:
                    # Skip if already have position or pending order
                    if symbol in active_positions or symbol in pending_orders:
                        continue
                    
                    # Check spread
                    symbol_info = mt5.symbol_info(symbol)
                    if symbol_info and symbol_info.spread > MAX_SPREAD:
                        print(f"  ⚠️ {symbol}: Spread too high ({symbol_info.spread})")
                        continue
                    
                    # Get session high/low so far
                    session_high, session_low, current_price = get_session_high_low(
                        symbol, trading_window_start, trading_window_end
                    )
                    
                    # Calculate limit price
                    price_data = calculate_limit_price(
                        symbol, session_info, current_price, session_high, session_low
                    )
                    
                    if price_data:
                        result, ticket = place_limit_order(symbol, current_session, price_data)
                        if result and ticket:
                            pending_orders[symbol] = {"ticket": ticket, **price_data}
                            orders_count += 1
                    else:
                        print(f"  ❌ {symbol}: Could not calculate price levels")
                
                print(f"\n  ✅ Placed {orders_count} limit orders for {current_session} session")
            
            # ── UPDATE POSITIONS (check for filled orders) ─────────────────
            new_positions = get_positions()
            for symbol, pos in new_positions.items():
                if symbol not in active_positions:
                    active_positions[symbol] = pos
                    if symbol in pending_orders:
                        print(f"\n  🎯 ORDER FILLED! {symbol} at {pos['open_price']:.5f}")
                        del pending_orders[symbol]
            
            # Update pending orders
            pending_orders = get_pending_orders()
            
            # ── SAVE DATA ─────────────────────────────────────────────────
            save_data(now, closed_trades, active_positions, pending_orders, 
                     (current_session, session_info) if current_session else None,
                     (trading_window_start, trading_window_end) if trading_window_start else None)
            
            # ── CONSOLE DISPLAY ──────────────────────────────────────────
            total_positions = len(active_positions)
            total_pending = len(pending_orders)
            unrealized_pnl = sum(p["current_pnl"] for p in active_positions.values())
            
            status = "WAITING"
            if current_session and trading_window_end:
                if now < trading_window_end:
                    time_left = trading_window_end - now
                    status = f"TRADING {current_session} ({int(time_left.total_seconds() / 60)}m left)"
                else:
                    status = f"CLOSING {current_session}"
            
            print(f"\r  [{now.strftime('%H:%M:%S')}] {status:<35} | Positions: {total_positions:2} | Pending: {total_pending:2} | PnL: ${unrealized_pnl:+7.2f}", end="")
            
            time.sleep(2)
            
        except KeyboardInterrupt:
            print("\n\n  🛑 Session Strategy stopping...")
            break
        except Exception as e:
            print(f"\n  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)
    
    # Cleanup
    if pending_orders:
        print("\n  Cancelling all pending orders...")
        for symbol, order in pending_orders.items():
            cancel_pending_order(order["ticket"])
            time.sleep(0.3)
    
    if active_positions:
        print("\n  Closing all positions...")
        for symbol, pos in active_positions.items():
            close_position(symbol, pos["ticket"], pos["volume"])
            time.sleep(0.5)
    
    mt5.shutdown()
    print("\n  ✅ Session Strategy stopped")


if __name__ == "__main__":
    main()