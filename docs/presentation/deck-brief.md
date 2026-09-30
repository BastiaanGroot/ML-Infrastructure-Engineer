# Demo-day deck brief (for building the pptx with Claude)

This is a complete, text-only specification of the demo-day presentation for
the ML Infrastructure Engineer take-home (cluster validator + Option 1,
training). It is written so that Claude (web) can build the `.pptx` from this
file alone, without access to the repo. Every number comes from the
2026-09-30 re-run documented in `training/README.md` and
`cluster-validator/README.md`.

Structure: 15 core slides (about 15 minutes), 4 optional evidence slides for
screenshots, and 9 appendix slides for Q&A.

---

## 1. How to use this brief

1. Open a new Claude chat with file creation enabled.
2. Upload this file. Optionally upload the screenshots listed in section 1.2
   (the deck works without them; placeholders are drawn instead).
3. Paste the prompt below.

### 1.1 Paste-ready prompt

```text
Build a 16:9 PowerPoint deck (LAYOUT_WIDE, 13.33 x 7.5 in) with pptxgenjs
from the attached brief, deck-brief.md. Follow it exactly:

- Use the design system in section 2 on every slide (navy background, panel
  colours, lime/indigo roles, Arial, sizes, margins). No accent bars, stripes,
  gradients, shadows, emoji or clip art.
- Build slides 1-15, E1-E4 and A1-A9 in order, with the exact titles, bullets,
  table contents and speaker notes given. Speaker notes go in via
  slide.addNotes().
- Build every chart as a native, editable pptxgenjs chart (addChart) with the
  data, colours, axis titles and ordering specified. Hex colours without '#'.
- Build diagrams from native shapes and text boxes (addShape / addText) at the
  given positions, so they stay editable. Positions are in inches from the top
  left of the slide.
- Where the brief says SCREENSHOT PLACEHOLDER, draw the placeholder exactly as
  specified. If I uploaded a matching screenshot, place it there instead,
  scaled to fit without distortion.
- Render every slide to an image and check it against the QA checklist in
  section 7 (no overflow, no overlaps, no text below 10 pt) before giving me
  the file. Fix anything that fails.
```

### 1.2 Screenshots to upload (optional)

Name the files as below so the mapping is unambiguous.

| File name | What to capture | Used on |
|---|---|---|
| `shot-grafana-validator.png` | Grafana "cluster-validator" dashboard during a v9 run: GPU temp / util / power panels plus the check-results log panel including `gpu_compute` | E1 |
| `shot-validator-result.png` | `kubectl logs -l job-name=cluster-validator --prefix` ending in the `RESULT:` line | E1 |
| `shot-multinode.png` | Cross-node validator output: 16/16 IB ports ACTIVE and the `all_reduce_perf` table | E1 |
| `shot-mlflow-runs.png` | MLflow experiment `qwen3-parallelism-experiments`, run list filtered on tag `cluster=2x8-h100-ib` | E2 |
| `shot-mlflow-e2e-loss.png` | MLflow `e2e-q1p7b` loss chart (one continuous run across the resume) | E2 |
| `shot-mlflow-autoresume.png` | MLflow `e2e-q1p7b-autoresume` run (one run to iteration 300 across the automatic recovery) | E2 |
| `shot-dashboard-strategy.png` | Streamlit dashboard, strategy comparison tab | E3 |
| `shot-dashboard-comm.png` | Streamlit dashboard, communication tab (NCCL sweeps + Nsight breakdown) | E3 |
| `shot-dashboard-planner.png` | Streamlit dashboard, parallelism planner with the predicted-vs-measured table | E3 |
| `shot-console-cluster.png` | Nebius console: GPU cluster on fabric-4 and the 2 x 8 H100 node group | E4 |
| `shot-kubectl-pods.png` | Optional: `kubectl get pods -o wide` during a 2-node training job | E4 |

---

## 2. Design system

### 2.1 Colours

| Role | Hex | Use |
|---|---|---|
| Background | `001A2B` | Every slide, full bleed (deep navy) |
| Panel | `0F2839` | Cards, table header rows, diagram boxes |
| Panel stroke | `22394A` | 0.75 pt outline on panels and boxes |
| Lime (signature) | `E0FF4F` | Key numbers, kicker text, "inside a node / NVLink" series and shapes, pass marks |
| Indigo (secondary) | `614EFA` | "Across nodes / InfiniBand" series and shapes, second emphasis |
| White | `FFFFFF` | Titles, primary text, table body values |
| Light neutral | `F3F4F5` | Body text |
| Secondary text | `D5D8DB` | Bullets, table cells |
| Muted text | `97A1A8` | Captions, axis labels, sources, table headers |
| Neutral series | `8C979F` | Any chart series that is neither NVLink nor InfiniBand |
| Gridlines / tracks | `1E3547` | Chart gridlines, empty cells in diagrams |
| Danger (non-brand) | `FF6B6B` | Only for OOM, failure, and the "node killed" event |

Colour rules:

- Lime means "inside one node (NVLink)" and "the number to remember".
  Indigo means "across nodes (InfiniBand)". Keep this consistent in every
  chart and diagram; slide 10 teaches the audience this key.
- Text on a lime fill is navy `001A2B`, never white.
- Never put lime text on white or light backgrounds (there are none in this
  deck).

### 2.2 Typography

- Font: Arial everywhere (Calibri acceptable as fallback). Monospace text
  (commands) in Consolas.
- Kicker (small label above the title): 11 pt, bold, lime, all caps, character
  spacing 1.
- Slide title: 28 pt bold white, max two lines. Titles are full-sentence
  "action titles"; do not shorten them. Title slide: 40 pt.
- Body / bullets: 15 pt secondary text, 6 pt space after, bullet character
  "•" in lime.
- Table text: 12 pt (header 11 pt bold muted, on panel fill).
- Key numbers: 36-44 pt bold lime (or white where specified), label below in
  11 pt muted.
- Chart text: axis labels 10-11 pt muted, data labels 10 pt white, legend 11 pt
  secondary.
- Captions and source lines: 10 pt muted.
- Nothing smaller than 10 pt anywhere except tiny diagram labels that are
  explicitly given as 9 pt.

### 2.3 Layout grid (all slides except the title)

- Slide: 13.33 x 7.5 in, margins 0.5 in on all sides.
- Kicker: x 0.5, y 0.35, w 8.0, h 0.3.
- Title: x 0.5, y 0.65, w 12.33, h 1.0, top-aligned.
- Content area: x 0.5 to 12.83, y 1.8 to 6.85.
- Footer source line: x 0.5, y 7.0, w 10.5, h 0.3, 10 pt muted, starting with
  "Source: ".
- Slide number: x 12.0, y 7.0, w 0.83, h 0.3, right-aligned, 10 pt muted.
- Panels: rounded rectangle (`roundRect`, `rectRadius` 0.08), fill `0F2839`,
  line `22394A` 0.75 pt, inner padding 0.2 in.
- Tables: header row fill `0F2839`, body rows no fill, a single 0.5 pt
  `22394A` horizontal rule between rows, no vertical rules.

### 2.4 Native chart defaults

Apply to every chart unless the slide says otherwise:

- `plotArea` / chart background: none (transparent over navy).
- `catAxisLabelColor` and `valAxisLabelColor`: `97A1A8`, font size 10-11.
- `valGridLine`: color `1E3547`, size 0.5. `catGridLine`: none.
- Axis lines: `22394A`.
- Data labels: white `FFFFFF`, 10 pt, `dataLabelFormatCode` as specified.
- Legend: bottom or top as specified, `legendColor` `D5D8DB`, 11 pt.
- Axis titles on (`showValAxisTitle`, `showCatAxisTitle`) where specified,
  colour `97A1A8`, 11 pt.
- Reference lines (thresholds, 80 GB capacity): pptxgenjs has no native
  reference line, so draw a 1 pt dashed `F3F4F5` line shape over the plot area
  at the correct value position. Fix `valAxisMinVal`/`valAxisMaxVal` so the
  position can be computed, and put a 10 pt muted label next to the line.

### 2.5 Screenshot placeholders

A rounded rectangle, fill `0F2839`, 1 pt dashed lime `E0FF4F` border, with
centred 12 pt muted text: `SCREENSHOT: <description>`. If the matching image
is uploaded, place the image in the same box instead (fit, keep aspect ratio,
centre).

---

## 3. Core slides (15)

Timing is shown per slide; the total is about 15 minutes.

---

### Slide 1: Title (0.5 min)

- No kicker or title-grid; custom layout on navy.
- Top left, x 0.6, y 0.7, w 7.0, h 0.35: `PROOF OF CONCEPT · ML INFRASTRUCTURE`
  (12 pt bold lime, caps, character spacing 2).
- Title, x 0.6, y 1.2, w 6.4, h 2.2: `Validating and training on Nebius`
  (40 pt bold white, two lines allowed).
- Subtitle, x 0.6, y 3.45, w 6.4, h 1.0: `A 16-GPU PoC toward 512 H100s:
  cluster acceptance, end-to-end LLM training, and a parallelism playbook for
  100B+` (18 pt light neutral).
- Presenter line, x 0.6, y 5.9, w 6.4, h 0.4: `<Presenter name> · Demo day ·
  <date>` (14 pt muted). Leave as editable text.
