"""Event log capture with ground-truth labels.

The driver, not Odoo, is the source of truth for timestamps: Odoo stamps
records with the wall clock, so simulating months of history requires a
virtual clock owned by the simulation. Every business action the driver
performs is recorded here as one event, together with anomaly labels known
at generation time (trace-level and event-level).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

NORMAL = "normal"


BUSINESS_START, BUSINESS_END = 9, 18


class SimClock:
    """Virtual clock advancing by random business-plausible deltas.

    Normal steps land inside business hours (Mon-Fri, 9-18) so that off-hours
    activity is a meaningful anomaly signal rather than background noise.
    Rolls only forward: timestamps stay monotonic within a trace.
    """

    def __init__(self, start: datetime, rng: random.Random):
        self.now = start
        self.rng = rng

    def step(self, min_minutes: int = 10, max_minutes: int = 2880,
             off_hours: bool = False) -> datetime:
        self.now += timedelta(minutes=self.rng.randint(min_minutes, max_minutes))
        if off_hours:
            target = self.now.replace(hour=self.rng.randint(1, 4),
                                      minute=self.rng.randint(0, 59))
            self.now = target if target > self.now else target + timedelta(days=1)
        else:
            self._roll_to_business_hours()
        return self.now

    def _roll_to_business_hours(self) -> None:
        if self.now.hour < BUSINESS_START:
            self.now = self.now.replace(
                hour=BUSINESS_START + self.rng.randint(0, 2),
                minute=self.rng.randint(0, 59))
        elif self.now.hour >= BUSINESS_END:
            self.now = (self.now + timedelta(days=1)).replace(
                hour=BUSINESS_START + self.rng.randint(0, 2),
                minute=self.rng.randint(0, 59))
        while self.now.weekday() >= 5:
            self.now += timedelta(days=1)


@dataclass
class Event:
    case_id: str
    activity: str
    timestamp: datetime
    actor: str
    role: str
    amount: float | None = None
    doc_ref: str | None = None
    vendor: str | None = None  # partner on PO/bill events, as a real log would carry
    anomaly_type: str = NORMAL  # event-level label


@dataclass
class EventLog:
    events: list[Event] = field(default_factory=list)
    trace_labels: dict[str, str] = field(default_factory=dict)  # case_id -> anomaly type

    def record(self, event: Event) -> None:
        self.events.append(event)
        if event.anomaly_type != NORMAL:
            self.trace_labels[event.case_id] = event.anomaly_type
        else:
            self.trace_labels.setdefault(event.case_id, NORMAL)

    def mark_trace(self, case_id: str, anomaly_type: str) -> None:
        """Label a whole trace anomalous when no single event carries the anomaly
        (e.g. a *missing* step)."""
        self.trace_labels[case_id] = anomaly_type

    def to_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame([vars(e) for e in self.events])
        df["trace_label"] = df["case_id"].map(self.trace_labels)
        return df.sort_values(["case_id", "timestamp"], kind="stable")

    def save_csv(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_dataframe().to_csv(path, index=False)
        return path
