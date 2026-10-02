# Demo-day speaker transcript

Word-for-word script for the 16 core slides in
[`deck-brief.md`](deck-brief.md), plus short spoken answers for the evidence
and appendix slides and the questions most likely to come up.

- **Length:** about 16 minutes (16:00 with the per-slide budgets below), at
  roughly 135 words per minute.
- **Stage cues** are in [brackets]; don't read them out.
- **Numbers** match the brief and its data reference (section 6). If a
  number changes there, change it here too.

---

## Core talk

### Slide 1: Title (0:30, ends at 0:30)

Good morning. You're considering reserving 512 H100 GPUs for six months.
Before you commit, you want to know that the platform performs, and that
it's reliable. Over the next fifteen minutes I'll show you what we found on a
16-GPU proof of concept. [point at the strip] The four numbers at the bottom
are the short version: a healthy cluster, crossing nodes that's nearly free,
and training that scales and runs efficiently.

### Slide 2: Context (0:45, ends at 1:15)

You're a team of ML engineers who want to train your own model and then
serve it on your own inference server. You told us infrastructure isn't your
core strength, so I've framed this around your three questions rather than
our components. First: can you trust the cluster? Second: does real training
work on it, and what happens when something breaks? Third: how should you
lay out a model of more than 100 billion parameters on 512 GPUs? Everything
that follows answers one of those three. Serving is out of scope today, but
I'll show you the bridge to it at the end.

### Slide 3: PoC environment (1:00, ends at 2:15)

Here's what we ran on. The assignment mentioned H200, but there was no H200
capacity in the eight-GPU shape, and H100 is the GPU you plan to reserve, so
we used that. Two nodes of eight H100s. Inside a node, the GPUs talk over
NVLink at 450 gigabytes per second per GPU, in each direction. Between nodes,
every GPU has its own 400-gigabit InfiniBand card, so each node has eight.
Per link, NVLink is about nine times faster than a network card, and that
difference drives most of the design decisions you'll see later. Both nodes
mount a two-terabyte shared filesystem for data and checkpoints, plus a
two-terabyte network disk as scratch space. We chose fabric 4 because that's
where Nebius's capacity advice showed the most spare H100s.

### Slide 4: Architecture (0:45, ends at 3:00)

All of this comes from one Terraform configuration: the network, the managed
Kubernetes cluster with its GPU node group, both storage volumes, the
container registry, a logs bucket, managed MLflow and a small dashboard VM.
Permissions go through IAM groups with least privilege. The GPU nodes pull
images with their own service account, so there are no pull secrets to
expire, and secrets live in SecretStash. Your team can rebuild this in your
own project by following the READMEs step by step, and the live project
shows no drift from the code.

### Slide 5: Technical choices (1:00, ends at 4:00)

Each choice here is the simplest option that still scales to 512 GPUs. For
scheduling we used plain Kubernetes Jobs, one pod per node; Job retries plus
torchrun's elastic rendezvous recover a lost node automatically. The most
important choice is the framework, NVIDIA's Megatron-Bridge. FSDP or
DeepSpeed ZeRO shard memory, but they can't split a single layer, a stack of
layers, a long sequence or a set of experts across GPUs, and a model above
100 billion parameters needs all four. We used one model family, Qwen3, from
under one billion to 235 billion parameters, so every strategy runs on the
same architecture. Shared data sits on the shared filesystem, which is five
to eight times faster, and monitoring uses what Nebius already provides.
Once several teams share the GPUs, managed Soperator is the natural next
step.

### Slide 6: Cluster validator (1:00, ends at 5:00)

Before you train anything, you need a yes or no on the cluster. The
validator is a container built on Nebius's own NCCL test image, so CUDA,
NCCL and the InfiniBand drivers come pre-tested. Per node, it checks GPU
health including memory row remaps, runs a thirty-second matrix-multiply
burn on every GPU at once, measures NVLink bandwidth, runs a real small
Qwen3 model forward and backward, and benchmarks both storage volumes.
Across nodes, it first checks that all eight InfiniBand ports per node are
up at 400 gigabits, then runs an all-reduce over all sixteen GPUs. The
thresholds sit ten to fifteen percent below what healthy hardware delivers,
so a single slow GPU or a degraded link fails the run. The matrix-multiply
check matters most: one throttling GPU slows down every training step, and
it doesn't show up in network numbers.

### Slide 7: Validation results (1:00, ends at 6:00)