- Visual (right half), "from PoC to reservation", native shapes:
  - Label x 7.4, y 1.2: `PoC: 16 H100 (2 nodes)` (12 pt secondary).
  - Two node panels at x 7.4, y 1.6 and y 2.35, each w 2.3, h 0.6, panel fill.
    Inside each, 8 small lime rounded rectangles (w 0.2, h 0.36, gap 0.06),
    representing GPUs.
  - Arrow (line with end arrowhead, 1.5 pt muted) from x 9.85, y 2.2 to
    x 10.35, y 2.2, with label `same rules` (10 pt muted) above it.
  - Label x 10.5, y 1.2: `Reservation: 512 H100 (64 nodes)`
    (12 pt secondary).
  - A 16-column x 4-row grid of node squares starting x 10.5, y 1.6: each
    square w 0.13, h 0.2, gap 0.03 horizontally and 0.1 vertically (grid
    width ~2.5 in). The first row (16 squares) is lime; the other 48 are panel
    fill with stroke.
  - Caption x 7.4, y 3.1, w 5.5: `Highlighted: 16 nodes = one 128-GPU
    Qwen3-235B-A22B pretraining replica` (10 pt muted).
- Bottom strip (key numbers), panel x 0.6 to 12.73, y 4.7, h 1.0, five equal
  columns, each a key number (32 pt bold) with a 11 pt muted label:
  1. `16 H100` (white) / `2 nodes x 8, InfiniBand`
  2. `451 GB/s` (lime) / `16-GPU all-reduce, validator`
  3. `99.7%` (lime) / `weak scaling, 1 to 2 nodes`
  4. `409` (lime) / `TFLOP/s/GPU end to end (41% MFU)`
  5. `195 s` (lime) / `automatic recovery from a lost node`

  Move the presenter line to y 6.3 so it sits below this strip.

Speaker notes:

> Open with the decision in front of them: whether to commit to 512 H100s for
> six months. Everything that follows is evidence for that decision. The five
> numbers at the bottom are the whole talk in one line: the cluster is
> healthy, crossing nodes is nearly free, training scales, and it heals itself.

---

### Slide 2: Context (0.75 min)

- Kicker: `CONTEXT`
- Title: `Before committing to 512 H100s, the PoC answers three questions`
- Bullets, x 0.5, y 1.8, w 12.33, h 1.5 (15 pt):
  - A VC-funded startup wants to train its own LLM, then serve it on its own
    inference server
  - The team is ML engineers with little cloud or infrastructure experience
  - Exercise: validate the cluster, then Option 1 (multi-node training,
    strategies for 100B+)
- Three question panels, y 3.6, h 3.0, w 3.93 each, at x 0.5, 4.7, 8.9
  (gap 0.27). Inside each panel, top to bottom:
  - `QUESTION 1` / `2` / `3` (11 pt bold muted, caps).
  - The question (18 pt bold white).
  - The answer as a key number (40 pt bold lime).
  - The support line (12 pt secondary).

| # | Question | Answer (key number) | Support line |
|---|---|---|---|
| 1 | Can we trust the cluster? | `All checks pass` (use 30 pt so it fits on one line) | 16/16 GPUs at 681-712 TFLOP/s, 451 GB/s across nodes |
| 2 | Does real training work? | `99.7%` | weak scaling 1 to 2 nodes; loss 12.3 to 3.68; self-recovery in 195 s |
| 3 | How do we train 100B+? | `29 experiments` (30 pt) | DP, TP, PP, CP, EP, FP8, recompute, offload, profiles |

- Footer: `Source: docs/ML-Infrastructure-Engineer.md (assignment)`

Speaker notes:

> Frame the talk around their questions, not our components. They are ML
> people, so the question isn't "what did we deploy" but "can we trust it,
> does training work, and how do we lay out a 100B+ model". Inference
> (Option 2) is out of scope; the Hugging Face export at the end is the bridge
> to it.

---

### Slide 3: PoC environment (1 min)

- Kicker: `POC ENVIRONMENT`
- Title: `The PoC ran on the GPU you plan to reserve: 16 H100s on one
  InfiniBand fabric`
- Left column bullets, x 0.5, y 1.8, w 4.4, h 4.9 (15 pt):
  - The assignment specified H200, but the 8-GPU H200 shape had no capacity;
    H100 is also the reservation GPU
  - 2 nodes x 8 H100 SXM, 8 x 400 Gb/s NICs per node, GPUDirect RDMA
  - fabric-4 picked because capacity advice showed the most spare H100s there
  - 2 TB shared filesystem on every node, 2 TB network disk as scratch
- Right: topology diagram, area x 5.2 to 12.83, y 1.8 to 6.85. Native shapes:
  - Two node panels side by side: Node 1 at x 5.2, Node 2 at x 9.1, each
    w 3.7, h 2.55, y 1.8, panel fill. Heading inside at top-left:
    `Node 1: 8 x H100 SXM 80 GB` / `Node 2: 8 x H100 SXM 80 GB`
    (12 pt bold white).
  - Inside each node, a horizontal NVSwitch bar at y 2.25, h 0.28, spanning
    the node width minus 0.15 in padding: fill lime at 20% transparency
    (`transparency: 80`), 0.75 pt lime line, centred text
    `NVSwitch: NVLink, ~467 GB/s bus bandwidth` (10 pt white).
  - Below the bar, 8 GPU boxes in a row (y 2.75, w 0.36, h 0.42, gap 0.07),
    lime fill, navy text `GPU0` ... `GPU7` (9 pt bold). A short 1.5 pt lime
    vertical line connects each GPU up to the NVSwitch bar.
  - Below each GPU, a NIC box (y 3.4, w 0.36, h 0.22), indigo fill, white
    text `NIC` (9 pt), linked to its GPU by a thin muted line.
  - Small caption inside the node at y 3.85:
    `1 mlx5 NIC per GPU on the same PCIe switch (GPUDirect RDMA)`
    (9 pt muted).
  - From every NIC, a 1.5 pt indigo vertical line down to the fabric bar.
  - InfiniBand fabric bar across both nodes: x 5.2, y 4.55, w 7.6, h 0.4,
    indigo fill at 60% transparency with a 1 pt indigo line, centred white
    11 pt text: `InfiniBand fabric-4: 8 x 400 Gb/s per node (16/16 ports up),
    16-GPU all-reduce 451 GB/s`.
  - Two storage panels at y 5.2, h 0.95: `Shared filesystem, 2 TB
    (virtiofs)` at x 5.2, w 4.7, with sub-line `Mounted on both nodes,
    1.2-1.7 GB/s: tokenized data, HF cache, checkpoints`; and
    `Network disk, 2 TB (PVC)` at x 10.1, w 2.7, with sub-line
    `Per-job scratch, ~220 MB/s`. Title 12 pt bold white, sub-line 10 pt
    muted. Give the shared-filesystem panel a 1 pt lime outline (it is the
    one that matters).
  - Thin muted connector lines from the bottom of each node panel down to
    the shared-filesystem panel (it is mounted on both).
- Footer: `Source: infra/README.md, cluster-validator/README.md`

Speaker notes:

> Say the H200 swap up front so it isn't a surprise later: the 8-GPU H200
> shape had no capacity, and H100 is the GPU they plan to reserve anyway.
> Each GPU has its own 400 Gb/s NIC on the same PCIe switch, so GPUDirect
> RDMA works. Pods run privileged with /dev/infiniband mounted, so NCCL uses
> all eight NICs with no socket fallback.

---

### Slide 4: Architecture (0.75 min)

- Kicker: `ARCHITECTURE`
- Title: `One Terraform apply rebuilds the whole environment`
- Bullets, x 0.5, y 1.75, w 12.33, h 1.2 (14 pt, three lines):
  - Network, mk8s with the GPU node group in a GPU cluster, both storage
    volumes, registry, logs bucket, managed MLflow and the dashboard VM
  - Least-privilege IAM through groups: GPU nodes pull images as their own
    service account, MLflow is scoped to the project
  - Secrets live in SecretStash; applied from a reviewed saved plan and
    drift-free against the live project
- Diagram, area x 0.5 to 12.83, y 3.05 to 6.85. Native shapes (box titles
  11 pt bold white, sub-lines 9-10 pt muted, all boxes panel fill + stroke
  unless noted):
  - `Terraform` box, x 0.5, y 4.4, w 1.5, h 0.9, sub-line `infra/ · saved
    plan, apply`. Arrow (1.5 pt muted, arrowhead) to the project boundary at
    x 2.3.
  - Project boundary: dashed 1 pt muted rectangle, no fill, x 2.3, y 3.05,
    w 10.53, h 3.8. Label top-left inside: `Nebius project ml-infra-poc
    (eu-north1)` (10 pt muted).
  - VPC boundary: 0.75 pt stroke rectangle, no fill, x 2.5, y 3.4, w 6.3,
    h 2.45. Label: `VPC network + subnet` (10 pt muted).
  - Inside the VPC, a `Managed Kubernetes (mk8s)` panel, x 2.7, y 3.7, w 5.9,
    h 1.35, containing:
    - `GPU node group: 2 x 8 H100 (runs as gpu-nodes-sa)` box, x 2.85,
      y 4.0, w 5.6, h 0.5, 1 pt indigo outline, sub-line `GPU cluster on
      fabric-4 (InfiniBand); validator + training Jobs`.
    - Two small boxes, y 4.6, h 0.35, w 2.75: `Observability Agent`
      (x 2.85) and `Grafana (preinstalled)` (x 5.7).
  - Below mk8s, still in the VPC, two storage boxes, y 5.15, h 0.6, w 2.9:
    `Shared filesystem 2 TB` / `data, HF cache, checkpoints` (x 2.7, 1 pt
    lime outline) and `Network disk 2 TB` / `per-job scratch PVC` (x 5.7).
  - Right column of managed services, x 9.1, w 3.55, each h 0.52, stacked
    from y 3.4 with 0.08 gaps:
    1. `Container registry` / `validator v9, pulled by node SA`
    2. `Managed MLflow` / `all runs, public + basic auth`
    3. `Dashboard VM` / `Streamlit over MLflow`
    4. `SecretStash` / `MLflow password, S3 keys`
    5. `Object Storage bucket` / `summary.json, 90-day expiry`
    6. `IAM (groups only)` / `gpu-nodes-sa: registry viewer · mlflow-sa:
       project editor`
  - Bottom row inside the project, below the VPC, y 6.0, h 0.5:
    `Nebius Logging` / `pod stdout, LogQL` (x 2.5, w 3.0) and
    `Nebius Monitoring` / `DCGM GPU metrics, PromQL` (x 5.65, w 3.15).
  - Thin muted arrows: Observability Agent down to Logging and to
    Monitoring; Grafana box has a 10 pt muted note to its right or in the
    footer: `Agent ships logs and GPU metrics to Logging and Monitoring;
    Grafana reads both.`
