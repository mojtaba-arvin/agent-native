"""Static regression tests for CI cost controls and validation safeguards."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CIWorkflowContractTests(unittest.TestCase):
    def read(self, path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_t16_image_is_scoped_but_manual_and_task_branch_paths_remain(self):
        workflow = self.read(".github/workflows/t16-image.yml")
        self.assertIn("pull_request:\n    paths:", workflow)
        self.assertIn('".github/workflows/t16-image.yml"', workflow)
        self.assertIn('"experiments/e002/t16/**"', workflow)
        self.assertIn('"experiments/e002/go/**"', workflow)
        self.assertIn('"experiments/e002/rust/**"', workflow)
        self.assertIn('branches:\n      - "task/T16-controlled-host-slo"', workflow)
        self.assertIn("workflow_dispatch:", workflow)

    def test_t16_preflight_is_scoped_to_contract_inputs(self):
        workflow = self.read(".github/workflows/t16-preflight.yml")
        self.assertIn("pull_request:\n    paths:", workflow)
        self.assertIn('"experiments/e002/t16/**"', workflow)
        self.assertIn('"experiments/e002/storage-conformance-contract.md"', workflow)
        self.assertIn("workflow_dispatch:", workflow)

    def test_t16_image_and_preflight_share_persistent_build_caches(self):
        image = self.read(".github/workflows/t16-image.yml")
        preflight = self.read(".github/workflows/t16-preflight.yml")
        for workflow in (image, preflight):
            self.assertIn("cache-dependency-path:", workflow)
            self.assertIn("experiments/e002/go/go.mod", workflow)
            self.assertIn("experiments/e002/t16/loadgen/go.mod", workflow)
            self.assertIn("Swatinem/rust-cache@v2", workflow)
            self.assertIn("docker/setup-buildx-action@v4", workflow)
            self.assertIn("--cache-from type=gha,scope=t16-candidates", workflow)
            self.assertIn("--cache-to type=gha,mode=max,scope=t16-candidates", workflow)
        self.assertIn('--build-arg SOURCE_SHA="$GITHUB_SHA"', image)
        self.assertIn('--build-arg BUILD_TIME=', image)

    def test_extended_lane_keeps_full_validation_for_relevant_changes(self):
        workflow = self.read(".github/workflows/ci.yml")
        self.assertIn("path === '.github/workflows/ci.yml'", workflow)
        self.assertIn("path.startsWith('src/')", workflow)
        self.assertIn("path.startsWith('tests/')", workflow)
        self.assertIn("path.startsWith('experiments/e002/')", workflow)
        self.assertIn("path.startsWith('experiments/e009/')", workflow)
        self.assertNotIn("path.startsWith('.github/')", workflow)
        self.assertNotIn("path.startsWith('scripts/')", workflow)
        self.assertIn("github.event_name == 'schedule'", workflow)
        self.assertIn("github.event_name == 'merge_group'", workflow)

    def test_native_toolchain_caches_are_enabled_without_removing_validation(self):
        workflow = self.read(".github/workflows/ci.yml")
        self.assertIn("cache: true", workflow)
        self.assertIn("Swatinem/rust-cache@v2", workflow)
        for required_gate in (
            "E-001 Go and Rust baselines",
            "E-002 Go runtime",
            "E-002 Rust runtime",
            "E-002 WASI Preview 2 runtime",
            "E-002 BEAM runtime",
            "E-002 PostgreSQL storage and cross-engine parity",
            "E-009 cgroup-v2 capacity smoke",
        ):
            self.assertIn(required_gate, workflow)

    def test_required_acceptance_workflows_are_unchanged(self):
        self.assertIn("name: task-acceptance", self.read(".github/workflows/task-acceptance.yml"))
        self.assertIn("name: task-gate", self.read(".github/workflows/task-gate.yml"))


if __name__ == "__main__":
    unittest.main()