This is the result on freshly delivered nodes, which is exactly the
acceptance test you'd run on your reservation. Every check passed. All
sixteen GPUs are healthy and within four percent of each other, at 683 to
711 teraflops of bf16 matrix multiply, running at their 700-watt power cap
with no throttling. NVLink inside each node delivers about 467 gigabytes per
second, and across both nodes, over InfiniBand, all sixteen GPUs reach 451,
within four percent of NVLink. The shared filesystem is five to eight times
faster than the network disk; that comes from the storage backends, not from
a misconfiguration. Every result lands in Nebius Logging, visible in Grafana,
and in Object Storage for ninety days, so you keep a record per node and per
run.

### Slide 8: Interconnect (1:00, ends at 7:00)

This one chart explains most of the training results. It's all-reduce
bandwidth against message size. [point at the right] For large messages, a
gigabyte, sixteen GPUs across two nodes reach 95 percent of single-node
NVLink. [point at the left] For small messages, one megabyte, they reach
only a third, because latency dominates. A single network card on its own
gives 46 gigabytes per second, 93 percent of its line rate. So what does that
mean? Data parallelism sends large gradient buckets that overlap with
compute, so it can cross nodes almost for free. Tensor parallelism sends many
medium-sized messages on the critical path of every layer, so it belongs
inside a node, on NVLink. Keep that in mind for the next few slides.

### Slide 9: End-to-end run (1:30, ends at 8:30)

Now a real run. We pretrained Qwen3 1.7B from scratch on FineWeb-Edu, a real
text dataset, with data parallelism across all sixteen GPUs. The data was
tokenized once onto the shared filesystem, and both nodes read it from
there. Over 1.05 billion tokens, about seven tenths of an epoch, the loss
drops from 12.3 to 3.7. [point at the ceiling bar] Each GPU sustained 409
teraflops, which is 41 percent MFU. That can sound low, so here's the scale:
989 is the spec-sheet peak, and even the best case, a single large matrix
multiply, only reaches about 700. Real training also runs attention,
normalization, the optimizer and communication. 41 percent is exactly what
NVIDIA's Megatron-LM reports for a model this size.

Then reliability. We injected a node failure: we deleted the training pod on
one node in the middle of the run. [point at the timeline] Kubernetes
scheduled a replacement within fifteen seconds, both nodes rejoined, and
training resumed from the last checkpoint after 195 seconds, with no human
involved. The replayed iterations gave identical losses, so the run carried
on exactly where it left off. A manual relaunch after stopping the whole job
takes 65 seconds.

### Slide 10: Parallelism primer (0:45, ends at 9:15)

To lay out a bigger model, there are five ways to split the work. Data
parallelism splits the batch. Tensor parallelism splits each layer's matrix
multiplies. Pipeline parallelism splits the layers into stages. Context
parallelism splits long sequences. And expert parallelism splits the experts
of a mixture-of-experts model. The column that matters is "place it". [point
at the lime rows] The lime ones communicate constantly and belong inside a
node. [point at the indigo rows] The indigo ones can cross nodes. The next
slides measure each row.

### Slide 11: Qwen3-8B experiments (1:30, ends at 10:45)

Here we took an 8-billion-parameter model and changed one thing at a time
from a baseline of tensor parallelism 2 times data parallelism 8, the fastest
layout that fits in memory. Read each bar as a trade-off: how fast it
trains, and how much of the 80 gigabytes it needs.

[panel 1] First, how to split. Adding the second node over InfiniBand kept
99.7 percent of the per-GPU throughput. That's weak scaling: the same work
per GPU on twice the GPUs, with almost no loss. Going from tensor
parallelism 2 to 8 costs 61 percent, and plain data parallelism doesn't fit
at all. So use the smallest tensor-parallel degree that fits, and scale out
with data parallelism.

[panel 2] Second, optimizations. FP8 is only 2 percent faster here, because
only the matrix multiplies run in FP8. Recompute makes plain data
parallelism fit, but with a 13 percent longer step. Unfused attention costs
a quarter of the throughput and 41 percent more memory, and CPU offload
makes the step 3.3 times slower.

[panel 3] Third, long context. At 16,000 tokens the baseline runs out of
memory, and context parallelism is 7 percent faster than spending the same
split on tensor parallelism.

### Slide 12: Profiling (1:00, ends at 11:45)