- Footer: `Source: infra/README.md, docs/observability.md`

Speaker notes:

> The customer's team isn't infrastructure-heavy, so stress that they can
> recreate this in their own project from the READMEs, step by step. Every
> permission goes through an IAM group, which is what Nebius requires for
> bucket access anyway. The node-group change during the review rolled both
> GPU nodes, which doubled as an acceptance test of fresh hardware.

---

### Slide 5: Technical choices (1 min)

- Kicker: `TECHNICAL CHOICES`
- Title: `Each choice is the simplest option that still scales to 512 GPUs`
- One-line intro, x 0.5, y 1.75, w 12.33, h 0.4 (14 pt muted):
  `Each choice with the alternative the customer is most likely to ask about`
- Table, x 0.5, y 2.25, w 12.33, h ~4.5, four columns with widths
  1.6 / 3.0 / 4.33 / 3.4 in. Column 1 bold white; column 2 lime; columns 3-4
  secondary. 12 pt, rows ~0.7 in high.

| Area | Choice | Why | Alternative considered |
|---|---|---|---|
| Scheduler | Plain Kubernetes Indexed Jobs | One pod per node, torchrun rendezvous via a headless Service; Job retries give automatic recovery | Slurm / Soperator, Kubeflow training operator, MPI Operator |
| Framework | NeMo Megatron-Bridge (Megatron-Core) | TP, PP, CP and EP are first-class config fields, as 100B+ runs need | FSDP2 / DeepSpeed ZeRO: shards memory, but can't split layers or experts |
| Model | Qwen3, dense 0.6B-32B + MoE 30B-A3B / 235B-A22B | Apache-2.0, NVIDIA recipes, one family covering every strategy plus a real >100B target | Mixing model families across experiments |
| Storage | Shared FS for shared data, network disk as scratch | Shared FS is 5-8x faster and mounted on every node | Everything on the network disk (not shared, slower) |
| Observability | Nebius-hosted Logging + Monitoring, Grafana | Already wired at cluster creation; no self-hosted Prometheus/Loki | Self-hosted kube-prometheus-stack |
| Benchmarks | MLPerf metric definitions, not the suite | Validator stays lightweight; numbers stay comparable | Full MLPerf Training submission flow |

- Footer: `Source: README.md, docs/training-strategy-outline.md`

Speaker notes:

> Megatron-Bridge is the key choice. FSDP and ZeRO shard memory, but they
> can't split a layer, a stack of layers, a sequence or the experts, and a
> 100B+ model needs all four. Plain Kubernetes Jobs were enough at two nodes;
> managed Soperator is the natural move once many users share the GPUs.

---

### Slide 6: Cluster validator (1 min)

- Kicker: `CLUSTER VALIDATOR`
- Title: `A portable container turns 'is the cluster healthy?' into a
  pass/fail answer in minutes`
- Bullets, x 0.5, y 1.75, w 12.33, h 1.75 (14 pt):
  - Built on Nebius's own nccl-tests image, so CUDA, NCCL and OFED come
    pre-tested; the validator adds a thin check layer
  - Per node: GPU health (incl. row remaps), a 30 s bf16 GEMM burn per GPU,
    NVLink NCCL, a real Qwen3-0.6B generate + backward, fio on both volumes
  - Across nodes: pre-flight that all 8 IB ports per node are ACTIVE at
    400 Gb/s, then all_reduce over 16 GPUs via mpirun over SSH
  - H100 thresholds at ~85-90% of measured, so one degraded GPU, NVLink or
    NIC fails the run
- Flow diagram, left to right, area x 0.5 to 12.83, y 3.7 to 6.85 (box
  titles 11 pt bold white, sub-lines 9.5 pt muted):
  - Column A, image box, x 0.5, y 4.3, w 2.3, h 1.6:
    `cluster-validator v9` / `Nebius nccl-tests base: CUDA, NCCL, OFED ·
    + PyTorch, Transformers · + Qwen3-0.6B baked in` (sub-lines on separate
    lines).
  - Two arrows from column A to column B.
  - Column B, two Job boxes, x 3.15, w 2.6, h 1.2:
    - `Per-node Job` at y 3.7, 1 pt lime outline: `Indexed Job, 1 pod per
      node · pod anti-affinity · fresh 2 TiB disk per pod`.
    - `Cross-node Job` at y 5.6, 1 pt indigo outline: `sshd in every pod ·
      pod 0 runs mpirun over SSH · privileged + /dev/infiniband`.
  - Column C, check boxes, x 6.15, w 3.4. From the per-node Job, five thin
    lime connectors fan out to five stacked boxes (h 0.36, gap 0.06, from
    y 3.7), each a single 10.5 pt line:
    1. `gpu_health: count, temp, ECC, row remaps`
    2. `gpu_compute: bf16 GEMM per GPU, 30 s`
    3. `nccl_bench: 8 GPUs, NVLink`
    4. `llm_smoketest: generate + backward`
    5. `storage_bench: fio, both volumes`

    From the cross-node Job, one thin indigo connector to a box at y 5.85,
    h 0.7: `IB pre-flight: 8 ports ACTIVE` / `then nccl_multinode: 16 GPUs`.
  - Arrow from column C to column D.
  - Column D, outputs, x 9.95, w 2.88:
    - `summary.json` / `+ exit code 0/1 · per-check JSON` at y 4.0, h 0.8.
    - Down-arrow, then `Logging, Grafana` / `stdout, live` at y 5.05, h 0.6.
    - `Object Storage` / `kept 90 days` at y 5.8, h 0.6.
- Footer: `Source: cluster-validator/README.md`

Speaker notes:

> The GEMM check catches a single slow or throttling GPU. That GPU gates
> every synchronous training step, and it doesn't show up in NCCL numbers.
> Temperatures are read under load, not at idle. The thresholds are tight on
> purpose: losing one of eight NICs drops cross-node bandwidth to about
> 395 GB/s, below the 400 floor, so the run fails.

---

### Slide 7: Validation results (1 min)

- Kicker: `VALIDATION RESULTS`
- Title: `Every check passed on fresh nodes; cross-node bandwidth is within 4%
  of NVLink`
- Bullets, x 0.5, y 1.75, w 12.33, h 1.15 (14 pt):
  - 16/16 GPUs healthy and within 4% of each other at 681-712 TFLOP/s bf16,
    at the 700 W cap, no throttling
  - NVLink ~467 GB/s per node; 16 GPUs across nodes 451.5 GB/s; 16/16 IB
    ports up
  - Shared FS 5-8x faster than the network disk, from the storage backends,
    not misconfiguration
- Left: scorecard table, x 0.5, y 3.05, w 7.0, h ~3.7, columns 2.0 / 2.0 /
  1.6 / 1.4 in, 11.5 pt. Column 4 ("Result") text lime for pass rows, muted
  for "Reported" rows.

| Check | Node 1 | Node 2 | Result |
|---|---|---|---|
| GPU health (idle) | 8 GPUs, 26 °C, 0 ECC, 0 remaps | 8 GPUs, 28 °C, 0 ECC, 0 remaps | Pass (8 expected) |
| GPU compute, bf16 GEMM | 683-708 TFLOP/s, 61 °C max | 691-711 TFLOP/s, 64 °C max | Pass (> 600, no slowdown) |
| NCCL 8 GPUs (NVLink) | 467.9 GB/s | 466.0 GB/s | Pass (> 400) |
| IB ports | 8/8 ACTIVE, 400 Gb/s | 8/8 ACTIVE, 400 Gb/s | Pass |
| NCCL 16 GPUs (IB) | 451.5 GB/s | (same run) | Pass (> 400) |
| LLM smoketest | pass | pass | Pass |
| Network disk read / write | 219 / 223 MB/s | 219 / 223 MB/s | Reported |
| Shared FS read / write | 1309 / 1310 MB/s | 1346 / 1346 MB/s | Reported |

- Right top: native horizontal bar chart (`barDir: 'bar'`), x 7.8, y 3.05,
  w 5.03, h 1.9.
  - Title (chart title or text box above, 12 pt bold white):
    `All-reduce bus bandwidth (GB/s)`
  - Categories (top to bottom): `Node 1, NVLink`, `Node 2, NVLink`,
    `16 GPUs, IB`. Values: 467.9, 466.0, 451.5.
  - Single series, per-point colours via `chartColors` with
    `varyColors`-style per-bar colours: `E0FF4F`, `E0FF4F`, `614EFA`.
  - Value axis min 0, max 500, major unit 100. Data labels at the bar end,
    format `0.0`.
  - Reference line: dashed at 400, label `threshold 400`.
