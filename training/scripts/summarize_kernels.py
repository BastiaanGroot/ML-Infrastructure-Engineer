#!/usr/bin/env python3
"""Roll an `nsys stats --report cuda_gpu_kern_sum --format column` table up
into coarse kernel categories (NCCL communication, GEMM, attention, other).

Usage: summarize_kernels.py ../profiles/dp-cuda_gpu_kern_sum.txt [...]

Percentages are shares of *summed kernel time* across all CUDA streams, not
of wall-clock time: NCCL kernels run on their own stream and can overlap
with compute, so they can't be read as "fraction of the step spent waiting".
"""

import re
import sys

CATEGORIES = [
    ("NCCL communication", re.compile(r"^nccl")),
    ("GEMM (matmul)", re.compile(r"nvjet|gemm|cutlass|cublas", re.I)),
    ("Attention (fused/flash)", re.compile(r"sdpa|flash|fmha|attn", re.I)),
]
ROW = re.compile(r"^\s*([\d.]+)\s+(\d+)\s+(\d+)\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(.+?)\s*$")


def summarize(path: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for line in open(path):
        m = ROW.match(line)
        if not m:
            continue
        total_ns, name = int(m.group(2)), m.group(4)
        category = next((c for c, rx in CATEGORIES if rx.search(name)), "Other")
        totals[category] = totals.get(category, 0) + total_ns
    return totals


def main() -> None:
    for path in sys.argv[1:]:
        totals = summarize(path)
        grand = sum(totals.values())
        print(f"== {path} (total kernel time {grand / 1e9:.1f}s)")
        for category, ns in sorted(totals.items(), key=lambda kv: -kv[1]):
            print(f"  {category:<26} {ns / 1e9:7.2f}s  {100 * ns / grand:5.1f}%")


if __name__ == "__main__":
    main()
