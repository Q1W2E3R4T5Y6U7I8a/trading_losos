import os
from dotenv import load_dotenv
import MetaTrader5 as mt5

load_dotenv()

# Load trading settings from .env
LOGIN = int(os.getenv("LOGIN", "52459620"))
PASSWORD = os.getenv("PASSWORD", "")
SERVER = os.getenv("SERVER", "ICMarketsSC-Demo")
SYMBOL = os.getenv("SYMBOL", "AUDCHF")
VOLUME = float(os.getenv("VOLUME", "0.1"))
ORDER_TYPE_STR = os.getenv("ORDER_TYPE", "BUY").strip().upper()
ORDER_TYPE = mt5.ORDER_TYPE_BUY if ORDER_TYPE_STR == "BUY" else mt5.ORDER_TYPE_SELL

def place_order():
    # Initialize MT5
    if not mt5.initialize():
        print("MT5 initialization failed")
        return False
    
    # Login
    if not mt5.login(LOGIN, password=PASSWORD, server=SERVER):
        print("Login failed")
        mt5.shutdown()
        return False
    
    print(f"Logged in as {LOGIN}")
    
    # Get current price
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print(f"Failed to get {SYMBOL} price")
        mt5.shutdown()
        return False
    
    price = tick.ask if ORDER_TYPE == mt5.ORDER_TYPE_BUY else tick.bid
    
    # Prepare order request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": VOLUME,
        "type": ORDER_TYPE,
        "price": price,
        "deviation": 10,
        "magic": 123456,
        "comment": "Python bot order",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    # Send order
    result = mt5.order_send(request)
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"Order placed successfully!")
        print(f"Order ticket: {result.order}")
        print(f"Price: {price}")
    else:
        print(f"Order failed. Return code: {result.retcode}")
        print(f"Comment: {result.comment}")
    
    mt5.shutdown()
    return result.retcode == mt5.TRADE_RETCODE_DONE

if __name__ == "__main__":
    place_order()