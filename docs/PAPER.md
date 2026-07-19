# An ERP-Grounded Benchmark for Business-Process Anomaly Detection: When Feature Scope Beats Model Capacity

**Author:** Amin Miral · github.com/aminmiral

*Draft v0.1 — code, data generator, and all results:*
*https://github.com/aminmiral/erp-anomaly-bench*

---

## Abstract

Anomaly detection in business-process event logs is an active research area,
but public datasets are scarce: real ERP logs are confidential, and purely
synthetic generators ignore the constraints a real ERP imposes on behavior. We
present a reproducible pipeline that generates labeled procure-to-pay event
logs by driving a real (containerized, demo-only) Odoo 17 instance through
simulated business cases, injecting seven fraud typologies at controlled
rates — four "easy" types in which a single document is visibly wrong, and
three "hard" types in which no individual document is wrong (threshold-dodging
split purchases, 1–3% skims inside legitimate billing variation, and off-hours
processing). Benchmarking eleven detectors under a leakage-safe temporal
protocol yields three findings. (1) The easy tier is solved: document-level
audit rules and standard outlier models reach perfect average precision.
(2) The hard tier defeats every single-trace method, including two deep
sequence models from established families (DAE, BINet-style), which score at
or near random on it. (3) Widening the *feature scope* — time-of-day features
and ±14-day requester×vendor context windows — lets a plain Isolation Forest
recover most of the gap (overall AUPRC 0.536 → 0.947; split purchases
0.099 → 0.970), decisively outperforming the deep models. On this benchmark,
what a detector can see matters more than how sophisticated it is. One
typology (subtle overbilling) resists all methods, and we release it as the
benchmark's open challenge.

## 1. Introduction

Enterprise resource planning (ERP) systems record every step of a company's
operational processes — purchase orders, approvals, goods receipts, invoices,
payments — as event data. Occupational fraud typically hides inside this
data: duplicate invoices, inflated bills, purchases split to evade approval
thresholds. Detecting it automatically is a natural machine-learning task,
and a growing literature addresses anomaly detection on business-process
event logs [1, 2].

The field, however, has a data problem. Companies do not publish their ERP
logs, let alone logs with labeled fraud. Public event-log collections (e.g.,
the BPI Challenge logs [3]) are real but unlabeled; existing benchmarks
therefore inject artificial noise into them or use fully synthetic generators,
neither of which reflects how a real ERP constrains what can happen. A recent
systematic review explicitly lists the lack of standard labeled benchmark
datasets as an open gap [2].

My route into this problem came through security rather than process mining.
I had intended to work in cybersecurity but began my career as a backend
developer at an Odoo services company — and found that the two interests
meet inside the ERP: fraud in business processes is an insider threat, the
event log is the audit trail it hides in, and the natural place to detect it
is the ERP itself. The audit module accompanying this benchmark grew from
that idea; the benchmark grew from discovering that the labeled data needed
to evaluate such detection publicly did not exist.

**Contributions.**

1. **A generation pipeline, not just a dataset.** A driver plays simulated
   procure-to-pay cases against a stock Odoo 17 instance over RPC, so traces
   respect a real ERP's state machine, while the driver — which is the party
   injecting the fraud — emits an event log with ground-truth labels at trace
   *and* event level. Datasets regenerate exactly from a seed.
2. **A two-tier anomaly typology.** Four easy types (single document visibly
   wrong) and three hard types (no single document wrong: cross-trace,
   sub-tolerance, or timing-based). The hard tier is calibrated against
   deliberately realistic normal behavior: business-hours activity and
   legitimate ±2% billing variation.
3. **A leakage-safe benchmark of eleven detectors** across four families
   (audit rules, control-flow, feature-based outlier models, deep sequence
   models), with per-typology results, plus a controlled experiment isolating
   the effect of feature scope from model choice.

## 2. Related Work

