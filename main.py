import subprocess
import sys
import time

BASE = "M:/Projects/trading_losos"

def main():
    print("  TRADING SYSTEM  //  starting...\n")

    strategy = subprocess.Popen(
        [sys.executable, "src/components/MA_strategy.py"],
        cwd=BASE
    )
    time.sleep(3)

    viewer = subprocess.Popen(
        [sys.executable, "src/components/Viewer.py"],
        cwd=BASE
    )

    print("  Strategy PID :", strategy.pid)
    print("  Viewer PID   :", viewer.pid)
    print("  Press Ctrl+C to stop both.\n")

    try:
        strategy.wait()
        viewer.wait()
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        strategy.terminate()
        viewer.terminate()
        strategy.wait()
        viewer.wait()
        print("  Done.")

if __name__ == "__main__":
    main()