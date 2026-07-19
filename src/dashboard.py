"""Interactive results dashboard for erp-anomaly-bench.

Run from src/:  streamlit run dashboard.py

Reads the generated event logs in data/ and (if present) the benchmark
tables in results/. The selected detector is fitted live under the same
protocol as the benchmark: train on the earliest 70% of traces, score the
held-out latest 30%. Scores and labels shown side by side — the detector
never sees labels.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from erpbench.bench.data import load_log, strip_labels, temporal_split, trace_labels
from erpbench.bench.methods import registry
from sklearn.metrics import average_precision_score, roc_auc_score

st.set_page_config(page_title="erp-anomaly-bench", page_icon="🔎", layout="wide")

SCORE_CMAP = "Reds"  # single-hue sequential: magnitude only, labels carry identity
GREENBAR = "#E3EDDF"  # the pale band of tractor-feed ledger paper
INK = "#1E2B23"
FLAG_RED = "#B42318"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600&display=swap');

html, body, [class*="st-"] { font-family: 'IBM Plex Sans', sans-serif; }

/* keep Streamlit's icon glyphs on their ligature font — without this, icon
   names like "keyboard_double_arrow_left" render as literal text */
[data-testid="stIconMaterial"], .material-symbols-rounded,
span[translate="no"] {
    font-family: 'Material Symbols Rounded' !important;
}

h1, h2, h3, [data-testid="stMetricValue"], code, .stDataFrame {
    font-family: 'IBM Plex Mono', monospace !important;
}
h1 { letter-spacing: 0.04em; text-transform: uppercase; font-weight: 600; }
h3 { letter-spacing: 0.06em; text-transform: uppercase;
     font-size: 0.95rem !important; color: #5B7263; }

/* ledger-total tiles: heavy ink rule above, like the totals row of a ledger */
[data-testid="stMetric"] {
    border-top: 3px solid #1E2B23;
    background: #EDF3EA;
    padding: 10px 14px 8px 14px;
}
[data-testid="stMetricLabel"] { letter-spacing: 0.08em; text-transform: uppercase; }

/* rubber-stamp verdicts */
.stamp {
    display: inline-block; font-family: 'IBM Plex Mono', monospace;
    font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase;
    padding: 6px 14px; border: 3px double; border-radius: 4px;
    transform: rotate(-1.2deg); margin-top: 8px;
}
.stamp.flag  { color: #B42318; border-color: #B42318; background: #B4231810; }
.stamp.clear { color: #2F6B4F; border-color: #2F6B4F; background: #2F6B4F10; }
</style>
""", unsafe_allow_html=True)


# ---------- cached loaders ------------------------------------------------

@st.cache_data(show_spinner="Loading event log…")
def load(csv_path: str) -> pd.DataFrame:
    return load_log(csv_path)


@st.cache_data(show_spinner="Fitting detector on training traces…")
def fit_and_score(csv_path: str, method_name: str):
    df = load_log(csv_path)
    train, test = temporal_split(df)
    method = registry()[method_name]
    scores = method.fit(strip_labels(train)).score(strip_labels(test))
    return scores, trace_labels(test)


# ---------- sidebar -------------------------------------------------------

datasets = sorted(Path("data").glob("p2p_*.csv"))
if not datasets:
    st.error("No datasets found in data/ — generate one first "
             "(see README quickstart).")
    st.stop()

stems = [p.stem for p in datasets]
csv = st.sidebar.selectbox("Dataset", datasets,
                           index=stems.index("p2p_hard") if "p2p_hard" in stems else 0,
                           format_func=lambda p: p.stem)
methods = list(registry())
method = st.sidebar.selectbox("Detector", methods,
                              index=methods.index("iforest_ctx")
                              if "iforest_ctx" in methods else 0)
st.sidebar.caption(
    "Benchmark protocol: the detector fits on the earliest 70% of traces "
    "(labels stripped) and scores the held-out latest 30%. Labels appear "
    "only in the evaluation columns.")

