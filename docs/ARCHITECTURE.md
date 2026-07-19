# Architecture

The project is a factory for labeled ERP fraud data, plus the things that consume it.
One side **generates** a realistic event log with known anomalies injected; the other
side **detects** — a Python ML baseline and an in-Odoo audit module. Everything is
wired through two channels: JSON-RPC calls into Odoo (port 8069) and the CSV event
log on disk.

```
┌─────────────────────── Docker ───────────────────────┐
│  ┌────────────┐            ┌───────────────────────┐ │
│  │ Postgres 15 │◄──────────│  Odoo 17 CE           │ │
│  │ (db-data)   │  SQL      │  purchase/stock/acct  │ │
│  └────────────┘            │  + erpbench_audit ◄───┼─┼── mounted from ./addons
│                            └──────────┬────────────┘ │
└───────────────────────────────────────┼──────────────┘
                                :8069   │ JSON-RPC
                 ┌──────────────────────┴───────────┐
                 │  Simulation driver (src/erpbench)│
                 │  clock ─ scenarios ─ injectors   │
                 └──────────────┬───────────────────┘
                                ▼
                     data/p2p_small.csv  (events + labels)
                                ▼
                     detect.py (IsolationForest baseline)
                     [next: BPAD benchmark harness]
```

## Infrastructure (`docker-compose.yml`)

Two services:

- **Postgres 15** — Odoo's database, persisted in the `db-data` volume so data
  survives restarts.
- **Odoo 17 Community** — the real ERP, reached by both browser and scripts through
  the single doorway of port 8069. Startup auto-creates the `erpbench` database with
  purchase, inventory, and accounting installed and **no demo data**: Odoo's role is
  to enforce the real ERP state machine, not to supply data. The
  `./addons:/mnt/extra-addons` mount is how the custom audit module gets into the
  container — edit the module on the host, restart the container, Odoo sees the new
  code. (Python changes need a restart; view/XML changes need a module upgrade.)

## Generation layer (`src/erpbench/`)

| Module | Job |
|---|---|
| `eventlog.py` | Source of truth for the log |
| `odoo_client.py` | RPC connection + generated master data |
| `scenarios/procure_to_pay.py` | The business process + anomaly injection |
| `generate.py` | Config-driven conductor (CLI entry point) |

**`eventlog.py`.** `SimClock` is a virtual clock advancing by random
10-minutes-to-2-days steps — needed because Odoo stamps records with the wall clock,
and a simulated year of history must not collapse into one afternoon. `Event` is one
business action (case ID, activity, timestamp, actor, role, amount, doc ref,
event-level label); `EventLog` accumulates events, tracks the trace-level label per
case, and writes the CSV. Design rule: **the driver, not Odoo, owns the log** — the
code that causes each anomaly is the only party that knows the ground truth.

**`odoo_client.py`.** Wraps `odoorpc`, logs in, and creates master data (fake
vendors, fake products with random costs). Products are deliberately configured as
billable-on-*ordered*-quantities: that is the ERP configuration under which
skipped-receipt fraud is possible at all.

**`scenarios/procure_to_pay.py`.** One class per business process.
`run(case_id, mode)` plays a full purchase — create PO → approve → receive → bill →
pay — where every step is a real RPC call that Odoo validates, plus one `Event`
recorded on the virtual clock. `mode` is the injection switch:

| Mode | Deviation | Label granularity |
|---|---|---|
| `skipped_receipt` | receive step never happens | trace only (anomaly is a *missing* event) |
| `price_overbill` | bill priced 15–60% above PO | the bill event |
| `duplicate_invoice` | bill posted & paid twice | the second bill+payment events |
| `self_approval` | requester approves own PO | the approval event |
| `split_purchase` | one buy split into 2–3 POs just under the approval threshold (tax-inclusive), same requester+vendor, days apart; emitted as sibling traces `<case>-S1..S3` | trace only (every event is individually normal) |
| `subtle_overbill` | bill 1–3% above PO, overlapping the ±2% legitimate variation normal bills carry | the bill event |
| `after_hours` | approval/bill/payment at 1–5 AM under a business-hours clock | the off-hours events |

The hard tier changes normal behavior too: the `SimClock` snaps normal steps to
Mon–Fri 9–18 (so off-hours means something), and 30% of normal bills legitimately
deviate up to ±2% from the PO (so a small skim has cover to hide in). Datasets
generated before/after this change are not comparable — treat them as v1/v2.

Because the driver *causes* each anomaly, labels are ground truth by construction —
at trace level and event level, which is finer than most public datasets offer.

**`generate.py`.** Reads a YAML config (seed, start date, case count, anomaly rate,
output path, connection), seeds a single `random.Random`, and loops cases,
surviving individual failures. Same config + fresh instance ⇒ identical dataset:
reproducibility comes from the seed, not from shipping data.

### Odoo 17 integration notes (learned the hard way)

- `stock.picking.action_set_quantities_to_reservation()` no longer exists in 17.0;
  receipts are validated by writing `quantity` + `picked` on each move, then
  `button_validate()`.
- `account.move` must never be `browse()`d via odoorpc: browse reads *all* fields,
  and 17's computed `tax_totals` contains frozendicts that fail JSON-RPC
  serialization. Targeted `execute_kw` calls (`create`, `action_post`,
  `read([fields])`) avoid it.
