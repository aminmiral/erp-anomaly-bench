# erp-anomaly-bench

**A labeled event-log dataset and benchmark for anomaly detection in ERP business processes.**

Public research in business-process anomaly detection lacks realistic, labeled ERP
datasets — real logs are confidential, and purely synthetic generators ignore how an
actual ERP constrains behavior. This project generates event logs by driving a real
(clean, local, demo-only) Odoo instance through simulated procure-to-pay cases, injecting
known fraud/error typologies at controlled rates. Because every anomaly is injected,
every label is ground truth — at trace level and event level.

Detection methods are then benchmarked against the dataset, building on the
[BPAD](https://github.com/guanwei49/BPAD) suite (IEEE TKDE 2025).

## Anomaly typology

**Easy tier** — a single document is visibly wrong; document-level audit rules catch these:

| Type | Kind | Real-world meaning |
|---|---|---|
| `skipped_receipt` | control-flow | billed & paid with no goods receipt (3-way-match violation) |
| `price_overbill` | data | vendor bill price inflated 15–60% vs. the PO price |
| `duplicate_invoice` | control-flow/data | the same PO billed and paid twice |
| `self_approval` | role | requester approves their own PO (segregation-of-duties violation) |

**Hard tier** — no single document is wrong; the signal is subtle or spans traces:

| Type | Kind | Real-world meaning |
|---|---|---|
| `split_purchase` | cross-trace | one buy split into 2–3 POs, each just under the approval threshold; every individual trace is a normal flow |
| `subtle_overbill` | data | 1–3% skim, deliberately overlapping the ±2% legitimate billing variation on normal traces |
| `after_hours` | timing | approval/billing/payment at 1–5 AM (normal activity follows a Mon–Fri 9–18 business-hours clock) |

Full component/wiring walkthrough: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Paper-style report of the dataset, protocol, and findings: [docs/PAPER.md](docs/PAPER.md).

## Design notes

- **The driver owns time.** Odoo stamps records with the wall clock, so the simulation
  keeps its own virtual clock; event-log timestamps come from the driver, which is the
  single source of truth for the log.
- **Odoo provides realism, not data.** The instance is a stock Community Edition with
  no demo data and nothing sensitive; its role is to enforce the real ERP state machine
  so generated traces are structurally realistic. Master data (vendors, products) is
  generated.
- **Reproducible by construction.** `docker compose up` + a config with a fixed seed
  regenerates the exact dataset.

## Quickstart

```bash
docker compose up -d          # Odoo 17 CE + Postgres; first run initializes db "erpbench"
# wait until localhost:8069 responds, then set the admin password to "admin"
# (or adjust configs/p2p_small.yaml)

python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
cd src && python -m erpbench.generate ../configs/p2p_small.yaml
```

Output: `data/p2p_small.csv` — one row per event with `case_id`, `activity`,
`timestamp`, `actor`, `role`, `amount`, `doc_ref`, `anomaly_type` (event-level label)
and `trace_label` (trace-level label).

## Baseline results (v2 dataset: `p2p_hard`, 309 traces, 7 typologies)

Temporal split (train 216 / test 93, 17 anomalous). AUPRC per anomaly type;
~0.02–0.10 is random-guessing territory at these base rates.

| method | overall | dup_invoice | skipped_receipt | overbill | subtle_overbill | split_purchase | after_hours |
|---|---|---|---|---|---|---|---|
| iforest | 0.536 | 1.0 | 1.0 | 1.000 | **0.393** | 0.099 | 0.043 |
| lof | 0.482 | 1.0 | 1.0 | 1.000 | 0.074 | 0.064 | **0.194** |
| ocsvm | 0.471 | 1.0 | 1.0 | 1.000 | 0.113 | 0.091 | 0.028 |
| audit_rules | 0.423 | 1.0 | 1.0 | 1.000 | 0.026 | 0.095 | 0.026 |
| variant_freq | 0.375 | 1.0 | 1.0 | 0.013 | 0.026 | 0.095 | 0.026 |
| markov_nll | 0.375 | 1.0 | 1.0 | 0.013 | 0.026 | 0.095 | 0.026 |
| dae (deep) | 0.479 | 1.0 | 1.0 | 0.024 | 0.026 | 0.129 | 0.258 |
| binet_lite (deep) | 0.443 | 1.0 | 1.0 | 0.250 | 0.027 | 0.124 | 0.020 |

Adding **context features** (`*_ctx` methods: same outlier models over time-of-day
features plus ±14-day requester×vendor cross-trace windows — see
`erpbench/bench/features.py`) changes the picture:

| method | overall | subtle_overbill | split_purchase | after_hours |
|---|---|---|---|---|
| **iforest_ctx** | **0.947** | 0.303 | **0.970** | **1.000** |
| ocsvm_ctx | 0.797 | **0.530** | 0.647 | 0.325 |
| lof_ctx | 0.615 | 0.268 | 0.110 | 1.000 |

Findings:

1. **The easy tier is solved** — document-level rules and feature outlier models
   reach 1.0 on anomalies where a single document is visibly wrong.
2. **Control-flow methods are structurally blind to data/role anomalies**
   (0.013 on crude overbilling): the activity sequence is normal, only an
   amount or actor is wrong.
3. **The hard tier defeats every single-trace method** — cross-trace fraud
   (`split_purchase`), timing fraud (`after_hours`), and in-tolerance skims
   (`subtle_overbill`) all score at or near random for every baseline.
4. **Feature scope, not model choice, closes most of the gap**: the same
   Isolation Forest goes 0.099 → 0.970 on `split_purchase` and 0.043 → 1.000
   on `after_hours` once it can see context.
5. **Two open problems remain**: `subtle_overbill` resists everything (best
   0.530 — skims inside legitimate billing variation may set a detection
   floor), and context has a cost — `iforest_ctx` drops from 1.000 to 0.200
   on crude overbilling as added features dilute the bill-to-PO signal,
   pointing at per-type specialization/ensembling as future work.
6. **Feature scope beats model capacity.** Deep single-trace sequence models
   (`dae`, `binet_lite` — autoencoder and next-event-prediction families from
   the BPAD survey, implemented in `erpbench/bench/deep.py`) land mid-pack:
   perfect on sequence-changing frauds, mostly blind to the hard tier, and
   ~0.5 overall AUPRC behind a plain Isolation Forest that can see
   cross-trace context. Caveat: lite implementations, 216 training traces —
   the claim is scoped to this benchmark, not deep methods at large.

## Roadmap

- [x] v0: procure-to-pay driver + 4 anomaly types + CSV export
- [x] In-Odoo rule auditor (`addons/erpbench_audit`) as demo layer + rule baseline
- [x] Benchmark harness (`erpbench.bench`): 6 baseline detectors, temporal
      leakage-safe splits, per-anomaly-type AUPRC — `python -m erpbench.bench.run data/<log>.csv`
- [x] Deep single-trace methods (`dae`, `binet_lite` — DAE/BINet families, torch)
- [ ] Full-scale BPAD methods (GAMA, WAKE, ...) via the upstream repo
- [ ] Real per-role Odoo users so role anomalies are enforced by the ERP itself
- [ ] More typologies: split purchases under approval thresholds, off-hours activity
- [ ] XES export (pm4py) + dataset variants (sizes / anomaly rates)
- [ ] Paper-style report
