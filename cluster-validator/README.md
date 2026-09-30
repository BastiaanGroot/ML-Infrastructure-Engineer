# cluster-validator

A lightweight, portable container that validates a Nebius GPU cluster's
capabilities before running a training or inference job. Covers:

1. **GPU health** — `nvidia-smi` based checks (GPU count, temperature, ECC errors).
2. **GPU interconnect** — NCCL `all_reduce` bandwidth via [`nccl-tests`](https://github.com/NVIDIA/nccl-tests): NVLink within each node, and InfiniBand across both nodes (all 16 GPUs, launched with `mpirun`).
3. **LLM smoketest** — loads a real, minimal Qwen3-0.6B checkpoint (PyTorch + Transformers, same model family as [`training/`](../training/README.md)) and runs a short `generate()` (inference path) plus one forward+backward pass (training path) on GPU, so the actual ML framework stack is validated, not just raw GPU/NCCL numbers.
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
docker build --platform linux/amd64 -t cr.eu-north1.nebius.cloud/e00qprtt5j85j3syw7/cluster-validator:v7 .
nebius registry configure-helper
docker push cr.eu-north1.nebius.cloud/e00qprtt5j85j3syw7/cluster-validator:v7
```

Bump the tag on every change and update it in
[`k8s/job-validate.yaml`](k8s/job-validate.yaml) and
[`k8s/job-validate-multinode.yaml`](k8s/job-validate-multinode.yaml) to match (currently `v7`).

Image lives in the `cluster-validator` registry (`registry-e00qprtt5j85j3syw7`) in the
`ml-infra-poc` project. The registry path in the image tag is the registry ID
*without* the `registry-` prefix. Use `--platform linux/amd64` since the GPU
nodes are x86_64 (relevant when building from an Apple Silicon Mac).

## Run locally (single node, e.g. via SSH on a GPU node)

```bash
docker run --rm --gpus all \
  -v /mnt/network-disk:/mnt/network-disk \
  -v /mnt/shared-fs:/mnt/shared-fs \
  cr.eu-north1.nebius.cloud/e00qprtt5j85j3syw7/cluster-validator:v7
```

## Run on the cluster

Two Jobs, both one pod per GPU node (Indexed Jobs with pod anti-affinity):

- **Per-node checks** ([`k8s/job-validate.yaml`](k8s/job-validate.yaml)):
  GPU health, NCCL across the node's 8 GPUs, LLM smoketest and storage, on
  every node. Each pod gets its own fresh 2Ti network disk (an ephemeral
  volume, deleted with the pod) plus the shared filesystem.
- **Cross-node InfiniBand** ([`k8s/job-validate-multinode.yaml`](k8s/job-validate-multinode.yaml),
  [`scripts/nccl_multinode.sh`](scripts/nccl_multinode.sh)): one
  `all_reduce_perf` process per GPU across all 16 GPUs. Every pod runs
  `sshd`, and pod 0 launches the processes with `mpirun` over SSH, using the
  Open MPI already in the base image, so no MPI Operator is needed. The pods
  are privileged with `/dev/infiniband` mounted, like the training workers.
  It needs a one-time SSH keypair Secret:
  ```bash
  ssh-keygen -t ed25519 -N "" -f /tmp/cv_ssh -q
  kubectl create secret generic cluster-validator-ssh \
    --from-file=id_ed25519=/tmp/cv_ssh --from-file=id_ed25519.pub=/tmp/cv_ssh.pub
  rm /tmp/cv_ssh /tmp/cv_ssh.pub
  ```

```bash
kubectl apply -f k8s/job-validate.yaml
kubectl logs -l job-name=cluster-validator --prefix --tail=-1   # both nodes, once done
kubectl delete job cluster-validator                   # both Jobs need the whole cluster
kubectl apply -f k8s/job-validate-multinode.yaml
kubectl logs -f job/cluster-validator-multinode        # pod 0 prints the result
kubectl delete job,svc cluster-validator-multinode
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
| `LLM_SMOKETEST_MODEL_PATH` | `/opt/validate/qwen3-0.6b` | Path to the baked-in Qwen3-0.6B checkpoint |
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
overall validation exit code (see `upload_logs.py`).

## Grafana dashboard

[`grafana/cluster-validator-dashboard.json`](grafana/cluster-validator-dashboard.json)
combines GPU temp/utilization/power (from the pre-wired "Nebius Services"
Prometheus datasource — see [observability.md](../docs/observability.md) for
why that one and not "Nebius Monitoring") with `cluster-validator` logs
(from Nebius Logging) on one screen, filterable by node. It defaults to the
last 24 hours; a validator run lasts minutes, so widen the range to find
older runs. Two log panels:

- **Check results**: only each check's pass/fail line, the per-path storage
  numbers and the final `RESULT:` line.
- **cluster-validator logs**: everything, including the full
  `all_reduce_perf` bandwidth table.

Import it into the cluster's Grafana:

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

Ran on the live cluster (2 nodes x 8 H100 SXM, InfiniBand, 2 TiB shared
filesystem, a 2 TiB network disk per validator pod): the per-node Job on
2026-09-29 with image `v4`, the cross-node Job on 2026-09-30 with `v5`.
All checks passed on both nodes. Re-running both Jobs with the current `v7`
on 2026-09-30 passed again with the same numbers within a few percent
(NVLink 467.8/465.8 GB/s, cross-node 451.9 GB/s). Each pod uploads its `summary.json` to
`s3://ml-infra-poc-logs/cluster-validator/<pod-hostname>/<timestamp>/`.

**Per node** ([`k8s/job-validate.yaml`](k8s/job-validate.yaml)):

| Check | Node `computeinstance-e00qyx0nfcpnbgnk4z` | Node `computeinstance-e00gdss5xpj5gbybcs` |
|---|---|---|
| GPU health | 8 GPUs, max 26°C, 0 ECC errors | 8 GPUs, max 34°C, 0 ECC errors |
| NCCL, 8 GPUs over NVLink (avg bus bandwidth) | 467.9 GB/s | 465.7 GB/s |
| LLM smoketest (Qwen3-0.6B generate + backward) | pass | pass |
| Network disk, read / write | 217 / 222 MB/s | 218 / 223 MB/s |
| Shared filesystem, read / write | 1570 / 1572 MB/s | 1669 / 1673 MB/s |

**Across nodes** ([`k8s/job-validate-multinode.yaml`](k8s/job-validate-multinode.yaml)):
`all_reduce_perf` over all 16 GPUs averages **450.8 GB/s** bus bandwidth
(threshold 300), with 0 out-of-bounds values:

| Message size | 512 MiB | 1 GiB | 2 GiB | 4 GiB | 8 GiB |
|---|---|---|---|---|---|
| Bus bandwidth (out-of-place) | 414.6 GB/s | 446.8 GB/s | 459.5 GB/s | 465.9 GB/s | 459.7 GB/s |

**Reading these:**

- **GPU health**: all 16 H100s visible and healthy, zero ECC errors.
- **NCCL**: within a node, NVLink averages ~467 GB/s over 512 MiB-8 GiB,
  well above the 100 GB/s threshold. Across both nodes, all 16 GPUs reach
  447 GB/s at 1 GiB, within a few percent of NVLink, because NCCL uses all
  8 InfiniBand NICs per node. This matches the training NCCL sweep's
  442 GB/s (see [`training/README.md`](../training/README.md#nccl-bandwidth)).
- **LLM smoketest**: a real Qwen3-0.6B checkpoint (same model family as
  [`training/`](../training/README.md)) generates 20 tokens and completes a
  forward and backward pass on GPU, so the PyTorch/CUDA/Transformers stack
  works end to end, not just `nvidia-smi`.
- **Storage bench**: the network disk (`compute-csi-default-sc`, a Nebius
  Network SSD volume) does ~220 MB/s read and write on both nodes. The
  shared filesystem (`virtiofs`) does ~1.6 GB/s, about 7x faster; the gap
  comes from the storage backends, not misconfiguration. No
  `FIO_MIN_THROUGHPUT_MBPS` threshold was set, so both just report numbers.

**Live view while a job runs:** the [Grafana dashboard](#grafana-dashboard)
above overlays GPU temp/utilization/power from Nebius Services with
`cluster-validator`'s own log lines from Nebius Logging, filterable by node —
see [`docs/observability.md`](../docs/observability.md) for the verified
agent → Logging/Monitoring → Grafana pipeline and an example LogQL query.
