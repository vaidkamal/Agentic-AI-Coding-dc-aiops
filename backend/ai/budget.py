"""Monthly spend budget for model calls (AI-spec section 8, backend-spec Revision 2 section 10).

Reserve an upper bound before the call, settle the actual cost after. Month-to-date
spend lives in memory and, when AI_BUDGET_DB names a SQLite file, is persisted there so
it survives a restart. Token caps alone do not enforce the budget; this does.

Env:
  AI_MONTHLY_BUDGET_USD   default 5
  AI_PRICE_IN_PER_M       USD per million input tokens, default 1.0
  AI_PRICE_OUT_PER_M      USD per million output tokens, default 5.0
  AI_BUDGET_DB            optional SQLite path for month-to-date persistence
"""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import tracing

DEFAULT_MONTHLY_BUDGET_USD = 5.0
DEFAULT_PRICE_IN_PER_M = 1.0
DEFAULT_PRICE_OUT_PER_M = 5.0


class BudgetExhausted(Exception):
    """Raised by reserve() when the reservation would exceed the monthly budget."""


@dataclass
class Reservation:
    month: str
    reserved_usd: float
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    settled: bool = False
    actual_usd: float = 0.0


class _MemoryStore:
    def __init__(self) -> None:
        self._spent: dict[str, float] = {}

    def get(self, month: str) -> float:
        return self._spent.get(month, 0.0)

    def add(self, month: str, usd: float) -> float:
        self._spent[month] = self.get(month) + usd
        return self._spent[month]

    def clear(self) -> None:
        self._spent.clear()


class _SqliteStore:
    def __init__(self, path: str) -> None:
        self._path = path
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS ai_spend (month TEXT PRIMARY KEY, usd REAL NOT NULL)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, isolation_level=None)

    def get(self, month: str) -> float:
        with self._conn() as c:
            row = c.execute("SELECT usd FROM ai_spend WHERE month = ?", (month,)).fetchone()
        return float(row[0]) if row else 0.0

    def add(self, month: str, usd: float) -> float:
        with self._conn() as c:
            c.execute(
                "INSERT INTO ai_spend (month, usd) VALUES (?, ?) "
                "ON CONFLICT(month) DO UPDATE SET usd = usd + excluded.usd",
                (month, usd),
            )
            row = c.execute("SELECT usd FROM ai_spend WHERE month = ?", (month,)).fetchone()
        return float(row[0])

    def clear(self) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM ai_spend")


class Budget:
    def __init__(
        self,
        monthly_usd: float | None = None,
        *,
        db_path: str | None = None,
        price_in_per_m: float | None = None,
        price_out_per_m: float | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.monthly_usd = (
            float(os.environ.get("AI_MONTHLY_BUDGET_USD", DEFAULT_MONTHLY_BUDGET_USD))
            if monthly_usd is None
            else float(monthly_usd)
        )
        self.price_in_per_m = (
            float(os.environ.get("AI_PRICE_IN_PER_M", DEFAULT_PRICE_IN_PER_M))
            if price_in_per_m is None
            else float(price_in_per_m)
        )
        self.price_out_per_m = (
            float(os.environ.get("AI_PRICE_OUT_PER_M", DEFAULT_PRICE_OUT_PER_M))
            if price_out_per_m is None
            else float(price_out_per_m)
        )
        if db_path is None:
            db_path = os.environ.get("AI_BUDGET_DB") or None
        self._store = _SqliteStore(db_path) if db_path else _MemoryStore()
        self._reserved: dict[str, float] = {}
        self._lock = threading.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))

    # ---- accounting -------------------------------------------------------------

    def month_key(self) -> str:
        return self._clock().strftime("%Y-%m")

    def estimate_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.price_in_per_m + output_tokens * self.price_out_per_m
        ) / 1_000_000

    def mtd_usd(self) -> float:
        """Settled spend plus outstanding reservations for the current month."""
        month = self.month_key()
        with self._lock:
            return self._store.get(month) + self._reserved.get(month, 0.0)

    def reserve(self, est_input_tokens: int, max_output_tokens: int) -> Reservation:
        """Reserve the upper-bound cost of one call; raise BudgetExhausted when it does not fit."""
        month = self.month_key()
        amount = self.estimate_usd(est_input_tokens, max_output_tokens)
        with tracing.budget_reserve_span() as span:
            with self._lock:
                before = self._store.get(month) + self._reserved.get(month, 0.0)
                allowed = before + amount <= self.monthly_usd
                if allowed:
                    self._reserved[month] = self._reserved.get(month, 0.0) + amount
            tracing.set_attributes(
                span,
                {
                    "reserved_usd": round(amount, 6),
                    "mtd_usd_before": round(before, 6),
                    "allowed": allowed,
                    "budget_usd": self.monthly_usd,
                },
            )
            if not allowed:
                raise BudgetExhausted(
                    f"month-to-date {before:.4f} USD + reservation {amount:.4f} USD "
                    f"exceeds budget {self.monthly_usd:.2f} USD"
                )
        return Reservation(month=month, reserved_usd=amount)

    def settle(self, reservation: Reservation, input_tokens: int, output_tokens: int) -> float:
        """Replace the reservation with the actual cost. Returns month-to-date after settling."""
        actual = self.estimate_usd(input_tokens, output_tokens)
        with tracing.budget_settle_span() as span:
            with self._lock:
                if not reservation.settled:
                    month = reservation.month
                    self._reserved[month] = max(
                        0.0, self._reserved.get(month, 0.0) - reservation.reserved_usd
                    )
                    reservation.settled = True
                    reservation.actual_usd = actual
                    self._store.add(month, actual)
                after = self._store.get(reservation.month) + self._reserved.get(
                    reservation.month, 0.0
                )
            tracing.set_attributes(
                span, {"actual_usd": round(actual, 6), "mtd_usd_after": round(after, 6)}
            )
        return after

    def release(self, reservation: Reservation) -> float:
        """Settle with zero cost (the call never produced usage)."""
        return self.settle(reservation, 0, 0)

    def reset(self) -> None:
        with self._lock:
            self._store.clear()
            self._reserved.clear()
