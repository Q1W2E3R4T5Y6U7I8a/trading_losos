# close_trades.py - Close all strategy trades
import os
import sys
import time
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

LOGIN = int(os.getenv("LOGIN"))
PASSWORD = os.getenv("PASSWORD")
SERVER = os.getenv("SERVER")

def close_all_trades():
    """Close ALL positions that have a comment"""
    print("=" * 60)
    print("  CLOSING ALL STRATEGY TRADES")
    print("=" * 60)
    
    if not mt5.initialize():
        print("  ❌ Cannot connect to MT5")
        return
    
    if not mt5.login(LOGIN, password=PASSWORD, server=SERVER):
        print(f"  ❌ Login failed: {mt5.last_error()}")
        mt5.shutdown()
        return
    
    print("  ✅ Connected to MT5\n")
    
    try:
        positions = mt5.positions_get()
        
        if not positions:
            print("  ℹ️ No open positions found")
            return
        
        closed_count = 0
        for pos in positions:
            # Close ONLY positions with comments (strategy trades)
            if pos.comment and pos.comment.strip():
                symbol = pos.symbol
                ticket = pos.ticket
                volume = pos.volume
                
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    if pos.type == mt5.POSITION_TYPE_BUY:
                        price = tick.bid
                        order_type = mt5.ORDER_TYPE_SELL
                    else:
                        price = tick.ask
                        order_type = mt5.ORDER_TYPE_BUY
                    
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": symbol,
                        "volume": volume,
                        "type": order_type,
                        "position": ticket,
                        "price": price,
                        "slippage": 10,
                        "comment": "CLOSED_MANUALLY",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }
                    
                    result = mt5.order_send(request)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"  ✓ Closed {symbol} | PnL: ${pos.profit:+.2f}")
                        closed_count += 1
                    else:
                        print(f"  ✗ Failed to close {symbol}: {result.comment}")
                time.sleep(0.3)
        
        print(f"\n  ✅ Closed {closed_count} positions")
        
        # Cancel pending orders
        orders = mt5.orders_get()
        if orders:
            cancelled = 0
            for order in orders:
                if order.comment and order.comment.strip():
                    cancel_request = {"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket}
                    result = mt5.order_send(cancel_request)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"  ✓ Cancelled pending order {order.symbol}")
                        cancelled += 1
            if cancelled:
                print(f"  ✅ Cancelled {cancelled} pending orders")
                
    except Exception as e:
        print(f"  ❌ Error: {e}")
    finally:
        mt5.shutdown()
        print("\n  ✅ Done")

if __name__ == "__main__":
    close_all_trades()