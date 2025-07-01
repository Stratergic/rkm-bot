import MetaTrader5 as mt5
import tkinter as tk
from tkinter import messagebox
import threading
import time
from datetime import datetime, timedelta
import pytz
class MockAccountInfo:
    def __init__(self):
        self.login = 123456
        self.balance = 10000.0

class MockPosition:
    def __init__(self, ticket, symbol, volume, price_open, sl, type):
        self.ticket = ticket
        self.symbol = symbol
        self.volume = volume
        self.price_open = price_open
        self.sl = sl
        self.type = type

class MockSymbolInfo:
    def __init__(self):
        self.trade_contract_size = 100000
        self.trade_tick_value = 1

class MockSymbolTick:
    def __init__(self):
        self.bid = 1.1000
        self.ask = 1.1002
class MockOrder:
    def __init__(self, ticket, symbol, volume, sl):
        self.ticket = ticket
        self.symbol = symbol
        self.volume = volume
        self.sl = sl
class MockOrderDeleteResult:
    def __init__(self, retcode, comment=""):
        self.retcode = retcode
        self.comment = comment
def fake_order_delete(ticket):
    print(f"🧪 [FAKE] Cancelling order {ticket}")
    
    # Simulate successful deletion
    return MockOrderDeleteResult(retcode=10009, comment="Order canceled (mock)")

def fake_orders_get():
    return [
        MockOrder(ticket=1001, symbol="BTCUSD", volume=0.1, sl=30500.0),  # Fake BUY order
        MockOrder(ticket=1002, symbol="BTCUSD", volume=0.2, sl=30000.0),  # Fake SELL order
    ]
def fake_positions_get():
    return [
        MockPosition(ticket=1, symbol="EURUSD", volume=0.1, price_open=1.0950, sl=1.0900, type=0),  # Buy
        MockPosition(ticket=2, symbol="EURUSD", volume=0.2, price_open=1.1010, sl=1.0960, type=1),  # Sell
    ]
def fake_account_info():
    return MockAccountInfo()

def fake_symbol_info(symbol):
    return MockSymbolInfo()

def fake_symbol_info_tick(symbol):
    return MockSymbolTick()
# Default risk percentage (1% of account balance)
risk_percent=0; # V_1_2
# risk_percent = 100 V1_1
running = False
previous_trade_ids = set()  # Store trade IDs to track new trades

risk_limit_locked = False
risk_limit_set_time = None
risk_limit_reset_time = None
risk_limit_value = None

def get_next_rollover():
    sl_tz = pytz.timezone("Asia/Colombo")
    now = datetime.now(sl_tz)
    rollover = now.replace(hour=2, minute=30, second=0, microsecond=0)
    if now >= rollover:
        rollover += timedelta(days=1)
    return rollover

