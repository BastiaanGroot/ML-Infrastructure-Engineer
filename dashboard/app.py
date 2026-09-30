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
H100_BF16_PEAK_TFLOPS = 989
# Measured on this cluster (training/README.md): NVLink all_reduce bus
# bandwidth inside a node, and one GPU's InfiniBand NIC between nodes.
NVLINK_GBPS = 468
IB_PER_GPU_GBPS = 46

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
    if row.get("params.recompute") == "True":
        parts.append("recompute")
    if row.get("params.seq_length") not in (None, "4096"):
        parts.append(f"seq {row['params.seq_length']}")
    if row.get("params.nnodes") == "1":
        parts.append("1 node")
    elif row.get("params.gpus_per_node") not in (None, "8"):
        parts.append(f"{row['params.gpus_per_node']} GPUs/node")
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
        help="'profile' runs ran under nsys (5-37% overhead); 'e2e' is the "
        "real-data run with checkpointing (larger global batch).",
    )
    df = runs[runs["run_kind"].isin(kinds) & runs["metrics.steady_tflops_per_gpu"].notna()].copy()
    if df.empty:
        st.info("No runs with steady-state metrics for the selected kinds.")
        return
    df["model"] = df["params.model"]
    df["strategy"] = df["model"] + ": " + df.apply(strategy_label, axis=1)
    df["tflops"] = df["metrics.steady_tflops_per_gpu"]
    df["mfu_pct"] = 100 * df["tflops"] / H100_BF16_PEAK_TFLOPS
    df["step_s"] = df["metrics.steady_step_time_sec"]
    df["memory_gb"] = df["metrics.peak_gpu_memory_gb"]

    st.caption(
        "Steady-state = iterations 2-N, on 16 GPUs unless the label says "
        "otherwise. Qwen3-8B runs change one "
        "setting from the TP2 x DP8 baseline (seq 4096, or seq 16384 for CP). "
        "MoE runs count active parameters only. MFU is vs the H100 bf16 dense "
        "peak (989 TFLOP/s) for every run, including FP8."
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
                x=alt.X("step:Q", title="iteration"),
                y=alt.Y("value:Q", title="step time (s)", scale=alt.Scale(type="log")),
                color="run:N",
            ),
            width="stretch",
        )


def communication_tab(runs: pd.DataFrame) -> None:
    st.subheader("NCCL all_reduce bus bandwidth")
    bench = runs[runs["run_kind"] == "benchmark"].drop_duplicates("run_name", keep="last")
    if not bench.empty:
        bw = pd.concat([
            metric_history(r.run_id, "busbw_gbps").assign(run=r.run_name) for r in bench.itertuples()
        ]).rename(columns={"step": "size_mib"})
        st.altair_chart(
            alt.Chart(bw).mark_line(point=True).encode(
                x=alt.X("size_mib:Q", scale=alt.Scale(type="log"), title="message size (MiB)"),
                y=alt.Y("value:Q", title="bus bandwidth (GB/s)"),
                color=alt.Color("run:N", legend=alt.Legend(orient="bottom")),
                tooltip=["run", "size_mib", alt.Tooltip("value:Q", format=".1f")],
            ),
            width="stretch",
        )
        st.caption(
            f"At 1 GiB: ~{NVLINK_GBPS} GB/s over NVLink inside a node (8 GPUs), "
            "~442 GB/s across both nodes (16 GPUs, NVLink + 8 InfiniBand NICs "
            f"per node), and ~{IB_PER_GPU_GBPS} GB/s for one GPU per node over a "
            "single 400 Gb/s NIC."
        )

    st.subheader("Where GPU time goes: Nsight Systems kernel breakdown")
    summarize = load_summarize_kernels()
    labels = {
        "q8b-baseline": "Qwen3-8B TP2 x DP8 (TP over NVLink)",
        "q8b-tp8-2nodes": "Qwen3-8B TP8 x DP1, 4 GPUs/node (TP over InfiniBand)",
    }
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
            "these are shares of summed kernel time, not wall time (training/README.md, "
            "\"Nsight profiles\")."
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
        st.markdown("**Cluster** (H100 80GB)")
        nodes = st.number_input("Nodes", 1, 1024, 64)
        gpus_per_node = st.selectbox("GPUs per node", [1, 8], index=1)
        st.caption(
            f"Links as measured here: NVLink {NVLINK_GBPS} GB/s, "
            f"InfiniBand {IB_PER_GPU_GBPS} GB/s per GPU."
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
        hbm_gb=80, peak_tflops=H100_BF16_PEAK_TFLOPS,
        intra_node_gbps=NVLINK_GBPS, inter_node_gbps=IB_PER_GPU_GBPS,
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
        poc = rec.Cluster(2, 8, 80, H100_BF16_PEAK_TFLOPS, NVLINK_GBPS, IB_PER_GPU_GBPS)
        models = {m.name: m for m in rec.PRESET_MODELS}
        workload = rec.Workload(4096, 1, 64, 0.45)
        checks = [
            ("q8b-baseline", "Qwen3-8B", 2, 1, 1.94, 49.2),
            ("q8b-dp16 (OOM)", "Qwen3-8B", 1, 1, None, None),
            ("q8b-pp2", "Qwen3-8B", 2, 2, 2.29, 33.2),
            ("q8b-tp4-dp4", "Qwen3-8B", 4, 1, 2.60, 30.2),
            ("q8b-tp8-dp2", "Qwen3-8B", 8, 1, 5.06, 20.7),
            ("q32b-tp4-pp2-dp2", "Qwen3-32B", 4, 2, 10.69, 52.8),
            ("q32b-tp8-pp2-dp1", "Qwen3-32B", 8, 2, 14.79, 40.2),
        ]
        rows = []
        for run, model_name, tp, pp, step, mem in checks:
            p = rec.plan(models[model_name], poc, workload, tp, pp)
            rows.append({
                "run": run, "layout": p.label, "measured step (s)": step, "predicted step (s)": p.step_s,
                "measured memory (GB)": mem, "predicted memory (GB)": p.memory_gb,
            })
        st.dataframe(pd.DataFrame(rows).style.format(precision=2), hide_index=True, width="stretch")
        st.caption(
            "Runs on this cluster (2 nodes x 8 H100, measured NVLink/IB bandwidth), "
            "micro-batch 1, global batch 64, seq 4096, assumed MFU 0.45. The ranking "
            "matches for both models. TP1-TP4 step times are within about 25%, but "
            "TP8 is underestimated by ~2x: the model keeps MFU constant, while in "
            "reality each GPU's GEMMs shrink with TP. Memory is off by -27% to +16% "
            "and puts DP16 just under 80 GB, where it really OOMs, so treat anything "
            "within ~20% of HBM as not fitting."
        )


st.title("Qwen3 distributed training on Nebius")
st.caption(
    "Live from the PoC's managed MLflow. Two nodes x 8 H100 on InfiniBand, Megatron-Bridge "
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
