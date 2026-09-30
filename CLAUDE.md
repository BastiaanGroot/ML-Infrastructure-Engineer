# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A take-home PoC for a Nebius ML Infrastructure Engineer role
(`docs/ML-Infrastructure-Engineer.md`): validate a Nebius GPU cluster, then
run multi-node LLM training on it. It operates a **real, live Nebius
project** (`ml-infra-poc`, tenant `csa-hiring-sandbox2`) — this is not a
sandbox with mocked infra. Terraform applies, `kubectl` commands, and
`docker push` in this repo affect real cloud resources and real GPU jobs.
See the root `README.md` end to end before making infra/training changes;
it's the canonical source for hardware layout, design rationale, and
reproduction steps — don't duplicate its content elsewhere in the repo.

There is no unit test suite. "Correctness" here means: `terraform plan`
shows no unexpected diff, the validator/training Jobs actually pass on the
live cluster, and results get recorded in the relevant README's Results
section with real numbers from a real run.

## Repo layout (four independent pieces + docs)

- **`infra/`** — Terraform for everything shared: VPC, mk8s cluster, GPU
  node group (2x8 H100 in an InfiniBand `nebius_compute_v1_gpu_cluster`),
  shared filesystem, container registry, Object Storage logs bucket, gated
  managed MLflow (`enable_mlflow`), gated dashboard VM (`enable_dashboard`).
  State is local and gitignored — never committed, never shared.
- **`cluster-validator/`** — a container (built on Nebius's `nccl-tests`
  base image) run as Kubernetes Jobs to validate the cluster before
  training: GPU health, NCCL/NVLink+InfiniBand bandwidth, an LLM smoketest
  (real Qwen3-0.6B checkpoint), and storage throughput (`fio`). Two Jobs:
  per-node (`job-validate.yaml`) and cross-node InfiniBand via `mpirun`
  over SSH (`job-validate-multinode.yaml`, no MPI Operator).
- **`training/`** — Option 1 (multi-node LLM training) implementation.
  `launch.py` holds the experiment matrix and renders one Job template
  (`k8s/worker.yaml.tmpl`, an Indexed Job = one `torchrun` pod per node) per
  experiment. Runs on stock `nvcr.io/nvidia/nemo:25.09`; `scripts/run_experiment.py`
  calls Megatron-Bridge's Qwen3 recipes directly (that image's
  Megatron-Bridge version predates the generic launcher) and logs to MLflow.
- **`dashboard/`** — Streamlit app reading MLflow live: strategy comparison,
  NCCL/Nsight communication view, and an analytical TP x PP x DP planner
  (`recommender.py`) validated against the measured runs. Hosted on the
  Terraform-managed VM from `infra/dashboard.tf`.
- **`docs/`** — the assignment, a service overview, the observability
  design/verification, and `training-strategy-outline.md` (the full
  distribution-strategy design that `training/` implements a subset of).

Each of `infra/`, `cluster-validator/`, `training/`, `dashboard/` has its
own README with the authoritative commands and current results — read the
relevant one before working in that directory rather than relying on
summaries elsewhere.

## Common commands

```bash
# infra: always export a fresh token first, always plan before apply
export NEBIUS_IAM_TOKEN=$(nebius iam get-access-token | tr -d '\n\r')
cd infra && terraform plan && terraform apply

# cluster-validator: build (amd64 even from Apple Silicon), push, bump tag everywhere it's referenced
docker build --platform linux/amd64 -t cr.eu-north1.nebius.cloud/<registry>/cluster-validator:vN cluster-validator
docker push cr.eu-north1.nebius.cloud/<registry>/cluster-validator:vN
kubectl apply -f cluster-validator/k8s/job-validate.yaml
kubectl logs -l job-name=cluster-validator --prefix --tail=-1
kubectl delete job cluster-validator   # both validator Jobs need the whole cluster

# training: list/launch experiments, one Job claims both nodes
./training/launch.py --list
./training/launch.py <experiment-name>
kubectl logs -f job/<experiment-name>
kubectl delete job,svc <experiment-name>   # before starting the next one

# dashboard, local
python3 -m venv dashboard/.venv && dashboard/.venv/bin/pip install -r dashboard/requirements.txt
dashboard/.venv/bin/streamlit run dashboard/app.py
```

