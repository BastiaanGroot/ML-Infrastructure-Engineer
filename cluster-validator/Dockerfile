# Lightweight, portable cluster validation image.
#
# Built on top of Nebius's own public NCCL benchmark image (already has
# CUDA, NCCL, nccl-tests, and the Mellanox OFED userspace components) — we
# add a thin validation layer: GPU health (nvidia-smi), per-GPU bf16 GEMM
# throughput under load (PyTorch), NCCL/interconnect
# bandwidth (nccl-tests), an LLM smoketest (PyTorch + Transformers, a real
# minimal Qwen3-0.6B checkpoint - see scripts/llm_smoketest.*), and storage
# throughput (fio). See cluster-validator/README.md for the full rationale,
# including why the LLM smoketest needs a real PyTorch runtime rather than
# staying "thin" like the rest.
#
# Source image: https://docs.nebius.com/kubernetes/gpu/nccl-test
FROM cr.eu-north1.nebius.cloud/nebius-benchmarks/nccl-tests:2.26.5-ubu22.04-cu12.8

# python3-dev: Triton compiles a small C launcher against Python.h at runtime.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        fio jq bc python3 python3-pip python3-dev \
    && rm -rf /var/lib/apt/lists/*

# torch + transformers: LLM smoketest, pinned to a combination verified on
# the H100 nodes (the PyPI torch wheel bundles its own CUDA 13 runtime).
# boto3: optional Object Storage log upload.
# Checkpoint: Qwen3-0.6B, the smallest real model in the same Qwen3 family
# used for the actual training experiments (see ../training/README.md) -
# baked in at build time so the smoketest needs no network access at
# validation time, and it's small enough (~0.6B params) that this stays a
# quick smoke test, not a real inference benchmark.
RUN pip3 install --no-cache-dir \
        torch==2.14.0 transformers==5.17.0 boto3 \
    && python3 -c "from transformers import AutoModelForCausalLM, AutoTokenizer; \
m = 'Qwen/Qwen3-0.6B'; \
AutoModelForCausalLM.from_pretrained(m).save_pretrained('/opt/validate/qwen3-0.6b'); \
AutoTokenizer.from_pretrained(m).save_pretrained('/opt/validate/qwen3-0.6b')"

# The base image builds nccl-tests here but doesn't put it on PATH.
ENV PATH=/opt/nccl-tests/build:$PATH
COPY scripts/ /opt/validate/
RUN chmod +x /opt/validate/*.sh /opt/validate/*.py

ENTRYPOINT ["/opt/validate/run.sh"]