**Business-process anomaly detection.** Guan et al. [1] survey the field and
release BPAD, a benchmark of 16 methods (14 unsupervised, 2 weakly
supervised) evaluated on 32 synthetic and 19 real-life logs; anomalies in the
synthetic logs are injected as generic control-flow perturbations (skips,
reworks, reorderings). Ko and Comuzzi [2] systematically review detection
techniques for event logs and identify the shortage of labeled benchmark
data and the narrow attribute coverage of existing methods as open issues.
Our work is complementary: rather than new detection methods, we contribute
a data generator whose anomalies are *domain-defined frauds* (three-way-match
violations, threshold splitting) rather than generic perturbations.

**Deep methods.** Nolle et al. introduced autoencoder-based detection on
business processes and BINet [4, 5], a multivariate next-event predictor
whose prediction error localizes anomalies. Our `dae` and `binet_lite`
implementations follow these families at reduced scale (Section 5).

**Synthetic log generation.** Process-log generators such as PLG2 [6]
synthesize logs from process models. Our approach differs in provenance: we
do not simulate a model of a process — we execute the process in the ERP
itself, inheriting its validations, document flows, and side effects (stock
moves, accounting entries), then read the log off the driver.

**Fraud analytics.** Classic procurement-fraud controls (three-way matching,
segregation of duties, approval thresholds) are standard in the audit
literature and are precisely the controls our easy tier violates one at a
time — and our hard tier is designed to slip past.

## 3. The Dataset

### 3.1 Generation pipeline

A Python driver connects to a containerized Odoo 17 Community instance
(initialized with purchasing, inventory, and accounting apps and no demo
data) and plays procure-to-pay cases: create purchase order → approve →
receive goods → post vendor bill → pay. Every step is a real RPC call that
Odoo validates. Master data (8 vendors, 15 products) is generated; simulated
actors carry roles (requester, manager, accountant).

Two design rules matter:

- **The driver owns the log.** Odoo stamps records with the wall clock, so
  the driver keeps a virtual clock (random 10-minute-to-2-day steps) and is
  the single writer of the event log — one event per business action, with
  case id, activity, timestamp, actor, role, amount, document reference, and
  vendor. Because the driver is also the party committing each fraud, labels
  are ground truth by construction.
- **Normal must be realistic before abnormal can be meaningful.** Normal
  steps snap to business hours (Mon–Fri 9–18), and 30% of normal bills carry
  legitimate ±2% deviations from the PO. Without these, timing anomalies and
  subtle skims would be trivially separable.

### 3.2 Anomaly typology

**Easy tier** — a single document is visibly wrong:

| Type | Violation |
|---|---|
| `skipped_receipt` | bill paid, goods never received (three-way-match violation) |
| `price_overbill` | bill 15–60% above the PO |
| `duplicate_invoice` | same PO billed and paid twice |
| `self_approval` | requester approves their own PO (segregation of duties) |

**Hard tier** — no single document is wrong:

| Type | Violation |
|---|---|
| `split_purchase` | one purchase split into 2–3 POs, each just under the 5,000 approval threshold (tax-inclusive), same requester and vendor, days apart; every individual trace is a normal flow |
| `subtle_overbill` | 1–3% skim, overlapping the legitimate ±2% variation band |
| `after_hours` | approval/billing/payment at 1–5 AM |

Labels exist at trace level and, where the anomaly is localized, at event
level — finer granularity than most public alternatives.

### 3.3 The benchmark instance

The evaluated dataset (`p2p_hard`, seed 11) contains **309 traces / 1,548
events**, of which 44 traces (14.2%) are anomalous across the seven types.
It regenerates exactly from the committed config.

## 4. Benchmark Protocol

- **Temporal split.** Train on the earliest 70% of traces (216), test on the
  latest 30% (93; 17 anomalous, 18.3%). Random splits are deliberately not
  supported: they leak future behavior into training and inflate results.
- **Unsupervised regime.** Detectors see the training traces with all label
  columns stripped, and must output one anomaly score per test trace.
  Training data contains anomalies at the natural rate (no cleaning), as in
  deployment.
