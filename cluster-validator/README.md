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
- **Multi-node InfiniBand check** (2x 8-GPU nodes, matching the 16-GPU PoC capacity): `k8s/job-nccl-multinode.yaml` (requires the [MPI Operator](https://github.com/kubeflow/mpi-operator)). This targets the **future** node group once we switch from the current 1-GPU-per-node preset to `8gpu-128vcpu-1600gb` x 2 nodes (see the root README's Design Choices) — the Nebius Solutions Library's [`k8s-training`](https://github.com/nebius/nebius-solutions-library/tree/main/k8s-training) module confirms this is the correct preset name for InfiniBand-connected 8-GPU nodes.

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

`run.sh` can optionally upload `summary.json` to a Nebius Object Storage
bucket at the end of a run (in addition to the stdout logs already shipped to
Nebius Logging — see [`docs/observability.md`](../docs/observability.md)),
useful for retention past Logging's 14-day default. [`infra/main.tf`](../infra/main.tf)
defines a `nebius_storage_v1_bucket` (`<cluster_name>-logs`) for this; it
hasn't been applied against the live project yet (see `infra/README.md`).

To use it, set `UPLOAD_LOGS_BUCKET` (and optionally `UPLOAD_LOGS_ENDPOINT` /
`UPLOAD_LOGS_PREFIX`) plus S3 credentials with write access to the bucket.
Create a Nebius IAM (AWS-compatible) access key for a service account,
delivered straight into SecretStash (Nebius's secrets-management service —
CLI/API name `mysterybox`) so the secret value never touches your terminal
or shell history, then wire it into a Kubernetes Secret, similar to the
registry pull-secret pattern above:

```bash
nebius iam v2 access-key create \
  --parent-id <project-id> --account-service-account-id <service-account-id> \
  --description "cluster-validator logs upload" --secret-delivery-mode mystery_box
# note metadata.id (the access key's own ID) and status.aws_access_key_id
# from the output - both non-secret. status.secret_reference_id is the
# SecretStash secret holding the actual secret value (never printed).

kubectl create secret generic cluster-validator-logs-creds \
  --from-literal=AWS_ACCESS_KEY_ID=<status.aws_access_key_id> \
  --from-literal=AWS_SECRET_ACCESS_KEY="$(nebius mysterybox payload get-by-key --secret-id <status.secret_reference_id> --key secret)"
# then reference both keys via `envFrom: [{secretRef: {name: cluster-validator-logs-creds}}]`
# in the Job's pod spec, alongside UPLOAD_LOGS_BUCKET=<cluster_name>-logs.
```

Because the secret lives in SecretStash (not just a one-time CLI printout),
rebuilding the cluster or the Kubernetes Secret later is a matter of
re-running the `kubectl create secret` step above with the same
`--secret-id` — no need to regenerate the access key or have ever seen the
plaintext value.

The upload is best-effort: a failure logs a warning but doesn't change the
overall validation exit code (see `upload_logs.py`/`upload_logs.sh`).

## Grafana dashboard

[`grafana/cluster-validator-dashboard.json`](grafana/cluster-validator-dashboard.json)
combines GPU temp/utilization/power (from Nebius Monitoring, via the
[Nebius Observability Agent](../docs/observability.md)) with `cluster-validator`
logs (from Nebius Logging) on one screen, filterable by node. Import it into
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
