"""First-order parallelism planner for dense transformer pretraining.

Enumerates (TP, PP, DP) layouts for a GPU count, estimates per-GPU memory and
per-step communication, and ranks the layouts that fit. The communication
model is checked against this repo's real runs in the dashboard's planner
tab: per-collective bytes divided by the bandwidth of the slowest
link the collective's group spans.

Deliberately simple: no CP/EP, no virtual pipeline stages, 1F1B schedule,
Megatron distributed optimizer, optional full activation recomputation.
"""

import math
from dataclasses import dataclass

BF16 = 2
FP32 = 4


@dataclass(frozen=True)
class Model:
    name: str
    params: float
    layers: int
    hidden: int
    vocab: int = 151_936


@dataclass(frozen=True)
class Cluster:
    nodes: int
    gpus_per_node: int
    hbm_gb: float
    peak_tflops: float
    intra_node_gbps: float  # effective per-GPU NVLink bandwidth, GB/s
    inter_node_gbps: float  # effective per-GPU cross-node bandwidth, GB/s

    @property
    def gpus(self) -> int:
        return self.nodes * self.gpus_per_node


@dataclass(frozen=True)
class Workload:
    seq_length: int
    micro_batch: int
    global_batch: int
    mfu: float  # assumed compute efficiency while not waiting on comms
    recompute: bool = False  # full activation recomputation


@dataclass(frozen=True)
class Plan:
    tp: int
    pp: int
    dp: int
    microbatches: int
    memory_gb: float
    compute_s: float
    tp_comm_s: float
    pp_bubble_s: float
    pp_comm_s: float
    dp_comm_s: float
    inter_node_gb: float

    @property
    def step_s(self) -> float:
        # TP all-reduces and PP boundary sends are counted on the critical
        # path (conservative for PP - 1F1B hides some of it); DP's grad
        # reduce-scatter / param all-gather overlap with compute.
        critical = self.compute_s + self.tp_comm_s + self.pp_bubble_s + self.pp_comm_s
        return max(critical, self.dp_comm_s)

    @property
    def label(self) -> str:
        return f"TP{self.tp} x PP{self.pp} x DP{self.dp}"


PRESET_MODELS = [
    Model("Qwen3-1.7B", 1.72e9, 28, 2048),
    Model("Qwen3-8B", 8.2e9, 36, 4096),
    Model("Qwen3-32B", 32.8e9, 64, 5120),
    Model("Llama-3.1-70B", 70.6e9, 80, 8192, vocab=128_256),
    Model("Llama-3.1-405B", 405e9, 126, 16384, vocab=128_256),
]


def divisors(n: int) -> list[int]:
    return [d for d in range(1, n + 1) if n % d == 0]


def memory_gb(m: Model, w: Workload, tp: int, pp: int, dp: int) -> float:
    shard = m.params / (tp * pp)
    weights_and_grads = shard * (BF16 + FP32)  # grad_reduce_in_fp32
    optimizer = shard * 3 * FP32 / dp  # fp32 master + Adam m, v, sharded
    # Korthikanti et al. 2022: ~34*s*b*h bytes per layer with flash attention
    # and sequence parallelism, split across TP. Under 1F1B the first stage
    # holds `pp` in-flight microbatches of its ceil(layers/pp) layers. Full
    # recomputation keeps only each layer's bf16 input, plus one layer's
    # full working set while it's being recomputed.
    sbh = w.seq_length * w.micro_batch * m.hidden
    stored_layers = pp * math.ceil(m.layers / pp)
    if w.recompute:
        activations = (BF16 * sbh * stored_layers + 34 * sbh) / tp
    else:
        activations = 34 * sbh * stored_layers / tp
    logits = w.seq_length * w.micro_batch * m.vocab * FP32 / tp
    return (weights_and_grads + optimizer + activations + logits) / 1e9


def link_gbps(c: Cluster, group_spans_nodes: bool) -> float:
    return c.inter_node_gbps if group_spans_nodes else c.intra_node_gbps


def plan(m: Model, c: Cluster, w: Workload, tp: int, pp: int) -> Plan | None:
    if c.gpus % (tp * pp):
        return None
    dp = c.gpus // (tp * pp)
    if pp > m.layers or w.global_batch % (w.micro_batch * dp):
        return None
    microbatches = w.global_batch // (w.micro_batch * dp)
    if microbatches < pp:
        return None

    # Ranks are laid out TP-fastest, then DP, then PP (Megatron's default).
    tp_spans = tp > c.gpus_per_node
    dp_spans = tp * dp > c.gpus_per_node
    pp_spans = pp > 1 and c.nodes > 1

    tokens = w.global_batch * w.seq_length
    flops_per_token = (8 if w.recompute else 6) * m.params
    compute = flops_per_token * tokens / (c.gpus * c.peak_tflops * 1e12 * w.mfu)

    act_bytes = w.seq_length * w.micro_batch * m.hidden * BF16
    tp_comm = 0.0
    if tp > 1:
        per_allreduce = act_bytes * 2 * (tp - 1) / tp
        # 2 fwd + 2 bwd per layer, plus 2 more per layer when recomputing.
        calls = (6 if w.recompute else 4) * math.ceil(m.layers / pp) * microbatches
        tp_comm = calls * per_allreduce / (link_gbps(c, tp_spans) * 1e9)

    pp_bubble = compute * (pp - 1) / microbatches if pp > 1 else 0.0
    pp_bytes = 2 * act_bytes * microbatches if pp > 1 else 0.0
    pp_comm = pp_bytes / (link_gbps(c, pp_spans) * 1e9)

    dp_comm, dp_bytes = 0.0, 0.0
    if dp > 1:
        shard = m.params / (tp * pp)
        dp_bytes = shard * (FP32 + BF16) * (dp - 1) / dp  # reduce-scatter + all-gather
        dp_comm = dp_bytes / (link_gbps(c, dp_spans) * 1e9)

    inter_node = (
        (tp_comm * c.inter_node_gbps if tp_spans else 0.0)
        + (dp_bytes / 1e9 if dp_spans else 0.0)
        + (pp_bytes / 1e9 if pp_spans else 0.0)
    )
    return Plan(
        tp, pp, dp, microbatches, memory_gb(m, w, tp, pp, dp),
        compute, tp_comm, pp_bubble, pp_comm, dp_comm, inter_node,
    )


def rank_plans(m: Model, c: Cluster, w: Workload) -> list[Plan]:
    plans = [
        p for tp in divisors(c.gpus) for pp in divisors(c.gpus)
        if (p := plan(m, c, w, tp, pp)) is not None
    ]
    return sorted(plans, key=lambda p: (p.memory_gb > c.hbm_gb, p.step_s))
