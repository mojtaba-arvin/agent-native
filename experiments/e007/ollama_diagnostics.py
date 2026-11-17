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


def post_json(url: str, payload: dict, timeout: float = 300.0) -> dict:
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


def read_cpu_constraints() -> dict:
    def read_text(path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return None

    affinity_count = None
    affinity_list = None
    try:
        affinity = sorted(os.sched_getaffinity(0))
        affinity_count = len(affinity)
        affinity_list = ",".join(str(cpu) for cpu in affinity)
    except (AttributeError, OSError):
        pass

    cpu_max = read_text("/sys/fs/cgroup/cpu.max")
    quota_cores = None
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) == 2 and parts[0] != "max":
            try:
                quota_cores = int(parts[0]) / int(parts[1])
            except (ValueError, ZeroDivisionError):
                pass

    return {
        "logical_cpu_count": os.cpu_count(),
        "process_affinity_cpu_count": affinity_count,
        "process_affinity_cpus": affinity_list,
        "cgroup_cpu_max": cpu_max,
        "cgroup_cpu_quota_cores": quota_cores,
        "cgroup_cpuset_effective": read_text("/sys/fs/cgroup/cpuset.cpus.effective"),
        "proc_status_cpus_allowed_list": next(
            (
                line.split(":", 1)[1].strip()
                for line in (read_text("/proc/self/status") or "").splitlines()
                if line.startswith("Cpus_allowed_list:")
            ),
            None,
        ),
    }


def benchmark_prefill(base_url: str, model: str, thread_counts: list[int]) -> list[dict]:
    # Nested prompts preserve an exact prefix as the target grows. Each target is
    # requested twice while the model remains loaded: first for growth/prefix
    # reuse, then an exact warm repeat. Provider counts are authoritative.
    words = ["benchmark"] * 8000
    observations = []
    for num_threads in thread_counts:
        thread_prefix = "thread-count-" + str(num_threads) + " "
        for target_words in (1000, 2000, 4000, 8000):
            prompt = thread_prefix + " ".join(words[:target_words])
            for phase in ("growth_or_cold", "exact_warm_repeat"):
                started = time.monotonic()
                response = post_json(
                    base_url + "/api/generate",
                    {
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "keep_alive": "10m",
                        "options": {
                            "temperature": 0,
                            "seed": 42,
                            "num_ctx": 16384,
                            "num_predict": 1,
                            "num_thread": num_threads,
                        },
                    },
                )
                elapsed = time.monotonic() - started
                count = response.get("prompt_eval_count")
                cached = response.get("prompt_eval_cached_count")
                duration_ns = response.get("prompt_eval_duration")
                if type(count) is not int or type(duration_ns) is not int or duration_ns <= 0:
                    raise ValueError("ollama_prompt_telemetry_missing")
                uncached = count - cached if type(cached) is int else None
                observations.append({
                    "num_threads_requested": num_threads,
                    "target_words": target_words,
                    "phase": phase,
                    "prompt_eval_count": count,
                    "prompt_eval_cached_count": cached if type(cached) is int else None,
                    "prompt_eval_uncached_count": uncached,
                    "prompt_eval_duration_ns": duration_ns,
                    "prefill_duration_seconds": duration_ns / 1_000_000_000,
                    "uncached_prefill_tokens_per_second": (
                        uncached / (duration_ns / 1_000_000_000)
                        if uncached is not None and uncached > 0 else None
                    ),
                    "load_duration_ns": response.get("load_duration"),
                    "eval_count": response.get("eval_count"),
                    "eval_duration_ns": response.get("eval_duration"),
                    "request_elapsed_seconds": elapsed,
                    "done_reason": response.get("done_reason"),
                })
    return observations

def build_schema_probe_messages(surface: dict) -> list[dict]:
    # Match the actual local_agent upfront arm: the function schema is a
    # generic dispatch envelope, while per-tool schemas arrive in session data.
    return [
        {
            "role": "system",
            "content": (
                "You are testing the live Agent Native upfront disclosure arm. "
                "Use only agent.invoke and the supplied session surface. All exposed "
                "tool schemas are present in the session surface. Call exactly one "
                "tool: service.inspect for the Catalog service. The first call must "
                "use service_id='catalog' and omit operation. Do not write prose."
            ),
        },
        {
            "role": "user",
            "content": "Inspect the Catalog service using service.inspect.",
        },
        {
            "role": "user",
            "content": "Session surface JSON:\n"
            + json.dumps(surface, ensure_ascii=False, sort_keys=True),
        },
    ]


def schema_probe(base_url: str, model: str, num_threads: int) -> dict:
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
                "messages": build_schema_probe_messages(surface),
                "tools": [tool],
                "stream": False,
                "keep_alive": "10m",
                "options": {
                    "temperature": 0,
                    "seed": 42,
                    "num_ctx": 4096,
                    "num_predict": 128,
                    "num_thread": num_threads,
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
    parser.add_argument("--thread-counts", default="2,4,16")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        thread_counts = [int(value) for value in args.thread_counts.split(",")]
    except ValueError:
        parser.error("--thread-counts must be comma-separated integers")
    if not thread_counts or any(value < 1 or value > 64 for value in thread_counts) or len(set(thread_counts)) != len(thread_counts):
        parser.error("--thread-counts must contain unique values between 1 and 64")
    if not args.ollama_url.startswith("http://127.0.0.1:"):
        parser.error("--ollama-url must use the local loopback endpoint")

    result: dict[str, Any] = {
        "schema_version": 1,
        "model": args.model,
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            **read_cpu_constraints(),
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "rocr_visible_devices": os.environ.get("ROCR_VISIBLE_DEVICES"),
            "ollama_num_threads_env": os.environ.get("OLLAMA_NUM_THREADS"),
        },
        "prefill_benchmark": {
            "prompt_description": "nested repeated-token prompts at 1k/2k/4k/8k words; exact token and cache counts are provider-reported",
            "thread_counts_requested": thread_counts,
            "cache_method": "keep_alive=10m; each growing prompt preserves the previous exact prefix and is followed by an identical warm repeat",
            "oversubscription_hypothesis": "16 requested threads will be slower than 4 on a four-logical-CPU runner due to scheduling/context-switch overhead; treat a faster result as an unexpected observation",
            "timing_fields": ["load_duration_ns", "prompt_eval_duration_ns", "request_elapsed_seconds"],
            "observations": benchmark_prefill(args.ollama_url, args.model, thread_counts),
        },
        "short_schema_probe": schema_probe(args.ollama_url, args.model, thread_counts[0]),
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
