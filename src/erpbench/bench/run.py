"""Benchmark runner: every registered detector against one event log.

Protocol: temporal split (train on earliest traces, test on latest); each
detector fits on the unlabeled train portion and scores the test portion;
labels are used only for evaluation. Reported per method: overall ROC-AUC and
AUPRC, plus AUPRC per anomaly type (that type's test traces vs. all normal
test traces) — the per-type view is where methods actually differ.

Usage:
    python -m erpbench.bench.run data/p2p_medium.csv [--train-frac 0.7]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from .data import load_log, strip_labels, temporal_split, trace_labels
from .methods import registry


def evaluate(scores: pd.Series, labels: pd.Series) -> dict:
    labels = labels.reindex(scores.index)
    y = (labels != "normal").astype(int)
    row = {
        "roc_auc": roc_auc_score(y, scores),
        "auprc": average_precision_score(y, scores),
    }
    for atype in sorted(labels[labels != "normal"].unique()):
        mask = (labels == "normal") | (labels == atype)
        row[f"auprc:{atype}"] = average_precision_score(
            (labels[mask] == atype).astype(int), scores[mask])
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--train-frac", type=float, default=0.7)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    df = load_log(args.csv)
    train, test = temporal_split(df, args.train_frac)
    labels = trace_labels(test)
    n_anom = (labels != "normal").sum()
    print(f"{df['case_id'].nunique()} traces -> "
          f"train {train['case_id'].nunique()}, test {len(labels)} "
          f"({n_anom} anomalous, {n_anom / len(labels):.1%})\n")

    rows = {}
    for name, method in registry().items():
        scores = method.fit(strip_labels(train)).score(strip_labels(test))
        rows[name] = evaluate(scores, labels)
        print(f"  {name}: done")

    results = pd.DataFrame(rows).T.sort_values("auprc", ascending=False).round(3)

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    stem = Path(args.csv).stem
    results.to_csv(out / f"{stem}_results.csv")
    (out / f"{stem}_results.md").write_text(
        f"# Benchmark results: {stem}\n\n"
        f"Temporal split, train_frac={args.train_frac}. "
        f"Test: {len(labels)} traces, {n_anom} anomalous.\n\n"
        + results.to_markdown() + "\n")
    print(f"\n{results.to_string()}\n\nWrote {out}/{stem}_results.{{csv,md}}")


if __name__ == "__main__":
    main()
