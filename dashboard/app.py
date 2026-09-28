"""Streamlit dashboard: Qwen3 distributed-training experiments on Nebius.

Reads live from the MLflow tracking server (MLFLOW_TRACKING_URI /
MLFLOW_TRACKING_USERNAME / MLFLOW_TRACKING_PASSWORD) and from the Nsight
kernel tables committed under training/profiles/. Run from the repo root:

    streamlit run dashboard/app.py
"""

import importlib.util
import os
from pathlib import Path

import altair as alt
import mlflow
import pandas as pd
import streamlit as st
from mlflow.tracking import MlflowClient

import recommender as rec

REPO = Path(__file__).resolve().parents[1]
EXPERIMENT = "qwen3-parallelism-experiments"
H200_BF16_PEAK_TFLOPS = 989

st.set_page_config(page_title="Qwen3 parallelism on Nebius", layout="wide")


def load_summarize_kernels():
    path = REPO / "training" / "scripts" / "summarize_kernels.py"
    spec = importlib.util.spec_from_file_location("summarize_kernels", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.summarize


def strategy_label(row: pd.Series) -> str:
    parts = [
        f"{name}{int(row[f'params.{param}'])}"
        for name, param in [
            ("DP", "data_parallelism"), ("TP", "tensor_parallelism"),
            ("PP", "pipeline_parallelism"), ("CP", "context_parallelism"),
            ("EP", "expert_parallelism"),
        ]
        if pd.notna(row.get(f"params.{param}")) and int(row[f"params.{param}"]) > 1
    ]
    if row.get("params.precision") not in (None, "bf16_mixed"):
        parts.append("FP8")
    if row.get("params.attention_backend") not in (None, "default"):
        parts.append(f"{row['params.attention_backend']} attn")
    if row.get("params.cpu_offload") == "True":
        parts.append("CPU offload")
    if row.get("params.seq_length") not in (None, "4096"):
        parts.append(f"seq {row['params.seq_length']}")
    return " + ".join(parts) or "single GPU"


@st.cache_data(ttl=300, show_spinner="Querying MLflow...")
def load_runs() -> pd.DataFrame:
    experiment = mlflow.get_experiment_by_name(EXPERIMENT)
    runs = mlflow.search_runs([experiment.experiment_id], order_by=["start_time ASC"])
    runs = runs[runs["status"] == "FINISHED"].copy()
    runs["run_kind"] = runs.get("tags.run_kind", pd.Series(dtype=str)).fillna("experiment")
    runs["run_name"] = runs["tags.mlflow.runName"]
    return runs


@st.cache_data(ttl=300)
def metric_history(run_id: str, key: str) -> pd.DataFrame:
    history = MlflowClient().get_metric_history(run_id, key)
    return pd.DataFrame([(m.step, m.value) for m in history], columns=["step", "value"])


def bar(df: pd.DataFrame, value: str, title: str) -> alt.Chart:
    return (
        alt.Chart(df, title=title)
        .mark_bar()
        .encode(
            x=alt.X(f"{value}:Q", title=None),
            y=alt.Y("strategy:N", sort="-x", title=None),
            color=alt.Color("model:N", legend=alt.Legend(orient="bottom")),
            tooltip=["run_name", "strategy", alt.Tooltip(f"{value}:Q", format=".2f")],
        )
        .properties(height=36 * len(df))
    )


def comparison_tab(runs: pd.DataFrame) -> None:
    kinds = st.multiselect(
        "Run kinds", sorted(runs["run_kind"].unique()), default=["experiment"],
        help="'profile' runs ran under nsys (~8-10% overhead); 'superseded' is "
        "the early Qwen3-4B TP run, replaced by a same-model comparison.",
    )
    df = runs[runs["run_kind"].isin(kinds) & runs["metrics.steady_tflops_per_gpu"].notna()].copy()
    if df.empty:
        st.info("No runs with steady-state metrics for the selected kinds.")
        return
    df["strategy"] = df.apply(strategy_label, axis=1)
    df["model"] = df["params.model"]
    df["tflops"] = df["metrics.steady_tflops_per_gpu"]
    df["mfu_pct"] = 100 * df["tflops"] / H200_BF16_PEAK_TFLOPS
    df["step_s"] = df["metrics.steady_step_time_sec"]
    df["memory_gb"] = df["metrics.peak_gpu_memory_gb"]

    st.caption(
        "Steady-state = iterations 2-20. Each run changes one setting from its "
        "baseline (DP=2 at seq 4096, or DP=2 at seq 16384 for CP). MFU is vs "
        "the H200 bf16 dense peak (989 TFLOP/s) for every run, including FP8."
    )
    left, right = st.columns(2)
    left.altair_chart(bar(df, "tflops", "Throughput per GPU (TFLOP/s)"), width="stretch")
    right.altair_chart(bar(df, "memory_gb", "Peak GPU memory (GB)"), width="stretch")
    st.dataframe(
        df[["run_name", "strategy", "step_s", "tflops", "mfu_pct", "memory_gb", "params.global_batch_size"]]
        .rename(columns={"params.global_batch_size": "global_batch"})
        .style.format({"step_s": "{:.2f}", "tflops": "{:.1f}", "mfu_pct": "{:.2f}", "memory_gb": "{:.1f}"}),
        hide_index=True, width="stretch",
    )

    histories = [
        metric_history(r.run_id, "iter_step_time_sec").assign(run=r.run_name)
        for r in df.itertuples()
    ]
    histories = [h for h in histories if not h.empty]
    if histories:
        st.subheader("Per-iteration step time")
        st.altair_chart(
            alt.Chart(pd.concat(histories)).mark_line(point=True).encode(
                x=alt.X("step:Q", title="iteration"), y=alt.Y("value:Q", title="step time (s)"),
                color="run:N",
            ),
            width="stretch",
        )
    else:
        st.caption(
            "Per-iteration series are logged by runs made after the steady-state "
            "logging change; the runs shown here predate it (steady-state values "
            "backfilled from their pod logs)."
        )


def communication_tab(runs: pd.DataFrame) -> None:
    st.subheader("Cross-node NCCL all_reduce bandwidth (experiment 9)")
    bench = runs[runs["run_kind"] == "benchmark"]
    if not bench.empty:
        bw = metric_history(bench.iloc[-1]["run_id"], "algbw_gbps").rename(columns={"step": "size_mib"})
        st.altair_chart(
            alt.Chart(bw).mark_line(point=True).encode(
                x=alt.X("size_mib:Q", scale=alt.Scale(type="log"), title="message size (MiB)"),
                y=alt.Y("value:Q", title="algorithm bandwidth (GB/s)"),
                tooltip=["size_mib", alt.Tooltip("value:Q", format=".2f")],
            ),
            width="stretch",
        )
        st.caption(
            "Plateaus at ~2.3-2.4 GB/s (~19 Gbit/s): plain Ethernet between the "
            "two nodes, no InfiniBand. InfiniBand gives ~40-50 GB/s per GPU; "
            "NVLink inside an H100 node ~360+ GB/s."
        )

    st.subheader("Where GPU time goes: Nsight Systems kernel breakdown")
    summarize = load_summarize_kernels()
    labels = {"dp": "DP=2", "tp": "TP=2", "tp-seqpar": "TP=2 + sequence parallel"}
    rows = []
    for path in sorted((REPO / "training" / "profiles").glob("*-cuda_gpu_kern_sum.txt")):
        key = path.name.removesuffix("-cuda_gpu_kern_sum.txt")
        totals = summarize(str(path))
        grand = sum(totals.values())
        rows += [
            {"run": labels.get(key, key), "category": cat, "pct": 100 * ns / grand}
            for cat, ns in totals.items()
        ]
    if rows:
        st.altair_chart(
            alt.Chart(pd.DataFrame(rows)).mark_bar().encode(
                x=alt.X("pct:Q", stack="normalize", title="share of summed GPU kernel time"),
                y=alt.Y("run:N", title=None),
                color=alt.Color("category:N", legend=alt.Legend(orient="bottom")),
                tooltip=["run", "category", alt.Tooltip("pct:Q", format=".1f")],
            ),
            width="stretch",
        )
        st.caption(
            "NCCL kernels run on their own stream and overlap with compute, so "
            "these are shares of summed kernel time, not wall time. Per-call NCCL "
            "times match the measured bandwidth above (training/README.md, Takeaway 9)."
        )


def planner_tab() -> None:
    st.caption(
        "First-order estimate for dense models: Megatron distributed optimizer, "
        "1F1B pipeline, flash attention + sequence parallelism. Communication "
        "time = bytes / bandwidth of the slowest link each group spans."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Model**")
        names = [m.name for m in rec.PRESET_MODELS]
        model = rec.PRESET_MODELS[names.index(st.selectbox("Preset", names, index=len(names) - 1))]
    with c2:
        st.markdown("**Cluster**")
        gpu = st.selectbox("GPU", ["H100 80GB", "H200 141GB"])
        nodes = st.number_input("Nodes", 1, 1024, 64)
        gpus_per_node = st.selectbox("GPUs per node", [1, 8], index=1)
        link = st.selectbox(
            "Inter-node link",
            ["InfiniBand (~40 GB/s per GPU)", "Ethernet, as measured here (2.35 GB/s)"],
        )
    with c3:
        st.markdown("**Workload**")
        seq = st.selectbox("Sequence length", [2048, 4096, 8192, 16384], index=2)
        micro = st.selectbox("Micro-batch size", [1, 2, 4], index=0)
        global_batch = st.number_input("Global batch (sequences)", 1, 65536, 1024)
        mfu = st.slider("Assumed compute MFU", 0.05, 0.6, 0.40, 0.05)
        recompute = st.checkbox("Full activation recomputation", value=True)

    cluster = rec.Cluster(
        nodes=nodes, gpus_per_node=gpus_per_node,
        hbm_gb=80 if gpu.startswith("H100") else 141, peak_tflops=989,
        intra_node_gbps=360, inter_node_gbps=40 if link.startswith("Infini") else 2.35,
    )
    workload = rec.Workload(seq, micro, global_batch, mfu, recompute)
    plans = rec.rank_plans(model, cluster, workload)
    if not plans:
        st.warning("No valid layout: global batch must divide by micro-batch x DP for some layout.")
        return
    table = pd.DataFrame([
        {
            "layout": p.label, "fits": p.memory_gb <= cluster.hbm_gb,
            "memory_gb": p.memory_gb, "step_s": p.step_s, "compute_s": p.compute_s,
            "tp_comm_s": p.tp_comm_s, "pp_bubble_s": p.pp_bubble_s,
            "pp_comm_s": p.pp_comm_s, "dp_comm_s (overlapped)": p.dp_comm_s,
            "inter_node_gb/step": p.inter_node_gb,
        }
        for p in plans
    ])
    fitting = table[table["fits"]]
    if fitting.empty:
        st.error(f"No layout fits in {cluster.hbm_gb} GB per GPU - try recomputation or more GPUs.")
    else:
        best = fitting.iloc[0]
        st.success(
            f"**{best['layout']}** on {cluster.gpus} GPUs: ~{best['memory_gb']:.0f} GB/GPU, "
            f"~{best['step_s']:.1f} s/step "
            f"({workload.global_batch * workload.seq_length / best['step_s']:,.0f} tokens/s)"
        )
    st.dataframe(
        table.head(15).style.format({c: "{:.1f}" for c in table.columns if c not in ("layout", "fits")}),
        hide_index=True, width="stretch",
    )

    with st.expander("How well does this model match our real runs?"):
        poc = rec.Cluster(2, 1, 141, 989, 360, 2.35)
        qwen = rec.PRESET_MODELS[0]
        checks = [("DP=2", 1, 1, 4, 2, 2.29, 53.3), ("TP=2", 2, 1, 2, 2, 1.73, 33.8), ("PP=2", 1, 2, 4, 1, 1.00, 28.2)]
        st.dataframe(pd.DataFrame([
            {
                "run": name, "measured step (s)": step,
                "predicted step (s)": rec.plan(qwen, poc, rec.Workload(4096, mb, gb, 0.10), tp, pp).step_s,
                "measured memory (GB)": mem,
                "predicted memory (GB)": rec.plan(qwen, poc, rec.Workload(4096, mb, gb, 0.10), tp, pp).memory_gb,
            }
            for name, tp, pp, gb, mb, step, mem in checks
        ]).style.format(precision=2), hide_index=True, width="stretch")
        st.caption(
            "Qwen3-1.7B on this PoC (2 nodes x 1 H200, 2.35 GB/s), assumed MFU 0.10. "
            "Step time is within about -4% to +17% and ranks the three strategies "
            "correctly; memory is underestimated by 7-22% (CUDA context, allocator "
            "fragmentation and temporary buffers aren't modelled)."
        )


st.title("Qwen3 distributed training on Nebius")
st.caption(
    "Live from the PoC's managed MLflow. Two nodes x 1 H200, Megatron-Bridge "
    "(nvcr.io/nvidia/nemo:25.09). Details: training/README.md in the repo."
)
if not os.environ.get("MLFLOW_TRACKING_URI"):
    st.error("MLFLOW_TRACKING_URI is not set - see dashboard/README.md.")
    st.stop()

runs = load_runs()
tab1, tab2, tab3 = st.tabs(["Strategy comparison", "Communication", "Parallelism planner"])
with tab1:
    comparison_tab(runs)
with tab2:
    communication_tab(runs)
with tab3:
    planner_tab()
