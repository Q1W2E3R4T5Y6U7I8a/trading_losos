# main.py (updated for both with real orders)
import subprocess
import sys
import time

BASE = "M:/Projects/trading_losos"

def main():
    print("=" * 60)
    print("  TRADING SYSTEM // REAL ORDER EXECUTION")
    print("=" * 60)
    
    # MA Strategy (Magic: 123456)
    print("\n  Launching MA Crossover Strategy...")
    ma_strategy = subprocess.Popen(
        [sys.executable, "src/components/MA_strategy.py"],
        cwd=BASE
    )
    time.sleep(2)
    
    # RSI Strategy (Magic: 123457)
    print("  Launching RSI Mean Reversion Strategy...")
    rsi_strategy = subprocess.Popen(
        [sys.executable, "src/components/RSI_strategy.py"],
        cwd=BASE
    )
    time.sleep(2)
    
    # Viewer
    print("  Launching 3D Viewer...")
    viewer = subprocess.Popen(
        [sys.executable, "src/components/Viewer.py"],
        cwd=BASE
    )
    
    print("\n  ┌─────────────────────────────────────────────────────────┐")
    print("  │  STRATEGIES RUNNING WITH REAL ORDERS                    │")
    print(f"  │  MA Strategy  (Magic: 123456)  PID: {ma_strategy.pid:<25}│")
    print(f"  │  RSI Strategy (Magic: 123457)  PID: {rsi_strategy.pid:<25}│")
    print(f"  │  Viewer                         PID: {viewer.pid:<25}│")
    print("  ├─────────────────────────────────────────────────────────┤")
    print("  │  ⚠️  REAL MONEY TRADING - MONITOR CAREFULLY              │")
    print("  │  Viewer: http://localhost:8765                          │")
    print("  └─────────────────────────────────────────────────────────┘")
    print("\n  Press Ctrl+C to stop all.\n")
    
    try:
        ma_strategy.wait()
        rsi_strategy.wait()
        viewer.wait()
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        for proc in [ma_strategy, rsi_strategy, viewer]:
            proc.terminate()
        time.sleep(2)
        for proc in [ma_strategy, rsi_strategy, viewer]:
            if proc.poll() is None:
                proc.kill()
        print("  All processes stopped.")

if __name__ == "__main__":
    main()