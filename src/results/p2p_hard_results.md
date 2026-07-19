# Benchmark results: p2p_hard

Temporal split, train_frac=0.7. Test: 93 traces, 17 anomalous.

|              |   roc_auc |   auprc |   auprc:after_hours |   auprc:duplicate_invoice |   auprc:price_overbill |   auprc:skipped_receipt |   auprc:split_purchase |   auprc:subtle_overbill |
|:-------------|----------:|--------:|--------------------:|--------------------------:|-----------------------:|------------------------:|-----------------------:|------------------------:|
| iforest      |     0.687 |   0.536 |               0.043 |                         1 |                  1     |                       1 |                  0.099 |                   0.393 |
| lof          |     0.574 |   0.482 |               0.194 |                         1 |                  1     |                       1 |                  0.064 |                   0.074 |
| ocsvm        |     0.575 |   0.471 |               0.028 |                         1 |                  1     |                       1 |                  0.091 |                   0.113 |
| audit_rules  |     0.647 |   0.423 |               0.026 |                         1 |                  1     |                       1 |                  0.095 |                   0.026 |
| variant_freq |     0.618 |   0.375 |               0.026 |                         1 |                  0.013 |                       1 |                  0.095 |                   0.026 |
| markov_nll   |     0.618 |   0.375 |               0.026 |                         1 |                  0.013 |                       1 |                  0.095 |                   0.026 |
