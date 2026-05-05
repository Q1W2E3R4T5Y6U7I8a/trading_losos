#0. Imports
import os
import time
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv
import MetaTrader5 as mt5

load_dotenv()

#1. Credentials
LOGIN = int(os.getenv("LOGIN"))
PASSWORD = os.getenv("PASSWORD")
SERVER = os.getenv("SERVER")

#1.1 Hardcoded symbols to trade
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
           "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
           "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
           "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
           "CADJPY", "CADCHF", "CHFJPY", "NZDJPY", "NZDCAD"]

#1.2 Trading parameters
FAST_MA = 10
SLOW_MA = 30
VOLUME = 0.01
CLOSE_HOURS = 4
TIMEFRAME = mt5.TIMEFRAME_M5

#2 Saving data
os.makedirs("./data", exist_ok=True)
CSV_FILE = "./data/MA_strategy.csv"

if not os.path.exists(CSV_FILE):
    pd.DataFrame(columns=["open_date", "close_date", "symbol", "type", "open_price", "close_price", "result_pnl"]).to_csv(CSV_FILE, index=False)

def log_trade(open_date, close_date, symbol, trade_type, open_price, close_price, pnl):
    """Log trade to CSV"""
    df = pd.read_csv(CSV_FILE)
    new_row = pd.DataFrame([{
        "open_date": open_date,
        "close_date": close_date,
        "symbol": symbol,
        "type": trade_type,
        "open_price": open_price,
        "close_price": close_price,
        "result_pnl": pnl
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(CSV_FILE, index=False)

def get_ma_crossover(symbol):
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, 100)
    if rates is None:
        return None
    df = pd.DataFrame(rates)
    fast_ma = df['close'].rolling(FAST_MA).mean()
    slow_ma = df['close'].rolling(SLOW_MA).mean()
    
    if len(df) < 2:
        return None
    
    if fast_ma.iloc[-2] <= slow_ma.iloc[-2] and fast_ma.iloc[-1] > slow_ma.iloc[-1]:
        return "BUY"
    elif fast_ma.iloc[-2] >= slow_ma.iloc[-2] and fast_ma.iloc[-1] < slow_ma.iloc[-1]:
        return "SELL"
    return None

#3. Executing trades

def place_order(symbol, order_type):
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return False
    
    price = tick.ask if order_type == "BUY" else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": VOLUME,
        "type": mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "deviation": 20,
        "magic": 123456,
        "comment": f"MA_{FAST_MA}_{SLOW_MA}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ {symbol} {order_type} at {price:.5f}")
        return result.order
    return False

def close_position(ticket, symbol, order_type, open_price, open_time):
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return
    
    if order_type == "BUY":
        price = tick.bid
        close_type = mt5.ORDER_TYPE_SELL
    else:
        price = tick.ask
        close_type = mt5.ORDER_TYPE_BUY
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": VOLUME,
        "type": close_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": 123456,
        "comment": "close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        if order_type == "BUY":
            pnl = (price - open_price) * VOLUME * 100000
        else:
            pnl = (open_price - price) * VOLUME * 100000
        
        close_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        open_date_str = open_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Log to CSV
        log_trade(open_date_str, close_date, symbol, order_type, open_price, price, pnl)
        
        print(f"🔒 {symbol} closed | P&L: ${pnl:.2f} | Held: {(datetime.now() - open_time).total_seconds()/3600:.1f}h")

def main():
    if not mt5.initialize():
        print("MT5 init failed")
        return
    if not mt5.login(LOGIN, password=PASSWORD, server=SERVER):
        print("Login failed")
        mt5.shutdown()
        return
    
    print(f"Trading {len(SYMBOLS)} symbols | MA{FAST_MA}/{SLOW_MA} | Close after {CLOSE_HOURS}h")
    print(f"Logging to: {CSV_FILE}\n")
    
    positions = {}
    last_candle = {}
    
    while True:
        try:
            now = datetime.now()
            
            for symbol in SYMBOLS:
                if symbol in positions:
                    if now >= positions[symbol]['close_time']:
                        close_position(positions[symbol]['ticket'], symbol, 
                                     positions[symbol]['type'], 
                                     positions[symbol]['open_price'],
                                     positions[symbol]['open_time'])
                        del positions[symbol]
                    continue
                
                signal = get_ma_crossover(symbol)
                if signal:
                    candle_time = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, 1)[0]['time']
                    if last_candle.get(symbol) == candle_time:
                        continue
                    
                    print(f"\n🎯 {symbol} - {signal} signal")
                    ticket = place_order(symbol, signal)
                    if ticket:
                        positions[symbol] = {
                            'ticket': ticket,
                            'type': signal,
                            'open_price': mt5.symbol_info_tick(symbol).ask if signal == "BUY" else mt5.symbol_info_tick(symbol).bid,
                            'open_time': now,
                            'close_time': now + timedelta(hours=CLOSE_HOURS)
                        }
                        last_candle[symbol] = candle_time
            
            if positions:
                print(f"\rActive: {len(positions)} symbols | {now.strftime('%H:%M:%S')}", end="")
            
            time.sleep(5)
            
        except KeyboardInterrupt:
            print("\n\nStopping...")
            break
    
    mt5.shutdown()

if __name__ == "__main__":
    main()