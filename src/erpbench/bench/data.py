"""Dataset loading and leakage-safe splitting for the benchmark.

The split is temporal — train on the earliest traces, test on the latest —
mirroring deployment (a detector fitted on history, scoring new cases).
Random splits are deliberately not offered: they leak future behavior into
training and are a documented source of inflated results in this field.
"""

from __future__ import annotations

import pandas as pd

LABEL_COLS = ("trace_label", "anomaly_type")


def load_log(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values(["case_id", "timestamp"], kind="stable")


def trace_labels(df: pd.DataFrame) -> pd.Series:
    return df.groupby("case_id")["trace_label"].first()


def temporal_split(df: pd.DataFrame, train_frac: float = 0.7
                   ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split whole traces by their start time. Returns (train_df, test_df)."""
    starts = df.groupby("case_id")["timestamp"].min().sort_values()
    n_train = int(len(starts) * train_frac)
    train_ids = set(starts.index[:n_train])
    return (df[df["case_id"].isin(train_ids)],
            df[~df["case_id"].isin(train_ids)])


def strip_labels(df: pd.DataFrame) -> pd.DataFrame:
    """What detectors are allowed to see."""
    return df.drop(columns=[c for c in LABEL_COLS if c in df.columns])
