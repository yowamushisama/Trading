import os
import urllib3
from dotenv import load_dotenv
from binance import Client
from binance.exceptions import BinanceAPIException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

api_key    = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

client = Client(api_key, api_secret, testnet=True, requests_params={"verify": False})
client.ping()
print("Connection OK")

# Market depth
depth = client.get_order_book(symbol="BNBBTC")
print(f"Top bid: {depth['bids'][0]}  |  Top ask: {depth['asks'][0]}")

# Test order (simulated — no real/testnet funds used)
order = client.create_test_order(
    symbol="BNBBTC",
    side=Client.SIDE_BUY,
    type=Client.ORDER_TYPE_MARKET,
    quantity=10,
)
print(f"Test order result: {order}")  # {} means success

# All ticker prices
prices = client.get_all_tickers()
btc_price = next(p for p in prices if p["symbol"] == "BTCUSDT")
print(f"BTC/USDT price: ${float(btc_price['price']):,.2f}")

print("\nAll checks passed. Ready to build the AI agent.")
