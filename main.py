# main.py - Manages trading strategies
import os
import subprocess
import sys
import time
import signal
from dotenv import load_dotenv

load_dotenv()

BASE = "M:/Projects/trading_losos"

class StrategyManager:
    def __init__(self):
        self.ma_strategy = None
        self.rsi_strategy = None
        self.session_strategy = None 
        self.viewer = None
        
    def stop_all_strategies(self):
        """Stop all strategy processes (leaves trades open)"""
        print("\n" + "=" * 60)
        print("  STOPPING ALL STRATEGIES")
        print("=" * 60)
        
        print("\n  Stopping processes...")
        for proc in [self.ma_strategy, self.rsi_strategy, self.session_strategy]:
            if proc and proc.poll() is None:
                proc.terminate()
        
        time.sleep(1)
        
        for proc in [self.ma_strategy, self.rsi_strategy, self.session_strategy]:
            if proc and proc.poll() is None:
                proc.kill()
        
        print("\n  ✅ All strategies stopped. Trades remain OPEN.\n")
    
    def stop_everything(self):
        """Stop all processes including viewer"""
        print("\n" + "=" * 60)
        print("  STOPPING EVERYTHING")
        print("=" * 60)
        
        print("\n  Terminating all processes...")
        for proc in [self.ma_strategy, self.rsi_strategy, self.session_strategy, self.viewer]:
            if proc and proc.poll() is None:
                proc.terminate()
        
        time.sleep(2)
        
        for proc in [self.ma_strategy, self.rsi_strategy, self.session_strategy, self.viewer]:
            if proc and proc.poll() is None:
                proc.kill()
        
        print("  ✅ All processes stopped")


def main():
    print("=" * 60)
    print("  TRADING SYSTEM - REAL ORDERS")
    print("=" * 60)
    print("\n  ⚠️  Trades remain OPEN when stopped")
    print("  Manual trades (no comment) are SAFE")
    print("=" * 60)
    
    manager = StrategyManager()
    
    print("\n  Launching MA Strategy...")
    manager.ma_strategy = subprocess.Popen([sys.executable, "src/components/MA_strategy.py"], cwd=BASE)
    time.sleep(2)
    
    print("  Launching RSI Strategy...")
    manager.rsi_strategy = subprocess.Popen([sys.executable, "src/components/RSI_strategy.py"], cwd=BASE)
    time.sleep(2)

    print("  Launching Session Strategy...")
    manager.session_strategy = subprocess.Popen([sys.executable, "src/components/SESSION_strategy.py"], cwd=BASE)
    time.sleep(2)
    
    print("  Launching 3D Viewer...")
    manager.viewer = subprocess.Popen([sys.executable, "src/components/Viewer.py"], cwd=BASE)
    
    print("\n  ┌─────────────────────────────────────────────────────────────────┐")
    print("  │  STRATEGIES RUNNING                                             │")
    print(f"  │  MA Strategy      PID: {manager.ma_strategy.pid:<37}│")
    print(f"  │  RSI Strategy     PID: {manager.rsi_strategy.pid:<37}│")
    print(f"  │  Session Strategy PID: {manager.session_strategy.pid:<37}│")
    print(f"  │  Viewer           PID: {manager.viewer.pid:<37}│")
    print("  ├─────────────────────────────────────────────────────────────────┤")
    print("  │  Viewer: http://localhost:8765                                  │")
    print("  └─────────────────────────────────────────────────────────────────┘")
    print("\n  Commands:")
    print("    Ctrl+C - Stop all processes and exit")
    print("\n  Waiting for commands...\n")
    
    def signal_handler(sig, frame):
        print("\n" + "=" * 60)
        print("  SHUTTING DOWN")
        print("=" * 60)
        
        print("\n  Stopping all processes...")
        for proc in [manager.ma_strategy, manager.rsi_strategy, manager.session_strategy, manager.viewer]:
            if proc and proc.poll() is None:
                proc.terminate()
        
        time.sleep(1)
        
        for proc in [manager.ma_strategy, manager.rsi_strategy, manager.session_strategy, manager.viewer]:
            if proc and proc.poll() is None:
                proc.kill()
        
        print("\n  ✅ All processes stopped. Trades remain OPEN.")
        print("\n  ✅ Done. Exiting...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        while True:
            time.sleep(1)
            if manager.viewer and manager.viewer.poll() is not None:
                print("\n  ⚠️ Viewer stopped unexpectedly")
                break
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()