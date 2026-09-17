# cluster-validator

A lightweight, portable container that validates a Nebius GPU cluster's
capabilities before running a training or inference job. Covers:

1. **GPU health** — `nvidia-smi` based checks (GPU count, temperature, ECC errors).
2. **GPU interconnect** — NCCL bandwidth via [`nccl-tests`](https://github.com/NVIDIA/nccl-tests) (NVLink within a node; InfiniBand across nodes for the multi-node variant).
3. **LLM smoketest** — loads a tiny open-source causal-LM checkpoint (PyTorch + Transformers) and runs a short `generate()` (inference path) plus one forward+backward pass (training path) on GPU, so the actual ML framework stack is validated, not just raw GPU/NCCL numbers.
4. **Storage throughput** — `fio` against the mounted network disk and shared filesystem.

Built on top of Nebius's own public benchmark image
(`cr.eu-north1.nebius.cloud/nebius-benchmarks/nccl-tests`), which already
ships CUDA, NCCL, the `nccl-tests` binaries, and the Mellanox OFED userspace
components — so most of what we add is a thin validation layer instead of
rebuilding GPU/network tooling from scratch. The one exception is the LLM
smoketest, which needs a real (if minimal) PyTorch + Transformers runtime to
mean anything for an LLM workload — see [`Dockerfile`](Dockerfile) for the
trade-off.

## Build & push

```bash
docker build --platform linux/amd64 -t cr.eu-north1.nebius.cloud/e00qprtt5j85j3syw7/cluster-validator:latest .
nebius registry configure-helper
docker push cr.eu-north1.nebius.cloud/e00qprtt5j85j3syw7/cluster-validator:latest
```

Image lives in the `cluster-validator` registry (`registry-e00qprtt5j85j3syw7`) in the
`ml-infra-poc` project. The registry path in the image tag is the registry ID
*without* the `registry-` prefix. Use `--platform linux/amd64` since the GPU
nodes are x86_64 (relevant when building from an Apple Silicon Mac).

## Run locally (single node, e.g. via SSH on a GPU node)

```bash
docker run --rm --gpus all \
  -v /mnt/network-disk:/mnt/network-disk \
  -v /mnt/shared-fs:/mnt/shared-fs \
  cr.eu-north1.nebius.cloud/e00qprtt5j85j3syw7/cluster-validator:latest
```

## Run on the cluster

- **Single-node checks** (GPU health + NCCL within one node + LLM smoketest + storage): `k8s/job-validate.yaml`
- **Multi-node InfiniBand check** (2x 8-GPU nodes, matching the 16-GPU PoC capacity): `k8s/job-nccl-multinode.yaml` (requires the [MPI Operator](https://github.com/kubeflow/mpi-operator)). This targets the **future** node group — see the root README's ["Future hardware: 2x8-GPU nodes with InfiniBand"](../README.md#future-hardware-2x8-gpu-nodes-with-infiniband) for the full switch plan (preset, GPU-cluster resource, MPI Operator install).

```bash
kubectl apply -f k8s/job-validate.yaml
kubectl logs -f job/cluster-validator
```

Node groups need a service account with at least `viewer` role attached to pull
from Container Registry without extra auth (see [Nebius docs](https://docs.nebius.com/kubernetes/workloads/images-container-registry)).
If a node group lacks this (e.g. a quick test cluster), create an
`imagePullSecrets` entry from a short-lived token instead:

```bash
TOKEN=$(nebius iam get-access-token)
kubectl create secret docker-registry nebius-registry \
  --docker-server=cr.eu-north1.nebius.cloud --docker-username=iam --docker-password="$TOKEN"
# then add `imagePullSecrets: [{name: nebius-registry}]` to the pod spec
```

(`--docker-password-stdin` isn't supported by all `kubectl` versions — use `--docker-password` with the token in a variable instead. The token is short-lived, so recreate the secret if it expires.)

## Configuration

All checks are controlled via environment variables (see comments at the top of each script in `scripts/`):

| Variable | Default | Purpose |
|---|---|---|
| `RUN_GPU_HEALTH` / `RUN_NCCL` / `RUN_LLM_SMOKETEST` / `RUN_STORAGE` | `true` | Enable/disable a check |
| `EXPECTED_GPU_COUNT` | unset | Fail if detected GPU count differs |
| `MAX_GPU_TEMP_C` | `85` | Max acceptable GPU temperature |
| `NCCL_BENCH_ARGS` | `-b 512M -e 8G -f 2 -g <local GPU count>` | Args passed to `all_reduce_perf` |
| `NCCL_MIN_BUSBW_GBPS` | `100` | Minimum acceptable avg bus bandwidth |
| `LLM_SMOKETEST_MODEL_PATH` | `/opt/validate/tiny-llm` | Path to the baked-in tiny checkpoint |
| `LLM_SMOKETEST_PROMPT` | `"Nebius GPU cluster validation:"` | Prompt used for the smoketest |
| `LLM_SMOKETEST_MAX_NEW_TOKENS` | `20` | Tokens to generate during the smoketest |
| `STORAGE_PATHS` | `/mnt/network-disk,/mnt/shared-fs` | Comma-separated paths to benchmark (skipped if not mounted) |
| `FIO_SIZE` / `FIO_RUNTIME` | `1G` / `20` | fio test file size / duration per path |
| `FIO_MIN_THROUGHPUT_MBPS` | unset | Optional minimum read+write throughput |
| `UPLOAD_LOGS_BUCKET` | unset | If set, uploads `summary.json` to this Object Storage bucket after the run |
| `UPLOAD_LOGS_ENDPOINT` | `https://storage.eu-north1.nebius.cloud` | S3-compatible endpoint for the upload |
| `UPLOAD_LOGS_PREFIX` | `cluster-validator` | Object key prefix (full key: `<prefix>/<hostname>/<timestamp>/summary.json`) |

## Uploading logs to Object Storage

`run.sh` optionally uploads `summary.json` to a Nebius Object Storage bucket
at the end of a run (in addition to the stdout logs already shipped to
Nebius Logging — see [`docs/observability.md`](../docs/observability.md)),
useful for retention past Logging's 14-day default. **Live and verified
end-to-end** via [`k8s/job-validate.yaml`](k8s/job-validate.yaml), which
sets `UPLOAD_LOGS_BUCKET=ml-infra-poc-logs` and an `envFrom` secret ref for
the AWS-style credentials. Example object from a real run:
`s3://ml-infra-poc-logs/cluster-validator/cluster-validator-wsqfc/20260917T120216Z/summary.json`.

Everything needed to grant a workload write access is defined in
[`infra/main.tf`](../infra/main.tf) — no manual IAM console/CLI step:

- `nebius_storage_v1_bucket.logs` — the bucket (`ml-infra-poc-logs`), with a
  `bucket_policy` rule granting `storage.editor` on `*` to an IAM group.
- `nebius_iam_v1_service_account.cluster_validator_logs` — the workload
  identity.
- `nebius_iam_v1_group.cluster_validator_logs_writers` +
  `nebius_iam_v1_group_membership` — the service account joins this group
  (Nebius Object Storage roles are only grantable to a *group* in a bucket
  policy, not straight to a service account, so this group exists purely to
  satisfy that).

The one thing Terraform can't do is mint an actual access key (it's a
secret, deliberately not something you want in state). Create it once,
delivered straight into SecretStash (Nebius's secrets-management service —
CLI/API name `mysterybox`) so the plaintext never touches your terminal
history, then wire it into a Kubernetes Secret:

```bash
nebius iam v2 access-key create \
  --parent-id <project-id> \
  --account-service-account-id "$(terraform -chdir=../infra output -raw cluster_validator_logs_service_account_id)" \
  --description "cluster-validator logs upload" --secret-delivery-mode mystery_box
# note status.aws_access_key_id (non-secret) and status.secret_reference_id
# (the SecretStash secret holding the actual secret value, never printed)

kubectl create secret generic cluster-validator-logs-creds \
  --from-literal=AWS_ACCESS_KEY_ID=<status.aws_access_key_id> \
  --from-literal=AWS_SECRET_ACCESS_KEY="$(nebius mysterybox payload get-by-key --secret-id <status.secret_reference_id> --key secret --format json 2>&1 | grep -v 'token from' | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["string_value"])')"
# (the `grep -v` strips a stray "token from NEBIUS_IAM_TOKEN env is used"
# line the CLI prints to stdout when using that auth method — see the
# ops-gotchas rule)
```

Because the secret lives in SecretStash (not just a one-time CLI printout),
rebuilding the Kubernetes Secret later (new cluster, rotated context, etc.)
is a matter of re-running the `kubectl create secret` step above with the
same `--secret-id` — no need to regenerate the access key or ever see the
plaintext value outside that one command substitution.

The upload is best-effort: a failure logs a warning but doesn't change the
overall validation exit code (see `upload_logs.py`/`upload_logs.sh`).

## Grafana dashboard

[`grafana/cluster-validator-dashboard.json`](grafana/cluster-validator-dashboard.json)
combines GPU temp/utilization/power (from the pre-wired "Nebius Services"
Prometheus datasource — see [observability.md](../docs/observability.md) for
why that one and not "Nebius Monitoring") with `cluster-validator` logs
(from Nebius Logging) on one screen, filterable by node. Import it into
the cluster's Grafana:

```bash
curl -u admin:<password> -X POST -H "Content-Type: application/json" \
  -d "{\"dashboard\": $(cat grafana/cluster-validator-dashboard.json), \"overwrite\": true}" \
  http://<grafana-host>/api/dashboards/db
```

## Output

Each check writes a JSON result to `$RESULTS_DIR/<check>.json` (default
`/results`), and `run.sh` aggregates them into `$RESULTS_DIR/summary.json`
plus a human-readable log on stdout. Exit code is `0` only if every enabled
check passed. If `UPLOAD_LOGS_BUCKET` is set, `summary.json` is also uploaded
to Object Storage (see above).

## Results (last validated run)

Ran via `k8s/job-validate.yaml` on the live PoC cluster (2x `gpu-h200-sxm`
nodes, 1 GPU each, 2 TiB shared filesystem, 2 TiB network-disk PVC) on
2026-09-17. Full `summary.json`:

```json
[
  {
    "name": "gpu_health",
    "status": "pass",
    "message": "1 GPU(s) healthy, max temp 29C",
    "metrics": { "gpu_count": 1, "max_temp_c": 29, "uncorrectable_ecc_errors": 0, "corrected_ecc_errors": 0 }
  },
  {
    "name": "nccl_bench",
    "status": "fail",
    "message": "avg bus bandwidth 0 GB/s below threshold 100 GB/s",
    "metrics": { "gpu_count": 1, "avg_busbw_gbps": 0, "out_of_bounds": 0 }
  },
  {
    "name": "llm_smoketest",
    "status": "pass",
    "message": "generated 20 tokens and completed a backward pass on NVIDIA H200",
    "metrics": { "device_name": "NVIDIA H200", "load_seconds": 0.297, "generation_seconds": 0.344, "tokens_generated": 20, "backward_pass_ok": true }
  },
  {
    "name": "storage_bench",
    "status": "pass",
    "message": "storage benchmark completed for: /mnt/network-disk, /mnt/shared-fs",
    "metrics": {
      "paths": [
        { "path": "/mnt/network-disk", "read_bw_mbps": 219.6, "write_bw_mbps": 223.7, "read_iops": 219.6, "write_iops": 223.7 },
        { "path": "/mnt/shared-fs", "read_bw_mbps": 2012.6, "write_bw_mbps": 2007.3, "read_iops": 2012.6, "write_iops": 2007.3 }
      ]
    }
  }
]
```

**Reading these:**

- **GPU health** — pass. `nvidia-smi` reports a healthy H200 (143 GiB HBM3e), 29°C idle, zero ECC errors.
- **NCCL bench — expected fail, not a bug.** `all_reduce_perf -g 1` has nothing
  to actually reduce across on a single-GPU node, so bus bandwidth reads `0`
  and trips the (NVLink/IB-oriented) 100 GB/s threshold. This check only
  becomes meaningful once nodes have ≥2 GPUs — see the [multi-node /
  future-hardware note](../README.md#future-hardware-2x8-gpu-nodes-with-infiniband)
  for the 8-GPU + InfiniBand plan this is written for.
- **LLM smoketest — pass.** A real `generate()` (inference) plus one
  forward+backward pass (training) both ran successfully on GPU in well
  under a second, confirming the PyTorch/CUDA/Transformers stack works end
  to end, not just raw `nvidia-smi` numbers.
- **Storage bench — pass, and the two paths land very differently, as expected:**
  the network-disk PVC (`compute-csi-default-sc`, backed by a Nebius Network
  SSD block volume over the network) does ~220 MB/s read+write; the
  shared-fs mount (Nebius Shared Filesystem, `virtiofs`) does ~2 GB/s — a
  10x difference that reflects the different storage backends, not a
  misconfiguration. Neither a `FIO_MIN_THROUGHPUT_MBPS` threshold was set for
  this run, so both simply report their numbers.

**Live view while a job runs:** the [Grafana dashboard](#grafana-dashboard)
above overlays GPU temp/utilization/power from Nebius Services with
`cluster-validator`'s own log lines from Nebius Logging, filterable by node —
see [`docs/observability.md`](../docs/observability.md) for the verified
agent → Logging/Monitoring → Grafana pipeline and an example LogQL query.
