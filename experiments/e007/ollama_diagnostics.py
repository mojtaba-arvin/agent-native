#!/usr/bin/env python3
"""Bounded Ollama infrastructure and tool-schema diagnostics; not an E-007 lifecycle eval."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def post_json(url: str, payload: dict, timeout: float = 900.0) -> dict:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("ollama_response_must_be_object")
    return result


def read_gateway_surface() -> tuple[subprocess.Popen, dict]:
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "experiments/e009/agent_gateway.py"), "--arm", "upfront"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
    )
    if process.stdout is None:
        process.kill()
        raise RuntimeError("gateway_stdout_unavailable")
    raw = process.stdout.readline(256 * 1024 + 1)
    if not raw or len(raw) > 256 * 1024 or not raw.endswith(b"\n"):
        process.kill()
        raise RuntimeError("gateway_session_missing_or_oversized")
    session = json.loads(raw.decode("utf-8"))
    if not isinstance(session, dict) or session.get("type") != "session":
        process.kill()
        raise RuntimeError("gateway_session_invalid")
    return process, session


def benchmark_prefill(base_url: str, model: str, repetitions: int) -> list[dict]:
    # A stable, approximately 1k-token body. Ollama reports the exact token count.
    prompt = " ".join(["benchmark"] * 1000)
    observations = []
    for repetition in range(1, repetitions + 1):
        started = time.monotonic()
        response = post_json(
            base_url + "/api/generate",
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": 0,
                "options": {
                    "temperature": 0,
                    "seed": 42,
                    "num_ctx": 4096,
                    "num_predict": 1,
                },
            },
        )
        elapsed = time.monotonic() - started
        count = response.get("prompt_eval_count")
        duration_ns = response.get("prompt_eval_duration")
        if type(count) is not int or type(duration_ns) is not int or duration_ns <= 0:
            raise ValueError("ollama_prompt_telemetry_missing")
        observations.append({
            "repetition": repetition,
            "prompt_eval_count": count,
            "prompt_eval_duration_ns": duration_ns,
            "prefill_tokens_per_second": count / (duration_ns / 1_000_000_000),
            "load_duration_ns": response.get("load_duration"),
            "eval_count": response.get("eval_count"),
            "eval_duration_ns": response.get("eval_duration"),
            "request_elapsed_seconds": elapsed,
            "done_reason": response.get("done_reason"),
        })
    return observations


def schema_probe(base_url: str, model: str) -> dict:
    gateway, session = read_gateway_surface()
    try:
        surface = session.get("surface")
        dispatch = surface.get("dispatch") if isinstance(surface, dict) else None
        if not isinstance(dispatch, dict) or not isinstance(dispatch.get("input_schema"), dict):
            raise ValueError("gateway_dispatch_schema_missing")
        tool = {
            "type": "function",
            "function": {
                "name": dispatch.get("name"),
                "description": dispatch.get("summary", "Invoke one Agent Native tool."),
                "parameters": dispatch["input_schema"],
            },
        }
        response = post_json(
            base_url + "/api/chat",
            {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "This is a short isolated tool-schema conformance probe. "
                            "Call exactly one exposed tool. Invoke service.inspect for the Catalog service. "
                            "Use service_id='catalog'. Do not call any other tool and do not write prose."
                        ),
                    },
                    {
                        "role": "user",
                        "content": "Inspect the Catalog service using service.inspect.",
                    },
                ],
                "tools": [tool],
                "stream": False,
                "keep_alive": "5m",
                "options": {
                    "temperature": 0,
                    "seed": 42,
                    "num_ctx": 4096,
                    "num_predict": 128,
                },
                "think": False,
            },
        )
        message = response.get("message")
        calls = message.get("tool_calls") if isinstance(message, dict) else None
        observed = None
        if isinstance(calls, list) and calls:
            function = calls[0].get("function") if isinstance(calls[0], dict) else None
            if isinstance(function, dict):
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = None
                observed = {
                    "function_name": function.get("name"),
                    "arguments": arguments,
                }
        arguments = observed.get("arguments") if isinstance(observed, dict) else None
        passed = bool(
            observed
            and observed.get("function_name") == "agent.invoke"
            and isinstance(arguments, dict)
            and arguments.get("tool") == "service.inspect"
            and isinstance(arguments.get("arguments"), dict)
            and arguments["arguments"].get("service_id") == "catalog"
            and arguments["arguments"].get("operation") in (None, "")
        )
        return {
            "passed": passed,
            "observed_tool_call": observed,
            "prompt_eval_count": response.get("prompt_eval_count"),
            "prompt_eval_duration_ns": response.get("prompt_eval_duration"),
            "eval_count": response.get("eval_count"),
            "eval_duration_ns": response.get("eval_duration"),
            "response_done_reason": response.get("done_reason"),
            "schema_source": "live E-009 upfront Gateway session surface",
        }
    finally:
        gateway.terminate()
        try:
            gateway.wait(timeout=3)
        except subprocess.TimeoutExpired:
            gateway.kill()
            gateway.wait(timeout=3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 5:
        parser.error("--repetitions must be between 1 and 5")
    if not args.ollama_url.startswith("http://127.0.0.1:"):
        parser.error("--ollama-url must use the local loopback endpoint")

    result: dict[str, Any] = {
        "schema_version": 1,
        "model": args.model,
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "rocr_visible_devices": os.environ.get("ROCR_VISIBLE_DEVICES"),
        },
        "prefill_benchmark": {
            "prompt_description": "same 1000-word repeated-token prompt; exact token count is provider-reported",
            "repetitions": args.repetitions,
            "observations": benchmark_prefill(args.ollama_url, args.model, args.repetitions),
        },
        "short_schema_probe": schema_probe(args.ollama_url, args.model),
        "interpretation": (
            "Infrastructure diagnostics only. This does not exercise the full agent lifecycle "
            "and is not model-capability or E-007 acceptance evidence."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