def start_bot():
    global running, risk_percent, previous_trade_ids
    
    if risk_percent <= 0:
        log("Error Please set a valid risk percentage greater than 0.")
        return
    # Initialize MetaTrader 5
    running = True
    if not mt5.initialize():
        log("❌ Connection to MetaTrader 5 failed. Ensure MT5 is open and logged in.")
        return

    # Check account details
    account_info = mt5.account_info()
    if account_info is None:
        log("❌ Unable to retrieve account information. Check your MetaTrader 5 login.")
        mt5.shutdown()
        return

    log(f"✅ Connected to MetaTrader 5 | Account: {account_info.login} | Balance: {account_info.balance}")

    def monitor_trades():
        global running, previous_trade_ids, risk_limit_locked, risk_limit_reset_time, risk_limit_value
        account_info = fake_account_info()
        balance_at_set = account_info.balance
        risk_limit_value = balance_at_set * (risk_percent / 100.0)
        total_risk = 0  # Sum of all stop losses
        while running:
            account_info = fake_account_info()
            if account_info is None:
                log("❌ Lost connection to MT5. Stopping bot.")
                stop_bot()
                return
            sl_tz = pytz.timezone("Asia/Colombo")
            now = datetime.now(sl_tz)
            if risk_limit_locked and now >= risk_limit_reset_time:
                total_risk = 0
                risk_limit_locked = False
                risk_limit_value = None
                log("🔓 Risk limit lock expired. You can now update the risk % again.")

            if not risk_limit_value:
                log("⚠️ Risk limit not set. Cannot continue monitoring.")
                stop_bot()
                return
            account_balance = account_info.balance
            max_loss = risk_limit_value 

            # Get open positions
            positions = fake_positions_get()
            if positions is None:
                positions = []

            

            for pos in positions:
                print(f"Checking position: {pos.symbol} | SL: {pos.sl} | Volume: {pos.volume}")
                if pos.sl > 0:
                    symbol_info = fake_symbol_info("EURUSD")
                    tick_value = symbol_info.trade_tick_value if symbol_info else 1  
                    contract_size = symbol_info.trade_contract_size if symbol_info else 100000  # Default for Forex

                    # Correct SL risk calculation
                    sl_risk = abs(pos.price_open - pos.sl) * pos.volume * contract_size * tick_value
                    total_risk += sl_risk

            # **Calculate and print the stop-loss percentage**
            sl_percentage = (total_risk / account_balance) * 100
            log(f"📊 Current Stop-Loss Risk: {sl_percentage:.2f}% of Balance")

            # **Close Trades if Risk Exceeds Limit**
            if total_risk > max_loss:
                for pos in positions:
                    close_trade(pos)

            # **Prevent New Trades if Risk Exceeds Limit**
            orders = fake_orders_get()
            if orders is None:
                orders = []

            for order in orders:
                stop_loss = order.sl
                symbol_info = mt5.symbol_info_tick(order.symbol)

                if stop_loss > 0 and symbol_info:
                    order_risk = abs(symbol_info.bid - stop_loss) * order.volume * contract_size * tick_value
                    if total_risk + order_risk > max_loss:
                        # **Cancel Order Before Execution**
                        result = fake_order_delete(order.ticket)
                        if result:
                            log(f"❌ Trade {order.ticket} blocked (Total SL risk exceeds {risk_percent}% of balance)")
                        else:
                            log(f"⚠️ Failed to cancel trade {order.ticket}: {result.comment}")

            time.sleep(2)

    threading.Thread(target=monitor_trades, daemon=True).start()
    log("🚀 Bot started...")

def close_trade(position):
    """
    Close a trade using the correct bid/ask price.
    """
    symbol_info = mt5.symbol_info_tick(position.symbol)
    if not symbol_info:
        log(f"⚠️ Failed to close trade {position.ticket}: No symbol info")
        return False

    close_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "position": position.ticket,
        "type": mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "price": symbol_info.bid if position.type == mt5.ORDER_TYPE_BUY else symbol_info.ask,
        "deviation": 10,  # Price deviation allowed
        "magic": 0,
        "comment": "Closed by Risk Manager",
    }
    
    result = mt5.order_send(close_request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log(f"⚠️ Failed to close trade {position.ticket}: {result.comment}")
        return False
    else:
        log(f"✅ Trade {position.ticket} closed successfully")
        return True

def stop_bot():
    global running
    running = False
    mt5.shutdown()
    log("🛑 Bot stopped.")

def update_risk():
    global risk_percent, risk_limit_locked, risk_limit_set_time, risk_limit_value, risk_limit_reset_time

    if risk_limit_locked:
        sl_tz = pytz.timezone("Asia/Colombo")
        now = datetime.now(sl_tz)
        log(f"Locked Risk limit is already set and locked for {risk_limit_reset_time - now}.")
        return
    try:
        risk_percent = float(risk_input.get())
        log(f"✅ Risk percentage updated to {risk_percent}%")
        risk_limit_set_time = datetime.now(pytz.timezone("Asia/Colombo"))
        risk_limit_reset_time = get_next_rollover()
        risk_limit_locked = True
    except ValueError:
        messagebox.showerror("Error", "Invalid risk percentage. Please enter a number.")

def log(message):
    log_box.insert(tk.END, message + "\n")
    log_box.see(tk.END)
    print(message)  # Print to console as well

# UI Setup
app = tk.Tk()
app.title("MetaTrader Risk Limiter Bot")
app.geometry("400x300")

tk.Label(app, text="Set Maximum Risk %:").pack()
risk_input = tk.Entry(app)
risk_input.insert(0, str(risk_percent))
risk_input.pack()

tk.Button(app, text="Update Risk", command=update_risk).pack()
tk.Button(app, text="Start Bot", command=start_bot).pack()
tk.Button(app, text="Stop Bot", command=stop_bot).pack()

log_box = tk.Text(app, height=10)
log_box.pack()

app.mainloop()
