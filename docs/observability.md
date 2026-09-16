# Observability: metrics + logs

## Setup (done)

- **Nebius Observability Agent for Kubernetes** installed (Helm, `observability`
  namespace) on the `neb` test cluster — ships pod stdout logs → Nebius
  Logging and node/pod metrics → Nebius Monitoring, no extra auth needed
  (uses the node's own identity).
- **Grafana** was already deployed on the cluster (the "Grafana solution by
  Nebius" app, installed automatically at cluster creation) — Prometheus,
  Loki, and Tempo data sources are pre-wired, with Nebius dashboards
  preloaded (GPU, disk, shared-fs, node-exporter).
- **Verified end-to-end**: re-ran `cluster-validator`, then queried Nebius
  Logging directly — all of its output (including the `nccl_bench` result
  line) showed up within seconds:
  ```bash
  nebius logging query '{k8s_pod_name="<pod>"}' --bucket default --since 10m
  ```

No self-hosted Loki/Prometheus needed — Nebius's own Monitoring/Logging are
Prometheus/Loki-API-compatible, so Grafana just points at them directly.

## Is this (Loki-compatible logging) the right approach?

**Yes, for our use case** — cluster/job debugging logs (GPU health, NCCL,
storage, training/inference stdout):

- Already proven working: agent → Nebius Logging → LogQL query / Grafana, no
  extra plumbing.
- Text search (`|= "error"`, regex, label filters) covers what we need to
  debug a validator or job run.
- 14-day retention is plenty for a PoC; export to Object Storage
  (JSON/Parquet) if longer-term storage is ever needed.
- Free during the service's current preview stage.

**Known limitations to keep in mind:**

- **No alerting on aggregated LogQL metrics.** If we ever want an automatic
  alert like "NCCL bandwidth dropped below 100 GB/s", parsing that out of log
  lines won't support alerting — we'd need to emit it as a real *metric*
  (e.g. via the agent's OTLP endpoint) rather than relying on logs for that.
- A handful of LogQL functions are unsupported (`topk`/`bottomk` without
  label aggregation, `sort`, `bytes_rate`, `vector`, etc.) — fine for our
  simple filter/search needs, but worth knowing if queries get fancier.
- 14-day retention is a hard default; longer needs a support request.

## Next steps (optional)

- Add a Grafana dashboard panel: `{app="cluster-validator"}` logs next to
  node GPU metrics, for a one-screen view per validation run.
- If pass/fail thresholds need real alerting later, emit them as metrics
  instead of (or in addition to) log lines.
