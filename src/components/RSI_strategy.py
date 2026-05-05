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
RSI_PERIOD = 14
RSI_OVERSOLD = 15      # Buy when RSI < 15
RSI_OVERBOUGHT = 85    # Sell when RSI > 85
VOLUME = 0.01
CLOSE_HOURS = 24
TIMEFRAME = mt5.TIMEFRAME_M15   # 1-hour candles for daytrading

#2 Saving data
os.makedirs("./data", exist_ok=True)
CSV_FILE = "./data/RSI_strategy.csv"

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

def calculate_rsi(symbol):
    """Calculate RSI for given symbol"""
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, RSI_PERIOD + 1)
    if rates is None or len(rates) < RSI_PERIOD + 1:
        return None
    
    df = pd.DataFrame(rates)
    
    # Calculate price changes
    delta = df['close'].diff()
    
    # Separate gains and losses
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    # Calculate average gain and loss
    avg_gain = gain.rolling(window=RSI_PERIOD).mean()
    avg_loss = loss.rolling(window=RSI_PERIOD).mean()
    
    # Calculate RS and RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi.iloc[-1]

def get_rsi_signal(symbol):
    """Get trading signal based on RSI"""
    rsi = calculate_rsi(symbol)
    
    if rsi is None:
        return None
    
    if rsi < RSI_OVERSOLD:
        return "BUY"
    elif rsi > RSI_OVERBOUGHT:
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
        "magic": 123457,  # Different magic number to distinguish from MA bot
        "comment": f"RSI_{RSI_PERIOD}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ {symbol} {order_type} at {price:.5f} (RSI signal)")
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
        "magic": 123457,
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
    
    print(f"Trading {len(SYMBOLS)} symbols | RSI({RSI_PERIOD}) | Buy < {RSI_OVERSOLD} | Sell > {RSI_OVERBOUGHT}")
    print(f"Close after {CLOSE_HOURS}h | Timeframe: H1")
    print(f"Logging to: {CSV_FILE}\n")
    
    positions = {}
    last_rsi_check = {}
    
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
                
                # Only check RSI every minute (not every 5 seconds)
                last_check = last_rsi_check.get(symbol)
                if last_check and (now - last_check).total_seconds() < 60:
                    continue
                
                signal = get_rsi_signal(symbol)
                if signal:
                    print(f"\n🎯 {symbol} - {signal} signal (RSI)")
                    ticket = place_order(symbol, signal)
                    if ticket:
                        positions[symbol] = {
                            'ticket': ticket,
                            'type': signal,
                            'open_price': mt5.symbol_info_tick(symbol).ask if signal == "BUY" else mt5.symbol_info_tick(symbol).bid,
                            'open_time': now,
                            'close_time': now + timedelta(hours=CLOSE_HOURS)
                        }
                    last_rsi_check[symbol] = now
            
            if positions:
                print(f"\rActive: {len(positions)} symbols | {now.strftime('%H:%M:%S')}", end="")
            
            time.sleep(5)
            
        except KeyboardInterrupt:
            print("\n\nStopping...")
            break
    
    mt5.shutdown()

if __name__ == "__main__":
    main()