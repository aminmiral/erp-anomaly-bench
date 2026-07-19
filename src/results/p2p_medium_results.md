# Benchmark results: p2p_medium

Temporal split, train_frac=0.7. Test: 75 traces, 8 anomalous.

|              |   roc_auc |   auprc |   auprc:duplicate_invoice |   auprc:price_overbill |   auprc:self_approval |   auprc:skipped_receipt |
|:-------------|----------:|--------:|--------------------------:|-----------------------:|----------------------:|------------------------:|
| audit_rules  |      1    |   1     |                         1 |                  1     |                 1     |                       1 |
| iforest      |      1    |   1     |                         1 |                  1     |                 1     |                       1 |
| ocsvm        |      1    |   1     |                         1 |                  1     |                 1     |                       1 |
| lof          |      1    |   1     |                         1 |                  1     |                 1     |                       1 |
| variant_freq |      0.75 |   0.553 |                         1 |                  0.029 |                 0.029 |                       1 |
| markov_nll   |      0.75 |   0.553 |                         1 |                  0.029 |                 0.029 |                       1 |
