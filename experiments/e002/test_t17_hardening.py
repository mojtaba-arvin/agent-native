from __future__ import annotations

import unittest
from pathlib import Path

# Structural checks complement the Rust unit and raw-socket tests run by cargo test in CI.
ROOT = Path(__file__).resolve().parents[2]
RUST_PRODUCT = (ROOT / "experiments/e002/rust/src/product.rs").read_text(encoding="utf-8")
RUST_MAIN = (ROOT / "experiments/e002/rust/src/main.rs").read_text(encoding="utf-8")
GO_PRODUCT = (ROOT / "experiments/e002/go/product.go").read_text(encoding="utf-8")
GO_MAIN = (ROOT / "experiments/e002/go/main.go").read_text(encoding="utf-8")


class T17RustHttpHardeningTests(unittest.TestCase):
    def test_rust_body_is_consumed_incrementally_with_a_total_deadline(self):
        self.assertIn("async fn collect_bounded_body", RUST_PRODUCT)
        self.assertIn("timeout_at(deadline, body.frame())", RUST_PRODUCT)
        self.assertIn("output.len().saturating_add(data.len()) > MAX_BODY", RUST_PRODUCT)
        self.assertIn("BODY_READ_TIMEOUT", RUST_PRODUCT)
        self.assertNotIn("body.collect().await", RUST_PRODUCT)

    def test_rust_rejects_oversized_declared_lengths_before_reading(self):
        self.assertIn("header::CONTENT_LENGTH", RUST_PRODUCT)
        self.assertIn(".is_some_and(|length| length > MAX_BODY)", RUST_PRODUCT)
        self.assertIn("StatusCode::PAYLOAD_TOO_LARGE", RUST_PRODUCT)

    def test_rust_has_fixed_chunked_and_slow_body_regressions(self):
        for test_name in (
            "t17_exact_body_limit_is_accepted",
            "t17_fixed_body_over_limit_is_rejected",
            "t17_chunked_body_over_limit_is_rejected",
            "t17_body_read_deadline_is_enforced",
        ):
            self.assertIn(test_name, RUST_PRODUCT)

    def test_rust_connection_admission_and_header_wait_are_bounded(self):
        self.assertIn("const MAX_CONNECTIONS: usize = 64", RUST_MAIN)
        self.assertIn("try_acquire_connection_slot", RUST_MAIN)
        self.assertIn("try_acquire_owned()", RUST_MAIN)
        self.assertIn("header_read_timeout(HEADER_READ_TIMEOUT)", RUST_MAIN)
        self.assertIn("MAX_CONNECTION_LIFETIME", RUST_MAIN)
        self.assertIn("drop(stream)", RUST_MAIN)

    def test_raw_socket_regression_proves_capacity_recovery(self):
        self.assertIn("t17_stalled_headers_time_out_and_next_request_succeeds", RUST_MAIN)
        self.assertIn("t17_connection_admission_is_bounded_and_releases_capacity", RUST_MAIN)
        self.assertIn("GET /health HTTP/1.1", RUST_MAIN)
        self.assertIn("200 OK", RUST_MAIN)

    def test_go_reference_keeps_its_existing_body_and_header_bounds(self):
        self.assertIn("io.LimitReader(request.Body, t16MaxBodyBytes+1)", GO_PRODUCT)
        self.assertIn("ReadHeaderTimeout: 2 * time.Second", GO_MAIN)
        self.assertIn("IdleTimeout:       30 * time.Second", GO_MAIN)


if __name__ == "__main__":
    unittest.main()