- Right bottom: native horizontal bar chart, x 7.8, y 5.05, w 5.03, h 1.7.
  - Title: `bf16 GEMM, best GPU per node (TFLOP/s)`
  - Categories: `Node 1 (683-708)`, `Node 2 (691-711)`. Values: 708, 711.
    Lime bars.
  - Value axis min 0, max 800, major unit 200. Data labels `0`.
  - Reference line: dashed at 600, label `threshold 600`.
- Footer: `Source: cluster-validator/README.md (image v9, fresh nodes,
  2026-09-30). Thresholds: EXPECTED_GPU_COUNT=8, NCCL_MIN_BUSBW_GBPS=400,
  GPU_MIN_TFLOPS=600`

Speaker notes:

> This run was on replacement VMs after the node group rolled, so it's
> exactly the acceptance test the customer would run on delivered capacity.
> Every GPU is within 4% of every other one, at the 700 W power cap and under
> 70 °C, with no throttling. Cross-node all-reduce is only 4% below NVLink.
> All outputs land in Nebius Logging, visible in a Grafana panel, and in
> Object Storage for 90 days.

---

### Slide 8: Interconnect (1 min)

- Kicker: `INTERCONNECT`
- Title: `Crossing nodes is nearly free for large messages, but 3x slower for
  small ones`
- Left bullets, x 0.5, y 1.9, w 3.9, h 4.8 (15 pt):
  - At 1 GiB, 16 GPUs reach 95% of single-node NVLink
  - At 1 MiB they reach only a third: latency dominates
  - One NIC alone: 46 GB/s, 93% of 400 Gb/s line rate
- Right top: native line chart, x 4.7, y 1.8, w 8.13, h 3.3.
  - Title (text box above, 12 pt bold white):
    `all_reduce bus bandwidth vs message size`
  - Categories: `1 MiB`, `16 MiB`, `256 MiB`, `1 GiB`.
  - Series (line width 2.5, circle markers size 7):

    | Series | Colour | 1 MiB | 16 MiB | 256 MiB | 1 GiB |
    |---|---|---|---|---|---|
    | 8 GPUs, NVLink | `E0FF4F` | 69.5 | 246.1 | 424.4 | 468.0 |
    | 16 GPUs, NVLink + IB | `614EFA` | 22.6 | 158.1 | 381.4 | 442.4 |
    | 2 GPUs, one NIC | `8C979F` | 16.9 | 38.6 | 45.3 | 46.3 |

  - Data labels on the first two series only (`0.0`, lime series above,
    indigo series below); none on the one-NIC series (its values are in the
    bullets).
  - Value axis 0-500, major unit 100, title `Bus bandwidth (GB/s)`.
    Category axis title `Message size`. Legend top.
- Right bottom: compact table, x 4.7, y 5.3, w 8.13, h 1.5, 11 pt, numbers
  right-aligned:

| Message size | NVLink (GB/s) | 16 GPUs (GB/s) | 16 GPUs as % of NVLink |
|---|---|---|---|
| 1 MiB | 69.5 | 22.6 | 33% |
| 16 MiB | 246.1 | 158.1 | 64% |
| 256 MiB | 424.4 | 381.4 | 90% |
| 1 GiB | 468.0 | 442.4 | 95% |

- Footer: `Source: training/README.md, nccl-* experiments (first round,
  not re-run; code path unchanged)`

Speaker notes:

> This one chart sets up the whole training section. Data parallelism sends
> large gradient buckets that overlap with the backward pass, so it can cross
> nodes; the 99.7% weak scaling proves it. Tensor parallelism sends many
> medium-sized all-reduces on the critical path, which sit on the left of this
> chart, so it should stay inside a node.

---

### Slide 9: End-to-end run (1.5 min)

- Kicker: `END-TO-END RUN`
- Title: `Real training works end to end, and recovers from a lost node on
  its own`
- Bullets, x 0.5, y 1.75, w 12.33, h 1.45 (13.5 pt, four lines):
  - Qwen3-1.7B from scratch on FineWeb-Edu, DP16 across both nodes, about one
    epoch of 1.05B tokens: 409 TFLOP/s/GPU, 41% MFU
  - Data tokenized once onto the shared filesystem; checkpoints every 250
    iterations cost under 1% of the run
  - Manual resume: relaunch picks up the last checkpoint in 65 s. Automatic:
    a killed pod is replaced and training resumes in 195 s, no human
  - Replayed iterations give identical losses both times, so data order and
    optimizer state restore exactly
- Left: native line chart, x 0.5, y 3.3, w 5.2, h 2.55.
  - Title (text box, 12 pt bold white): `Qwen3-1.7B training loss`
  - Categories (iterations): `1`, `50`, `100`, `250`, `500`, `750`, `1000`.
  - One series `Training loss`, lime `E0FF4F`, line width 2.5, markers:
    12.32, 7.27, 6.53, 5.35, 4.24, 3.86, 3.68.
  - Data labels on first and last points only if possible (12.32, 3.68);
    otherwise all points, format `0.00`.
  - Value axis 0-14, major unit 2, title `Loss`. Category axis title
    `Iteration (unevenly spaced)`. No legend.
- Right top: manual-resume timeline, native shapes, area x 6.0 to 12.83,
  y 3.3 to 4.55.
  - Label top-left (11 pt bold white): `Manual resume (1000-iteration run)`.
  - Horizontal 2 pt muted line at y 4.05 from x 6.2 (iteration 0) to x 12.6
    (iteration 1000); x position = 6.2 + iteration x 0.0064.
  - Diamonds (rotated squares, 0.14 in) at iterations 0 (muted), 250, 500,
    750, 1000 (lime), with labels below (10 pt secondary): `start`,
    `ckpt 250`, `ckpt 500`, `ckpt 750`, `ckpt 1000`.
  - Red `FF6B6B` vertical tick at iteration 519 (x ≈ 9.52), label below it in
    red: `Job deleted at 519`.
  - Curved lime arrow from the 519 tick back to iteration 501 (x ≈ 9.41),
    arcing above the line; label above (10 pt white):
    `relaunched: training at 501 after 65 s; 501-519 losses identical`.
- Right middle: automatic-recovery timeline, area x 6.0 to 12.83, y 4.65 to
  5.85.
  - Label (11 pt bold white): `Automatic recovery (e2e-q1p7b-autoresume, no
    human involved)`.
  - Horizontal 2 pt muted line at y 5.25 from x 6.2 (t = 0 s) to x 12.6
    (t = 200 s); x = 6.2 + t x 0.032.
  - Event dots (0.12 in circles) with short leader lines, labels alternating
    above and below so none overlap (10 pt):

    | t (s) | Label | Colour | Label position |
    |---|---|---|---|
    | 0 | pod with last rank killed (iter 222) | `FF6B6B` | above, high |
    | 15 | +15 s replacement pod | `D5D8DB` | below |
    | 19 | +19 s survivor stops workers | `D5D8DB` | above, low |
    | 86 | +86 s rendezvous timeout, pods exit | `D5D8DB` | below, lower |
    | 129 | +129 s Job recreates both pods | `D5D8DB` | above, low |
    | 195 | +195 s training again | `E0FF4F` | below, right-aligned to the dot |

- Bottom: four key-number panels, y 5.95, h 0.85, w 2.95 each, at x 0.5,
  3.63, 6.76, 9.89 (32 pt bold number, 10.5 pt muted label beside or below):
  1. `1.88 s` (white) / `steady step time`
  2. `409` (lime) / `TFLOP/s per GPU (41% MFU)`
  3. `558k` (white) / `tokens/s, whole cluster`
  4. `195 s` (lime) / `kill to training, automatic`
- Footer: `Source: training/README.md, MLflow runs e2e-q1p7b and
  e2e-q1p7b-autoresume. The 1000-iteration run logged 2.09 s / 368 TFLOP/s
  due to a since-fixed blocking MLflow call; 1.88 s / 409 is the same config.`

Speaker notes:

> This is their daily loop: shared data, cheap checkpoints and self-healing
> Jobs. The loss drops from 12.3 to 3.7 over one epoch. We deleted the Job at
> iteration 519 and relaunched: it was training again from checkpoint 500 in
> 65 seconds, with identical losses. Then we killed a pod mid-run with no human
> involved: the Job and torchrun's elastic rendezvous brought it back in
> 195 seconds. An earlier attempt with a static rendezvous hung for 18 minutes
> in NCCL, which is why the elastic mode matters. Honest caveat: recovery goes
> through a Job retry after the rendezvous times out.

---

### Slide 10: Parallelism primer (0.75 min)

- Kicker: `PARALLELISM PRIMER`
- Title: `Five ways to split a model, and where each one belongs`
- One-line intro, x 0.5, y 1.75, w 12.33, h 0.4 (14 pt):
  `Lime splits go inside a node (NVLink); indigo splits can cross nodes
  (InfiniBand)`. Colour the words "Lime" lime and "indigo" indigo.
- Table, x 0.5, y 2.3, w 12.33, h 4.4, five body rows ~0.8 in high, columns
  1.3 (glyph) / 1.6 / 2.7 / 2.7 / 1.4 / 2.63 in. 12 pt. The "Place it" cell
  is bold, in lime for "Inside a node" and white for "Across nodes".

| Glyph | Strategy | Splits | Communication | Place it | Measured here |
|---|---|---|---|---|---|
| (DP glyph) | Data (DP) | The batch; every GPU holds the model | Gradient reduce, overlaps backward | Across nodes | 8B: 99.7% weak scaling 1 to 2 nodes |
| (TP glyph) | Tensor (TP) | Each layer's matmuls | All-reduce per layer, on the critical path | Inside a node | 8B: TP2 to TP8 costs 61% |
| (PP glyph) | Pipeline (PP) | Layers into stages | Point-to-point activations + bubble | Across nodes | 8B: adding PP2 costs 16% |
| (CP glyph) | Context (CP) | The sequence | Ring exchange of K/V, overlaps compute | Inside a node | 16k seq: CP2 7% faster than TP4 |
| (EP glyph) | Expert (EP) | MoE experts | Token all-to-all, twice per MoE layer | Inside a node | 30B-A3B: EP16 2.6x slower than EP8 |