- **Metrics.** ROC-AUC and AUPRC overall, and AUPRC per anomaly type
  (that type's test traces vs. all normal test traces). At the observed base
  rates, AUPRC ≈ 0.02–0.10 corresponds to random guessing. The per-type view
  is where methods actually differ.

## 5. Detectors

Four families, eleven entries; all implement `fit(train) / score(test)`:

- **Domain rules** (`audit_rules`): duplicate posted bills per PO reference;
  bill > PO total beyond 2%; paid without validated receipt; requester ==
  approver. No training.
- **Control-flow** (`variant_freq`, `markov_nll`): activity-sequence variant
  rarity; mean negative log-likelihood under a smoothed first-order Markov
  model.
- **Feature-based** (`iforest`, `lof`, `ocsvm`): per-trace engineered
  features (event/bill/payment counts, receipt flag, bill-to-PO ratio,
  creator==approver, duration) scored by Isolation Forest [7], Local Outlier
  Factor [8], and One-Class SVM [9].
  The **context variants** (`*_ctx`) run the *same estimators* over a wider
  scope: fraction of off-hours and weekend events, own PO's proximity to the
  approval threshold, and counts/summed-amounts of same-requester×vendor
  traces within a ±14-day window (modeling a periodic batch audit). Any
  baseline-vs-context difference is therefore attributable to feature scope,
  not model choice.
- **Deep single-trace** (`dae`, `binet_lite`): an autoencoder over the
  encoded padded trace (reconstruction error as score) and a GRU next-event
  predictor conditioned on event attributes (mean NLL as score), following
  the families of [4, 5]. Both see per-event attributes (activity,
  log-amount, hour, weekday, actor) but no cross-trace context.
  Deterministic seeds; CPU-scale.

## 6. Results

AUPRC on `p2p_hard` (test: 93 traces, 17 anomalous). Random ≈ 0.02–0.10 per
type. Full table in `results/p2p_hard_results.md`.

| method | overall | dup_inv | skip_rcpt | overbill | subtle_ovb | split | after_hrs |
|---|---|---|---|---|---|---|---|
| **iforest_ctx** | **0.947** | 1.00 | 1.00 | 0.200 | 0.303 | **0.970** | **1.000** |
| ocsvm_ctx | 0.797 | 0.75 | 0.45 | 0.500 | **0.530** | 0.647 | 0.325 |
| lof_ctx | 0.615 | 1.00 | 1.00 | 1.000 | 0.268 | 0.110 | 1.000 |
| iforest | 0.536 | 1.00 | 1.00 | 1.000 | 0.393 | 0.099 | 0.043 |
| lof | 0.482 | 1.00 | 1.00 | 1.000 | 0.074 | 0.064 | 0.194 |
| dae | 0.479 | 1.00 | 1.00 | 0.024 | 0.026 | 0.129 | 0.258 |
| ocsvm | 0.471 | 1.00 | 1.00 | 1.000 | 0.113 | 0.091 | 0.028 |
| binet_lite | 0.443 | 1.00 | 1.00 | 0.250 | 0.027 | 0.124 | 0.020 |
| audit_rules | 0.423 | 1.00 | 1.00 | 1.000 | 0.026 | 0.095 | 0.026 |
| variant_freq | 0.375 | 1.00 | 1.00 | 0.013 | 0.026 | 0.095 | 0.026 |
| markov_nll | 0.375 | 1.00 | 1.00 | 0.013 | 0.026 | 0.095 | 0.026 |

**Finding 1 — the easy tier is solved.** All families reach 1.0 on
duplicates and skipped receipts; rules and feature models also solve crude
overbilling. Control-flow methods are structurally blind to data/role
anomalies (0.013 on overbilling): the activity sequence is normal, only an
amount or an actor is wrong.

**Finding 2 — the hard tier defeats every single-trace method.** Best
single-trace scores: split purchases 0.129, subtle overbilling 0.393,
after-hours 0.258 — mostly within random range. This holds for the deep
models as much as the shallow ones: `dae` and `binet_lite` land mid-pack
overall (0.479 / 0.443), unable to see across traces or inside the
legitimate-variation band.

**Finding 3 — feature scope, not model capacity, closes the gap.** The same
Isolation Forest moves 0.099 → 0.970 on split purchases and 0.043 → 1.000 on
after-hours when given context features, reaching 0.947 overall — roughly
0.5 AUPRC ahead of both deep models. The estimator is identical in both
rows; only its inputs changed.

**Finding 4 — context is not free.** `iforest_ctx` falls from 1.000 to 0.200
on crude overbilling: the added context features dilute the bill-to-PO
signal. No single feature scope dominates all typologies, suggesting
per-type specialization or ensembling across scopes as future work.

**Finding 5 — one problem stays open.** Subtle overbilling resists every
method (best 0.530, `ocsvm_ctx`). Skims inside legitimate billing variation
may impose a detection floor at the single-trace level; per-vendor
longitudinal modeling is the natural next attack.

## 7. Limitations

- **Synthetic provenance.** The data is generated, not observed. ERP
  execution constrains it structurally, but actor behavior follows our
  simulation policies; a motivated critic can argue the typologies mirror the
  injectors. We mitigate by making normal behavior deliberately noisy
  (billing variation, business-hours jitter) and by publishing the generator
  so others can add typologies we did not anticipate.
- **Diagnostic, not blind, context features.** The context features were
  designed knowing the hard typologies exist (though not their parameters or
  which traces carry them). The claim they support is diagnostic — the
  failures are feature-scope failures — not that such features would be
  discovered blind. The deep models make the complementary point: attribute
  access without the right scope did not suffice.
- **Scale and scope.** One process (procure-to-pay), one simulated
  organization, 309 traces, lite deep models trained on 216 traces. Findings
  are scoped to this benchmark; full-scale BPAD methods [1] and larger logs
  are future work.
- **Batch-audit window.** Cross-trace features use a symmetric ±14-day
  window, modeling periodic audit rather than strict online detection.

## 8. Conclusion and Future Work

We contribute a reproducible ERP-grounded generator for labeled
business-process fraud data, a two-tier typology calibrated against
realistic normal behavior, and an eleven-method benchmark whose headline
result is that feature scope beats model capacity: hard-tier frauds that
defeat deep sequence models yield almost entirely to a simple outlier model
once it can see time and cross-trace context. Subtle overbilling remains
open. Future work: scope-ensembles, per-vendor longitudinal models for
sub-tolerance skims, additional processes (order-to-cash, expenses),
per-role ERP users so role anomalies are enforced by the system itself, and
evaluation of the full BPAD method suite.

## References

[1] W. Guan, J. Cao, Y. Zhao, G. Gu, W. Qian. "Survey and Benchmark of
Anomaly Detection in Business Processes." *IEEE Transactions on Knowledge
and Data Engineering*, vol. 37, no. 1, pp. 493–512, 2025.
Code: https://github.com/guanwei49/BPAD

[2] J. Ko, M. Comuzzi. "A Systematic Review of Anomaly Detection for
Business Process Event Logs." *Business & Information Systems Engineering*,
2023.

[3] Business Process Intelligence (BPI) Challenge event logs, 4TU Centre for
Research Data. https://data.4tu.nl

[4] T. Nolle, A. Seeliger, M. Mühlhäuser. "BINet: Multivariate Business
Process Anomaly Detection Using Deep Learning." *International Conference on
Business Process Management (BPM)*, 2018.

[5] T. Nolle, S. Luettgen, A. Seeliger, M. Mühlhäuser. "Analyzing Business
Process Anomalies Using Autoencoders." *Machine Learning*, 2018.

[6] A. Burattin. "PLG2: Multiperspective Process Randomization with Online
and Offline Simulations." *BPM Demo Track*, 2016.

[7] F. T. Liu, K. M. Ting, Z.-H. Zhou. "Isolation Forest." *IEEE
International Conference on Data Mining (ICDM)*, 2008.

[8] M. M. Breunig, H.-P. Kriegel, R. T. Ng, J. Sander. "LOF: Identifying
Density-Based Local Outliers." *ACM SIGMOD*, 2000.

[9] B. Schölkopf, J. C. Platt, J. Shawe-Taylor, A. J. Smola,
R. C. Williamson. "Estimating the Support of a High-Dimensional
Distribution." *Neural Computation*, 2001.