Why is extra tensor parallelism so expensive? We profiled two runs with
Nsight. [point at the top bar] With tensor parallelism 2 on NVLink, almost
half of the GPU time is useful matrix math. [point at the bottom bar] With
tensor parallelism 8 split across two nodes, nearly two thirds is
communication. Each tensor-parallel all-reduce takes about four times
longer, 0.64 instead of 0.17 milliseconds, and there are three quarters of a
million of them in the profile. Interestingly, splitting TP8 across nodes
ran within 4 percent of TP8 inside one node, because TP8 is already
communication-bound either way. That's the evidence behind the rule from the
previous slide: use the smallest tensor-parallel degree that fits.

### Slide 13: MoE and 32B (1:00, ends at 12:45)

Two larger cases. For the 30-billion-parameter mixture-of-experts model,
keeping the experts inside a node is 2.6 times faster than spreading them
over both nodes. The all-to-all exchange of tokens can't overlap with
compute, and spreading out only saves 9 gigabytes per GPU. For the dense
32-billion model, the weights, gradients and optimizer state alone come to
about 525 gigabytes, so it has to be sharded over at least eight GPUs.
NVIDIA's recipe, tensor 8 times pipeline 2, leaves no data parallelism on
sixteen GPUs; our layout of tensor 4, pipeline 2, data 2 is 39 percent
faster, at about 32 percent MFU. NVIDIA's 235-billion-parameter recipe
follows the same shape, which brings us to your reservation.

### Slide 14: Scale-out plan (1:30, ends at 14:15)

On 512 H100s, sixty-four nodes, the same three rules give you a
235-billion-parameter mixture-of-experts pretraining run. Rule one: tensor,
context and expert parallelism stay inside a node. Rule two: pipeline stages
cross nodes, which only needs point-to-point traffic. Rule three: scale out
with data parallelism. [point at the grid] NVIDIA's recipe needs 128 GPUs per
copy of the model, sixteen nodes, so 512 GPUs give you four data-parallel
replicas.

What should you expect? [point at the panel] We measured 99.7 percent from
one to two nodes, but that won't simply hold at sixty-four. Two public
references on the same Hopper and InfiniBand technology both lose about two
percent each time the GPU count doubles: Nebius's own MLPerf result, 1.97
times faster going from 512 to 1,024 GPUs, and Megatron-LM's runs on up to
4,608 H100s. Five doublings from two to sixty-four nodes gives about 90
percent, and that's conservative. For this model, NVIDIA's own H100
benchmark reaches about 250 teraflops per GPU. Before training, run the
validator on every batch of delivered nodes, and a short scaling ramp to
confirm the 90 percent.

### Slide 15: Results dashboard (0:45, ends at 15:00)

To plan runs like this yourselves, we built a small results dashboard that
reads MLflow live. [point at the first screenshot] The first tab compares
every strategy run. [second] The second shows where the time goes, from the
NCCL sweeps and the Nsight profiles. [third] And the third is a planner: you
pick a dense model and a cluster size, and it ranks tensor, pipeline and
data parallel layouts by memory and step time, next to what we actually
measured. It ships with five example models, from Qwen3 1.7B to Llama 3.1
405B, and adding your own is one line. It's a first estimate, not a
replacement for measuring.

### Slide 16: Wrap-up (1:00, ends at 16:00)

To wrap up. Everything you've seen can be rebuilt from an empty project in
six documented steps: infrastructure, the validator image, validation, data
preparation, training and monitoring. Every run is stored in MLflow, the
cluster is visible in Grafana, and the dashboard turns the results into a
planning tool. The next steps: use the validator as your acceptance
test on the reserved capacity; export the trained checkpoint to Hugging Face
format, which is the bridge to your own inference server; turn the validator
thresholds into alerts; and add authentication to the dashboard, with
managed Soperator once several teams share the GPUs. So, to your three
questions: the cluster is healthy, training works and recovers on its own,
and there's a measured plan for 512 GPUs. I'm happy to take your questions.

---

## Evidence slides (show during Q&A)

**E1: The validator in Grafana and the logs.** Here's the validator running
live. Grafana shows GPU temperature, utilization and power per node, next to
the check results from the validator's own logs. The pass or fail answer is
the RESULT line at the end, and the same summary is kept in Object Storage
for ninety days. On the right you can see all sixteen InfiniBand ports up and
the raw all-reduce table.

**E2: MLflow.** [point at the run list] Every run we did is stored in
MLflow, tagged by cluster, with its parameters and its loss, step time,
throughput and memory logged live, so you can compare or reproduce any of
them later. [point at the right] The failure-test run continues as one
MLflow run to iteration 300 across the injected node failure, so its loss
curve is continuous.

