import MetaTrader5 as mt5
import tkinter as tk
from tkinter import messagebox
import threading
import time

# Default risk percentage (1% of account balance)
risk_percent = 1  # V_1_2
# risk_percent = 100 V1_1
running = False
previous_trade_ids = set()  # Store trade IDs to track new trades


def start_bot():
    global running, risk_percent, previous_trade_ids
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

    log(
        f"✅ Connected to MetaTrader 5 | Account: {account_info.login} | Balance: {account_info.balance}"
    )

    def monitor_trades():
        global running, previous_trade_ids
        while running:
            account_info = mt5.account_info()
            if account_info is None:
                log("❌ Lost connection to MT5. Stopping bot.")
                stop_bot()
                return

            account_balance = account_info.balance
            max_loss = account_balance * (risk_percent / 100.0)  # 1% of balance

            # Get open positions
            positions = mt5.positions_get()
            if positions is None:
                positions = []

            total_risk = 0  # Sum of all stop losses

            for pos in positions:
                if pos.sl > 0:
                    symbol_info = mt5.symbol_info(pos.symbol)
                    tick_value = symbol_info.trade_tick_value if symbol_info else 1
                    contract_size = (
                        symbol_info.trade_contract_size if symbol_info else 100000
                    )  # Default for Forex

                    # Correct SL risk calculation
                    sl_risk = (
                        abs(pos.price_open - pos.sl)
                        * pos.volume
                        * contract_size
                        * tick_value
                    )
                    total_risk += sl_risk

            # **Calculate and print the stop-loss percentage**
            sl_percentage = (total_risk / account_balance) * 100
            log(f"📊 Current Stop-Loss Risk: {sl_percentage:.2f}% of Balance")

            # **Close Trades if Risk Exceeds Limit**
            if total_risk > max_loss:
                for pos in positions:
                    close_trade(pos)

            # **Prevent New Trades if Risk Exceeds Limit**
            orders = mt5.orders_get()
            if orders is None:
                orders = []

            for order in orders:
                stop_loss = order.sl
                symbol_info = mt5.symbol_info_tick(order.symbol)

                if stop_loss > 0 and symbol_info:
                    order_risk = (
                        abs(symbol_info.bid - stop_loss)
                        * order.volume
                        * contract_size
                        * tick_value
                    )
                    if total_risk + order_risk > max_loss:
                        # **Cancel Order Before Execution**
                        result = mt5.order_delete(order.ticket)
                        if result:
                            log(
                                f"❌ Trade {order.ticket} blocked (Total SL risk exceeds {risk_percent}% of balance)"
                            )
                        else:
                            log(
                                f"⚠️ Failed to cancel trade {order.ticket}: {result.comment}"
                            )

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
        "type": (
            mt5.ORDER_TYPE_SELL
            if position.type == mt5.ORDER_TYPE_BUY
            else mt5.ORDER_TYPE_BUY
        ),
        "price": (
            symbol_info.bid if position.type == mt5.ORDER_TYPE_BUY else symbol_info.ask
        ),
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
    global risk_percent
    try:
        risk_percent = float(risk_input.get())
        log(f"✅ Risk percentage updated to {risk_percent}%")
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
