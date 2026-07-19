"""CLI entry point: generate a labeled event log from a scenario config.

Usage:
    python -m erpbench.generate configs/p2p_small.yaml
"""

from __future__ import annotations

import random
import sys
from datetime import datetime
from pathlib import Path

import yaml

from .eventlog import EventLog, SimClock
from .odoo_client import OdooClient, make_master_data
from .scenarios.procure_to_pay import (ANOMALY_MODES, SPLIT_PURCHASE,
                                       ProcureToPayCase)


def main(config_path: str) -> None:
    cfg = yaml.safe_load(Path(config_path).read_text())
    rng = random.Random(cfg["seed"])

    client = OdooClient(**cfg.get("odoo", {}))
    vendors, products = make_master_data(client, rng)

    log = EventLog()
    clock = SimClock(datetime.fromisoformat(cfg["start_date"]), rng)
    scenario = ProcureToPayCase(client, log, clock, rng, vendors, products)

    n_cases = cfg["n_cases"]
    anomaly_rate = cfg["anomaly_rate"]
    modes = cfg.get("anomaly_modes", ANOMALY_MODES)
    for i in range(n_cases):
        case_id = f"P2P-{i:05d}"
        mode = rng.choice(modes) if rng.random() < anomaly_rate else "normal"
        try:
            if mode == SPLIT_PURCHASE:
                scenario.run_split(case_id)  # emits 2-3 traces, ids suffixed -S<n>
            else:
                scenario.run(case_id, mode)
        except Exception as e:  # noqa: BLE001 — one bad case must not kill a long run
            print(f"[warn] {case_id} ({mode}) failed: {e}", file=sys.stderr)
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{n_cases} cases done")

    out = log.save_csv(cfg["output"])
    df = log.to_dataframe()
    n_anomalous = (df.groupby("case_id")["trace_label"].first() != "normal").sum()
    print(f"Wrote {len(df)} events, {df['case_id'].nunique()} traces "
          f"({n_anomalous} anomalous) -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