- Glyphs (native shapes, about 1.0 x 0.6 in, centred in the glyph cell). Each
  glyph shows two GPUs side by side as two outlined rectangles (0.45 x 0.55,
  0.75 pt `97A1A8` outline, 0.08 gap). Inside each GPU is a 4 x 4 grid of
  tiny squares representing the model (a layer stack: rows = layers,
  columns = the width of each layer). Filled squares are what that GPU holds;
  empty squares are `1E3547`.
  - DP (indigo): both GPUs have all 16 squares filled (full copy each).
  - TP (lime): GPU 1 has the left two columns filled, GPU 2 the right two
    (each layer split in width).
  - PP (indigo): GPU 1 has the top two rows filled, GPU 2 the bottom two
    (layers split into stages).
  - CP (lime): both GPUs full (shorter squares), plus a thin sequence bar
    under both GPUs; GPU 1 has the left half of the bar filled, GPU 2 the
    right half (each holds half the sequence).
  - EP (lime): instead of a grid, each GPU has four circles (experts);
    GPU 1 fills circles 1-2, GPU 2 fills circles 3-4.
- Footer: `Source: docs/training-strategy-outline.md, training/README.md`

Speaker notes:

> Keep this short for an ML audience; they know the strategies. The point is
> the "place it" column: what must stay on NVLink inside a node, and what can
> cross InfiniBand. The next three slides prove each row with measurements.

---

### Slide 11: Qwen3-8B experiments (1.5 min)

- Kicker: `QWEN3-8B EXPERIMENTS`
- Title: `Scale out with data parallelism; use the smallest tensor-parallel
  degree that fits`
- No bullet block on the slide (the four key numbers carry the message;
  bullets are in the speaker notes).
- Two native horizontal bar charts side by side, sharing the same category
  order so each row lines up. Both at y 1.8, h 4.0. Category order top to
  bottom as listed below (in pptxgenjs horizontal bar charts, set
  `catAxisOrientation: 'maxMin'` so the first category is at the top).
  - Left chart, x 0.5, w 7.4, title `TFLOP/s per GPU (steady state)`, lime
    bars `E0FF4F`, except the `TP2 x DP4, one node` bar in indigo `614EFA`
    (it is the 1-node comparison point). Category labels 10.5 pt secondary.
    Value axis 0-500, major unit 100. Data labels `0.0`. Dashed reference
    line at 415.3 labelled `baseline 415.3`.
  - Right chart, x 8.1, w 4.73, title `Peak GPU memory (GB, max over
    ranks)`, neutral bars `8C979F`, no category labels (they align with the
    left chart). Value axis 0-90, major unit 20. Data labels `0.0`. Dashed
    reference line at 80 labelled `80 GB capacity`.

| Category (top to bottom) | TFLOP/s/GPU | Peak memory (GB) |
|---|---|---|
| TP2 x DP8 (baseline) | 415.3 | 49.2 |
| TP2 x DP4, one node | 416.6 | 55.3 |
| DP16 + full recompute | 368.2* | 65.5 |
| TP4 x DP4 | 311.0 | 30.2 |
| TP8 x DP2 | 162.0 | 20.7 |
| TP8, one node | 165.5 | 26.8 |
| TP8 split 4 + 4 | 159.5 | 26.8 |
| TP2 x PP2 x DP4 | 350.1 | 33.2 |
| FP8 (current scaling) | 426.6 | 47.2 |
| Unfused attention | 309.0 | 69.4 |
| Activation CPU offload | 126.9 | 40.5 |
| TP2 x CP2 x DP4, seq 16k | 439.8 | 66.7 |
| TP4 x DP4, seq 16k | 411.8 | 63.8 |

- OOM callout, below the charts, x 0.5, y 5.85, w 12.33, h 0.3, 10.5 pt:
  red `FF6B6B` text `OOM (> 80 GB): DP16 without recompute; TP2 x DP8 at seq
  16k.` followed by muted text `*Recompute counts the extra forward pass.`
- Bottom: four key-number panels, y 6.2, h 0.65, w 2.95 each, at x 0.5,
  3.63, 6.76, 9.89. Number 26 pt bold, label 10.5 pt muted to its right:
  1. `99.7%` (lime) / `weak scaling, 1 node (indigo) to 2 nodes`
  2. `-61%` (white) / `TP2 to TP8 throughput`
  3. `+2%` (white) / `FP8 step-time gain only`
  4. `3.3x` (white) / `slower step with CPU offload`
- Footer: `Source: training/README.md (2026-09-30 re-run). Micro-batch 1,
  global batch 64, seq 4096 unless noted; 20 iterations on synthetic data.`

Speaker notes:

> One change at a time from a TP2 x DP8 baseline. Adding the second node over
> InfiniBand scales at 99.7% (416.6 to 415.3 TFLOP/s per GPU at the same
> per-GPU work). Going from TP2 to TP8 loses 61%; TP8 split across nodes is
> within 4% of TP8 in one node, because TP8 is already communication-bound.
> At 16k sequence length, CP2 fits and is 7% faster than TP4. FP8 is only 2%
> faster, because only the GEMMs run in FP8. Unfused attention needs 41% more
> memory, and CPU offload makes the step 3.3x slower. The memory column
> explains why each layout exists: TP, PP and recompute trade throughput for
> memory. 99.7% is the number to extrapolate from for 512 GPUs.

---

### Slide 12: MoE and 32B (1 min)

- Kicker: `MOE AND 32B`
- Title: `Keep expert and tensor parallelism inside a node; cross nodes with
  pipeline and data parallelism`
- Bullets, x 0.5, y 1.75, w 12.33, h 1.2 (15 pt):
  - MoE all-to-all can't overlap with compute, so EP across nodes is 2.6x
    slower
  - 32B needs ~525 GB of weights, grads and Adam state, so it must be sharded
    over 8+ GPUs
  - NVIDIA's TP8 x PP2 recipe leaves no DP on 16 GPUs; TP4 x PP2 x DP2 is 39%
    faster
- Two panels side by side, y 3.15, h 3.6, w 6.0 each, at x 0.5 and 6.83.
  Each panel holds a heading, a native horizontal bar chart and a takeaway
  line.
  - Left panel heading (13 pt bold white):
    `Qwen3-30B-A3B (MoE): seconds per step, lower is better`
    - Chart: categories `EP8, all-to-all in node` (3.71, lime `E0FF4F`) and
      `EP16, across nodes` (9.52, indigo `614EFA`). Value axis 0-10, data
      labels `0.00" s"`.
    - Takeaway (12 pt secondary): `EP8: 101.6 TFLOP/s/GPU at 62.1 GB. EP16
      saves 9 GB/GPU but is 2.6x slower.`
    - Small print (10 pt muted): `TP1, DP16, global batch 64`
  - Right panel heading: `Qwen3-32B (3D parallelism): seconds per step,
    lower is better`
    - Chart: categories `TP4 x PP2 x DP2` (10.64, lime) and
      `TP8 x PP2 (NVIDIA recipe)` (14.84, neutral `8C979F`). Value axis 0-16.
    - Takeaway: `TP4 x PP2 x DP2: 315.3 TFLOP/s/GPU at 53.0 GB. The recipe
      fits in 40.2 GB but leaves no DP, so it's 39% slower.`
    - Small print: `Global batch 64`
- Footer: `Source: training/README.md`

Speaker notes:

> Expert parallelism's all-to-all can't overlap with compute, so pushing it
> across nodes costs 2.6x for only 9 GB of memory saved per GPU. For 32B,
> NVIDIA's recipe is TP8 x PP2, which on 16 GPUs leaves no data parallelism;
> TP4 x PP2 x DP2 fits and is 39% faster. NVIDIA's 235B-A22B recipe is shaped
> the same way, with EP8 on 8-GPU nodes. Low MoE MFU is expected at
> micro-batch 1, because each expert sees few tokens.

---

### Slide 13: Profiling (1 min)

- Kicker: `PROFILING`
- Title: `Nsight shows why: extra TP turns GEMM time into communication time`
- Left bullets, x 0.5, y 1.9, w 4.0, h 4.8 (15 pt):
  - TP2 on NVLink: GEMMs are 47% of kernel time
  - TP8 across nodes: NCCL is 63%, GEMMs 19%
  - Each TP all-reduce takes ~4x longer, and there are 747k of them
- Right top: native 100% stacked horizontal bar chart
  (`barDir: 'bar'`, `barGrouping: 'percentStacked'`), x 4.8, y 1.8, w 8.03,
  h 3.0.
  - Title (12 pt bold white): `Share of summed GPU kernel time, Qwen3-8B`
  - Categories (top to bottom): `TP2 x DP8 (TP on NVLink)`,
    `TP8 split 4 + 4 (TP over IB)`.
  - Series and colours:

    | Series | Colour | TP2 x DP8 | TP8 split 4 + 4 |
    |---|---|---|---|
    | GEMM | `E0FF4F` | 47.0 | 19.0 |
    | NCCL communication | `614EFA` | 26.1 | 63.4 |
    | Attention + everything else | `8C979F` | 26.9 | 17.6 |

  - Data labels centred in the segments (`dataLabelPosition: 'ctr'`, never
    `outEnd` for stacked charts), format `0"%"`. Label colour navy
    `001A2B` on the lime and neutral segments and white on the indigo
    segment. If per-series label colours aren't possible, use white and make
    sure the lime-segment labels are still readable, or add text boxes.
  - Legend at the bottom. Value axis hidden or 0-100%.
