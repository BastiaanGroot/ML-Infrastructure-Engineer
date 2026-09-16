# cluster-validator

A lightweight, portable container that validates a Nebius GPU cluster's
capabilities before running a training or inference job. Covers:

1. **GPU health** — `nvidia-smi` based checks (GPU count, temperature, ECC errors).
2. **GPU interconnect** — NCCL bandwidth via [`nccl-tests`](https://github.com/NVIDIA/nccl-tests) (NVLink within a node; InfiniBand across nodes for the multi-node variant).
3. **Storage throughput** — `fio` against the mounted network disk and shared filesystem.

Built on top of Nebius's own public benchmark image
(`cr.eu-north1.nebius.cloud/nebius-benchmarks/nccl-tests`), which already
ships CUDA, NCCL, the `nccl-tests` binaries, and the Mellanox OFED userspace
components — so we only add a thin validation layer instead of rebuilding
GPU/network tooling from scratch.

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

- **Single-node checks** (GPU health + NCCL within one node + storage): `k8s/job-validate.yaml`
- **Multi-node InfiniBand check** (2x 8-GPU nodes, matching the 16-GPU PoC capacity): `k8s/job-nccl-multinode.yaml` (requires the [MPI Operator](https://github.com/kubeflow/mpi-operator))

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
| `RUN_GPU_HEALTH` / `RUN_NCCL` / `RUN_STORAGE` | `true` | Enable/disable a check |
| `EXPECTED_GPU_COUNT` | unset | Fail if detected GPU count differs |
| `MAX_GPU_TEMP_C` | `85` | Max acceptable GPU temperature |
| `NCCL_BENCH_ARGS` | `-b 512M -e 8G -f 2 -g <local GPU count>` | Args passed to `all_reduce_perf` |
| `NCCL_MIN_BUSBW_GBPS` | `100` | Minimum acceptable avg bus bandwidth |
| `STORAGE_PATHS` | `/mnt/network-disk,/mnt/shared-fs` | Comma-separated paths to benchmark (skipped if not mounted) |
| `FIO_SIZE` / `FIO_RUNTIME` | `1G` / `20` | fio test file size / duration per path |
| `FIO_MIN_THROUGHPUT_MBPS` | unset | Optional minimum read+write throughput |

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
check passed.
