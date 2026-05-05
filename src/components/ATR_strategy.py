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
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.4
LOOKBACK_BARS = 20   
VOLUME = 0.01
CLOSE_HOURS = 1.2
TIMEFRAME = mt5.TIMEFRAME_M5 

#2 Saving data
os.makedirs("./data", exist_ok=True)
CSV_FILE = "./data/ATR_strategy.csv"

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

def calculate_atr(symbol):
    """Calculate ATR for given symbol"""
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, ATR_PERIOD + 1)
    if rates is None or len(rates) < ATR_PERIOD + 1:
        return None
    
    df = pd.DataFrame(rates)
    
    # Calculate True Range
    high = df['high']
    low = df['low']
    close = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Calculate ATR (simple moving average of True Range)
    atr = true_range.rolling(window=ATR_PERIOD).mean()
    
    return atr.iloc[-1]

def get_breakout_levels(symbol):
    """Get highest high and lowest low over lookback period"""
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, LOOKBACK_BARS + 1)
    if rates is None or len(rates) < LOOKBACK_BARS:
        return None, None
    
    df = pd.DataFrame(rates)
    highest_high = df['high'].max()
    lowest_low = df['low'].min()
    
    return highest_high, lowest_low

def get_atr_signal(symbol):
    """Get trading signal based on ATR breakout"""
    # Get current price
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return None
    
    current_price = tick.ask  # Use ask for BUY decisions
    
    # Calculate ATR
    atr = calculate_atr(symbol)
    if atr is None:
        return None
    
    # Get breakout levels
    highest_high, lowest_low = get_breakout_levels(symbol)
    if highest_high is None or lowest_low is None:
        return None
    
    # Calculate breakout thresholds
    buy_breakout = highest_high + (atr * ATR_MULTIPLIER)
    sell_breakout = lowest_low - (atr * ATR_MULTIPLIER)
    
    # Generate signal
    if current_price > buy_breakout:
        return "BUY"
    elif current_price < sell_breakout:
        return "SELL"
    return None

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
        "magic": 123458,  # Different magic number to distinguish
        "comment": f"ATR_{ATR_PERIOD}_{ATR_MULTIPLIER}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ {symbol} {order_type} at {price:.5f} (ATR breakout)")
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
        "magic": 123458,
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
    
    print(f"Trading {len(SYMBOLS)} symbols | ATR({ATR_PERIOD}) x{ATR_MULTIPLIER}")
    print(f"Breakout: BUY > {LOOKBACK_BARS}-bar high + ATR*{ATR_MULTIPLIER}")
    print(f"Breakout: SELL < {LOOKBACK_BARS}-bar low - ATR*{ATR_MULTIPLIER}")
    print(f"Close after {CLOSE_HOURS}h | Timeframe: {TIMEFRAME}")
    print(f"Logging to: {CSV_FILE}\n")
    
    positions = {}
    last_candle = {}
    last_check = {}
    
    while True:
        try:
            now = datetime.now()
            
            for symbol in SYMBOLS:
                # Check if position exists and needs closing
                if symbol in positions:
                    if now >= positions[symbol]['close_time']:
                        close_position(positions[symbol]['ticket'], symbol, 
                                     positions[symbol]['type'], 
                                     positions[symbol]['open_price'],
                                     positions[symbol]['open_time'])
                        del positions[symbol]
                    continue
                
                # Only check every 10 seconds (not every 5)
                last = last_check.get(symbol)
                if last and (now - last).total_seconds() < 10:
                    continue
                
                # Get signal
                signal = get_atr_signal(symbol)
                
                if signal:
                    # Get current candle time to avoid duplicate signals on same candle
                    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, 1)
                    if rates is not None and len(rates) > 0:
                        candle_time = rates[0]['time']
                        if last_candle.get(symbol) == candle_time:
                            last_check[symbol] = now
                            continue
                    
                    print(f"\n🚀 {symbol} - {signal} signal (ATR breakout)")
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
                    
                    last_check[symbol] = now
            
            if positions:
                print(f"\rActive: {len(positions)} symbols | {now.strftime('%H:%M:%S')}", end="")
            
            time.sleep(5)
            
        except KeyboardInterrupt:
            print("\n\nStopping...")
            break
    
    mt5.shutdown()

if __name__ == "__main__":
    main()