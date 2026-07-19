"""Context-aware trace features: what it takes to see the hard anomaly tier.

The baseline features (erpbench.detect.trace_features) describe one trace in
isolation, which is exactly why the hard typologies evade them. Two extensions
close the scope gap:

- **Time context**: fraction of a trace's events outside business hours /
  on weekends. Targets `after_hours`.
- **Cross-trace context**: for each trace, look at the other traces by the
  same (requester, vendor) pair starting within a +/-14-day window — how many
  there are, their summed PO amount relative to the approval threshold, and
  how many sit just under it. Targets `split_purchase`, which is invisible at
  single-trace scope by construction.

The window is symmetric, modeling a periodic batch audit (when case X is
scored, the neighboring cases of the same period are on the auditor's desk
too). The approval threshold is domain knowledge, on the same footing as the
three-way-match rule the audit baseline uses.
"""

from __future__ import annotations

import pandas as pd

from ..detect import trace_features

APPROVAL_THRESHOLD = 5000.0
WINDOW_DAYS = 14
NEAR_BAND = (0.80, 1.00)  # PO total as a fraction of the threshold


def context_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    feats = trace_features(df)

    # --- time context ---------------------------------------------------
    hours = df["timestamp"].dt.hour
    off_hours = (hours < 8) | (hours >= 19)
    feats["frac_off_hours"] = off_hours.groupby(df["case_id"]).mean()
    feats["frac_weekend"] = ((df["timestamp"].dt.weekday >= 5)
                             .groupby(df["case_id"]).mean())

    # --- cross-trace context -------------------------------------------
    po_events = df[df["activity"] == "Create PO"].set_index("case_id")
    info = pd.DataFrame({
        "start": df.groupby("case_id")["timestamp"].min(),
        "requester": po_events["actor"],
        "vendor": po_events["vendor"] if "vendor" in df.columns else "",
        "po_amount": po_events["amount"],
    }).reindex(feats.index)

    ratio = info["po_amount"] / APPROVAL_THRESHOLD
    info["near_threshold"] = ratio.between(*NEAR_BAND)
    window = pd.Timedelta(days=WINDOW_DAYS)

    pair_count, pair_sum_ratio, pair_near = {}, {}, {}
    for case_id, row in info.iterrows():
        group = info[(info["requester"] == row["requester"])
                     & (info["vendor"] == row["vendor"])
                     & ((info["start"] - row["start"]).abs() <= window)]
        pair_count[case_id] = len(group)
        pair_sum_ratio[case_id] = group["po_amount"].sum() / APPROVAL_THRESHOLD
        pair_near[case_id] = int(group["near_threshold"].sum())

    feats["near_threshold"] = info["near_threshold"].astype(int)
    feats["pair_count_14d"] = pd.Series(pair_count)
    feats["pair_sum_ratio_14d"] = pd.Series(pair_sum_ratio)
    feats["pair_near_count_14d"] = pd.Series(pair_near)
    return feats.fillna(0.0)
