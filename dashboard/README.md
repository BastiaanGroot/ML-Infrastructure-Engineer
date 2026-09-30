# dashboard

Streamlit app over the Option 1 training experiments, reading MLflow live:

- **Strategy comparison** — steady-state step time, TFLOP/s/GPU and peak
  memory per run (DP/TP/PP/CP/EP, FP8, attention backend, CPU offload,
  recompute), plus per-iteration curves. Runs are filtered by the `run_kind`
  MLflow tag. Nsight-profiled runs (`profile`) are hidden by default since
  `nsys` overhead skews them.
- **Communication** — the NVLink and InfiniBand NCCL all-reduce sweeps and the
  Nsight kernel-time breakdown (NCCL vs GEMM vs attention) from
  [`training/profiles/`](../training/profiles/).
- **Parallelism planner** — [`recommender.py`](recommender.py): an analytical
  model (memory: bf16 weights + fp32 grads + sharded optimizer + activations
  with optional full recompute; time: compute at a given MFU plus TP/PP/DP
  communication over the slowest link each group spans, plus the 1F1B
  bubble) that ranks TP x PP x DP layouts for a model/cluster. Its
  predictions are compared against the measured PoC runs in the app.

## Hosted

`terraform apply -var="enable_mlflow=true" -var="enable_dashboard=true"` in
[`infra/`](../infra/README.md#dashboard-vm) creates a CPU VM that serves it
over plain HTTP with no authentication (`terraform output dashboard_url`).
To deploy new commits of `main` to it:

```bash
ssh <user>@<ip> 'sudo git -C /opt/dashboard/repo pull && sudo systemctl restart dashboard'
```

## Local

```bash
python3 -m venv dashboard/.venv
dashboard/.venv/bin/pip install -r dashboard/requirements.txt
export MLFLOW_TRACKING_URI=https://<tracking-endpoint> MLFLOW_TRACKING_USERNAME=admin
nebius mysterybox payload get-by-key --secret-id mbsec-e00c36r6fzh80jfkc5 \
  --key password --format json > /tmp/pw.json   # file first: CLI may print a "token from" line
export MLFLOW_TRACKING_PASSWORD=$(python3 -c 'import json; t=open("/tmp/pw.json").read(); print(json.loads(t[t.index("{"):])["data"]["string_value"])')
rm /tmp/pw.json
dashboard/.venv/bin/streamlit run dashboard/app.py
```