df = load(str(csv))
scores, labels = fit_and_score(str(csv), method)
y_true = (labels != "normal").astype(int)

# ---------- header metrics ------------------------------------------------

st.markdown('<div style="font-family:\'IBM Plex Mono\',monospace; '
            'letter-spacing:.16em; color:#5B7263; font-size:.78rem;">'
            'PROCURE-TO-PAY LEDGER · ANOMALY AUDIT</div>',
            unsafe_allow_html=True)
st.title("erp-anomaly-bench")
st.caption("Labeled ERP fraud dataset + detection benchmark — "
           "github.com/aminmiral/erp-anomaly-bench")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Traces", df["case_id"].nunique())
m2.metric("Events", len(df))
m3.metric("Anomalous (test)", f"{int(y_true.sum())} / {len(y_true)}")
m4.metric("ROC-AUC", f"{roc_auc_score(y_true, scores):.3f}")
m5.metric("AUPRC", f"{average_precision_score(y_true, scores):.3f}")

# ---------- suspects list + drill-down ------------------------------------

left, right = st.columns([1, 2], gap="large")

table = (pd.DataFrame({"suspicion": scores, "true label": labels})
         .sort_values("suspicion", ascending=False))
table["true label"] = table["true label"].map(
    lambda v: "· normal" if v == "normal" else f"⚠ {v}")

with left:
    st.subheader(f"Suspects, ranked by {method}")
    st.dataframe(
        table.style
        .background_gradient(subset=["suspicion"], cmap=SCORE_CMAP)
        .format({"suspicion": "{:.3f}"}),
        width="stretch", height=420)

with right:
    st.subheader("Trace drill-down")
    case = st.selectbox("Case (ranked most suspicious first)", table.index)
    events = df[df["case_id"] == case].sort_values("timestamp")
    cols = [c for c in ("activity", "timestamp", "actor", "role", "amount",
                        "vendor", "doc_ref", "anomaly_type") if c in events]
    shown = (events[cols].rename(columns={"anomaly_type": "event label"})
             .reset_index(drop=True))
    greenbar = shown.style.apply(
        lambda row: [f"background-color: {GREENBAR}" if row.name % 2 else ""]
        * len(row), axis=1)
    st.dataframe(greenbar, width="stretch", hide_index=True)
    verdict = labels.get(case, "?")
    score_txt = f"suspicion {scores.get(case, float('nan')):.3f}"
    if verdict == "normal":
        st.markdown(f'<span class="stamp clear">✓ clear — {score_txt}</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="stamp flag">✗ {verdict} — {score_txt}</span>',
                    unsafe_allow_html=True)

# ---------- benchmark results, if the runner has produced them ------------

results_file = Path("results") / f"{csv.stem}_results.csv"
if results_file.exists():
    st.divider()
    st.subheader("Benchmark: all detectors on this dataset")
    res = pd.read_csv(results_file, index_col=0)

    c1, c2 = st.columns([1, 2], gap="large")
    with c1:
        st.markdown("**Overall AUPRC** (higher is better)")
        st.bar_chart(res["auprc"].sort_values(), horizontal=True,
                     color=FLAG_RED, height=330)
    with c2:
        per_type = res[[c for c in res.columns if c.startswith("auprc:")]]
        per_type.columns = [c.removeprefix("auprc:") for c in per_type.columns]
        st.markdown("**AUPRC per anomaly type** — the blind spots are the story")
        st.dataframe(
            per_type.style.background_gradient(cmap=SCORE_CMAP, axis=None,
                                               vmin=0.0, vmax=1.0)
            .format("{:.2f}"),
            width="stretch")
    st.caption("Values near the anomaly base rate (~0.02-0.10) mean the "
               "detector is guessing; 1.00 means every fraud of that type "
               "was ranked above every normal trace.")
else:
    st.info(f"No benchmark table for this dataset yet — run "
            f"`python -m erpbench.bench.run data/{csv.name}` to produce it.")
