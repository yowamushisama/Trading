"""DB integration tests — require DATABASE_URL in environment. Skipped otherwise."""

from __future__ import annotations

import os
import pytest
from datetime import datetime, timezone

# Skip entire module if no DATABASE_URL
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping DB integration tests",
)


@pytest.fixture(scope="module")
def db_session():
    import urllib.parse
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from contextlib import contextmanager

    url = os.environ["DATABASE_URL"]
    url = url.replace("postgresql+psycopg://", "postgresql+psycopg2://")
    url = urllib.parse.unquote(url)

    engine = create_engine(url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def get():
        s = SessionLocal()
        try:
            yield s
            s.commit()
        except:
            s.rollback()
            raise
        finally:
            s.close()

    return get


class TestDBConnection:
    def test_connection_ok(self, db_session):
        from sqlalchemy import text
        with db_session() as s:
            result = s.execute(text("SELECT 1")).scalar()
        assert result == 1


class TestSignalRepo:
    def test_save_and_retrieve_signal(self, db_session):
        from btc_bot.storage.repos import save_signal
        from btc_bot.storage.models import Signal

        with db_session() as s:
            sig = save_signal(
                s, "scalper", "BTC/USDT", "5m", "long",
                50000.0, 49000.0, 51500.0,
                accepted=True, reason="test"
            )
            s.flush()
            assert sig.id is not None

        with db_session() as s:
            row = s.query(Signal).filter_by(strategy="scalper", reason="test").first()
            assert row is not None
            assert row.accepted is True
            assert float(row.entry) == pytest.approx(50000.0)

    def test_rejected_signal_saves_reject_reason(self, db_session):
        from btc_bot.storage.repos import save_signal
        from btc_bot.storage.models import Signal

        with db_session() as s:
            sig = save_signal(
                s, "scalper", "BTC/USDT", "5m", "long",
                50000.0, 49900.0, 50100.0,
                accepted=False, reason="test-reject",
                reject_reason="R:R 0.2 < 1.5"
            )
            s.flush()
            assert sig.id is not None

        with db_session() as s:
            row = s.query(Signal).filter_by(reason="test-reject").first()
            assert row is not None
            assert row.accepted is False
            assert "R:R" in row.reject_reason


class TestRiskEventRepo:
    def test_log_and_retrieve_risk_event(self, db_session):
        from btc_bot.storage.repos import log_risk_event
        from btc_bot.storage.models import RiskEvent

        with db_session() as s:
            ev = log_risk_event(s, "test_kill_switch", "critical", {"test": True})
            s.flush()
            assert ev.id is not None

        with db_session() as s:
            row = s.query(RiskEvent).filter_by(kind="test_kill_switch").first()
            assert row is not None
            assert row.severity == "critical"
            assert row.payload == {"test": True}


class TestBotStateRepo:
    def test_set_and_get_state(self, db_session):
        from btc_bot.storage.repos import get_state, set_state

        with db_session() as s:
            set_state(s, "test_key_pytest", {"value": 42, "flag": True})

        with db_session() as s:
            val = get_state(s, "test_key_pytest")
            assert val == {"value": 42, "flag": True}

    def test_update_existing_state(self, db_session):
        from btc_bot.storage.repos import get_state, set_state

        with db_session() as s:
            set_state(s, "test_update_key", {"v": 1})
        with db_session() as s:
            set_state(s, "test_update_key", {"v": 2})
        with db_session() as s:
            val = get_state(s, "test_update_key")
            assert val == {"v": 2}


class TestNewsRepo:
    def test_upsert_news_item(self, db_session):
        from btc_bot.storage.repos import upsert_news_item
        from btc_bot.storage.models import NewsItem
        from datetime import datetime, timezone

        url = f"https://test.example.com/news/{datetime.now().timestamp()}"
        with db_session() as s:
            item, is_new = upsert_news_item(
                s, "test", url, "Test headline", "body",
                datetime.now(tz=timezone.utc),
                ["regulatory"], -0.8, "keyword"
            )
            s.flush()
            assert is_new is True
            assert item.id is not None

        with db_session() as s:
            item2, is_new2 = upsert_news_item(
                s, "test", url, "Test headline", "body",
                datetime.now(tz=timezone.utc),
                ["regulatory"], -0.8, "keyword"
            )
            assert is_new2 is False  # duplicate URL → not inserted
