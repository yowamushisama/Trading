"""Binance user-data WebSocket stream.

Listens for executionReport (order lifecycle) and outboundAccountPosition (balances).
This is the PRIMARY source of order status — REST reconciliation is the fallback.

Architecture:
  - Runs in a background thread
  - Pushes events into a queue consumed by the main loop
  - Auto-reconnects on disconnect; REST reconciler triggers on reconnect
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from loguru import logger


@dataclass
class OrderEvent:
    """Parsed executionReport event from user-data stream."""
    client_order_id: str
    exchange_order_id: str
    symbol: str
    side: str
    order_type: str
    status: str                  # NEW | PARTIALLY_FILLED | FILLED | CANCELED | REJECTED | EXPIRED
    qty: float
    qty_filled: float
    price: float
    last_fill_qty: float
    last_fill_price: float
    event_time: datetime
    raw: dict


@dataclass
class BalanceEvent:
    asset: str
    free: float
    locked: float
    event_time: datetime


UserDataEvent = OrderEvent | BalanceEvent


class UserDataStream:
    """Manages the Binance user-data WebSocket stream lifecycle."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        event_callback: Callable[[UserDataEvent], None] | None = None,
        reconnect_callback: Callable[[], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.event_callback = event_callback
        self.reconnect_callback = reconnect_callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listen_key: str | None = None
        self.event_queue: queue.Queue[UserDataEvent] = queue.Queue()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="UserDataStream")
        self._thread.start()
        logger.info("User-data stream thread started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _get_client(self):
        from binance import Client
        import urllib3
        urllib3.disable_warnings()
        kwargs = {"requests_params": {"verify": False}}
        if self.testnet:
            kwargs["testnet"] = True
        return Client(self.api_key, self.api_secret, **kwargs)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as e:
                logger.error(f"User-data stream error: {e}")
                if self.reconnect_callback:
                    self.reconnect_callback()
            if not self._stop.is_set():
                logger.info("User-data stream reconnecting in 5s...")
                time.sleep(5)

    def _connect_and_listen(self) -> None:
        from binance import ThreadedWebsocketManager

        client = self._get_client()
        self._listen_key = client.stream_get_listen_key()
        logger.info(f"Got listen key: {self._listen_key[:8]}...")

        twm = ThreadedWebsocketManager(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet,
            requests_params={"verify": False},
        )
        twm.start()

        def handle_msg(msg: dict) -> None:
            event = self._parse_event(msg)
            if event is None:
                return
            self.event_queue.put(event)
            if self.event_callback:
                self.event_callback(event)

        twm.start_user_socket(callback=handle_msg)

        # Keep-alive: Binance listen keys expire after 60 min without a PUT
        keep_alive_interval = 30 * 60  # 30 minutes
        elapsed = 0
        while not self._stop.is_set():
            time.sleep(10)
            elapsed += 10
            if elapsed >= keep_alive_interval:
                try:
                    client.stream_keepalive(self._listen_key)
                    elapsed = 0
                except Exception as e:
                    logger.warning(f"Listen key keepalive failed: {e}")
                    break

        twm.stop()

    @staticmethod
    def _parse_event(msg: dict) -> UserDataEvent | None:
        event_type = msg.get("e")
        ts = datetime.fromtimestamp(msg.get("E", 0) / 1000, tz=timezone.utc)

        if event_type == "executionReport":
            return OrderEvent(
                client_order_id=msg.get("c", ""),
                exchange_order_id=str(msg.get("i", "")),
                symbol=msg.get("s", ""),
                side=msg.get("S", ""),
                order_type=msg.get("o", ""),
                status=msg.get("X", ""),
                qty=float(msg.get("q", 0)),
                qty_filled=float(msg.get("z", 0)),
                price=float(msg.get("p", 0)),
                last_fill_qty=float(msg.get("l", 0)),
                last_fill_price=float(msg.get("L", 0)),
                event_time=ts,
                raw=msg,
            )

        if event_type == "outboundAccountPosition":
            for bal in msg.get("B", []):
                if bal.get("a") in ("BTC", "USDT"):
                    return BalanceEvent(
                        asset=bal["a"],
                        free=float(bal["f"]),
                        locked=float(bal["l"]),
                        event_time=ts,
                    )

        return None