- Right bottom: three key-number panels, y 5.05, h 1.4, w 2.55 each, at
  x 4.8, 7.54, 10.28:
  1. `0.17 ms` (white) / `median TP all-reduce, NVLink TP2`
  2. `0.64 ms` (lime) / `median TP all-reduce, TP8 across nodes`
  3. `747k` (white) / `TP all-reduce calls in the TP8 profile`
- Footer: `Source: training/profiles/*.txt via nsys cuda_gpu_kern_sum
  (first-round profiles). % of kernel time summed over CUDA streams, not wall
  time; NCCL partly overlaps.`

Speaker notes:

> This is the kernel-level evidence behind "smallest TP that fits". With TP2
> on NVLink, almost half the GPU time is useful matrix math. With TP8 split
> across nodes, nearly two thirds is communication: each all-reduce takes
> about four times longer, and there are three quarters of a million of them.
> Profiling overhead was +5% on the baseline and +37% on TP8. These profiles
> are from the first round; the code paths haven't changed.

---

### Slide 14: Scale-out plan (1.5 min)

- Kicker: `SCALE-OUT PLAN`
- Title: `On 512 H100s, the same rules give a 235B MoE pretraining run with
  4x data parallelism`
- Left column, x 0.5, y 1.8, w 4.2: three rule panels, each h 1.05, gap 0.12,
  stacked from y 1.8. Inside each: `RULE 1` / `2` / `3` (11 pt bold lime)
  and the rule (14 pt white):
  1. `TP, CP and EP stay inside a node, on NVLink`
  2. `PP crosses nodes, point-to-point over InfiniBand`
  3. `Scale out with DP (99.7% measured across the node boundary); use the
     smallest TP that fits`

  Below the panels, y 5.35, w 4.2, h 0.5 (13 pt secondary):
  `Alternatively: 8 concurrent 64-GPU fine-tuning jobs (see notes).`
- Right top: 64-node grid, native shapes, area x 5.0 to 12.83, y 1.8 to 4.35.
  - Eight rows of eight node boxes. Row label column at x 5.0, w 1.1: rows
    1, 3, 5 and 7 are labelled `DP replica 1` ... `DP replica 4` (10 pt;
    white for replica 1, muted otherwise). Rows 2, 4, 6 and 8 have no label.
  - Node boxes: x from 6.15, w 0.78, h 0.27, gap 0.05 horizontally and 0.045
    vertically. Text in each box: `PP stage N`, where N runs 1-8 in odd rows
    and 9-16 in even rows (9 pt).
  - Rows 1-2 (replica 1, 16 nodes) are lime with navy text; all other rows
    are panel fill with stroke and faint text.
  - Dashed 2 pt indigo separators between replicas (below rows 2, 4 and 6).
  - Caption, y 4.4, w 7.83 (10 pt muted): `64 nodes x 8 H100. One replica =
    16 nodes = 128 GPUs (NVIDIA recipe: TP4, PP16, CP2, EP8); 4 replicas give
    DP4 over all 512 GPUs. Conceptual: Megatron's rank order interleaves DP
    and PP nodes, both over InfiniBand.`
- Right bottom: dimension table, x 5.0, y 4.95, w 7.83, h 1.85, 11 pt.
  Rows 1-3 "Link" text lime, rows 4-5 indigo.

| Dimension | Degree | Spans | Link |
|---|---|---|---|
| Tensor (TP) | 4 | 4 GPUs in a node | NVLink |
| Context (CP) | 2 | 2 TP groups = 1 node | NVLink |
| Expert (EP) | 8 | All 8 GPUs of a node (MoE layers) | NVLink |
| Pipeline (PP) | 16 | 16 nodes, one stage per node | InfiniBand, point-to-point |
| Data (DP) | 4 | 4 replicas | InfiniBand, overlaps backward (99.7% measured) |

- Footer: `Source: docs/training-strategy-outline.md, NVIDIA Megatron-Bridge
  Qwen3 recipes`

Speaker notes:

> Apply the three rules measured on 16 GPUs to 512. NVIDIA's 235B-A22B
> pretraining recipe needs 128 GPUs per replica (TP4, PP16, CP2, EP8), so 512
> GPUs give four data-parallel replicas; DP is the dimension we measured at
> 99.7% across the node boundary. The alternative is eight concurrent 64-GPU
> SFT or PEFT jobs, since NVIDIA's 235B SFT and PEFT recipes each need 64
> GPUs. 16 GPUs was right-sized for 30-32B fine-tuning; 512 covers 235B-A22B
> pretraining with room. Either way, run the validator on every batch of
> delivered nodes first.

---

### Slide 15: Wrap-up (1 min)

- Kicker: `WRAP-UP`
- Title: `Everything is reproducible and observable, and the next steps are
  clear`
- One-line intro, x 0.5, y 1.75, w 12.33, h 0.35 (14 pt):
  `Six steps from an empty project to monitored training, each documented in
  a README`
- Step cards: one row of six panels, y 2.2, h 1.15, w 1.93 each, gap 0.15,
  from x 0.5. Each: `STEP n` (10.5 pt bold lime), title (13 pt bold white),
  command (9.5 pt Consolas muted):

| Step | Title | Command |
|---|---|---|
| 1 | Infrastructure | `terraform plan -out, then apply` |
| 2 | Validator image | `docker push .../cluster-validator:v9` |
| 3 | Validate | `kubectl apply -f k8s/job-validate*.yaml` |
| 4 | Training data | `kubectl apply -f k8s/prepare-data.yaml` |
| 5 | Train | `./launch.py e2e-q1p7b` |
| 6 | Monitor | `MLflow, Grafana, dashboard` |

- Bottom left: "Where to look" table, x 0.5, y 3.6, w 6.3, h 3.2, 11.5 pt,
  column widths 1.8 / 4.5:

| Where to look | What it shows |
|---|---|
| MLflow | Loss, step time, TFLOP/s and memory for every run, logged live |
| Grafana (cluster) | GPU temp, utilization, power from DCGM; validator and training logs |
| Results dashboard | Strategy comparison, NCCL + Nsight view, TP x PP x DP planner validated against MLflow |
| Object Storage | Validator summary.json per node and run, 90 days |

- Bottom right: panel x 7.1, y 3.6, w 5.73, h 3.2, heading `Next steps`
  (14 pt bold white), bullets (12.5 pt secondary):
  - Run the validator as the acceptance test on every batch of delivered
    nodes, before any training
  - Export the final checkpoint to Hugging Face format (Megatron-Bridge
    AutoBridge) and serve it
  - Raise torchrun rendezvous timeouts or move to JobSet, so recovery doesn't
    need a Job retry
  - Emit validator thresholds as metrics so bandwidth regressions can alert
  - Add auth and TLS to the results dashboard; consider managed Soperator
    once several teams share the GPUs
- Footer: `Source: README.md and component READMEs. Questions?`

Speaker notes:

> Everything you saw can be rebuilt from an empty project in six documented
> steps, and every run is visible in MLflow, Grafana and the dashboard. The
> next steps start with using the validator as the acceptance test on the
> reserved capacity, and exporting the trained model to Hugging Face format as
> the bridge to their inference server. Hand over to questions; the appendix
> has the full tables.

---

## 4. Evidence slides (optional, screenshots)

Place these after slide 15. Use them live in Q&A, or flash them briefly
during the talk if time allows. Kicker `EVIDENCE`. If a screenshot isn't
uploaded, draw the placeholder (section 2.5).

### E1: The validator in Grafana and the logs

- Title: `The validator's results are visible live in Grafana and in the pod
  logs`
- Screenshot placeholder, large: x 0.5, y 1.8, w 7.6, h 5.0:
  `SCREENSHOT: Grafana cluster-validator dashboard (GPU temp/util/power +
  check results incl. gpu_compute)` (`shot-grafana-validator.png`).
- Two stacked placeholders on the right, x 8.35, w 4.48, h 2.4, at y 1.8 and
  y 4.4: `SCREENSHOT: validator log ending in RESULT:`
  (`shot-validator-result.png`) and `SCREENSHOT: 16/16 IB ports ACTIVE +
  all_reduce_perf table` (`shot-multinode.png`).
- Notes: `Show that the pass/fail answer is visible without kubectl: the
  Grafana panel filters the check-result lines, and the summary.json copy
  lives in Object Storage.`

### E2: MLflow

- Title: `Every run is tracked in MLflow, including across restarts`
- Placeholder left, x 0.5, y 1.8, w 6.05, h 5.0: `SCREENSHOT: MLflow run
  list, tag cluster=2x8-h100-ib` (`shot-mlflow-runs.png`).
- Two stacked placeholders right, x 6.78, w 6.05, h 2.4, at y 1.8 and 4.4:
  `SCREENSHOT: e2e-q1p7b loss chart` (`shot-mlflow-e2e-loss.png`) and
  `SCREENSHOT: e2e-q1p7b-autoresume run to iteration 300`
  (`shot-mlflow-autoresume.png`).
- Notes: `One MLflow run survives both the manual resume and the automatic
  recovery, so the loss curve is continuous.`

### E3: Results dashboard

- Title: `The results dashboard turns the experiments into a planning tool`
- Three placeholders in a row, y 1.8, h 4.6, w 3.93 each, at x 0.5, 4.7,
  8.9: `SCREENSHOT: strategy comparison tab` (`shot-dashboard-strategy.png`),
  `SCREENSHOT: communication tab (NCCL + Nsight)`
  (`shot-dashboard-comm.png`), `SCREENSHOT: parallelism planner with
  predicted vs measured` (`shot-dashboard-planner.png`).
