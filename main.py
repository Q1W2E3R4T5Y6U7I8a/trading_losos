import subprocess
import sys
import time

BASE = "M:/Projects/trading_losos"

def main():
    print("  TRADING SYSTEM  //  starting...\n")
    print("  Launching MA Crossover Strategy...")
    ma_strategy = subprocess.Popen(
        [sys.executable, "src/components/MA_strategy.py"],
        cwd=BASE
    )
    time.sleep(2)
    
    print("  Launching RSI Strategy (Buy <15, Sell >85)...")
    rsi_strategy = subprocess.Popen(
        [sys.executable, "src/components/RSI_strategy.py"],
        cwd=BASE
    )
    time.sleep(2)

    print("  Launching 3D Viewer...")
    viewer = subprocess.Popen(
        [sys.executable, "src/components/Viewer.py"],
        cwd=BASE
    )

    print("\n  ┌─────────────────────────────────────────────────────┐")
    print("  │  STRATEGIES RUNNING                                 │")
    print(f"  │  MA Strategy  PID: {ma_strategy.pid:<37}│")
    print(f"  │  RSI Strategy PID: {rsi_strategy.pid:<37}│")
    print(f"  │  Viewer       PID: {viewer.pid:<37}│")
    print("  ├─────────────────────────────────────────────────────┤")
    print("  │  MA:  10/30 crossover on M5                         │")
    print("  │  RSI: Buy <15, Sell >85, period 14 on M5            │")
    print("  │  Viewer: http://localhost:8765                      │")
    print("  └─────────────────────────────────────────────────────┘")
    print("\n  Press Ctrl+C to stop all.\n")

    try:
        ma_strategy.wait()
        rsi_strategy.wait()
        viewer.wait()
    except KeyboardInterrupt:
        print("\n  Shutting down all processes...")
        ma_strategy.terminate()
        rsi_strategy.terminate()
        viewer.terminate()
        
        # Wait for graceful shutdown
        time.sleep(1)
        
        # Force kill if still running
        if ma_strategy.poll() is None:
            ma_strategy.kill()
        if rsi_strategy.poll() is None:
            rsi_strategy.kill()
        if viewer.poll() is None:
            viewer.kill()
            
        ma_strategy.wait()
        rsi_strategy.wait()
        viewer.wait()
        print("  All processes stopped.")

if __name__ == "__main__":
    main()