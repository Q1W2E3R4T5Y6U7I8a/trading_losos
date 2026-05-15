# main.py (updated - ONLY closes positions with specific magic numbers)
import os
import subprocess
import sys
import time
import signal
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

BASE = "M:/Projects/trading_losos"

LOGIN    = int(os.getenv("LOGIN"))
PASSWORD = os.getenv("PASSWORD")
SERVER   = os.getenv("SERVER")

class StrategyManager:
    def __init__(self):
        self.ma_strategy = None
        self.rsi_strategy = None
        self.session_strategy = None 
        self.viewer = None
        
    def close_positions_by_magic(self, magic_number):
        """Close ONLY positions with specific magic number - leave everything else alone"""
        print(f"\n  Closing positions with Magic: {magic_number}...")
        
        # Connect to MT5 temporarily if not already connected
        mt5_connected = mt5.terminal_info() is not None
        if not mt5_connected:
            if not mt5.initialize():
                print(f"  ❌ Cannot connect to MT5 to close positions")
                return
            if not mt5.login(LOGIN, password=PASSWORD, server=SERVER):
                print(f"  ❌ Cannot login to MT5")
                mt5.shutdown()
                return
        
        try:
            # Get ALL positions from MT5
            all_positions = mt5.positions_get()
            
            if all_positions:
                closed_count = 0
                for pos in all_positions:
                    # ONLY close if magic number matches
                    if pos.magic == magic_number:
                        # Close this position
                        symbol = pos.symbol
                        ticket = pos.ticket
                        volume = pos.volume
                        
                        # Determine close price and order type
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
                                "magic": magic_number,
                                "comment": "STRATEGY_STOP",
                                "type_time": mt5.ORDER_TIME_GTC,
                                "type_filling": mt5.ORDER_FILLING_IOC,
                            }
                            
                            result = mt5.order_send(request)
                            if result.retcode == mt5.TRADE_RETCODE_DONE:
                                print(f"  ✓ Closed {symbol} (Magic: {magic_number}) PnL: ${pos.profit:+.2f}")
                                closed_count += 1
                            else:
                                print(f"  ✗ Failed to close {symbol}: {result.comment}")
                    
                    else:
                        # Position has different magic number - LEAVE IT ALONE
                        print(f"  ⏭️ Skipping {pos.symbol} (Magic: {pos.magic} - not our strategy)")
                
                print(f"  ✅ Closed {closed_count} positions for Magic: {magic_number}")
            else:
                print(f"  ℹ️ No open positions found for Magic: {magic_number}")
            
            # Also cancel pending orders with this magic number
            pending_orders = mt5.orders_get()
            if pending_orders:
                cancelled_count = 0
                for order in pending_orders:
                    if order.magic == magic_number:
                        request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket,
                        }
                        result = mt5.order_send(request)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            print(f"  ✓ Cancelled pending order {order.symbol} (Magic: {magic_number})")
                            cancelled_count += 1
                if cancelled_count > 0:
                    print(f"  ✅ Cancelled {cancelled_count} pending orders for Magic: {magic_number}")
                    
        except Exception as e:
            print(f"  ❌ Error closing positions: {e}")
        finally:
            if not mt5_connected:
                mt5.shutdown()
    
    def stop_strategy_by_magic(self, magic_number):
        """Stop a specific strategy process by its magic number and close its positions"""
        print(f"\n  Stopping strategy with Magic: {magic_number}...")
        
        # First, close ALL positions with this magic number
        self.close_positions_by_magic(magic_number)
        
        # Then terminate the process
        if magic_number == 123456 and self.ma_strategy and self.ma_strategy.poll() is None:
            self.ma_strategy.terminate()
            time.sleep(1)
            if self.ma_strategy.poll() is None:
                self.ma_strategy.kill()
            print(f"  ✓ MA Strategy process stopped")
            
        elif magic_number == 123458 and self.rsi_strategy and self.rsi_strategy.poll() is None:
            self.rsi_strategy.terminate()
            time.sleep(1)
            if self.rsi_strategy.poll() is None:
                self.rsi_strategy.kill()
            print(f"  ✓ RSI Strategy process stopped")
            
        elif magic_number == 123459 and self.session_strategy and self.session_strategy.poll() is None:
            self.session_strategy.terminate()
            time.sleep(1)
            if self.session_strategy.poll() is None:
                self.session_strategy.kill()
            print(f"  ✓ Session Strategy process stopped")
            
        else:
            print(f"  ✗ Strategy process not found or already stopped")
    
    def stop_all_strategies(self):
        """Stop all trading strategies (close their positions, cancel their orders, kill processes)"""
        print("\n" + "=" * 60)
        print("  STOPPING ALL TRADING STRATEGIES")
        print("  (Only closing positions with our magic numbers)")
        print("=" * 60)
        
        self.stop_strategy_by_magic(123456)  # MA Strategy
        self.stop_strategy_by_magic(123458)  # RSI Strategy  
        self.stop_strategy_by_magic(123459)  # Session Strategy
        
        print("\n  ✅ All strategies stopped. Viewer remains running.\n")
    
    def stop_everything(self):
        """Stop all processes including viewer (emergency shutdown)"""
        print("\n" + "=" * 60)
        print("  EMERGENCY SHUTDOWN - Closing everything")
        print("=" * 60)
        
        # Close all positions from our strategies
        self.close_positions_by_magic(123456)
        self.close_positions_by_magic(123458)
        self.close_positions_by_magic(123459)
        
        # Terminate all processes
        print("\n  Terminating processes...")
        for proc in [self.ma_strategy, self.rsi_strategy, self.session_strategy, self.viewer]:
            if proc and proc.poll() is None:
                proc.terminate()
        
        time.sleep(2)
        
        for proc in [self.ma_strategy, self.rsi_strategy, self.session_strategy, self.viewer]:
            if proc and proc.poll() is None:
                proc.kill()
        
        print("  ✅ All processes stopped")
        print("  ⚠️ Note: Other positions in MT5 (different magic numbers) were NOT touched")


