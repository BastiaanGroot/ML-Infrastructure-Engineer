# Lightweight, portable cluster validation image.
#
# Built on top of Nebius's own public NCCL benchmark image, which already
# ships CUDA, NCCL, the nccl-tests binaries, and the Mellanox OFED userspace
# components needed for InfiniBand — so we don't need to rebuild any of that
# from scratch. We add a thin validation layer on top:
#   - GPU health checks (nvidia-smi based)
#   - NCCL / GPU-interconnect bandwidth checks (nccl-tests, already bundled)
#   - Storage throughput checks (fio) against the mounted network disk /
#     shared filesystem
#   - LLM smoketest (PyTorch + Transformers): loads a tiny open-source
#     causal-LM checkpoint baked into the image and runs a short generate()
#     (inference path) plus one forward+backward pass (training path) on
#     GPU, so the actual ML framework stack — not just raw GPU/NCCL
#     throughput — is validated before a real training/inference job runs.
#     This is the one part of the image that isn't "thin": it adds a real
#     (CPU-arch-matched) PyTorch runtime, which is unavoidable if we want the
#     check to mean anything for an LLM workload — still far smaller than a
#     full training image, and needs no network access at validation time
#     since the checkpoint is baked in at build time.
#
# Source image: https://docs.nebius.com/kubernetes/gpu/nccl-test
FROM cr.eu-north1.nebius.cloud/nebius-benchmarks/nccl-tests:2.26.5-ubu22.04-cu12.8

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        fio \
        jq \
        bc \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# torch cu128 wheel matches the base image's CUDA 12.8. transformers is only
# needed for the LLM smoketest; boto3 is only needed for the optional
# object-storage log upload (see upload_logs.py) — both are already this
# lightweight so it's not worth splitting into a separate image layer/stage.
RUN pip3 install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu128 \
    && pip3 install --no-cache-dir transformers boto3

# Bake a tiny (few-MB, randomly-initialized GPT-2 architecture) checkpoint
# into the image at build time, so the smoketest needs no network access at
# validation time — keeping the container portable/air-gapped-friendly.
RUN python3 -c "\
from transformers import AutoModelForCausalLM, AutoTokenizer; \
m = 'hf-internal-testing/tiny-random-gpt2'; \
AutoModelForCausalLM.from_pretrained(m).save_pretrained('/opt/validate/tiny-llm'); \
AutoTokenizer.from_pretrained(m).save_pretrained('/opt/validate/tiny-llm')"

COPY scripts/ /opt/validate/
RUN chmod +x /opt/validate/*.sh

ENTRYPOINT ["/opt/validate/run.sh"]
