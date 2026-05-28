"""
Live trade test — buys $6 worth of BNB then immediately sells it back.
BNB/USDT is used because it has the lowest minimum notional (~$5) on Binance.
Requires LIVE_API_KEY and LIVE_API_SECRET in .env with Spot Trading enabled.
"""

import math
import os
import urllib3
from dotenv import load_dotenv
from binance import Client
from binance.exceptions import BinanceAPIException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

API_KEY    = os.getenv("LIVE_API_KEY")
API_SECRET = os.getenv("LIVE_API_SECRET")

SYMBOL        = "BNBUSDT"
SPEND_USDT    = 6.0          # min tradeable: 0.01 BNB (~$6.50 at current price)


def get_client() -> Client:
    if not API_KEY or API_KEY == "your_live_api_key_here":
        raise ValueError("Live API keys not set in .env")
    client = Client(API_KEY, API_SECRET, requests_params={"verify": False})
    return client


def get_balance(client: Client, asset: str) -> float:
    return float(client.get_asset_balance(asset=asset)["free"])


def get_funding_balance(client: Client, asset: str) -> float:
    """Check Funding wallet balance (separate from Spot on Binance)."""
    try:
        result = client.get_funding_asset(asset=asset)
        for item in result:
            if item.get("asset") == asset:
                return float(item.get("free", 0))
    except Exception:
        pass
    return 0.0


def get_bnb_quantity(client: Client) -> float:
    """Calculate how much BNB we can buy with SPEND_USDT."""
    ticker = client.get_symbol_ticker(symbol=SYMBOL)
    price  = float(ticker["price"])
    qty    = SPEND_USDT / price
    # BNB requires 2 decimal places on Binance
    return round(qty, 2)


def place_market_order(client: Client, side: str, quantity: float) -> dict:
    return client.create_order(
        symbol=SYMBOL,
        side=side,
        type=Client.ORDER_TYPE_MARKET,
        quantity=quantity,
    )


def print_order(label: str, order: dict) -> None:
    fills     = order.get("fills", [])
    total_qty = sum(float(f["qty"]) for f in fills)
    avg_price = sum(float(f["price"]) * float(f["qty"]) for f in fills) / total_qty if total_qty else 0

    print(f"\n{'='*48}")
    print(f"  {label}")
    print(f"{'='*48}")
    print(f"  Order ID   : {order['orderId']}")
    print(f"  Symbol     : {order['symbol']}")
    print(f"  Side       : {order['side']}")
    print(f"  Status     : {order['status']}")
    print(f"  Qty filled : {order['executedQty']} BNB")
    print(f"  Avg price  : ${avg_price:,.4f}")
    print(f"  Total cost : ${float(order['executedQty']) * avg_price:,.4f} USDT")
    print(f"{'='*48}\n")


def main() -> None:
    print("\n*** LIVE TRADING — REAL MONEY ***\n")

    client = get_client()
    client.ping()
    print("Connection OK")

    usdt_before = get_balance(client, "USDT")
    bnb_before  = get_balance(client, "BNB")
    print(f"Balances before  ->  USDT: {usdt_before:.4f}  |  BNB: {bnb_before:.4f}")

    if usdt_before < SPEND_USDT:
        funding = get_funding_balance(client, "USDT")
        hint = f"\n  Hint: Found {funding:.4f} USDT in your Funding wallet — transfer it to Spot first." if funding >= SPEND_USDT else ""
        raise ValueError(f"Insufficient USDT in Spot wallet. Have {usdt_before:.4f}, need {SPEND_USDT}.{hint}")

    qty = get_bnb_quantity(client)
    print(f"\nBuying {qty} BNB (~${SPEND_USDT} USDT)...")

    # --- BUY ---
    buy_order = place_market_order(client, Client.SIDE_BUY, qty)
    print_order("BUY ORDER", buy_order)

    bnb_after_buy = get_balance(client, "BNB")
    print(f"Balances after buy  ->  USDT: {get_balance(client, 'USDT'):.4f}  |  BNB: {bnb_after_buy:.4f}")

    # --- SELL ---
    # Re-fetch balance: fees paid in BNB reduce it below executedQty
    raw_bnb = get_balance(client, "BNB")
    sell_qty = math.floor(raw_bnb * 100) / 100  # round down to 2 dp (Binance step size)
    print(f"\nSelling {sell_qty} BNB back...")

    sell_order = place_market_order(client, Client.SIDE_SELL, sell_qty)
    print_order("SELL ORDER", sell_order)

    usdt_final = get_balance(client, "USDT")
    bnb_final  = get_balance(client, "BNB")
    print(f"Balances after sell ->  USDT: {usdt_final:.4f}  |  BNB: {bnb_final:.4f}")

    spread = usdt_final - usdt_before
    print(f"Net P&L (after fees): ${spread:+.4f} USDT\n")


if __name__ == "__main__":
    try:
        main()
    except BinanceAPIException as e:
        print(f"\n[Binance Error] code={e.status_code}  msg={e.message}")
    except Exception as e:
        print(f"\n[Error] {e}")
