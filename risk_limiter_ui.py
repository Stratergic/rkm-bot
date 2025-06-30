import MetaTrader5 as mt5
import tkinter as tk
from tkinter import messagebox
import threading
import time
import json
from datetime import datetime, timedelta
import os
from datetime import datetime, time as dtime, timedelta

# ==== Persistent State Management ====
STATE_FILE = "daily_risk.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            if os.path.getsize(STATE_FILE) == 0:
                return {}
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

state = load_state()
risk_percent = state.get("risk_percent", 1)
running = False

def is_new_day(last_set_time_str):
    try:
        last = datetime.fromisoformat(last_set_time_str)
    except:
        return True

    now = datetime.now()
    rollover_time = dtime(2, 30)
    last_reset = last.replace(hour=2, minute=30, second=0, microsecond=0)
    if last.time() < rollover_time:
        last_reset -= timedelta(days=1)
    next_reset = last_reset + timedelta(days=1)
    return now >= next_reset

def reset_daily_risk_if_needed():
    if "risk_set_time" in state and is_new_day(state["risk_set_time"]):
        state["risk_used"] = 0
        state["risk_set_time"] = datetime.now().isoformat()
        state["open_balance"] = None
        save_state(state)
        safe_log("🔄 Daily risk usage reset at 2:30 AM.")

# Default risk percentage (1% of account balance)
#risk_percent = 1 # V_1_2
# risk_percent = 100 V1_1
running = False
previous_trade_ids = set()  # Store trade IDs to track new trades

def start_bot():
    global running, risk_percent, previous_trade_ids,state
    
    print("risk precentage",risk_percent)
    if not("risk_set_time" in state) and is_new_day(state["risk_set_time"]):
        log("❌ Not allowed to start bot. Risk isn't set for today.")
        stop_bot()
        return
    
    running = True

    # Initialize MetaTrader 5
    if not mt5.initialize():
        log("❌ Connection to MetaTrader 5 failed. Ensure MT5 is open and logged in.")
        return

    # Check account details
    account_info = mt5.account_info()
    if account_info is None:
        log("❌ Unable to retrieve account information. Check your MetaTrader 5 login.")
        mt5.shutdown()
        return
    if state["open_balance"] is None:
        state["open_balance"] = account_info.balance
        save_state(state)
        log(f"✅ Base balance set to {state['open_balance']}")

    log(f"✅ Connected to MetaTrader 5 | Account: {account_info.login} | Balance: {account_info.balance}")

    def monitor_trades():
        global running, previous_trade_ids
        while running:
            account_info = mt5.account_info()
            if account_info is None:
                log("❌ Lost connection to MT5. Stopping bot.")
                stop_bot()
                return  

            account_balance = account_info.balance
            max_loss = state["open_balance"] * (risk_percent / 100.0)  # 1% of balance
            
            
            # Get open positions
            positions = mt5.positions_get()
            if positions is None:
                positions = []

            total_risk = 0  # Sum of all stop losses

            for pos in positions:
                
                if pos.sl > 0:
                    symbol_info = mt5.symbol_info(pos.symbol)
                    tick_value = symbol_info.trade_tick_value if symbol_info else 1  
                    contract_size = symbol_info.trade_contract_size if symbol_info else 100000  # Default for Forex

                    # Correct SL risk calculation
                    sl_risk = abs(pos.price_open - pos.sl) * pos.volume * contract_size * tick_value
                    total_risk += sl_risk
                    #print(symbol_info.name,symbol_info.bid,symbol_info.volume,symbol_info.price_change,contract_size,"sl_risk",sl_risk,total_risk)
                    print("symbol",pos.symbol,pos.sl,"sl_risk",sl_risk,"price_open",pos.price_open,"pos.sl",pos.sl,"pos.volume",pos.volume)
            # **Calculate and print the stop-loss percentage**
            sl_percentage = (total_risk / state['open_balance']) * 100
            log(f"📊 Current Stop-Loss Risk: {sl_percentage:.2f}% of Balance")
            log(f"Account Balance - Open Balance: {account_balance - state['open_balance']}")
            

            total_risk = (state['open_balance']-account_balance)+ total_risk
            log(f"Total Risk: {total_risk:.2f} | Max Allowed Risk: {max_loss:.2f} ({risk_percent}%)")
            # **Close Trades if Risk Exceeds Limit**
            if total_risk > max_loss:
                messagebox.showerror("trade risk exceeded", f"Total risk {total_risk:.2f} exceeds limit {max_loss:.2f} ({risk_percent}%). Closing trades.")
                if(len(positions) > 0):
                    close_trade(positions[-1])  # Close the last position if risk exceeds limit
                    time.sleep(2)
                    continue


            # **Prevent New Trades if Risk Exceeds Limit**
            orders = mt5.orders_get()
            if orders is None:
                orders = []

            for order in orders:
                stop_loss = order.sl
                symbol_info = mt5.symbol_info_tick(order.symbol)
                print("order",order.symbol,order.ticket,order.volume,stop_loss)
                if stop_loss > 0 and symbol_info:
                    order_risk = abs(symbol_info.bid - stop_loss) * order.volume * contract_size * tick_value
                    if total_risk + order_risk > max_loss:
                        # **Cancel Order Before Execution**
                        result = mt5.order_delete(order.ticket)
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
    global risk_percent, state
    if "risk_set_time" in state and not is_new_day(state["risk_set_time"]):
        messagebox.showerror("Error", "Risk already set today. Try after 2:30 AM.")
        return
    
    try:
        risk_percent = float(risk_input.get())
        state["risk_percent"] = risk_percent
        state["risk_set_time"] = datetime.now().isoformat()
        state["risk_used"] = 0  # reset daily usage
        state["open_balance"] = None  # Store base balance
        save_state(state)
        log(f"✅ Daily risk set to {risk_percent}%. Locked until next rollover.")
    except ValueError:
        messagebox.showerror("Error", "Invalid risk percentage. Please enter a number.")

def log(message):
    log_box.insert(tk.END, message + "\n")
    log_box.see(tk.END)
    print(message)  # Print to console as well

def safe_log(msg):
    app.after(0, lambda: log(msg))

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