- Caption under each (10 pt muted): `Compare layouts`, `See where time
  goes`, `Plan a new model`.
- Notes: `The planner ranks TP x PP x DP layouts for a new model and shows
  its prediction next to the measured MLflow runs.`

### E4: Nebius console

- Title: `The GPU cluster and node group in the Nebius console`
- Placeholder, x 0.5, y 1.8, w 8.0, h 5.0: `SCREENSHOT: GPU cluster on
  fabric-4 and the 2 x 8 H100 node group` (`shot-console-cluster.png`).
- Optional placeholder right, x 8.75, y 1.8, w 4.08, h 5.0: `SCREENSHOT:
  kubectl get pods -o wide, one training pod per node`
  (`shot-kubectl-pods.png`).
- Notes: `Everything here was created by Terraform; nothing was clicked
  together in the console.`

---

## 5. Appendix slides (A1-A9)

Kicker `APPENDIX`. Same grid and styling as the core slides. Tables 11-12 pt.
These are for Q&A; speaker notes are optional one-liners.

### A1: Qwen3-8B, full results table

- Title: `A1. Qwen3-8B: all 15 experiments`
- Table, x 0.5, y 1.8, w 12.33, 11 pt, numbers right-aligned. Baseline row
  text lime; OOM rows red `FF6B6B`.

| Experiment | Change | Step | TFLOP/s/GPU | MFU | Peak mem |
|---|---|---|---|---|---|
| q8b-baseline | TP2 x DP8 (baseline) | 1.93 s | 415.3 | 42.0% | 49.2 GB |
| q8b-baseline-1node | TP2 x DP4, one node | 1.93 s | 416.6 | 42.1% | 55.3 GB |
| q8b-dp16 | DP16 | - | OOM | - | OOM |
| q8b-dp16-recompute | DP16 + full recompute | 2.18 s | 368.2 | 37.2%* | 65.5 GB |
| q8b-tp4-dp4 | TP4 x DP4 | 2.59 s | 311.0 | 31.4% | 30.2 GB |
| q8b-tp8-dp2 | TP8 x DP2 | 4.96 s | 162.0 | 16.4% | 20.7 GB |
| q8b-tp8-1node | TP8, one node | 9.71 s | 165.5 | 16.7% | 26.8 GB |
| q8b-tp8-2nodes | TP8 split 4 + 4 | 10.08 s | 159.5 | 16.1% | 26.8 GB |
| q8b-pp2 | TP2 x PP2 x DP4 | 2.30 s | 350.1 | 35.4% | 33.2 GB |
| q8b-fp8 | FP8 (current scaling) | 1.90 s | 426.6 | 43.1%** | 47.2 GB |
| q8b-unfused-attn | Unfused attention | 2.60 s | 309.0 | 31.2% | 69.4 GB |
| q8b-cpu-offload | Activation CPU offload | 6.33 s | 126.9 | 12.8% | 40.5 GB |
| q8b-seq16k-baseline | TP2 x DP8, seq 16k | - | OOM | - | OOM |
| q8b-seq16k-cp2 | TP2 x CP2 x DP4, seq 16k | 4.46 s | 439.8 | 44.5% | 66.7 GB |
| q8b-seq16k-tp4 | TP4 x DP4, seq 16k | 4.77 s | 411.8 | 41.6% | 63.8 GB |

- Caption (10 pt muted): `Micro-batch 1, global batch 64, seq 4096 (global
  batch 32 at seq 16384; the 1-node run uses global batch 32 for the same
  per-GPU work). *Includes recomputed forward. **Against the bf16 peak; 22%
  of the FP8 peak. MFU = TFLOP/s per GPU / 989 (H100 dense bf16).`

### A2: Qwen3-1.7B, DP vs TP vs PP

- Title: `A2. Qwen3-1.7B: a model that fits on one GPU should use plain DP`
- Left: table, x 0.5, y 1.8, w 6.5:

| Layout | Step | TFLOP/s/GPU | MFU | Peak mem |
|---|---|---|---|---|
| DP16 | 0.279 s | 344.2 | 34.8% | 44.3 GB |
| TP2 x DP8 | 0.345 s | 278.7 | 28.2% | 24.7 GB |
| PP2 x DP8 | 0.430 s | 223.4 | 22.6% | 30.7 GB |

- Right: native horizontal bar chart, x 7.3, y 1.8, w 5.53, h 3.0,
  TFLOP/s/GPU: DP16 344.2 (indigo `614EFA`), TP2 x DP8 278.7 (lime),
  PP2 x DP8 223.4 (neutral). Axis 0-400.
- Caption: `A model this small fits on one GPU, so plain DP wins; TP and PP
  only buy memory it doesn't need. PP memory is the max over ranks (the stage
  holding the logits).`

### A3: Cross-node validator sweep

- Title: `A3. Cross-node validator sweep: 16 GPUs over InfiniBand`
- Native horizontal bar chart, x 0.5, y 1.8, w 8.0, h 4.2, all bars indigo
  `614EFA`, value axis 0-500, dashed reference line at 400 (`threshold
  400 GB/s`), data labels `0.0`:

| Message size | Bus bandwidth (GB/s) |
|---|---|
| 512 MiB | 414.2 |
| 1 GiB | 445.8 |
| 2 GiB | 458.9 |
| 4 GiB | 464.4 |
| 8 GiB | 469.2 |

- Right, key numbers stacked (x 8.9, w 3.93): `451.5 GB/s` (lime) /
  `average, threshold 400`; `16/16` (white) / `IB ports ACTIVE at 400 Gb/s`;
  `0` (white) / `out-of-bounds values`.
- Caption: `Out-of-place bus bandwidth per message size, image v9 on fresh
  nodes. Source: cluster-validator/README.md`

### A4: Parallelism planner vs measured runs

- Title: `A4. The planner ranks layouts correctly, but is optimistic about
  TP8`
- Two text panels side by side (y 1.8, h 3.2, w 6.0 each), 13 pt:
  - `How it works`: `An analytical model ranks TP x PP x DP layouts for a
    model, cluster and link bandwidth. Memory: bf16 weights, fp32 grads,
    sharded optimizer, activations with optional recompute. Time: compute at
    a given MFU, TP/PP/DP communication over the slowest link each group
    spans, and the 1F1B bubble.`
  - `How well it matches`: `On the measured 8B and 32B runs it ranks layouts
    correctly, but underestimates TP8's cost by about 2x (it assumes constant
    MFU) and memory by up to about 27%. The comparison table now reads the
    measured runs live from MLflow.`
- Optional screenshot placeholder below (y 5.2, h 1.6, full width):
  `SCREENSHOT: planner predicted-vs-measured table`.
- Footer: `Source: dashboard/recommender.py`

### A5: Observability pipeline and queries

- Title: `A5. Observability: Nebius-hosted logs and GPU metrics, read by
  Grafana`
- Top: small flow of four boxes in a row (y 1.8, h 0.8): `Pods (stdout)` and
  `DCGM receiver (in the Observability Agent)` -> `Observability Agent` ->
  two targets `Nebius Logging (LogQL)` and `"Nebius Services" Prometheus
  datasource (label instance_id)` -> `Grafana (preinstalled)`.
- Text (13 pt): `GPU metrics come from the agent's built-in DCGM receiver and
  land in the "Nebius Services" Prometheus datasource, not "Nebius
  Monitoring".`
- Code box (panel, Consolas 11 pt, x 0.5, y 3.6, w 12.33, h 2.0):

```text
# check results only
{__bucket__="default", k8s_job_name=~"cluster-validator.*"}
  |~ "\\[(gpu_health|gpu_compute|nccl_bench|llm_smoketest|storage_bench|nccl_multinode)\\] |RESULT:"

# GPU temperature per node
DCGM_FI_DEV_GPU_TEMP{instance_id="<node>"}
```

- Caption: `Limits: no alerting on LogQL-derived values; 14-day log
  retention by default (hence the Object Storage copy). Source:
  docs/observability.md`

### A6: IAM and secrets

- Title: `A6. IAM and secrets are fully in Terraform, with no manual steps`
- Table, full width, column widths 3.6 / 8.73:

| Need | How |
|---|---|
| GPU nodes pull the validator image | gpu-nodes-sa in a registry-readers group with viewer on the registry; no pull secret to expire |
| MLflow reaches its bucket | mlflow-sa in a project-scoped group with editor on the project (was tenant-wide) |
| MLflow admin password | Terraform random_password stored in SecretStash; read by the training Secret, the dashboard VM and humans |
| Validator writes to the logs bucket | Service account in an IAM group; bucket_policy grants storage.editor to the group (buckets only accept groups) |
| S3 access key | Created once with --secret-delivery-mode mystery_box, so the plaintext never appears in a terminal |
| Dashboard exposure | Own security group: only port 80 (and 22 if a key is set); the default VPC group allows all ingress |

- Footer: `Source: infra/README.md`

### A7: Why not the MLPerf suite

- Title: `A7. MLPerf metric definitions, not the MLPerf suite`
- Single panel, x 0.5, y 1.8, w 12.33, h 2.0, 15 pt: `MLPerf's fixed
  reference models, datasets and submission/compliance process don't fit a
  lightweight, portable validator or this PoC's scope. The PoC reuses its
  metric definitions instead (throughput per accelerator, time-to-train), so
  the numbers stay comparable in industry terms.`
- Footer: `Source: README.md`

### A8: NVIDIA Megatron-Bridge Qwen3 H100 recipes

