"""
Binance test trade — places a small market buy then immediately sells.
Uses Testnet by default. Set BINANCE_ENV=live in .env to use real funds.
"""

import os
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException

load_dotenv()

API_KEY    = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
ENV        = os.getenv("BINANCE_ENV", "testnet")

SYMBOL   = "BTCUSDT"
QUANTITY = 0.001          # ~$60–70 worth at current BTC prices


def get_client() -> Client:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    testnet = ENV == "testnet"
    client = Client(API_KEY, API_SECRET, testnet=testnet)
    client.session.verify = False
    return client


def get_balance(client: Client, asset: str) -> float:
    info = client.get_asset_balance(asset=asset)
    return float(info["free"])


def place_market_order(client: Client, side: str, quantity: float) -> dict:
    return client.create_order(
        symbol=SYMBOL,
        side=side,
        type=Client.ORDER_TYPE_MARKET,
        quantity=quantity,
    )


def print_order(label: str, order: dict) -> None:
    fills      = order.get("fills", [])
    avg_price  = sum(float(f["price"]) * float(f["qty"]) for f in fills)
    total_qty  = sum(float(f["qty"]) for f in fills)
    avg_price  = avg_price / total_qty if total_qty else 0

    print(f"\n{'='*45}")
    print(f"  {label}")
    print(f"{'='*45}")
    print(f"  Order ID   : {order['orderId']}")
    print(f"  Symbol     : {order['symbol']}")
    print(f"  Side       : {order['side']}")
    print(f"  Status     : {order['status']}")
    print(f"  Qty filled : {order['executedQty']}")
    print(f"  Avg price  : ${avg_price:,.2f}")
    print(f"{'='*45}\n")


def main() -> None:
    env_label = "TESTNET" if ENV == "testnet" else "*** LIVE ***"
    print(f"\n[Binance {env_label}] Connecting...")

    client = get_client()

    # Verify connection
    client.ping()
    print("Connection OK")

    usdt_before = get_balance(client, "USDT")
    btc_before  = get_balance(client, "BTC")
    print(f"Balances before  ->  USDT: {usdt_before:.2f}  |  BTC: {btc_before:.6f}")

    # --- BUY ---
    print(f"\nPlacing MARKET BUY  {QUANTITY} {SYMBOL}...")
    buy_order = place_market_order(client, Client.SIDE_BUY, QUANTITY)
    print_order("BUY ORDER", buy_order)

    usdt_after_buy = get_balance(client, "USDT")
    btc_after_buy  = get_balance(client, "BTC")
    print(f"Balances after buy  ->  USDT: {usdt_after_buy:.2f}  |  BTC: {btc_after_buy:.6f}")

    # --- SELL ---
    print(f"\nPlacing MARKET SELL {QUANTITY} {SYMBOL}...")
    sell_order = place_market_order(client, Client.SIDE_SELL, QUANTITY)
    print_order("SELL ORDER", sell_order)

    usdt_final = get_balance(client, "USDT")
    btc_final  = get_balance(client, "BTC")
    print(f"Balances after sell ->  USDT: {usdt_final:.2f}  |  BTC: {btc_final:.6f}")

    spread = usdt_final - usdt_before
    print(f"\nNet P&L from round trip: ${spread:+.4f} USDT  (exchange fees deducted)\n")


if __name__ == "__main__":
    try:
        main()
    except BinanceAPIException as e:
        print(f"\n[Binance API Error] code={e.status_code}  msg={e.message}")
    except Exception as e:
        print(f"\n[Error] {e}")
