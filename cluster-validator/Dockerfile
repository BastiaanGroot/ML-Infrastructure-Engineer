# Lightweight, portable cluster validation image.
#
# Built on top of Nebius's own public NCCL benchmark image, which already
# ships CUDA, NCCL, the nccl-tests binaries, and the Mellanox OFED userspace
# components needed for InfiniBand — so we don't need to rebuild any of that
# from scratch. We just add a thin validation layer on top:
#   - GPU health checks (nvidia-smi based)
#   - NCCL / GPU-interconnect bandwidth checks (nccl-tests, already bundled)
#   - Storage throughput checks (fio) against the mounted network disk /
#     shared filesystem
#
# Source image: https://docs.nebius.com/kubernetes/gpu/nccl-test
FROM cr.eu-north1.nebius.cloud/nebius-benchmarks/nccl-tests:2.26.5-ubu22.04-cu12.8

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        fio \
        jq \
        bc \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/ /opt/validate/
RUN chmod +x /opt/validate/*.sh

ENTRYPOINT ["/opt/validate/run.sh"]
