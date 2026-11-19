"""Run the existing E-009/E-004 deterministic suites against the installed package API.

The legacy experiment tests are reused as parity tests: their import names are
redirected to agent_native.runtime and agent_native.security. This test harness
may add experiment fixture directories to sys.path; installed package modules
must never do so.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import agent_native.runtime
import agent_native.security

ROOT = Path(__file__).resolve().parents[1]
E009 = ROOT / "experiments" / "e009"
E004 = ROOT / "experiments" / "e004"

for directory in (E009, E004):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

sys.modules["kernel"] = agent_native.runtime
sys.modules["security_model"] = agent_native.security


def _load_legacy_tests(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load parity suite: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_KERNEL_TESTS = _load_legacy_tests("agent_native_package_kernel_parity", E009 / "test_kernel.py")
_SECURITY_TESTS = _load_legacy_tests("agent_native_package_security_parity", E004 / "test_security_model.py")


def load_tests(loader, standard_tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromModule(_KERNEL_TESTS))
    suite.addTests(loader.loadTestsFromModule(_SECURITY_TESTS))
    return suite
