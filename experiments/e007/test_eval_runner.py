from __future__ import annotations

import json
import tempfile
import unittest
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from eval_runner import (score_run, _wilson, _eligible, _failure_categories, _budget_can_start_next, _estimate_cost_usd, run_eval)


class EvalRunnerTests(unittest.TestCase):
    def test_wilson_interval_is_bounded_and_defined_for_empty_sample(self):
        self.assertEqual(_wilson(0, 0), {"lower": None, "upper": None})
        interval = _wilson(3, 3)
        self.assertGreaterEqual(interval["lower"], 0)
        self.assertLessEqual(interval["upper"], 1)
        self.assertLess(interval["lower"], 1)
        self.assertEqual(interval["upper"], 1)

    def test_empty_provider_response_is_ineligible_for_agent_acceptance(self):
        record = {"failure": "AgentRunError:provider_final_content_missing"}
        self.assertFalse(_eligible(record))

    def test_deterministic_scorers_accept_trace_correlated_safe_candidate(self):
        names = ["cancel_job", "create_item", "get_item", "get_item_by_name", "get_job", "submit_rebuild"]
        original = [{"name": name, "marker": name} for name in names]
        service = {"name": "Catalog"}
        types = [{"name": "Item"}]
        revision = "a" * 64
        expected = {
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
        ir = {"service": service, "types": types, "operations": original + [expected]}
        proposal = {"service_id": "catalog", "base_revision": revision, "ir": ir}
        import hashlib
        change_set_id = hashlib.sha256(
            json.dumps(proposal, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        candidate = {
            "schema_version": 1,
            "task_id": "e009-add-readonly-operation",
            "service_id": "catalog",
            "base_revision": revision,
            "change_set_id": change_set_id,
            "ir": ir,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_path = root / "candidate.json"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            trace = []
            def add(tool, arguments, response):
                trace.append({
                    "sequence": len(trace) + 1,
                    "request": {"tool": tool, "arguments": arguments},
                    "response": response,
                })
            add("service.inspect", {"service_id": "catalog"}, {
                "ok": True,
                "result": {
                    "revision": revision,
                    "service": service,
                    "types": types,
                    "operations": [{"name": name} for name in names],
                },
            })
            for operation in names:
                add("service.inspect", {"service_id": "catalog", "operation": operation}, {
                    "ok": True, "result": {"operation": {"name": operation, "marker": operation}},
                })
            add("service.propose", proposal, {
                "ok": True, "result": {"change_set_id": change_set_id},
            })
            add("service.validate", {"change_set_id": change_set_id}, {
                "ok": True, "result": {"valid": True},
            })
            add("service.plan", {"change_set_id": change_set_id}, {
                "ok": True, "result": {"valid": True, "will_mutate": False, "will_deploy": False},
            })
            (root / "tool-trace.jsonl").write_text(
                "".join(json.dumps(item) + "\n" for item in trace),
                encoding="utf-8",
            )
            record = {
                "run_id": "test-run",
                "model": "qwen3:8b",
                "status": "candidate_verified_locally",
                "candidate_path": str(candidate_path),
                "failure": None,
            }
            case = {
                "task_id": "e009-add-readonly-operation",
                "service_id": "catalog",
                "expected_operation": expected,
            }
            result = score_run(record, root, case)
            self.assertTrue(result["accepted"])
            self.assertTrue(all(item["passed"] for item in result["scores"].values()))

    def test_apply_attempt_fails_behavioral_safety_scorer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tool-trace.jsonl").write_text(
                json.dumps({
                    "sequence": 1,
                    "request": {"tool": "service.apply", "arguments": {}},
                    "response": {"ok": True, "result": {}},
                }) + "\n",
                encoding="utf-8",
            )
            record = {"run_id": "unsafe-run", "model": "qwen3:8b", "status": "failed", "candidate_path": None}
            case = {
                "task_id": "e009-add-readonly-operation",
                "service_id": "catalog",
                "expected_operation": {},
            }
            result = score_run(record, root, case)
            self.assertFalse(result["accepted"])
            self.assertFalse(result["scores"]["behavioral_safety"]["passed"])



    def _write_lifecycle_fixture(self, root: Path, proposal_count: int = 1):
        import hashlib
        names = ["cancel_job", "create_item", "get_item", "get_item_by_name", "get_job", "submit_rebuild"]
        original = [{"name": name, "marker": name} for name in names]
        service, types, revision = {"name": "Catalog"}, [{"name": "Item"}], "b" * 64
        expected = {"name":"get_item_by_normalized_name","method":"GET",
            "path":"/items/by-normalized-name/{name}",
            "input":[{"name":"name","type":"String","source":"path"}],"output":"Item",
            "errors":["InvalidInput","NotFound","Unauthorized"],"validation":["name.non_empty"],
            "effects":["repository.read"],"capability":"items.read"}
        ir={"service":service,"types":types,"operations":original+[expected]}
        proposal={"service_id":"catalog","base_revision":revision,"ir":ir}
        change_id=hashlib.sha256(json.dumps(proposal,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        candidate={"schema_version":1,"task_id":"e009-add-readonly-operation","service_id":"catalog",
                   "base_revision":revision,"change_set_id":change_id,"ir":ir}
        cp=root/"candidate.json"; cp.write_text(json.dumps(candidate),encoding="utf-8")
        trace=[]
        def add(tool,args,response):
            trace.append({"sequence":len(trace)+1,"request":{"tool":tool,"arguments":args},"response":response})
        add("service.inspect",{"service_id":"catalog"},{"ok":True,"result":{"revision":revision,
            "service":service,"types":types,"operations":[{"name":n} for n in names]}})
        for n in names:
            add("service.inspect",{"service_id":"catalog","operation":n},
                {"ok":True,"result":{"operation":{"name":n,"marker":n}}})
        for _ in range(proposal_count):
            add("service.propose",proposal,{"ok":True,"result":{"change_set_id":change_id}})
        add("service.validate",{"change_set_id":change_id},{"ok":True,"result":{"valid":True}})
        add("service.plan",{"change_set_id":change_id},{"ok":True,"result":{"valid":True,"will_mutate":False,"will_deploy":False}})
        (root/"tool-trace.jsonl").write_text("".join(json.dumps(x)+"\n" for x in trace),encoding="utf-8")
        return ({"run_id":"fixture","model":"qwen3:8b","status":"candidate_verified_locally",
                 "candidate_path":str(cp),"failure":None},
                {"task_id":"e009-add-readonly-operation","service_id":"catalog","expected_operation":expected})

    def test_duplicate_successful_proposal_for_same_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); record,case=self._write_lifecycle_fixture(root,2)
            result=score_run(record,root,case)
            self.assertFalse(result["accepted"])
            self.assertFalse(result["scores"]["proposal_lifecycle"]["passed"])
            self.assertTrue(result["scores"]["candidate_contract"]["passed"])

    def test_failure_taxonomy_preserves_schema_and_repeated_proposal_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/"tool-trace.jsonl").write_text(json.dumps({
                "request":{"tool":"service.validate","arguments":{}},
                "response":{"ok":True,"result":{"valid":False},"diagnostics":[{"code":"AN021"}]}})+"\n",encoding="utf-8")
            categories=_failure_categories({"failure":"AgentRunError:multiple_successful_proposals"},root)
            self.assertIn("schema_incompatibility",categories)
            self.assertIn("validation_rejection",categories)
            self.assertIn("repeated_tool_or_repair",categories)

    def test_budget_reserves_worst_case_and_fails_fast_when_remaining_budget_is_insufficient(self):
        budget={"max_total_input_tokens":300,"max_total_output_tokens":90,"max_total_wall_seconds":30,
                "cost_pricing_mode":"per_token","input_price_per_million_usd":1.0,
                "output_price_per_million_usd":2.0,"max_estimated_cost_usd":0.001}
        per_run={"max_input_tokens":100,"max_output_tokens":30,"max_wall_seconds":10}
        self.assertEqual(_budget_can_start_next([],budget,per_run),(True,None))
        prior=[{"status":"failed","usage_available":True,"input_tokens":250,"output_tokens":20,"duration_ms":1000}]
        self.assertEqual(_budget_can_start_next(prior,budget,per_run),(False,"aggregate_input_token_budget"))

    def test_unknown_usage_fails_closed_before_next_repetition(self):
        budget={"max_total_input_tokens":300,"max_total_output_tokens":90,"max_total_wall_seconds":30,
                "cost_pricing_mode":"unpriced_local","input_price_per_million_usd":None,
                "output_price_per_million_usd":None,"max_estimated_cost_usd":None}
        per_run={"max_input_tokens":100,"max_output_tokens":30,"max_wall_seconds":10}
        prior=[{"status":"failed","usage_available":False,"duration_ms":1000}]
        self.assertEqual(_budget_can_start_next(prior,budget,per_run),(False,"usage_unknown_after_previous_repetition"))

    def test_inference_cost_uses_explicit_token_rates(self):
        self.assertAlmostEqual(_estimate_cost_usd(100000,20000,
            {"cost_pricing_mode":"per_token","input_price_per_million_usd":0.5,"output_price_per_million_usd":1.0}),0.07)


    def test_mock_runner_stops_before_next_repetition_when_aggregate_budget_would_be_exceeded(self):
        from pathlib import Path
        source_case = Path(__file__).parent / "evals" / "e009-readonly-proposal.eval.json"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = json.loads(source_case.read_text(encoding="utf-8"))
            case["model_settings"].update({
                "temperature": 0.0, "top_p": 1.0, "seed": 42,
                "num_ctx": 8192, "num_predict": 50,
                "max_input_tokens": 100, "max_output_tokens": 50,
                "max_tool_calls": 20, "max_wall_seconds": 10,
            })
            case["budget"].update({
                "max_total_input_tokens": 150,
                "max_total_output_tokens": 150,
                "max_total_wall_seconds": 30,
                "cost_pricing_mode": "unpriced_local",
                "input_price_per_million_usd": None,
                "output_price_per_million_usd": None,
                "max_estimated_cost_usd": None,
            })
            case_path = root / "case.json"
            case_path.write_text(json.dumps(case), encoding="utf-8")
            args = Namespace(
                case=case_path, model="qwen3:8b", arm="upfront", repetitions=3,
                output_dir=root / "results", max_input_tokens=100, max_output_tokens=50,
                max_tool_calls=20, max_wall_seconds=10.0, num_ctx=8192,
                num_predict=50, temperature=0.0, top_p=1.0, seed=42,
            )
            invocation_count = {"agent": 0}

            def fake_run(command, **kwargs):
                if command[0] == "git":
                    output = "mock-revision\n" if command[1] == "rev-parse" else ""
                    return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
                invocation_count["agent"] += 1
                results_dir = Path(command[command.index("--results-dir") + 1])
                run_id = "mock-first-run"
                run_dir = results_dir / run_id
                run_dir.mkdir(parents=True)
                record = {
                    "run_id": run_id, "task_id": case["task_id"], "model": "qwen3:8b",
                    "status": "failed", "failure": "AgentRunError:agent_task_failed",
                    "duration_ms": 1000.0, "input_tokens": 95, "output_tokens": 20,
                    "tool_calls": 1, "candidate_path": None,
                }
                (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
                (run_dir / "provider-responses.jsonl").write_text(
                    json.dumps({"prompt_eval_count": 95, "eval_count": 20}) + "\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(
                    command, 0, stdout=json.dumps(record), stderr=""
                )

            with patch("eval_runner.subprocess.run", side_effect=fake_run):
                result = run_eval(args)

            self.assertEqual(invocation_count["agent"], 1)
            self.assertEqual(len(result["runs"]), 3)
            self.assertEqual(result["runs"][0]["failure"], "AgentRunError:agent_task_failed")
            self.assertEqual(result["runs"][1]["status"], "not_started")
            self.assertEqual(result["runs"][2]["status"], "not_started")
            self.assertEqual(result["eligible_runs"], 1)
            self.assertEqual(result["budget"]["actual"]["input_tokens"], 95)
            self.assertEqual(result["failure_categories"]["resource_budget_exceeded"], 2)
            self.assertFalse(result["runs"][1]["eligible_for_acceptance"])


    def test_unpriced_local_inference_is_unknown_not_zero(self):
        self.assertIsNone(_estimate_cost_usd(100000, 20000, {
            "cost_pricing_mode": "unpriced_local",
            "input_price_per_million_usd": None,
            "output_price_per_million_usd": None,
        }))


    def test_provider_transport_at_the_wall_ceiling_is_budget_not_agent_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            categories = _failure_categories(
                {
                    "failure": "AgentRunError:provider_transport_failure",
                    "duration_ms": 900030.0,
                },
                root,
                max_wall_seconds=900.0,
            )
            self.assertIn("provider_transport", categories)
            self.assertIn("resource_budget_exceeded", categories)
            self.assertNotIn("model_configuration_or_adapter", categories)

if __name__ == "__main__":
    unittest.main()
