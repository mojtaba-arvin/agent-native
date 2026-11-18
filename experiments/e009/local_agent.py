"""Run one bounded local Ollama agent against the integrated E-009 kernel.

This is a local research adapter, not the framework's final agent protocol and
not an acceptance oracle. It writes private run artifacts outside the checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import subprocess
import socket
import threading
import sys
import time
import uuid
from http.client import HTTPConnection
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
E009_ROOT = Path(__file__).resolve().parent
MAX_MESSAGE_BYTES = 256 * 1024
MAX_PROVIDER_BYTES = 8 * 1024 * 1024
MAX_CANDIDATE_BYTES = 1024 * 1024
TASK_ID = "e009-add-readonly-operation"
SERVICE_ID = "catalog"
EXPECTED_OPERATION = {
    "name": "get_item_by_normalized_name",
    "method": "GET",
    "path": "/items/by-normalized-name/{name}",
    "input": [{"name": "name", "type": "String", "source": "path"}],
    "output": "Item",
    "errors": ["InvalidInput", "NotFound", "Unauthorized"],
    "validation": ["name.non_empty"],
    "effects": ["repository.read"],
    "capability": "items.read",
}


class AgentRunError(RuntimeError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AgentRunError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise AgentRunError("non_finite_json_number")


def strict_json(raw: bytes | str) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(
        raw,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_constant,
    )


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def validate_ollama_endpoint(value: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port or 80
        address = ipaddress.ip_address(host) if host else None
    except ValueError as error:
        raise ValueError("ollama_endpoint_must_use_loopback_ip") from error
    if (
        parsed.scheme != "http"
        or address is None
        or not address.is_loopback
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ollama_endpoint_must_be_plain_http_loopback_ip")
    return str(address), port


def provider_chat(
    endpoint: tuple[str, int],
    payload: dict,
    timeout: float,
) -> dict:
    host, port = endpoint
    connection = HTTPConnection(host, port, timeout=timeout)
    deadline_expired = threading.Event()
    response = None

    def interrupt_socket() -> None:
        deadline_expired.set()
        active_socket = connection.sock
        if response is not None:
            response_file = getattr(response, "fp", None)
            raw_stream = getattr(response_file, "raw", None)
            response_socket = getattr(raw_stream, "_sock", None)
            if response_socket is not None:
                active_socket = response_socket
        if active_socket is not None:
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                active_socket.close()
            except OSError:
                pass

    timer = threading.Timer(timeout, interrupt_socket)
    timer.daemon = True
    try:
        timer.start()
        connection.request(
            "POST",
            "/api/chat",
            body=canonical_json(payload),
            headers={"Content-Type": "application/json", "Connection": "close"},
        )
        if deadline_expired.is_set():
            raise AgentRunError("provider_deadline_exceeded")
        response = connection.getresponse()
        raw = response.read(MAX_PROVIDER_BYTES + 1)
        if deadline_expired.is_set():
            raise AgentRunError("provider_deadline_exceeded")
        if len(raw) > MAX_PROVIDER_BYTES:
            raise AgentRunError("provider_response_too_large")
        if response.status != 200:
            raise AgentRunError(f"provider_http_{response.status}")
        result = strict_json(raw)
    except AgentRunError:
        if deadline_expired.is_set():
            raise AgentRunError("provider_deadline_exceeded")
        raise
    except Exception as error:
        if deadline_expired.is_set():
            raise AgentRunError("provider_deadline_exceeded") from error
        raise AgentRunError("provider_transport_failure") from error
    finally:
        timer.cancel()
        connection.close()
    if not isinstance(result, dict):
        raise AgentRunError("provider_response_must_be_object")
    return result


def read_gateway(process: subprocess.Popen) -> dict:
    if process.stdout is None:
        raise AgentRunError("gateway_stdout_unavailable")
    raw = process.stdout.readline(MAX_MESSAGE_BYTES + 1)
    if not raw or len(raw) > MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
        raise AgentRunError("gateway_response_missing_or_oversized")
    value = strict_json(raw)
    if not isinstance(value, dict):
        raise AgentRunError("gateway_response_must_be_object")
    return value


def gateway_exchange(process: subprocess.Popen, message: dict) -> dict:
    if process.stdin is None:
        raise AgentRunError("gateway_stdin_unavailable")
    raw = canonical_json(message) + b"\n"
    if len(raw) > MAX_MESSAGE_BYTES:
        raise AgentRunError("gateway_request_too_large")
    process.stdin.write(raw)
    process.stdin.flush()
    return read_gateway(process)


def close_gateway(process: subprocess.Popen | None) -> str | None:
    if process is None:
        return None
    if process.stdin and not process.stdin.closed:
        process.stdin.close()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    stderr = ""
    if process.stderr:
        stderr = process.stderr.read().decode("utf-8", errors="replace")[-2000:]
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream and not stream.closed:
            stream.close()
    if process.returncode != 0:
        return stderr or f"gateway_exit_{process.returncode}"
    return None


def map_tool_call(call: Any, index: int) -> dict:
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
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = strict_json(arguments)
        except (ValueError, UnicodeDecodeError):
            return fallback
    if not isinstance(arguments, dict):
        return fallback
    return {
        "type": "tool_call",
        "request_id": arguments.get("request_id", ""),
        "tool": arguments.get("tool", ""),
        "arguments": arguments.get("arguments"),
    }



def prevalidate_tool_call(request: dict, surface: dict) -> dict | None:
    """Validate known tool-specific required arguments before crossing the Gateway boundary."""
    tool_name = request.get("tool")
    arguments = request.get("arguments")
    exposed_tools = surface.get("tools") if isinstance(surface, dict) else None
    if not isinstance(tool_name, str) or not isinstance(exposed_tools, list):
        return None
    tool_spec = next(
        (item for item in exposed_tools if isinstance(item, dict) and item.get("name") == tool_name),
        None,
    )
    schema = tool_spec.get("input_schema") if isinstance(tool_spec, dict) else None
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return None
    if not isinstance(arguments, dict):
        return {
            "protocol_version": "0.1",
            "request_id": request.get("request_id"),
            "ok": False,
            "result": None,
            "diagnostics": [{
                "code": "ARGUMENT_SHAPE",
                "message": f"{tool_name} arguments must be a JSON object.",
                "source_span": None,
                "fix_hint": "Pass the tool arguments as an object.",
            }],
            "next_actions": ["Retry with an arguments object matching the exposed input schema."],
        }
    required = schema.get("required", [])
    if not isinstance(required, list):
        return None
    missing = [name for name in required if isinstance(name, str) and name not in arguments]
    if not missing:
        return None
    if tool_name == "service.inspect" and "service_id" in missing:
        message = 'service.inspect requires arguments.service_id; provide service_id: "catalog".'
        fix_hint = 'Set arguments to {"service_id":"catalog"}; omit operation for the service-level inspection.'
    else:
        message = f"{tool_name} is missing required argument(s): {', '.join(missing)}."
        fix_hint = f"Provide all required fields: {', '.join(missing)}."
    return {
        "protocol_version": "0.1",
        "request_id": request.get("request_id"),
        "ok": False,
        "result": None,
        "diagnostics": [{
            "code": "ARGUMENTS_REQUIRED",
            "message": message,
            "source_span": None,
            "fix_hint": fix_hint,
        }],
        "next_actions": ["Correct the missing required argument(s) and retry once."],
    }


def _append_jsonl(path: Path, event: dict) -> None:
    with path.open("ab") as stream:
        stream.write(canonical_json(event) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _persist_candidate_response(path: Path, raw_candidate: bytes, record: dict) -> None:
    """Retain a parsed final JSON candidate even when trusted verification fails."""
    newline = b"\n"
    _write_exclusive(path, raw_candidate + (b"" if raw_candidate.endswith(newline) else newline))
    record["candidate_path"] = str(path)



def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def verify_candidate(
    candidate: Any,
    *,
    inspected: dict,
    inspected_operations: dict[str, dict],
    successful_proposal: dict,
    validation_result: dict,
    plan_result: dict,
    tool_sequence: list[str],
    validation_change_set_id: str | None = None,
    plan_change_set_id: str | None = None,
) -> dict:
    required = {
        "schema_version", "task_id", "service_id",
        "base_revision", "change_set_id", "ir",
    }
    if not isinstance(candidate, dict) or set(candidate) != required:
        raise AgentRunError("candidate_fields_invalid")
    if type(candidate["schema_version"]) is not int or candidate["schema_version"] != 1 or candidate["task_id"] != TASK_ID:
        raise AgentRunError("candidate_identity_invalid")
    if candidate["service_id"] != SERVICE_ID:
        raise AgentRunError("candidate_service_invalid")

    proposal_args = successful_proposal["arguments"]
    proposal_result = successful_proposal["result"]
    ir = candidate["ir"]
    if not isinstance(ir, dict):
        raise AgentRunError("candidate_ir_invalid")
    proposal = {
        "service_id": SERVICE_ID,
        "base_revision": candidate["base_revision"],
        "ir": ir,
    }
    computed_id = digest(proposal)
    if validation_change_set_id is not None and validation_change_set_id != computed_id:
        raise AgentRunError("candidate_validation_hash_mismatch")
    if plan_change_set_id is not None and plan_change_set_id != computed_id:
        raise AgentRunError("candidate_plan_hash_mismatch")
    if (
        candidate["base_revision"] != inspected["revision"]
        or candidate["base_revision"] != proposal_args["base_revision"]
        or candidate["change_set_id"] != computed_id
        or proposal_result.get("change_set_id") != computed_id
        or proposal_args.get("ir") != ir
    ):
        raise AgentRunError("candidate_proposal_identity_mismatch")

    if not validation_result.get("ok") or not validation_result.get("result", {}).get("valid"):
        raise AgentRunError("proposal_validation_not_successful")
    if not plan_result.get("ok"):
        raise AgentRunError("proposal_plan_not_successful")
    plan = plan_result.get("result") or {}
    if not plan.get("valid") or plan.get("will_mutate") is not False or plan.get("will_deploy") is not False:
        raise AgentRunError("proposal_plan_not_safe")

    expected_service = inspected["service"]
    if ir.get("service") != expected_service or ir.get("types") != inspected["types"]:
        raise AgentRunError("candidate_changed_service_or_types")
    original_names = [item["name"] for item in inspected["operations"]]
    if set(inspected_operations) != set(original_names):
        raise AgentRunError("not_all_existing_operations_were_inspected")
    original_operations = [inspected_operations[name] for name in original_names]
    operations = ir.get("operations")
    if not isinstance(operations, list) or operations[:-1] != original_operations:
        raise AgentRunError("candidate_modified_existing_operations")
    if operations[-1] != EXPECTED_OPERATION:
        raise AgentRunError("candidate_new_operation_does_not_match_task")
    if len(operations) != len(original_operations) + 1:
        raise AgentRunError("candidate_operation_count_invalid")
    if plan.get("effects") is None or "repository.read" not in plan["effects"]:
        raise AgentRunError("planned_read_effect_missing")

    proposal_indices = [i for i, name in enumerate(tool_sequence) if name == "service.propose"]
    validation_indices = [i for i, name in enumerate(tool_sequence) if name == "service.validate"]
    plan_indices = [i for i, name in enumerate(tool_sequence) if name == "service.plan"]
    if (
        not proposal_indices
        or len(proposal_indices) > 3
        or not validation_indices
        or not plan_indices
        or tool_sequence.count("service.apply") != 0
        or "service.inspect" not in tool_sequence
        or proposal_indices[-1] <= tool_sequence.index("service.inspect")
        or validation_indices[-1] <= proposal_indices[-1]
        or plan_indices[-1] <= validation_indices[-1]
    ):
        raise AgentRunError("required_tool_sequence_invalid")
    return {
        "task_id": TASK_ID,
        "service_id": SERVICE_ID,
        "base_revision": candidate["base_revision"],
        "change_set_id": computed_id,
        "preserved_operation_count": len(original_operations),
        "added_operation": EXPECTED_OPERATION["name"],
        "validation": "passed",
        "plan": "valid_no_mutation_no_deployment",
    }


def _proposal_attempt_gate(request: dict, attempts: int) -> tuple[int, dict | None]:
    """Count every proposal request and block the fourth attempt."""
    next_attempt = attempts + 1
    if next_attempt > 3:
        return next_attempt, _proposal_budget_response(request)
    return next_attempt, None


def _proposal_budget_response(request: dict) -> dict:
    return {
        "protocol_version": "0.1",
        "request_id": request.get("request_id", "invalid"),
        "ok": False,
        "result": None,
        "diagnostics": [{
            "code": "PROPOSAL_REPAIR_BUDGET_EXCEEDED",
            "message": "The bounded evaluation adapter permits at most three service.propose attempts per task run.",
            "source_span": None,
            "fix_hint": "Do not repeat proposal attempts. Inspect and correct the full IR before using the remaining attempt budget.",
        }],
        "next_actions": ["Stop proposing; finish only with an honest failure response."],
    }


def _plan_gate_response(
    request: dict,
    successful_proposal: dict | None,
    validation_result: dict | None,
    validation_change_set_id: str | None,
) -> dict | None:
    """Block planning unless the latest proposal hash passed semantic validation."""
    arguments = request.get("arguments")
    current_id = (successful_proposal or {}).get("result", {}).get("change_set_id")
    valid = bool(
        validation_result
        and validation_result.get("ok")
        and (validation_result.get("result") or {}).get("valid") is True
        and isinstance(current_id, str)
        and validation_change_set_id == current_id
        and isinstance(arguments, dict)
        and arguments.get("change_set_id") == current_id
    )
    if valid:
        return None
    return {
        "protocol_version": "0.1",
        "request_id": request.get("request_id", "invalid"),
        "ok": False,
        "result": None,
        "diagnostics": [{
            "code": "VALIDATION_REQUIRED",
            "message": "Planning is blocked until the current complete IR proposal passes validation.",
            "source_span": None,
            "fix_hint": (
                "Check result.valid, not only the outer ok flag. Rebuild the complete IR snapshot "
                "(ir_version=1, service, types, all existing operations plus the new operation), "
                "then propose and validate it."
            ),
        }],
        "next_actions": [
            "service.propose a corrected complete IR; then service.validate the new change_set_id"
        ],
    }


def run(args: argparse.Namespace) -> dict:
    endpoint = validate_ollama_endpoint(args.ollama_url)
    results_root = args.results_dir.expanduser().resolve()
    try:
        results_root.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("results_directory_must_be_outside_repository")
    results_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_id = f"e009-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    run_dir = results_root / run_id
    run_dir.mkdir(mode=0o700, exist_ok=False)
    trace_path = run_dir / "tool-trace.jsonl"
    _write_exclusive(trace_path, b"")
    provider_diagnostics_path = run_dir / "provider-responses.jsonl"
    _write_exclusive(provider_diagnostics_path, b"")
    candidate_path = run_dir / "candidate.json"
    result_path = run_dir / "run.json"

    started = time.monotonic_ns()
    deadline = time.monotonic() + args.max_wall_seconds
    process = None
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "task_id": TASK_ID,
        "model": args.model,
        "arm": args.arm,
        "status": "running",
        "started_at_monotonic_ns": started,
        "finished_at_monotonic_ns": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_calls": 0,
        "candidate_path": None,
        "verification": None,
        "failure": None,
    }

    try:
        clean_env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}
        process = subprocess.Popen(
            [
                sys.executable,
                str(E009_ROOT / "agent_gateway.py"),
                "--arm",
                args.arm,
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_env,
        )
        session = read_gateway(process)
        if session.get("type") != "session" or session.get("protocol_version") != "0.1":
            raise AgentRunError("gateway_session_invalid")
        surface = session.get("surface")
        dispatch = surface.get("dispatch") if isinstance(surface, dict) else None
        if (
            not isinstance(dispatch, dict)
            or dispatch.get("name") != "agent.invoke"
            or not isinstance(dispatch.get("input_schema"), dict)
        ):
            raise AgentRunError("gateway_dispatch_contract_invalid")

        disclosure_instruction = (
            "This run uses the upfront disclosure arm: all exposed tool schemas are already present in the session surface. Never call interface.describe. "
            "Your first tool call must be service.inspect with exactly service_id='catalog' and no operation argument. "
            if args.arm == "upfront"
            else
            "This run uses the progressive disclosure arm. Before each tool whose detailed schema has not yet been retrieved, call interface.describe with its exact name and use that returned schema. Retrieve the service.inspect schema first. "
        )
        system_prompt = (
            "You are an engineering agent working on the live Agent Native E-009 service. "
            "Use only the single agent.invoke function and the session surface. "
            + disclosure_instruction
            + "Then inspect each existing operation name returned by the service-level inspection exactly once; never inspect the requested new operation. "
            "After service.propose returns ok=true, your immediate next tool call MUST be service.validate with the exact returned change_set_id. If result.valid=true, your immediate next tool call MUST be service.plan with that same change_set_id. Do not inspect or propose again after a proposal is accepted. "
            "The service identifier is exactly 'catalog'; its display name is 'Catalog'. "
            "For service.inspect, the argument key is service_id, never name; pass service_id='catalog'. "
            "Follow every exposed input schema exactly and do not invent or rename argument fields. "
            "The ir argument to service.propose is a COMPLETE canonical service IR snapshot, never a patch or delta. "
            "It MUST have exactly these top-level fields: ir_version (integer 1), service, types, operations. "
            "Copy the complete service name/version and every existing type/field from the service inspection. "
            "Copy every existing operation as the exact JSON object returned by its own service.inspect result; do not recreate, normalize, infer, or edit any field. Preserve method, path, input declarations, errors, validation, effects, and capability exactly, then append the requested operation. "
            "If a proposal is rejected with INSPECTION_INCOMPLETE, inspect every operation named in next_actions and then immediately resubmit the corrected complete IR. "
            "If you receive IR_PRESERVATION_MISMATCH, copy the named existing operation objects exactly from the retained inspect results and retry with a new proposal. "
            "The new operation input MUST be an array of declarations, not an object map: [{name:'name',source:'path',type:'String'}]. "
            "Every input declaration must contain name, source, and type. Do not omit ir_version or existing operations. "
            "A service.validate response can have outer ok=true while result.valid=false. Treat valid=false as a validation failure. "
            "When validation fails, do not call service.plan. Read result.diagnostics and next_actions, fix the COMPLETE IR, and submit a different proposal hash. "
            "Call service.plan only after service.validate returns result.valid=true for the same change_set_id. "
            "If a tool returns ok=false, read its diagnostics, correct the request, and never repeat an identical invalid call. "
            "The service-level inspection lists every existing operation name. Call service.inspect once for each listed existing operation, using service_id='catalog' and operation=<exact listed name>, before proposing. "
            "Do not inspect the requested new operation; it does not exist until proposed. Inspect only names returned by the service-level inspection. "
            "Follow the gateway next_actions and diagnostics; never propose while an inspection is still missing. "
            "Preserve every existing type and operation exactly. Propose exactly the task operation. "
            "Use the inspected revision. Validate the exact proposal, then plan it. "
            "Never call service.apply. No shell, files, network, secrets, or deployment tools exist. "
            "Return only the exact final JSON candidate requested by the task. Never invent tool results."
        )
        task = (E009_ROOT / "AGENT_TASK.md").read_text(encoding="utf-8")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
            {
                "role": "user",
                "content": "Session surface JSON:\n" + json.dumps(surface, ensure_ascii=False, sort_keys=True),
            },
        ]
        tool_definition = {
            "type": "function",
            "function": {
                "name": "agent.invoke",
                "description": dispatch.get("summary", "Invoke one named Agent Native operation."),
                "parameters": dispatch["input_schema"],
            },
        }

        inspected = None
        inspected_operations: dict[str, dict] = {}
        successful_proposal = None
        proposal_attempts = 0
        validation_result = None
        validation_change_set_id = None
        plan_result = None
        plan_change_set_id = None
        tool_sequence: list[str] = []
        failed_tool_requests: set[str] = set()
        prevalidation_repair_attempts: set[str] = set()
        final_content = None
        turn = 0
        call_number = 0
        while final_content is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AgentRunError("wall_clock_budget_exhausted")
            turn += 1
            if turn > args.max_tool_calls + 1:
                raise AgentRunError("model_turn_budget_exhausted")
            remaining_output = args.max_output_tokens - record["output_tokens"]
            if remaining_output <= 0:
                raise AgentRunError("output_token_budget_exhausted")
            payload = {
                "model": args.model,
                "messages": messages,
                "tools": [tool_definition],
                "stream": False,
                "options": {
                    "temperature": args.temperature,
                    "top_p": args.top_p,
                    "seed": args.seed,
                    "num_ctx": args.num_ctx,
                    "num_predict": min(args.num_predict, remaining_output),
                },
                "think": args.think,
            }
            response = provider_chat(endpoint, payload, timeout=max(0.1, remaining))
            message = response.get("message")
            if isinstance(message, dict):
                calls_for_diagnostics = message.get("tool_calls")
                _append_jsonl(provider_diagnostics_path, {
                    "response_index": turn,
                    "model": response.get("model"),
                    "done": response.get("done"),
                    "done_reason": response.get("done_reason"),
                    "prompt_eval_count": response.get("prompt_eval_count"),
                    "eval_count": response.get("eval_count"),
                    "message_keys": sorted(message.keys()),
                    "content_chars": len(message.get("content")) if isinstance(message.get("content"), str) else None,
                    "thinking_chars": len(message.get("thinking")) if isinstance(message.get("thinking"), str) else None,
                    "tool_calls_count": len(calls_for_diagnostics) if isinstance(calls_for_diagnostics, list) else None,
                })
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise AgentRunError("provider_assistant_message_missing")
            input_tokens = response.get("prompt_eval_count")
            output_tokens = response.get("eval_count")
            if type(input_tokens) is not int or input_tokens < 0 or type(output_tokens) is not int or output_tokens < 0:
                raise AgentRunError("provider_token_usage_missing")
            record["input_tokens"] += input_tokens
            record["output_tokens"] += output_tokens
            if record["input_tokens"] > args.max_input_tokens:
                raise AgentRunError("input_token_budget_exceeded")

            calls = message.get("tool_calls", [])
            if not isinstance(calls, list):
                raise AgentRunError("provider_tool_calls_invalid")
            assistant_message = {"role": "assistant", "content": message.get("content") or ""}
            if calls:
                assistant_message["tool_calls"] = calls
            messages.append(assistant_message)

            if calls:
                for provider_call in calls:
                    call_number += 1
                    if call_number > args.max_tool_calls:
                        raise AgentRunError("tool_call_budget_exceeded")
                    request = map_tool_call(provider_call, call_number)
                    tool_name = request.get("tool")
                    arguments = request.get("arguments")
                    if tool_name == "service.plan":
                        nested = _plan_gate_response(
                            request, successful_proposal, validation_result, validation_change_set_id
                        )
                    elif tool_name == "service.propose":
                        proposal_attempts, nested = _proposal_attempt_gate(
                            request, proposal_attempts
                        )
                    else:
                        nested = None
                    execution_origin = "runner_gate" if nested is not None else "gateway"
                    prevalidation_repair_exhausted = False
                    if nested is None:
                        prevalidated = prevalidate_tool_call(request, surface)
                        if prevalidated is not None:
                            execution_origin = "runner_prevalidation"
                            diagnostic = (prevalidated.get("diagnostics") or [{}])[0]
                            repair_key = f"{tool_name}:{diagnostic.get('code')}"
                            if repair_key in prevalidation_repair_attempts:
                                prevalidation_repair_exhausted = True
                            else:
                                prevalidation_repair_attempts.add(repair_key)
                            nested = prevalidated
                        else:
                            result = gateway_exchange(process, request)
                            if result.get("type") != "tool_result" or not isinstance(result.get("response"), dict):
                                raise AgentRunError("gateway_tool_result_invalid")
                            nested = result["response"]
                    if tool_name == "service.propose" and nested.get("ok") and successful_proposal is not None:
                        previous_valid = bool(
                            validation_result
                            and validation_result.get("ok")
                            and (validation_result.get("result") or {}).get("valid") is True
                        )
                        previous_id = (successful_proposal.get("result") or {}).get("change_set_id")
                        current_id = (nested.get("result") or {}).get("change_set_id")
                        repair_code = None
                        repair_message = None
                        if previous_valid:
                            repair_code = "PROPOSAL_ALREADY_VALIDATED"
                            repair_message = "A proposal has already passed validation. Continue with its plan; do not submit another proposal."
                        elif validation_result is None:
                            repair_code = "PROPOSAL_REQUIRES_VALIDATION"
                            repair_message = "Validate the current proposal before replacing it."
                        elif current_id == previous_id:
                            repair_code = "DUPLICATE_UNREPAIRED_PROPOSAL"
                            repair_message = "This exact proposal was already rejected by validation. Change the IR structure; input must be an array such as [{name:'name',source:'path',type:'String'}], not an object map."
                        if repair_code is not None:
                            nested = {
                                **nested,
                                "ok": False,
                                "result": None,
                                "diagnostics": [{
                                    "code": repair_code,
                                    "message": repair_message,
                                    "source_span": None,
                                    "fix_hint": "Use the inspected get_item_by_name input declaration shape: an array of {name, source, type} objects.",
                                }],
                                "next_actions": [
                                    "Correct the IR input array using {name, source, type}; then submit one new proposal."
                                ],
                            }
                    _append_jsonl(trace_path, {
                        "sequence": call_number,
                        "request": request,
                        "response": nested,
                        "execution_origin": execution_origin,
                    })
                    record["tool_calls"] = call_number
                    tool_sequence.append(tool_name if isinstance(tool_name, str) else "<invalid>")
                    if prevalidation_repair_exhausted:
                        raise AgentRunError("prevalidation_repair_failed")
                    if not nested.get("ok"):
                        fingerprint = json.dumps(
                            request,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if fingerprint in failed_tool_requests:
                            raise AgentRunError("repeated_invalid_tool_call")
                        failed_tool_requests.add(fingerprint)
                    if tool_name == "service.inspect" and nested.get("ok"):
                        inspected_result = nested.get("result") or {}
                        if isinstance(arguments, dict) and "operation" not in arguments:
                            inspected = inspected_result
                        elif isinstance(arguments, dict) and isinstance(arguments.get("operation"), str):
                            inspected_operations[arguments["operation"]] = inspected_result.get("operation")
                    elif tool_name == "service.propose" and nested.get("ok"):
                        if (
                            inspected is None
                            or set(inspected_operations) != {
                                item["name"] for item in inspected["operations"]
                            }
                        ):
                            raise AgentRunError("inspect_all_existing_operations_before_proposal")
                        successful_proposal = {
                            "arguments": arguments,
                            "result": nested.get("result") or {},
                        }
                        validation_result = None
                        validation_change_set_id = None
                        plan_result = None
                        plan_change_set_id = None
                    elif tool_name == "service.validate" and nested.get("ok"):
                        validation_result = nested
                        validation_change_set_id = arguments.get("change_set_id") if isinstance(arguments, dict) else None
                    elif tool_name == "service.plan" and nested.get("ok"):
                        plan_result = nested
                        plan_change_set_id = arguments.get("change_set_id") if isinstance(arguments, dict) else None
                    elif tool_name == "service.apply":
                        raise AgentRunError("agent_attempted_apply")
                    messages.append({
                        "role": "tool",
                        "tool_name": "agent.invoke",
                        "content": json.dumps(nested, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    })
                continue

            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise AgentRunError("provider_final_content_missing")
            final_content = content

        raw_candidate = final_content.encode("utf-8")
        if len(raw_candidate) > MAX_CANDIDATE_BYTES:
            raise AgentRunError("candidate_too_large")
        candidate = strict_json(raw_candidate)
        if isinstance(candidate, dict):
            # Preserve final structured output before semantic verification so
            # rejected candidates remain available for post-run inspection.
            _persist_candidate_response(candidate_path, raw_candidate, record)
        if successful_proposal is None:
            raise AgentRunError("proposal_not_successfully_created")
        verification = verify_candidate(
            candidate,
            inspected=inspected or {},
            inspected_operations=inspected_operations,
            successful_proposal=successful_proposal or {},
            validation_result=validation_result or {},
            plan_result=plan_result or {},
            tool_sequence=tool_sequence,
            validation_change_set_id=validation_change_set_id,
            plan_change_set_id=plan_change_set_id,
        )
        record["verification"] = verification
        record["status"] = "candidate_verified_locally"

    except Exception as error:
        record["status"] = "failed"
        record["failure"] = f"{type(error).__name__}:{str(error)[:400]}"
    finally:
        gateway_error = close_gateway(process)
        if gateway_error and record["status"] != "failed":
            record["status"] = "failed"
            record["failure"] = "gateway_shutdown_failed:" + gateway_error
        record["finished_at_monotonic_ns"] = time.monotonic_ns()
        record["duration_ms"] = round(
            (record["finished_at_monotonic_ns"] - started) / 1_000_000,
            3,
        )
        _write_exclusive(
            result_path,
            json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n",
        )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--arm", choices=("progressive", "upfront"), default="progressive")
    parser.add_argument("--results-dir", type=Path, default=Path("/tmp/agent-native-e009-runs"))
    parser.add_argument("--max-input-tokens", type=int, default=24000)
    parser.add_argument("--max-output-tokens", type=int, default=6000)
    parser.add_argument("--max-tool-calls", type=int, default=20)
    parser.add_argument("--max-wall-seconds", type=float, default=600)
    parser.add_argument("--num-ctx", type=int, default=32768)
    parser.add_argument("--num-predict", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--think", action="store_true")
    args = parser.parse_args()
    for name in ("max_input_tokens", "max_output_tokens", "max_tool_calls", "max_wall_seconds", "num_ctx", "num_predict"):
        value = getattr(args, name)
        if isinstance(value, bool) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.num_predict > args.max_output_tokens:
        parser.error("--num-predict cannot exceed --max-output-tokens")
    if (
        not math.isfinite(args.max_wall_seconds)
        or not math.isfinite(args.temperature)
        or not math.isfinite(args.top_p)
        or not 0 <= args.temperature <= 2
        or not 0 < args.top_p <= 1
        or not 0 <= args.seed <= 2**32 - 1
        or args.num_ctx < 1024
    ):
        parser.error("generation settings, seed, context, or time budget are out of range")
    try:
        record = run(args)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))
    if record["status"] != "candidate_verified_locally":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