## Appendix slides (show if asked)

**A1: Qwen3-8B, all 15 experiments.** This is the full table behind slide
11, including the two runs that ran out of memory and the two tensor
parallel 8 placement runs. MFU is TFLOP/s per GPU divided by H100's 989
bf16 peak, counting model FLOPs only, so recompute's extra forward pass
isn't counted.

**A2: Qwen3-1.7B.** For a model that fits on one GPU, plain data parallelism
wins: tensor and pipeline parallelism only buy memory it doesn't need. These
are synthetic-data runs at a small batch; the real-data run on slide 9
reaches 41 percent MFU with the same layout, because a larger batch overlaps
more of the communication.

**A3: NVIDIA's Qwen3 recipes.** These are NVIDIA's published H100 layouts.
We started from them and changed them where measurement said so, for
example for 32B, where our layout is 39 percent faster on sixteen GPUs.

**A4: Operations.** Monitoring is fully managed: the observability agent
ships logs and GPU metrics, and Grafana reads both. On the right is how
permissions and secrets work: every permission goes through an IAM group,
nothing is a long-lived manual credential, and the dashboard VM only opens
the ports it needs.

**A5: Limitations.** I want to be upfront about these. The strategy runs
measure throughput and memory, not convergence. Everything is measured on
sixteen GPUs; the 512-GPU plan is an extrapolation. Some profiles are from
our first round, pods claim whole nodes, and the dashboard has no
authentication yet. And on expert placement, NVIDIA's tuned benchmark
spreads experts across four nodes with optimized communication, so that rule
is worth re-testing on your cluster.

## Likely questions

**Why H100 and not H200, as the assignment says?** There was no capacity in
the eight-GPU H200 shape when we built this. H100 is also what you plan to
reserve, so the numbers apply directly to your reservation.

**Why Kubernetes Jobs and not Slurm or Soperator?** At two nodes, plain
Jobs were the simplest thing that works, and they give automatic recovery
through retries. For a 512-GPU reservation shared by several people,
managed Soperator gives you Slurm's queueing and accounting on the same
Kubernetes foundation, so it's the natural next step.

**Isn't 41 percent MFU low?** No. MFU compares against a spec-sheet peak
that even a single large matrix multiply only reaches about 71 percent of.
Megatron-LM reports 41 percent for a model this size on H100, rising to 47
percent for very large models, and Meta reported 38 to 43 percent for Llama
3 405B on sixteen thousand H100s.

**Will 99.7 percent scaling hold at 64 nodes?** Not by itself; it shows the
node boundary is nearly free. Public results on Hopper with InfiniBand lose
about two percent per doubling of GPUs, including Nebius's own MLPerf run
from 512 to 1,024 GPUs at 1.97 times. From two to sixty-four nodes that's
about 90 percent, and a short scaling ramp on the reserved cluster confirms
it.

**Why is cross-node bandwidth almost as high as NVLink?** Per link it isn't:
NVLink is about nine times faster than one network card. But a node has
eight cards, and NCCL's bus bandwidth is a per-GPU figure, so for large
all-reduces sixteen GPUs land close to NVLink. Small messages show the real
gap: three times slower at one megabyte.

**Why a separate InfiniBand port check before the bandwidth test?** It names
the exact port that's down or running slow, instead of a vague bandwidth
drop, and it catches a degraded port that might still pass the bandwidth
threshold. It takes seconds.

**You keep experts inside a node, but NVIDIA's benchmark doesn't. Why?** Our
rule comes from the 30-billion MoE model on the default software stack,
where spreading experts was 2.6 times slower. NVIDIA's tuned 235B benchmark
uses optimized all-to-all communication and spreads experts over four nodes.
That's a setting to re-test on the reserved cluster, not something to assume.

**Can the planner handle our model?** If it's a dense model, yes: it ships
with five example presets, and adding yours is one line with its parameter
count, layers and hidden size. It doesn't model mixture-of-experts yet; for
those, start from NVIDIA's recipe, as we did for the 235B plan. On our
measured runs it ranks layouts correctly but is optimistic about tensor
parallel 8 by about a factor of two, so use it to shortlist layouts, then
measure.

**How do we get to inference?** Megatron-Bridge exports the trained
checkpoint to Hugging Face format, which standard inference servers load
directly. That's the first next step.
