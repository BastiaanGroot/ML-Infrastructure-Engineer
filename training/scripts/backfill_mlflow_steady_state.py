#!/usr/bin/env python3
"""One-off: backfill steady-state metrics and run_kind tags onto MLflow runs
logged before run_experiment.py captured them itself.

Those runs only logged whole-run averages (wall time incl. startup and eval),
e.g. DP=2 step_time_sec 8.7s vs 2.29s steady-state. The values below are the
iteration 2-20 averages of each run's "Step Time : ...s GPU utilization:
...TFLOP/s/GPU" pod-log lines - the same numbers as ../README.md's tables.
Re-running is safe: it overwrites the same metrics/tags.

Requires MLFLOW_TRACKING_URI / MLFLOW_TRACKING_USERNAME / MLFLOW_TRACKING_PASSWORD.
"""

from mlflow.tracking import MlflowClient

# run_id: (run_kind, steady_step_time_sec, steady_tflops_per_gpu)
RUNS = {
    "14a3393a0c63406a9487453d382eff50": ("experiment", 2.29, 42.0),  # dp-baseline
    "0aa09cd060a940dfadee442e327ea18d": ("experiment", 1.73, 27.9),  # tp 1.7B
    "02bd574d2db94f018047f503c7a2db80": ("experiment", 1.00, 95.8),  # pp
    "167b0ae1dbb243e79e044406bfc70638": ("experiment", 2.74, 47.7),  # cp seq16384
    "65123a0219e049a795e1c867d1c78a42": ("experiment", 2.43, 107.6),  # dp seq16384
    "38a8c403b6e04462a5985d7f8c3a9312": ("experiment", 2.0642, 46.73),  # fp8
    "bc376002cdba4cb09c40bf61113f97b6": ("experiment", 2.2958, 41.91),  # unfused attn
    "3fd91e0b292a454da1198221ccd85571": ("experiment", 2.2679, 42.39),  # cpu offload
    "bad599f9a4c949cdaf375115bac5a330": ("profile", 2.4816, 38.86),  # nsys dp
    "bf7b007498ea49d981fd68b0f86cfed2": ("profile", 2.3568, 20.44),  # nsys tp, seq-parallel
    "175f94f1b5dc437b8c873937b5b5712c": ("profile", 1.8984, 25.35),  # nsys tp
    "16bdeb9f518b43aca88dc4c815815786": ("superseded", None, None),  # tp Qwen3-4B
    "017032ab07314753bc71c0d9d59b6cef": ("benchmark", None, None),  # nccl sweep
}
EXTRA_TAGS = {
    "bf7b007498ea49d981fd68b0f86cfed2": {"sequence_parallel": "true"},
}


def main() -> None:
    client = MlflowClient()
    for run_id, (run_kind, step_time, tflops) in RUNS.items():
        client.set_tag(run_id, "run_kind", run_kind)
        for key, value in EXTRA_TAGS.get(run_id, {}).items():
            client.set_tag(run_id, key, value)
        if step_time is not None:
            client.log_metric(run_id, "steady_step_time_sec", step_time)
            client.log_metric(run_id, "steady_tflops_per_gpu", tflops)
            client.set_tag(run_id, "steady_state_source", "backfilled_from_pod_logs")
        print(f"{run_id} -> {run_kind}")


if __name__ == "__main__":
    main()