- Title: `A8. NVIDIA's Qwen3 recipes on H100: the layouts we started from`
- Table, full width, numbers centred. Rows for Qwen3-32B and the
  235B-A22B pretraining row in lime text (those are the two used in the
  talk).

| Model | Scenario | TP | PP | CP | EP | GPUs |
|---|---|---|---|---|---|---|
| Qwen3-600M | Pretrain | 1 | 1 | 1 | - | 1 |
| Qwen3-600M | SFT, long context (128K) | 1 | 1 | 8 | - | 8 |
| Qwen3-1.7B | Pretrain | 1 | 1 | 1 | - | 1 |
| Qwen3-4B | Pretrain | 2 | 1 | 1 | - | 2 |
| Qwen3-8B | Pretrain | 4 | 1 | 1 | - | 4 |
| Qwen3-14B | Pretrain / SFT | 8 | 1 | 1 | - | 8 |
| Qwen3-32B | Pretrain / SFT | 8 | 2 | 1 | - | 16 |
| Qwen3-30B-A3B | Pretrain | 4 | 2 | 1 | 4 | 8 |
| Qwen3-235B-A22B | Pretrain | 4 | 16 | 2 | 8 | 128 |
| Qwen3-235B-A22B | SFT | 4 | 16 | 1 | 4 | 64 |
| Qwen3-235B-A22B | PEFT (LoRA/DoRA) | 4 | 4 | 1 | 4 | 64 |

- Footer: `Source: docs/training-strategy-outline.md (NVIDIA Megatron-Bridge
  recipes). GPUs = minimum per model replica.`

### A9: Limitations to state openly

- Title: `A9. Limitations to state openly`
- Bullets, x 0.5, y 1.8, w 12.33, 14 pt:
  - Strategy runs use synthetic data for 20 iterations: they measure
    throughput and memory, not convergence (the end-to-end runs cover
    convergence).
  - Everything is measured at 16 GPUs; the 512-GPU layout is extrapolated
    from NVIDIA's recipes, the placement rules and the 99.7% two-node
    scaling.
  - Automatic recovery works through a Job-level retry after the elastic
    rendezvous times out, not a pure in-agent restart.
  - Nsight profiles and NCCL sweeps are from the first round (code paths
    unchanged); CPU offload varied between host VMs (7.87 s vs 6.33 s).
  - Pods run privileged with /dev/infiniband mounted, so each pod claims its
    whole node (managed DRA was available but not needed).
  - The PoC used H100 instead of the assignment's H200 because of capacity;
    H100 matches the reservation.
  - The results dashboard is public over plain HTTP with no auth.

---

## 6. Data reference

All numbers used in the deck, with their source files in the repo. Use this
to double-check any value.

### 6.1 Cluster and validator (`cluster-validator/README.md`, image v9, fresh nodes)

| Metric | Value |
|---|---|
| GPUs | 2 nodes x 8 H100 SXM 80 GB, fabric-4 |
| Idle temperature / ECC / row remaps | 26 °C (node 1), 28 °C (node 2); 0 ECC; 0 remaps |
| bf16 GEMM per GPU (8192³, 30 s, all 8 at once) | Node 1 683-708, node 2 691-711 TFLOP/s; across runs 681-712 (within 4%) |
| Max temperature under load / slowdown | 61 °C / 64 °C, no slowdown reasons, 700 W cap |
| NVLink all_reduce (8 GPUs) | 467.9 / 466.0 GB/s |
| IB ports | 16/16 ACTIVE at 400 Gb/s |
| Cross-node all_reduce (16 GPUs) | 451.5 GB/s average (512 MiB 414.2, 1 GiB 445.8, 2 GiB 458.9, 4 GiB 464.4, 8 GiB 469.2) |
| Network disk read / write | 219 / 223 MB/s |
| Shared filesystem read / write | 1309 / 1310 MB/s (node 1), 1346 / 1346 MB/s (node 2); 1.2-1.7 GB/s across runs |
| Thresholds | 8 GPUs; NCCL 400 GB/s per node and across nodes; GEMM 600 TFLOP/s and ≥ 90% of node median |
| One NIC lost | 7/8 x 451 ≈ 395 GB/s, below 400 (fails) |

### 6.2 NCCL sweep (`training/README.md`, nccl-* experiments, first round)

| Size | 8 GPUs NVLink | 16 GPUs IB | 2 GPUs one NIC |
|---|---|---|---|
| 1 MiB | 69.5 | 22.6 | 16.9 |
| 16 MiB | 246.1 | 158.1 | 38.6 |
| 256 MiB | 424.4 | 381.4 | 45.3 |
| 1 GiB | 468.0 | 442.4 | 46.3 |

### 6.3 End-to-end training (`training/README.md`, MLflow `e2e-q1p7b`, `e2e-q1p7b-autoresume`)

| Metric | Value |
|---|---|
| Model / data | Qwen3-1.7B from scratch, FineWeb-Edu, 1.49B tokens prepared (5.6 GB, 5 min), 1.05B trained |
| Layout | DP16, 2 nodes, 256 x 4096 tokens per step, 1000 iterations |
| Loss | 12.32 (1), 7.27 (50), 6.53 (100), 5.35 (250), 4.24 (500), 3.86 (750), 3.68 (1000) |
| Throughput | 1.88 s per step, 409 TFLOP/s/GPU, 41% MFU, 34.9k tokens/s/GPU, 558k tokens/s cluster, 44.3 GB peak |
| Original 1000-iteration run | 2.09 s / 368 TFLOP/s (blocking MLflow call per step, since fixed) |
| Checkpoints | 22.4 GB, ~17 s each, every 250 iterations, shared filesystem |
| Manual resume | Job deleted at 519, training at 501 after 65 s, losses 501-519 identical (4.231, 4.169) |
| Automatic recovery | 300 iterations, checkpoint every 100, pod killed at 222: +15 s replacement pod, +19 s survivor stops workers, +86 s rendezvous timeout, +129 s both pods recreated, +195 s training again (at iteration 204) from checkpoint 200; iterations 201-222 replayed with identical losses (5.782 at 201, 5.664 at 222) |
| Mechanism | Job backoffLimit 6 + torchrun elastic c10d rendezvous; static rendezvous hung 18 min and failed after 7 failures |

### 6.4 Strategy experiments (`training/README.md`)

- Qwen3-8B: see A1. Derived: weak scaling 415.3 / 416.6 = 99.7%; TP2 to TP8
  -61%; TP8 split vs one node within 4%; PP2 -16%; CP2 vs TP4 at 16k 7% faster
  (4.46 vs 4.77 s); FP8 2% faster; recompute 13% slower than baseline;
  unfused attention -26% throughput, +41% memory; CPU offload 3.3x slower.
- Qwen3-1.7B: see A2.
- Qwen3-30B-A3B: EP8 3.71 s, 101.6 TFLOP/s/GPU, 10.3% MFU, 62.1 GB; EP16
  9.52 s, 39.7 TFLOP/s/GPU, 4.0% MFU, 53.2 GB (2.6x slower, 9 GB saved).
- Qwen3-32B: TP4 x PP2 x DP2 10.64 s, 315.3 TFLOP/s/GPU, 31.9% MFU, 53.0 GB;
  TP8 x PP2 14.84 s, 226.2 TFLOP/s/GPU, 22.9% MFU, 40.2 GB (39% slower).
  Weights + grads + Adam ≈ 525 GB.
- Nsight (first round): GEMM 47.0% / 19.0%, NCCL 26.1% / 63.4%, fused
  attention 7.7% / 4.0%, other 19.2% / 13.6% (TP2 x DP8 / TP8 split).
  Median TP all-reduce 0.17 ms vs 0.64 ms; 747k calls; profiling overhead
  +5% / +37%.
- Total: 29 experiments defined in `training/launch.py` (NCCL sweeps,
  strategy runs, profiles and the two end-to-end runs), all logged to MLflow.

### 6.5 Scale-out (`docs/training-strategy-outline.md`)

- 512 H100 = 64 nodes. 235B-A22B pretraining: TP4 x PP16 x CP2 x EP8, 128
  GPUs (16 nodes) per replica, DP4. SFT and PEFT: 64 GPUs per job, 8 jobs.

---

## 7. QA checklist (check every rendered slide)

- [ ] 16:9, 13.33 x 7.5 in; navy `001A2B` background on every slide.
- [ ] Every title matches this brief word for word and fits in two lines at
      28 pt without overflowing into the content area.
- [ ] No text box overflows its shape or the slide; nothing is cut off at
      the edges; 0.5 in margins respected.
- [ ] No text smaller than 10 pt (9 pt only in the diagram labels that say
      so).
- [ ] No overlapping elements: timeline labels on slide 9, chart labels on
      slides 8 and 11, and diagram connectors on slides 4 and 6.
- [ ] Charts are native and editable (not images), with the specified data,
      colours, axis ranges and axis titles.
- [ ] Colour key holds everywhere: lime = inside a node / key number,
      indigo = across nodes, red only for OOM / failure / kill.
- [ ] Text on lime fills is navy, not white.
- [ ] Reference lines (400 GB/s, 600 TFLOP/s, 415.3 baseline, 80 GB) sit at
      the right value on their axis.
- [ ] Slide 11's two charts line up row by row (same category order and
      height).
- [ ] No accent bars, stripes, gradients, shadows, emoji or stock images.
- [ ] Every core slide has speaker notes; every slide with data has a source
      footer.
- [ ] Screenshot placeholders use the dashed-lime style and the exact
      labels, or the uploaded image scaled without distortion.
- [ ] Spot-check numbers against section 6: 451.5 GB/s, 99.7%, 409 TFLOP/s,
      41% MFU, 195 s, 681-712 TFLOP/s, 29 experiments.