def main():
    print("=" * 60)
    print("  TRADING SYSTEM // REAL ORDER EXECUTION")
    print("=" * 60)
    print("\n  ⚠️  IMPORTANT: This system ONLY manages positions with")
    print("     specific magic numbers. It will NEVER touch:")
    print("     • Manually opened trades")
    print("     • Trades from other EAs")
    print("     • Any position with a different magic number")
    print("=" * 60)
    
    manager = StrategyManager()
    
    # MA Strategy (Magic: 123456)
    print("\n  Launching MA Crossover Strategy...")
    manager.ma_strategy = subprocess.Popen(
        [sys.executable, "src/components/MA_strategy.py"],
        cwd=BASE
    )
    time.sleep(2)
    
    # RSI Strategy (Magic: 123458)
    print("  Launching RSI Mean Reversion Strategy...")
    manager.rsi_strategy = subprocess.Popen(
        [sys.executable, "src/components/RSI_strategy.py"],
        cwd=BASE
    )
    time.sleep(2)

    # Session Strategy (Magic: 123459)
    print("  Launching Session Strategy...")
    manager.session_strategy = subprocess.Popen(
        [sys.executable, "src/components/SESSION_strategy.py"],
        cwd=BASE
    )
    time.sleep(2)
    
    # Viewer
    print("  Launching 3D Viewer...")
    manager.viewer = subprocess.Popen(
        [sys.executable, "src/components/Viewer.py"],
        cwd=BASE
    )
    
    print("\n  ┌─────────────────────────────────────────────────────────────────┐")
    print("  │  STRATEGIES RUNNING WITH REAL ORDERS                            │")
    print(f"  │  MA Strategy     (Magic: 123456)  PID: {manager.ma_strategy.pid:<28}│")
    print(f"  │  RSI Strategy    (Magic: 123458)  PID: {manager.rsi_strategy.pid:<28}│")
    print(f"  │  Session Strategy(Magic: 123459)  PID: {manager.session_strategy.pid:<28}│")
    print(f"  │  Viewer                            PID: {manager.viewer.pid:<28}│")
    print("  ├─────────────────────────────────────────────────────────────────┤")
    print("  │  ⚠️  REAL MONEY TRADING - MONITOR CAREFULLY                      │")
    print("  │  Viewer: http://localhost:8765                                  │")
    print("  │                                                                 │")
    print("  │  🔒 SAFETY: Will ONLY manage positions with magic numbers:      │")
    print("  │     123456 (MA), 123458 (RSI), 123459 (Session)                 │")
    print("  │     Manual trades and other EAs are SAFE                        │")
    print("  └─────────────────────────────────────────────────────────────────┘")
    print("\n  Sessions (Session Strategy):")
    print("    ASIA    (00:00-09:00 UTC) - Trade FIRST HOUR on JPY pairs")
    print("    EUROPE  (08:00-17:00 UTC) - Trade FIRST HOUR on GBP/EUR pairs")
    print("    US      (13:00-22:00 UTC) - Trade FIRST HOUR on USD pairs")
    print("\n  Commands:")
    print("    Ctrl+C     - Stop all strategies (close their positions, keep viewer)")
    print("    Ctrl+\\     - Emergency stop (close everything, exit)")
    print("\n  Waiting for commands...\n")
    
    # Custom signal handlers
    def signal_handler(sig, frame):
        if sig == signal.SIGINT:  # Ctrl+C
            manager.stop_all_strategies()
            print("\n  ✅ Trading strategies stopped. Viewer still running at http://localhost:8765")
            print("  Press Ctrl+C again to stop viewer, or close the browser window")
            # Keep the script running for viewer
            signal.signal(signal.SIGINT, lambda s, f: exit_handler(s, f))
            signal.signal(signal.SIGQUIT, exit_handler)
        elif sig == signal.SIGQUIT:  # Ctrl+\
            manager.stop_everything()
            sys.exit(0)
    
    def exit_handler(sig, frame):
        print("\n  Stopping viewer...")
        if manager.viewer and manager.viewer.poll() is None:
            manager.viewer.terminate()
            time.sleep(1)
            if manager.viewer.poll() is None:
                manager.viewer.kill()
        sys.exit(0)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGQUIT, exit_handler)
    
    try:
        # Wait for viewer to finish (or until interrupted)
        if manager.viewer:
            manager.viewer.wait()
    except KeyboardInterrupt:
        pass
    finally:
        # Only clean up if viewer is already closed
        if manager.viewer and manager.viewer.poll() is not None:
            manager.stop_everything()

if __name__ == "__main__":
    main()