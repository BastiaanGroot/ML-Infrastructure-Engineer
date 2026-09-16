# Lightweight, portable cluster validation image.
#
# Built on top of Nebius's own public NCCL benchmark image (already has
# CUDA, NCCL, nccl-tests, and the Mellanox OFED userspace components) — we
# add a thin validation layer: GPU health (nvidia-smi), NCCL/interconnect
# bandwidth (nccl-tests), an LLM smoketest (PyTorch + Transformers, see
# scripts/llm_smoketest.*), and storage throughput (fio). See
# cluster-validator/README.md for the full rationale, including why the LLM
# smoketest needs a real PyTorch runtime rather than staying "thin" like the
# rest.
#
# Source image: https://docs.nebius.com/kubernetes/gpu/nccl-test
FROM cr.eu-north1.nebius.cloud/nebius-benchmarks/nccl-tests:2.26.5-ubu22.04-cu12.8

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        fio jq bc python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# torch: cu128 wheel matches the base image's CUDA 12.8 (LLM smoketest).
# transformers: LLM smoketest. boto3: optional Object Storage log upload.
# The tiny checkpoint is baked in here too, so the smoketest needs no
# network access at validation time.
RUN pip3 install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cu128 \
        torch transformers boto3 \
    && python3 -c "from transformers import AutoModelForCausalLM, AutoTokenizer; \
m = 'hf-internal-testing/tiny-random-gpt2'; \
AutoModelForCausalLM.from_pretrained(m).save_pretrained('/opt/validate/tiny-llm'); \
AutoTokenizer.from_pretrained(m).save_pretrained('/opt/validate/tiny-llm')"

COPY scripts/ /opt/validate/
RUN chmod +x /opt/validate/*.sh

ENTRYPOINT ["/opt/validate/run.sh"]
