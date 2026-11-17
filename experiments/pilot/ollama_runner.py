"""Run one scheduled Agent Native pilot trial against a local Ollama model.

The adapter is deliberately limited to the disposable E-005 disclosure pilot.
It uses one provider function (agent.invoke), a local-only Ollama endpoint,
and the existing NDJSON gateway. It does not evaluate acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PILOT_ROOT = ROOT / "experiments" / "pilot"
E007_ROOT = ROOT / "experiments" / "e007"
sys.path.insert(0, str(PILOT_ROOT))
sys.path.insert(0, str(E007_ROOT))

from candidate import (  # noqa: E402
    CandidateError,
    extract_trace_proposal_ids,
    validate_candidate,
)
from metrics import load_jsonl  # noqa: E402
from schedule import ScheduleError, verify_schedule_checkout  # noqa: E402
from verify_schedule import load_schedule  # noqa: E402

MAX_PROVIDER_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_GATEWAY_MESSAGE_BYTES = 256 * 1024
MAX_CANDIDATE_BYTES = 1024 * 1024
ALLOWED_SETTINGS = {"temperature", "top_p", "seed", "num_ctx", "num_predict", "think"}


class TrialFailure(RuntimeError):
    """A classified failure that can be retained in the run manifest."""

    def __init__(self, failure_class: str, detail: str):
        self.failure_class = failure_class
        self.detail = detail
        super().__init__(detail)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise ValueError("non_finite_json_number")


def strict_json_loads(raw: str | bytes) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(
        raw,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite,
    )


def _write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def validate_local_ollama_url(base_url: str) -> str:
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        is_loopback = host == "localhost" or (
            host is not None and ipaddress.ip_address(host).is_loopback
        )
    except ValueError as error:
        raise ValueError("ollama_url_invalid") from error
    if (
        parsed.scheme != "http"
        or not host
        or not is_loopback
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("ollama_url_must_be_plain_http_loopback")
    return base_url.rstrip("/") + "/api/chat"


def build_ollama_options(settings: Any, max_output_tokens: int) -> tuple[dict, Any]:
    if not isinstance(settings, dict) or set(settings) - ALLOWED_SETTINGS:
        raise ValueError("generation_settings_not_supported_by_ollama_adapter")
    required = {"temperature", "top_p", "seed", "num_ctx", "think"}
    if not required.issubset(settings):
        raise ValueError("generation_settings_must_pin_temperature_top_p_seed_num_ctx_and_think")

    temperature = settings["temperature"]
    top_p = settings["top_p"]
    seed = settings["seed"]
    num_ctx = settings["num_ctx"]
    think = settings["think"]
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(temperature)
        or not 0 <= temperature <= 2
    ):
        raise ValueError("generation_temperature_invalid")
    if (
        isinstance(top_p, bool)
        or not isinstance(top_p, (int, float))
        or not math.isfinite(top_p)
        or not 0 < top_p <= 1
    ):
        raise ValueError("generation_top_p_invalid")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("generation_seed_invalid")
    if type(num_ctx) is not int or num_ctx < 1024:
        raise ValueError("generation_num_ctx_invalid")
    if not isinstance(think, (bool, str)) or (isinstance(think, str) and not think.strip()):
        raise ValueError("generation_think_invalid")

    num_predict = settings.get("num_predict", max_output_tokens)
    if type(num_predict) is not int or not 1 <= num_predict <= max_output_tokens:
        raise ValueError("generation_num_predict_exceeds_output_budget")

    options = {
        "temperature": temperature,
        "top_p": top_p,
        "seed": seed,
        "num_ctx": num_ctx,
        "num_predict": num_predict,
    }
    return options, think


def _provider_post(endpoint: str, payload: dict, timeout: float) -> dict:
    raw_request = _canonical_json(payload)
    request = Request(
        endpoint,
        data=raw_request,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
            if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
                raise TrialFailure("PROVIDER_ERROR", "provider_response_too_large")
    except HTTPError as error:
        error.close()
        raise TrialFailure("PROVIDER_ERROR", f"provider_http_{error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise TrialFailure("PROVIDER_ERROR", "provider_transport_failure") from error

    try:
        value = strict_json_loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise TrialFailure("PROVIDER_ERROR", "provider_response_invalid_json") from error
    if not isinstance(value, dict):
        raise TrialFailure("ADAPTER_ERROR", "provider_response_must_be_object")
    return value


def _read_gateway_message(process: subprocess.Popen) -> dict:
    if process.stdout is None:
        raise TrialFailure("ADAPTER_ERROR", "gateway_stdout_unavailable")
    raw = process.stdout.readline(MAX_GATEWAY_MESSAGE_BYTES + 1)
    if not raw:
        stderr = ""
        if process.stderr is not None and process.poll() is not None:
            stderr = process.stderr.read().decode("utf-8", errors="replace")[-2000:]
        raise TrialFailure("ADAPTER_ERROR", f"gateway_exited_without_response:{stderr}")
    if len(raw) > MAX_GATEWAY_MESSAGE_BYTES or not raw.endswith(b"\n"):
        raise TrialFailure("ADAPTER_ERROR", "gateway_response_too_large_or_unterminated")
    try:
        value = strict_json_loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise TrialFailure("ADAPTER_ERROR", "gateway_response_invalid_json") from error
    if not isinstance(value, dict):
        raise TrialFailure("ADAPTER_ERROR", "gateway_response_must_be_object")
    return value


def _gateway_exchange(process: subprocess.Popen, message: dict) -> dict:
    if process.stdin is None:
        raise TrialFailure("ADAPTER_ERROR", "gateway_stdin_unavailable")
    raw = _canonical_json(message) + b"\n"
    if len(raw) > MAX_GATEWAY_MESSAGE_BYTES:
        raise TrialFailure("ADAPTER_ERROR", "gateway_request_too_large")
    try:
        process.stdin.write(raw)
        process.stdin.flush()
    except (BrokenPipeError, OSError) as error:
        raise TrialFailure("ADAPTER_ERROR", "gateway_pipe_write_failed") from error
    return _read_gateway_message(process)


def _map_provider_tool_call(call: Any, index: int) -> dict:
    """Map one Ollama function call to the fixed gateway envelope.

    Malformed model arguments are represented as an invalid tool attempt so the
    gateway records them instead of silently repairing or dropping the call.
    """
    fallback = {
        "type": "tool_call",
        "request_id": f"invalid-call-{index}",
        "tool": "<invalid>",
        "arguments": {},
    }
    if not isinstance(call, dict):
        return fallback
    function = call.get("function")
    if not isinstance(function, dict) or function.get("name") != "agent.invoke":
        return fallback
    supplied = function.get("arguments")
    if isinstance(supplied, str):
        try:
            supplied = strict_json_loads(supplied)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return fallback
    if not isinstance(supplied, dict):
        return fallback

    return {
        "type": "tool_call",
        "request_id": supplied.get("request_id", ""),
        "tool": supplied.get("tool", ""),
        "arguments": supplied.get("arguments"),
    }


def _start_gateway(trial: dict, trace_path: Path) -> subprocess.Popen:
    budgets = trial["budgets"]
    command = [
        sys.executable,
        str(PILOT_ROOT / "gateway.py"),
        "--arm", trial["candidate_id"],
        "--trace-output", str(trace_path),
        "--run-id", trial["run_id"],
        "--candidate-id", trial["candidate_id"],
        "--model-id", trial["model_id"],
        "--task-id", trial["task_id"],
        "--attempt", str(trial["attempt"]),
        "--max-input-tokens", str(budgets["max_input_tokens"]),
        "--max-output-tokens", str(budgets["max_output_tokens"]),
        "--max-tool-calls", str(budgets["max_tool_calls"]),
    ]
    clean_environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
    }
    try:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_environment,
        )
    except OSError as error:
        raise TrialFailure("ADAPTER_ERROR", "gateway_process_start_failed") from error


def _close_gateway(process: subprocess.Popen | None) -> str:
    if process is None:
        return ""
    if process.stdin is not None and not process.stdin.closed:
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    stderr = ""
    if process.stderr is not None:
        stderr = process.stderr.read().decode("utf-8", errors="replace")[-2000:]
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
            stream.close()
    if process.returncode != 0:
        return stderr or f"gateway_exit_{process.returncode}"
    return ""


def _write_run_record(path: Path, record: dict) -> None:
    _write_exclusive(path, json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8") + b"\n")


def run_one_trial(
    trial: dict,
    *,
    plan_id: str,
    results_root: str | Path,
    base_url: str = "http://127.0.0.1:11434",
    root: str | Path = ROOT,
) -> dict:
    endpoint = validate_local_ollama_url(base_url)
    root_path = Path(root).resolve()
    results_path = Path(results_root).expanduser().resolve()
    try:
        results_path.relative_to(root_path)
    except ValueError:
        pass
    else:
        raise ValueError("results_directory_must_be_outside_checkout")
    if trial.get("candidate_id") not in {"progressive", "upfront"}:
        raise ValueError("trial_arm_invalid")
    if trial.get("fresh_state_required") is not True or trial.get("agent_visible_treatment_label") is not False:
        raise ValueError("trial_policy_invalid")

    run_dir = results_path / trial["run_id"]
    results_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir.mkdir(mode=0o700, exist_ok=False)
    trace_path = run_dir / "gateway.jsonl"
    response_path = run_dir / "model-response.txt"
    candidate_path = run_dir / "candidate.json"
    run_record_path = run_dir / "run.json"

    started_at_ns = time.monotonic_ns()
    deadline = time.monotonic() + trial["budgets"]["max_wall_seconds"]
    process = None
    record = {
        "schema_version": 1,
        "plan_id": plan_id,
        "sequence": trial["sequence"],
        "pair_id": trial["pair_id"],
        "run_id": trial["run_id"],
        "candidate_id": trial["candidate_id"],
        "task_id": trial["task_id"],
        "attempt": trial["attempt"],
        "model_id": trial["model_id"],
        "source_revision": trial["source_revision"],
        "agent_started_at_ns": started_at_ns,
        "agent_finished_at_ns": None,
        "status": "running",
        "failure_class": None,
        "failure_detail": None,
        "trace_path": str(trace_path),
        "candidate_path": None,
        "candidate_sha256": None,
        "candidate_summary": None,
        "evaluator_status": "not_run",
    }

    failure: TrialFailure | None = None
    try:
        process = _start_gateway(trial, trace_path)
        session = _read_gateway_message(process)
        if (
            session.get("type") != "session"
            or session.get("protocol_version") != "0.1"
            or not isinstance(session.get("surface"), dict)
        ):
            raise TrialFailure("ADAPTER_ERROR", "gateway_session_invalid")
        surface = session["surface"]
        dispatch = surface.get("dispatch")
        if (
            not isinstance(dispatch, dict)
            or dispatch.get("name") != "agent.invoke"
            or not isinstance(dispatch.get("input_schema"), dict)
        ):
            raise TrialFailure("ADAPTER_ERROR", "gateway_dispatch_contract_invalid")

        try:
            system_prompt = (PILOT_ROOT / "PROMPT.md").read_text(encoding="utf-8")
            task_prompt = (PILOT_ROOT / "TASK.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise TrialFailure("ADAPTER_ERROR", "pilot_prompt_unavailable") from error

        surface_text = (
            "Session surface (JSON). Use only this surface and its discovery operation:\n"
            + json.dumps(surface, ensure_ascii=False, sort_keys=True, indent=2)
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_prompt},
            {"role": "user", "content": surface_text},
        ]
        tool_definition = {
            "type": "function",
            "function": {
                "name": "agent.invoke",
                "description": dispatch.get("summary", "Invoke one named E-005 operation."),
                "parameters": dispatch["input_schema"],
            },
        }
        options, think = build_ollama_options(
            trial["generation_settings"],
            trial["budgets"]["max_output_tokens"],
        )
        turn_number = 0
        call_number = 0
        final_content = None

        while final_content is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TrialFailure("AGENT_BUDGET_EXHAUSTED", "wall_clock_budget_exhausted")
            turn_number += 1
            if turn_number > trial["budgets"]["max_tool_calls"] + 1:
                raise TrialFailure("AGENT_BUDGET_EXHAUSTED", "model_turn_budget_exhausted")

            provider_request = {
                "model": trial["model_id"],
                "messages": messages,
                "tools": [tool_definition],
                "stream": False,
                "options": options,
                "think": think,
            }
            response = _provider_post(endpoint, provider_request, timeout=max(0.1, remaining))
            message = response.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise TrialFailure("ADAPTER_ERROR", "provider_assistant_message_missing")
            input_tokens = response.get("prompt_eval_count")
            output_tokens = response.get("eval_count")
            if (
                type(input_tokens) is not int or input_tokens < 0
                or type(output_tokens) is not int or output_tokens < 0
            ):
                raise TrialFailure("ADAPTER_ERROR", "provider_token_usage_missing_or_invalid")

            usage_id = f"usage-{turn_number}-{uuid.uuid4().hex}"
            acknowledgement = _gateway_exchange(process, {
                "type": "model_usage",
                "request_id": usage_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            })
            if (
                acknowledgement.get("type") != "telemetry_ack"
                or acknowledgement.get("request_id") != usage_id
                or acknowledgement.get("accepted") is not True
            ):
                diagnostic = acknowledgement.get("diagnostic")
                if diagnostic == "MODEL_TOKEN_BUDGET_EXCEEDED":
                    raise TrialFailure("AGENT_BUDGET_EXHAUSTED", diagnostic)
                raise TrialFailure("ADAPTER_ERROR", "gateway_rejected_provider_usage")

            tool_calls = message.get("tool_calls", [])
            if not isinstance(tool_calls, list):
                raise TrialFailure("ADAPTER_ERROR", "provider_tool_calls_invalid")
            assistant_message = {"role": "assistant", "content": message.get("content") or ""}
            if "tool_calls" in message:
                assistant_message["tool_calls"] = tool_calls
            if isinstance(message.get("thinking"), str):
                assistant_message["thinking"] = message["thinking"]
            messages.append(assistant_message)

            if tool_calls:
                for call in tool_calls:
                    call_number += 1
                    gateway_request = _map_provider_tool_call(call, call_number)
                    tool_result = _gateway_exchange(process, gateway_request)
                    if tool_result.get("type") != "tool_result":
                        raise TrialFailure("ADAPTER_ERROR", "gateway_tool_result_invalid")
                    nested = tool_result.get("response")
                    if not isinstance(nested, dict):
                        raise TrialFailure("ADAPTER_ERROR", "gateway_tool_payload_invalid")
                    diagnostic_codes = {
                        item.get("code")
                        for item in nested.get("diagnostics", [])
                        if isinstance(item, dict)
                    }
                    if diagnostic_codes & {
                        "TOOL_CALL_BUDGET_EXCEEDED",
                        "MODEL_TOKEN_BUDGET_EXCEEDED",
                    }:
                        raise TrialFailure("AGENT_BUDGET_EXHAUSTED", "gateway_agent_budget_exhausted")
                    messages.append({
                        "role": "tool",
                        "tool_name": "agent.invoke",
                        "content": json.dumps(
                            nested,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    })
                continue

            content = message.get("content")
            if not isinstance(content, str):
                raise TrialFailure("ADAPTER_ERROR", "provider_final_content_missing")
            final_content = content
            _write_exclusive(response_path, content.encode("utf-8"))

        record["agent_finished_at_ns"] = time.monotonic_ns()
        candidate_object = None
        try:
            if len(final_content.encode("utf-8")) > MAX_CANDIDATE_BYTES:
                raise CandidateError("candidate_too_large")
            candidate_object = strict_json_loads(final_content)
            if not isinstance(candidate_object, dict):
                raise CandidateError("candidate_must_be_object")
            candidate_bytes = final_content.encode("utf-8")
            if not candidate_bytes.endswith(b"\n"):
                candidate_bytes += b"\n"
            _write_exclusive(candidate_path, candidate_bytes)
            record["candidate_path"] = str(candidate_path)
            record["candidate_sha256"] = hashlib.sha256(candidate_bytes).hexdigest()
        except (UnicodeEncodeError, json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError) as error:
            raise TrialFailure("INVALID_CANDIDATE", f"candidate_output_invalid:{type(error).__name__}") from error

    except TrialFailure as error:
        failure = error
    except (OSError, ValueError, KeyError, TypeError, ScheduleError) as error:
        failure = TrialFailure("ADAPTER_ERROR", f"adapter_execution_failed:{type(error).__name__}")
    finally:
        gateway_error = _close_gateway(process)
        if record["agent_finished_at_ns"] is None:
            record["agent_finished_at_ns"] = time.monotonic_ns()
        if gateway_error and failure is None:
            failure = TrialFailure("ADAPTER_ERROR", "gateway_process_failed")

    if failure is None and candidate_object is not None:
        try:
            events = load_jsonl(trace_path)
            proposal_ids = extract_trace_proposal_ids(events)
            record["candidate_summary"] = validate_candidate(
                candidate_object,
                traced_change_set_ids=proposal_ids,
            )
        except (CandidateError, OSError, ValueError) as error:
            detail = str(error)
            failure_class = (
                "TOOL_TRACE_INCOMPLETE"
                if "proposal_not_present_in_trace" in detail
                else "INVALID_CANDIDATE"
            )
            failure = TrialFailure(failure_class, detail)

    if failure is None:
        record["status"] = "candidate_ready_for_external_evaluation"
    else:
        record["status"] = "failed"
        record["failure_class"] = failure.failure_class
        record["failure_detail"] = failure.detail[:500]

    _write_run_record(run_record_path, record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", required=True, type=Path)
    parser.add_argument("--trial-sequence", required=True, type=int)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    args = parser.parse_args()

    try:
        schedule_path = args.schedule.expanduser().resolve()
        try:
            schedule_path.relative_to(ROOT.resolve())
        except ValueError:
            pass
        else:
            raise ScheduleError("schedule_must_be_outside_checkout")
        schedule = load_schedule(schedule_path)
        verify_schedule_checkout(schedule)
        if type(args.trial_sequence) is not int or not 1 <= args.trial_sequence <= len(schedule["trials"]):
            raise ScheduleError("trial_sequence_out_of_range")
        trial = schedule["trials"][args.trial_sequence - 1]
        if trial["sequence"] != args.trial_sequence:
            raise ScheduleError("trial_sequence_mismatch")
        record = run_one_trial(
            trial,
            plan_id=schedule["plan_id"],
            results_root=args.results_dir,
            base_url=args.ollama_url,
        )
    except (ScheduleError, ValueError, OSError) as error:
        parser.error(str(error))

    print(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))
    if record["status"] != "candidate_ready_for_external_evaluation":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