There's no `pyproject.toml`-managed application code (`tool.uv.package =
false`; `dependencies = []`) — it exists only so the repo has a proper `uv`
structure. Python code lives per-component with its own
`requirements.txt`/inline deps (`dashboard/`, `training/scripts/`,
`cluster-validator/scripts/`).

## Operational gotchas (checked before re-debugging)

- `NEBIUS_IAM_TOKEN=$(nebius iam get-access-token)` pollutes stdout with a
  `"token from ... is used"` line even under `--format json` — never pipe
  straight into `jq`/`json.tool`; redirect to a file or `grep -v` it first.
  Strip the token itself of newlines (`tr -d '\n\r'`).
- `mysterybox payload get-by-key --format json` — the secret value is at
  `.data.string_value`, not top-level. A secret's `id` (`mbsec-...`) is a
  container, not the value. Soft-deleted secrets only show up in `list`
  with `--show-scheduled-for-deletion`.
- `enable_mlflow` / `enable_dashboard` default to `true` in `infra/` —
  passing `-var="...=false"` on a `plan`/`apply` **destroys** MLflow (and
  its tracking data) or the dashboard VM. Always pass both `=true`
  explicitly unless you actually intend to tear one down.
- Some resources force full replacement on attribute change (e.g. MLflow's
  `public_access`, a VM's `cloud_init_user_data` via `-replace=`) —
  destroy+recreate, new ID. Always check the plan for `-/+` and confirm with
  the user before applying. (Terraform plans a VM `cloud_init_user_data`
  change as in-place, but the API rejects it on a running instance — hence
  `-replace=` on the stateless dashboard VM.)
- HCL heredocs: don't mix `<<-` dedenting with a `%{if~}` directive as the
  first line — use a left-flush `<<EOT` to avoid spurious diffs.
- The VPC's default security group allows all ingress — give any public-IP
  VM its own security group with only the needed ports.
- In-cluster DNS (2 CoreDNS replicas, `cache 30`) can keep serving a cached
  NXDOMAIN for a pod name that just started resolving — resolve peers once
  and use the IP (see `cluster-validator/scripts/nccl_multinode.sh`).
- The local kubeconfig's default context may point at an unrelated cluster —
  check `kubectl config current-context` before applying anything, or use a
  dedicated kubeconfig from `nebius mk8s cluster get-credentials --kubeconfig`.
- `kubectl exec` fails on terminated Job pods — use a short-lived debug pod
  with the same volume mounts instead.
- Platform-managed baseline addons (`kube-system`/`observability` Helm
  releases installed at cluster creation, e.g. `nebius-dcgm`, `cilium`)
  aren't ours to edit or delete — verify live, don't trust memory of past
  edits.
- GPU host metrics come from the Observability Agent's own `dcgmreceiver`,
  in the **"Nebius Services"** Prometheus datasource (`instance_id` label)
  — not "Nebius Monitoring" (stays empty for GPU data), and not the
  in-cluster `nebius-dcgm` DaemonSet (redundant/broken).
- Grafana `datasource`-type template variables default to the
  alphabetically-first matching datasource, ignoring `isDefault` — always
  set an explicit `current` in dashboard JSON.
- GPU capacity on this tenant is tight — even 1-GPU replacements can hit
  transient `NotEnoughResources`; this usually self-resolves via platform
  retries within tens of minutes.
- Object Storage bucket permissions are grantable to an IAM *group* only,
  never directly to a service account — grant via a group +
  `bucket_policy.rules[].group_id`, fully in Terraform.
- Privileged containers (training/validator pods use `/dev/infiniband`) see
  every GPU on the node regardless of what they requested — each pod claims
  the whole node and uses only its first `NPROC` GPUs.

## Working conventions

- **Cost is not a constraint** in this project's Nebius sandbox — provision,
  resize, or leave real resources running as needed without asking for
  cost-based confirmation. Still confirm before genuinely destructive
  actions (deleting resources, applies that would down GPU nodes/data or
  destroy MLflow/dashboard) and before any `git push` to `main`.
- Commit at logical checkpoints (one feature/fix/self-contained change per
  commit) rather than batching unrelated changes. Never push to `main`
  without explicit confirmation, even if the user already asked once
  earlier in the session.
- When changing anything about the 2-node H100/InfiniBand hardware setup,
  update the single canonical note in the root README
  (`README.md#hardware-2x8-h100-with-infiniband`) rather than duplicating
  detail elsewhere — other docs intentionally just link to it.
- The Nebius MCP server (`.cursor/mcp.json`, `SAFE_MODE=true`) is available
  for direct Nebius resource queries/management as an alternative to the
  `nebius` CLI.
