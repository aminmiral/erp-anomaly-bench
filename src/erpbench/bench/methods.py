"""Detector registry: every method fits on unlabeled train traces and returns
one anomaly score per test trace (higher = more suspicious).

Families mirror the standard taxonomy in the business-process anomaly
detection literature (cf. the BPAD survey, IEEE TKDE 2025):

- control-flow methods read only the activity sequence (variant frequency,
  Markov transitions);
- multi-perspective methods read engineered features over all attributes
  (amounts, actors, durations) with standard outlier models;
- the rule baseline encodes domain audit controls and needs no training.

Deep sequence models from the BPAD suite (DAE, BINet, GAMA, ...) plug in as
additional entries here once torch is available; the interface is the same.
"""

from __future__ import annotations

import math

import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

from ..detect import trace_features


def _variants(df: pd.DataFrame) -> pd.Series:
    return df.groupby("case_id")["activity"].agg(tuple)


class VariantFrequency:
    """Control-flow 'Naive' baseline: a trace is anomalous if its activity
    sequence (variant) was rare or unseen in training."""

    def fit(self, train: pd.DataFrame):
        counts = _variants(train).value_counts()
        self.freq = (counts / counts.sum()).to_dict()
        return self

    def score(self, test: pd.DataFrame) -> pd.Series:
        return _variants(test).map(lambda v: 1.0 - self.freq.get(v, 0.0))


class MarkovNLL:
    """Control-flow likelihood baseline: mean negative log-probability of the
    trace's activity transitions under a first-order Markov model with
    Laplace smoothing."""

    def fit(self, train: pd.DataFrame):
        transitions = {}
        self.alphabet = set(train["activity"]) | {"<END>"}
        for variant in _variants(train):
            seq = ["<START>", *variant, "<END>"]
            for a, b in zip(seq, seq[1:]):
                transitions.setdefault(a, {}).setdefault(b, 0)
                transitions[a][b] += 1
        self.transitions = transitions
        return self

    def _nll(self, variant: tuple) -> float:
        seq = ["<START>", *variant, "<END>"]
        total = 0.0
        for a, b in zip(seq, seq[1:]):
            outs = self.transitions.get(a, {})
            p = (outs.get(b, 0) + 1) / (sum(outs.values()) + len(self.alphabet))
            total -= math.log(p)
        return total / (len(seq) - 1)

    def score(self, test: pd.DataFrame) -> pd.Series:
        return _variants(test).map(self._nll)


class FeatureOutlier:
    """Multi-perspective baseline: engineered per-trace features scored by a
    standard novelty-detection model. `features` selects the feature scope —
    single-trace (default) or context-aware."""

    def __init__(self, estimator, features=trace_features):
        self.estimator = estimator
        self.features = features
        self.scaler = StandardScaler()

    def fit(self, train: pd.DataFrame):
        X = self.features(train)
        self.columns = X.columns
        self.estimator.fit(self.scaler.fit_transform(X))
        return self

    def score(self, test: pd.DataFrame) -> pd.Series:
        X = self.features(test)[self.columns]
        return pd.Series(-self.estimator.score_samples(self.scaler.transform(X)),
                         index=X.index)


class AuditRules:
    """Domain rule baseline (same controls as the erpbench_audit Odoo module).
    Score = number of violated audit controls; no training required."""

    def fit(self, train: pd.DataFrame):
        return self

    def score(self, test: pd.DataFrame) -> pd.Series:
        scores = {}
        for case_id, g in test.groupby("case_id"):
            acts = g["activity"]
            po = g.loc[acts == "Create PO", "amount"]
            bills = g.loc[acts == "Post Vendor Bill", "amount"]
            creator = g.loc[acts == "Create PO", "actor"]
            approver = g.loc[acts == "Approve PO", "actor"]
            violations = 0
            violations += int((acts == "Post Vendor Bill").sum() > 1)
            violations += int(len(po) > 0 and len(bills) > 0
                              and bills.iloc[0] > po.iloc[0] * 1.02)
            violations += int((acts == "Pay Vendor Bill").any()
                              and not (acts == "Receive Goods").any())
            violations += int(len(creator) > 0 and len(approver) > 0
                              and creator.iloc[0] == approver.iloc[0])
            scores[case_id] = float(violations)
        return pd.Series(scores)


def registry() -> dict[str, object]:
    from .features import context_features
    entries = {
        "audit_rules": AuditRules(),
        "variant_freq": VariantFrequency(),
        "markov_nll": MarkovNLL(),
        "iforest": FeatureOutlier(IsolationForest(n_estimators=200, random_state=0)),
        "lof": FeatureOutlier(LocalOutlierFactor(n_neighbors=10, novelty=True)),
        "ocsvm": FeatureOutlier(OneClassSVM(nu=0.1, gamma="scale")),
        "iforest_ctx": FeatureOutlier(
            IsolationForest(n_estimators=200, random_state=0),
            features=context_features),
        "lof_ctx": FeatureOutlier(
            LocalOutlierFactor(n_neighbors=10, novelty=True),
            features=context_features),
        "ocsvm_ctx": FeatureOutlier(
            OneClassSVM(nu=0.1, gamma="scale"),
            features=context_features),
    }
    try:  # deep single-trace methods require torch (CPU build is fine)
        from .deep import BINetLite, DAEDetector
        entries["dae"] = DAEDetector()
        entries["binet_lite"] = BINetLite()
    except ImportError:
        pass
    return entries
