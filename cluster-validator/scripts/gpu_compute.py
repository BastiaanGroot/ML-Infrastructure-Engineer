#!/usr/bin/env python3
"""GPU compute check: bf16 GEMM throughput on every GPU at once, plus
temperature and clock-slowdown reasons read while they're under load.

gpu_health.sh reads temperatures at idle and nccl_bench.sh measures the
interconnect; neither would catch one GPU that computes slowly (bad clocks,
thermal or hardware slowdown). This runs 8192x8192 bf16 matmuls on all GPUs
concurrently for GPU_COMPUTE_SECONDS, like a training step loads them, and
fails if any GPU is below GPU_MIN_TFLOPS or GPU_MIN_REL_TO_MEDIAN x the
node's median. Hitting the power cap is normal under a GEMM burn and doesn't
fail; thermal or hardware slowdown does.

Writes $RESULTS_DIR/gpu_compute.json with the same schema as common.sh's
write_result.

Env vars:
  RESULTS_DIR            - where to write gpu_compute.json (default: /results)
  GPU_COMPUTE_SECONDS    - burn duration (default: 30)
  GPU_MIN_TFLOPS         - optional absolute per-GPU floor (unset: relative check only)
  GPU_MIN_REL_TO_MEDIAN  - per-GPU floor relative to the node median (default: 0.9)
  MAX_GPU_TEMP_C         - max temperature under load (default: 85)
"""
import json
import os
import statistics
import subprocess
import sys
import time

NAME = "gpu_compute"
RESULTS_DIR = os.environ.get("RESULTS_DIR", "/results")
SECONDS = float(os.environ.get("GPU_COMPUTE_SECONDS", "30"))
MIN_TFLOPS = float(os.environ["GPU_MIN_TFLOPS"]) if os.environ.get("GPU_MIN_TFLOPS") else None
MIN_REL = float(os.environ.get("GPU_MIN_REL_TO_MEDIAN", "0.9"))
MAX_TEMP_C = float(os.environ.get("MAX_GPU_TEMP_C", "85"))
N = 8192
SLOWDOWNS = ["hw_slowdown", "hw_thermal_slowdown", "sw_thermal_slowdown"]


def write_result(status, message, metrics=None):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, f"{NAME}.json"), "w") as f:
        json.dump({"name": NAME, "status": status, "message": message, "metrics": metrics or {}}, f)
    print(f"[{NAME}] {status}: {message}")


def query_under_load() -> list[dict]:
    fields = ["index", "temperature.gpu", "clocks.sm", "power.draw"] + [f"clocks_event_reasons.{s}" for s in SLOWDOWNS]
    out = subprocess.run(
        ["nvidia-smi", f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    ).stdout
    rows = []
    for line in out.strip().splitlines():
        values = [v.strip() for v in line.split(",")]
        rows.append({
            "index": int(values[0]),
            "temp_c": float(values[1]),
            "sm_clock_mhz": float(values[2]),
            "power_w": float(values[3]),
            "slowdowns": [s for s, v in zip(SLOWDOWNS, values[4:]) if v == "Active"],
        })
    return rows


def main():
    import torch

    devices = list(range(torch.cuda.device_count()))
    if not devices:
        write_result("fail", "no CUDA devices visible to PyTorch")
        return 1
    operands = [
        (torch.randn(N, N, device=d, dtype=torch.bfloat16), torch.randn(N, N, device=d, dtype=torch.bfloat16))
        for d in devices
    ]

    def enqueue(iters):
        """Queue `iters` matmuls on every GPU; return per-GPU (start, end) events."""
        events = []
        for d, (a, b) in zip(devices, operands):
            with torch.cuda.device(d):
                start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
                start.record()
                for _ in range(iters):
                    torch.mm(a, b)
                end.record()
                events.append((start, end))
        return events

    def wait(events):
        for _, end in events:
            end.synchronize()

    wait(enqueue(10))  # warmup: cuBLAS heuristics, clocks ramp up
    busy_ms = [0.0] * len(devices)
    iters = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < SECONDS:
        events = enqueue(50)
        wait(events)
        busy_ms = [total + s.elapsed_time(e) for total, (s, e) in zip(busy_ms, events)]
        iters += 50
    # Queue ~0.5 s of work per GPU and sample nvidia-smi while it runs.
    events = enqueue(400)
    load = query_under_load()
    wait(events)

    tflops = [2 * N**3 * iters / (ms / 1e3) / 1e12 for ms in busy_ms]
    median = statistics.median(tflops)
    fail = []
    for i, t in enumerate(tflops):
        if MIN_TFLOPS is not None and t < MIN_TFLOPS:
            fail.append(f"GPU {i} {t:.0f} TFLOP/s below {MIN_TFLOPS:.0f}")
        elif t < MIN_REL * median:
            fail.append(f"GPU {i} {t:.0f} TFLOP/s below {MIN_REL:.0%} of the node median {median:.0f}")
    for gpu in load:
        if gpu["temp_c"] > MAX_TEMP_C:
            fail.append(f"GPU {gpu['index']} at {gpu['temp_c']:.0f}C under load (max {MAX_TEMP_C:.0f}C)")
        if gpu["slowdowns"]:
            fail.append(f"GPU {gpu['index']} clock slowdown under load: {', '.join(gpu['slowdowns'])}")

    metrics = {
        "bf16_gemm_tflops_per_gpu": [round(t, 1) for t in tflops],
        "min_tflops": round(min(tflops), 1),
        "median_tflops": round(median, 1),
        "max_temp_under_load_c": max(g["temp_c"] for g in load),
        "under_load": load,
    }
    if fail:
        write_result("fail", "; ".join(fail), metrics)
        return 1
    write_result(
        "pass",
        f"{len(devices)} GPU(s) bf16 GEMM {min(tflops):.0f}-{max(tflops):.0f} TFLOP/s, "
        f"max {metrics['max_temp_under_load_c']:.0f}C under load, no thermal/HW slowdown",
        metrics,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # last-resort catch so we always write a result file
        write_result("fail", f"unhandled exception: {e}")
        sys.exit(1)
