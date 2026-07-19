"""Baseline unsupervised detector: Isolation Forest over per-trace features.

The detector sees ONLY raw event data (activities, actors, amounts, times) —
never the label columns. Labels are used afterwards, purely to evaluate how
well the anomaly scores rank the injected frauds.

Usage:
    python -m erpbench.detect data/p2p_small.csv
"""

from __future__ import annotations

import sys

import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score


def trace_features(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate each case's events into one feature row (labels excluded)."""
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    rows = []
    for case_id, g in df.groupby("case_id"):
        by_act = g.set_index("activity")
        po_amt = by_act.loc["Create PO", "amount"] if "Create PO" in by_act.index else 0.0
        bills = g[g["activity"] == "Post Vendor Bill"]["amount"]
        creator = g[g["activity"] == "Create PO"]["actor"]
        approver = g[g["activity"] == "Approve PO"]["actor"]
        rows.append({
            "case_id": case_id,
            "n_events": len(g),
            "n_bills": (g["activity"] == "Post Vendor Bill").sum(),
            "n_payments": (g["activity"] == "Pay Vendor Bill").sum(),
            "has_receipt": int((g["activity"] == "Receive Goods").any()),
            "bill_to_po_ratio": (bills.sum() / po_amt) if po_amt else 1.0,
            "same_creator_approver": int(
                len(creator) > 0 and len(approver) > 0
                and creator.iloc[0] == approver.iloc[0]),
            "duration_hours": (g["timestamp"].max() - g["timestamp"].min())
                              .total_seconds() / 3600,
        })
    return pd.DataFrame(rows).set_index("case_id")


def main(csv_path: str) -> None:
    df = pd.read_csv(csv_path)
    X = trace_features(df)
    y_true = (df.groupby("case_id")["trace_label"].first() != "normal").astype(int)
    y_true = y_true.reindex(X.index)

    model = IsolationForest(n_estimators=200, random_state=0)
    # score_samples: higher = more normal, so negate for an anomaly score
    scores = pd.Series(-model.fit(X).score_samples(X), index=X.index,
                       name="anomaly_score")

    labels = df.groupby("case_id")["trace_label"].first()
    top = scores.sort_values(ascending=False).head(10)
    print("Top 10 most suspicious traces (detector had no access to labels):\n")
    print(pd.DataFrame({"anomaly_score": top.round(3),
                        "true_label": labels.reindex(top.index)}).to_string())

    print(f"\nROC-AUC: {roc_auc_score(y_true, scores):.3f}   "
          f"AUPRC: {average_precision_score(y_true, scores):.3f}   "
          f"(anomaly base rate: {y_true.mean():.2%})")


if __name__ == "__main__":
    main(sys.argv[1])
