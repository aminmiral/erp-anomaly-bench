# Benchmark results: p2p_small

Temporal split, train_frac=0.7. Test: 18 traces, 2 anomalous.

|              |   roc_auc |   auprc |   auprc:duplicate_invoice |   auprc:price_overbill |
|:-------------|----------:|--------:|--------------------------:|-----------------------:|
| audit_rules  |     1     |   1     |                         1 |                  1     |
| ocsvm        |     1     |   1     |                         1 |                  1     |
| lof          |     1     |   1     |                         1 |                  1     |
| iforest      |     0.969 |   0.833 |                         1 |                  0.5   |
| variant_freq |     0.75  |   0.556 |                         1 |                  0.059 |
| markov_nll   |     0.75  |   0.556 |                         1 |                  0.059 |