- PO lines need explicit `price_unit` (no vendor pricelists exist in a bare
  instance), and vendor bills are created directly as `account.move` records with
  `purchase_line_id` links — sidestepping `action_create_invoice`'s unserializable
  return value while modeling how a keyed-in duplicate bill happens in practice.

## Detection layer

**`detect.py` — ML baseline.** Aggregates each trace's raw events into features
(event counts, bill-to-PO ratio, has-receipt flag, creator==approver flag,
duration) and ranks traces with an unsupervised Isolation Forest. Labels are used
only *after* scoring, to evaluate the ranking (ROC-AUC / AUPRC). Current
near-perfect scores are expected and honest to report as such: the features mirror
the injected typologies. The benchmark's real question is how detectors fare on
subtler anomalies from raw sequences.

**`addons/erpbench_audit/` — in-ERP rule auditor.** A standard Odoo addon:

- `models/audit_finding.py` — the `audit.finding` model and `action_scan()`, which
  re-derives frauds **from Odoo's own documents**, never the CSV: duplicate posted
  bills per (vendor, PO reference); bills exceeding their PO total beyond 2%
  tolerance; paid bills on POs with no validated receipt.
- `views/audit_finding_views.xml` — list/form views, severity badges, the Rescan
  header button, the Audit menu.
- `security/ir.model.access.csv` — access rights (mandatory; without it the model
  is invisible to users).

Because the module is an independent second witness, its findings agreeing 1:1 with
the generator's labels is a genuine cross-validation of the dataset. It also serves
as the benchmark's **rule-based baseline**: anomaly types it catches perfectly are
"easy"; the ML methods must earn their keep on the types it structurally cannot see
(e.g. `self_approval` is invisible while all RPC runs as admin — see roadmap).

Quirk worth remembering: Odoo list-header buttons invoke their method **with the
current selection as an argument**, even on `@api.model` methods — hence
`action_scan(self, _selected_ids=None)`.

## End-to-end flow

1. `docker compose up -d` — Postgres starts; Odoo initializes `erpbench`.
2. `python -m erpbench.generate configs/p2p_small.yaml` — cases hammer the ERP over
   RPC while the event log accumulates → `data/p2p_small.csv`.
3. `python -m erpbench.detect data/p2p_small.csv` — ranked suspicion scores +
   metrics.
4. **Audit → Findings → Rescan** in the browser — the module independently
   re-derives the frauds from the database.

## Benchmark harness (`src/erpbench/bench/`)

- `data.py` — log loading, `strip_labels()` (what detectors may see), and the
  **temporal split**: train on the earliest traces, test on the latest, mirroring
  deployment. Random splits are deliberately not offered — they leak future
  behavior into training and inflate results.
- `methods.py` — the detector registry. Families mirror the BPAD survey taxonomy:
  control-flow methods reading only activity sequences (`variant_freq`,
  `markov_nll`), multi-perspective feature models (`iforest`, `lof`, `ocsvm`),
  and the domain `audit_rules` baseline (same controls as the Odoo module, no
  training). Every method implements `fit(train_df)` / `score(test_df) -> Series`;
  BPAD's deep sequence models plug in as further entries once torch is installed.
- `features.py` — the chapter-two answer to the hard tier: **context features**.
  Time context (fraction of events off-hours / on weekends) targets
  `after_hours`; cross-trace context (count, summed-amount-vs-threshold, and
  near-threshold count of same requester+vendor traces within a ±14-day
  window) targets `split_purchase`, which is invisible at single-trace scope
  by construction. The `*_ctx` registry entries are the same outlier models
  run over this wider scope — so any baseline-vs-context gap in the results
  is attributable to feature scope, not model choice. The symmetric window
  models a periodic batch audit; the approval threshold is domain knowledge,
  on the same footing as the audit baseline's three-way-match rule.
- `run.py` — CLI runner: fits and scores every method, reports overall ROC-AUC /
  AUPRC plus **AUPRC per anomaly type** (that type vs. normal), and writes
  `results/<log>_results.{csv,md}`. The per-type view is where methods actually
  differ — e.g. control-flow methods are structurally blind to `price_overbill`
  (the sequence is normal; only an amount is wrong).

- `deep.py` — deep single-trace detectors mirroring two BPAD-survey families:
  `dae` (autoencoder over the encoded padded trace; score = reconstruction
  error) and `binet_lite` (GRU next-activity predictor conditioned on event
  attributes; score = mean NLL of the observed continuation). Both see
  per-event attributes (activity, log-amount, hour, weekday, actor) but no
  cross-trace context. Registered automatically when torch is importable
  (CPU build suffices; traces are 4-7 events, training takes seconds).
  Headline result: both land mid-pack — feature scope beats model capacity
  on this benchmark.

## Roadmap

- Full-scale BPAD methods (GAMA, WAKE, ...) via the upstream repo, and
  non-lite versions of DAE/BINet at realistic data scale.
- Subtler typologies rule-based auditing can't catch: split purchases under
  approval thresholds, off-hours timing, collusion patterns.
- Real per-role Odoo users, so role anomalies exist in (or are blocked by) the
  ERP's own records.
- XES export via `pm4py` for process-mining interoperability.
- Scale configs (thousands of traces) and dataset variants by size / anomaly rate.
