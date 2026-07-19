"""Deep single-trace detectors, mirroring two families from the BPAD survey:

- ``DAEDetector`` — autoencoder over the (padded) encoded trace; anomaly
  score = reconstruction error. Family of Nolle et al.'s DAE.
- ``BINetLite`` — recurrent next-event predictor; anomaly score = mean
  negative log-likelihood of each observed next activity given the prefix
  and the event attributes. Family of BINet.

Both read one trace at a time — activities plus per-event attributes
(log-amount, hour, weekday, actor) — but no cross-trace context. That scope
limit is the point: the benchmark asks whether deep sequence models can see
what single-trace feature models cannot.

Training is deterministic (fixed torch seed) and CPU-sized: traces here are
4-7 events, so both models train in seconds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from torch import nn

PAD = 0  # activity index reserved for padding


class TraceEncoder:
    """df -> (activity index tensor [n, L], attribute tensor [n, L, 4],
    mask [n, L], case_ids). Vocabulary and attribute scaling fit on train."""

    def fit(self, df: pd.DataFrame):
        acts = sorted(df["activity"].unique())
        self.vocab = {a: i + 1 for i, a in enumerate(acts)}  # 0 = PAD
        self.actors = {a: i for i, a in enumerate(sorted(df["actor"].unique()))}
        amounts = np.log1p(df["amount"].fillna(0.0))
        self.amount_mu, self.amount_sd = amounts.mean(), amounts.std() or 1.0
        self.max_len = int(df.groupby("case_id").size().max())
        return self

    def transform(self, df: pd.DataFrame):
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        case_ids, act_rows, attr_rows, mask_rows = [], [], [], []
        for case_id, g in df.groupby("case_id"):
            g = g.sort_values("timestamp")
            acts = [self.vocab.get(a, 0) for a in g["activity"]][: self.max_len]
            amount = ((np.log1p(g["amount"].fillna(0.0)) - self.amount_mu)
                      / self.amount_sd).tolist()[: self.max_len]
            hour = (g["timestamp"].dt.hour / 23.0).tolist()[: self.max_len]
            wday = (g["timestamp"].dt.weekday / 6.0).tolist()[: self.max_len]
            actor = [self.actors.get(a, len(self.actors)) / max(len(self.actors), 1)
                     for a in g["actor"]][: self.max_len]
            pad = self.max_len - len(acts)
            case_ids.append(case_id)
            act_rows.append(acts + [PAD] * pad)
            attr_rows.append(
                [[amount[i], hour[i], wday[i], actor[i]] for i in range(len(acts))]
                + [[0.0] * 4] * pad)
            mask_rows.append([1.0] * len(acts) + [0.0] * pad)
        return (torch.tensor(act_rows, dtype=torch.long),
                torch.tensor(attr_rows, dtype=torch.float32),
                torch.tensor(mask_rows, dtype=torch.float32),
                case_ids)


def _train(model, loss_fn, epochs=60, lr=1e-3):
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    for _ in range(epochs):
        opt.zero_grad()
        loss = loss_fn()
        loss.backward()
        opt.step()


class DAEDetector:
    """Autoencoder over one-hot activities + attributes, flattened per trace."""

    def __init__(self, hidden=32, bottleneck=8, epochs=60):
        self.hidden, self.bottleneck, self.epochs = hidden, bottleneck, epochs

    def _flatten(self, acts, attrs):
        onehot = nn.functional.one_hot(acts, self.n_acts).float()
        return torch.cat([onehot, attrs], dim=-1).flatten(1)

    def fit(self, train: pd.DataFrame):
        torch.manual_seed(0)
        self.enc = TraceEncoder().fit(train)
        acts, attrs, _, _ = self.enc.transform(train)
        self.n_acts = len(self.enc.vocab) + 1
        X = self._flatten(acts, attrs)
        dim = X.shape[1]
        self.model = nn.Sequential(
            nn.Linear(dim, self.hidden), nn.ReLU(),
            nn.Linear(self.hidden, self.bottleneck), nn.ReLU(),
            nn.Linear(self.bottleneck, self.hidden), nn.ReLU(),
            nn.Linear(self.hidden, dim))
        _train(self.model, lambda: nn.functional.mse_loss(self.model(X), X),
               self.epochs)
        return self

    def score(self, test: pd.DataFrame) -> pd.Series:
        acts, attrs, _, case_ids = self.enc.transform(test)
        X = self._flatten(acts, attrs)
        with torch.no_grad():
            err = ((self.model(X) - X) ** 2).mean(dim=1)
        return pd.Series(err.numpy(), index=case_ids)


class BINetLite:
    """GRU next-activity predictor conditioned on event attributes;
    score = mean NLL of the observed continuation."""

    def __init__(self, embed=16, hidden=32, epochs=60):
        self.embed, self.hidden, self.epochs = embed, hidden, epochs

    def _nll(self, acts, attrs, mask):
        emb = self.embedding(acts)
        h, _ = self.gru(torch.cat([emb, attrs], dim=-1))
        logits = self.head(h[:, :-1])          # predict event t+1 from prefix
        targets = acts[:, 1:]
        nll = nn.functional.cross_entropy(
            logits.transpose(1, 2), targets, reduction="none")
        m = mask[:, 1:]
        return (nll * m).sum(dim=1) / m.sum(dim=1).clamp(min=1.0)

    def fit(self, train: pd.DataFrame):
        torch.manual_seed(0)
        self.enc = TraceEncoder().fit(train)
        acts, attrs, mask, _ = self.enc.transform(train)
        n_acts = len(self.enc.vocab) + 1
        self.embedding = nn.Embedding(n_acts, self.embed, padding_idx=PAD)
        self.gru = nn.GRU(self.embed + 4, self.hidden, batch_first=True)
        self.head = nn.Linear(self.hidden, n_acts)
        params = nn.ModuleList([self.embedding, self.gru, self.head])
        _train(params, lambda: self._nll(acts, attrs, mask).mean(), self.epochs)
        return self

    def score(self, test: pd.DataFrame) -> pd.Series:
        acts, attrs, mask, case_ids = self.enc.transform(test)
        with torch.no_grad():
            nll = self._nll(acts, attrs, mask)
        return pd.Series(nll.numpy(), index=case_ids)
