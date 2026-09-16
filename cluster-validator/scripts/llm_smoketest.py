#!/usr/bin/env python3
"""LLM smoketest: loads a tiny open-source causal-LM checkpoint baked into
the image (see Dockerfile) and runs a short model.generate() (the inference
path) plus one forward+backward pass (the training path) on GPU.

This validates the actual ML framework stack (CUDA <-> driver <-> PyTorch <->
model loading/execution) end-to-end - gpu_health.sh and nccl_bench.sh already
cover raw GPU health and interconnect throughput, but neither of them proves
an actual PyTorch model can load and run correctly on this hardware, which is
what matters right before a real LLM training or inference job.

Writes its result directly to $RESULTS_DIR/llm_smoketest.json using the same
schema as common.sh's write_result (name/status/message/metrics), so run.sh's
summary aggregation picks it up like every other check.

Env vars:
  RESULTS_DIR                   - where to write llm_smoketest.json (default: /results)
  LLM_SMOKETEST_MODEL_PATH      - path to the baked-in checkpoint (default: /opt/validate/tiny-llm)
  LLM_SMOKETEST_PROMPT          - prompt text (default: "Nebius GPU cluster validation:")
  LLM_SMOKETEST_MAX_NEW_TOKENS  - tokens to generate (default: 20)
"""
import json
import os
import sys
import time

NAME = "llm_smoketest"
RESULTS_DIR = os.environ.get("RESULTS_DIR", "/results")
MODEL_PATH = os.environ.get("LLM_SMOKETEST_MODEL_PATH", "/opt/validate/tiny-llm")
PROMPT = os.environ.get("LLM_SMOKETEST_PROMPT", "Nebius GPU cluster validation:")
MAX_NEW_TOKENS = int(os.environ.get("LLM_SMOKETEST_MAX_NEW_TOKENS", "20"))


def write_result(status, message, metrics=None):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{NAME}.json")
    with open(path, "w") as f:
        json.dump(
            {"name": NAME, "status": status, "message": message, "metrics": metrics or {}},
            f,
        )
    print(f"[{NAME}] {status}: {message}")


def main():
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as e:
        write_result("fail", f"required python packages missing: {e}")
        return 1

    if not torch.cuda.is_available():
        write_result(
            "fail",
            "torch.cuda.is_available() is False - no usable GPU for the ML framework stack",
        )
        return 1

    if not os.path.isdir(MODEL_PATH):
        write_result(
            "fail",
            f"model checkpoint not found at {MODEL_PATH} (expected baked into the image)",
        )
        return 1

    device = torch.device("cuda")
    device_name = torch.cuda.get_device_name(device)

    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
    model = AutoModelForCausalLM.from_pretrained(MODEL_PATH).to(device)
    load_seconds = time.time() - t0

    inputs = tokenizer(PROMPT, return_tensors="pt").to(device)

    # Inference path: generate a few tokens.
    model.eval()
    t0 = time.time()
    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
    generation_seconds = time.time() - t0
    tokens_generated = int(output_ids.shape[-1] - inputs["input_ids"].shape[-1])

    # Training path: one forward + backward pass, confirm gradients actually
    # flow (not just that .backward() doesn't crash).
    model.train()
    model.zero_grad()
    outputs = model(**inputs, labels=inputs["input_ids"])
    outputs.loss.backward()
    grad_norms = [p.grad.norm().item() for p in model.parameters() if p.grad is not None]
    backward_pass_ok = len(grad_norms) > 0 and all(
        gn == gn and gn != float("inf") for gn in grad_norms  # gn == gn is False for NaN
    )

    metrics = {
        "device_name": device_name,
        "load_seconds": round(load_seconds, 3),
        "generation_seconds": round(generation_seconds, 3),
        "tokens_generated": tokens_generated,
        "backward_pass_ok": backward_pass_ok,
    }

    if tokens_generated <= 0:
        write_result("fail", "model.generate() produced no new tokens", metrics)
        return 1
    if not backward_pass_ok:
        write_result("fail", "backward pass produced no valid gradients", metrics)
        return 1

    write_result(
        "pass",
        f"generated {tokens_generated} tokens and completed a backward pass on {device_name}",
        metrics,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # last-resort catch so we always write a result file
        write_result("fail", f"unhandled exception: {e}")
        sys.exit(1)
