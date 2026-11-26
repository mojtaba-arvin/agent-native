from __future__ import annotations

import unittest

from product_workload import WORKLOAD_SEED, mix_counts, request_class


class ProductWorkloadScheduleTests(unittest.TestCase):
    def test_exact_product_mix_for_multiple_of_ten(self):
        self.assertEqual(mix_counts(5000), {
            "authorized_read": 3000,
            "expected_denial": 500,
            "job_admission": 500,
            "validate_plan": 1000,
        })

    def test_schedule_is_reproducible_and_seeded(self):
        first = [request_class(index, seed=WORKLOAD_SEED) for index in range(100)]
        second = [request_class(index, seed=WORKLOAD_SEED) for index in range(100)]
        alternate = [request_class(index, seed=WORKLOAD_SEED + 1) for index in range(100)]
        self.assertEqual(first, second)
        self.assertNotEqual(first, alternate)

    def test_each_ten_request_block_has_exact_mix(self):
        for block in range(10):
            counts = mix_counts(10, seed=WORKLOAD_SEED + block)
            self.assertEqual(counts, {
                "authorized_read": 6,
                "expected_denial": 1,
                "job_admission": 1,
                "validate_plan": 2,
            })

    def test_negative_request_index_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "request_index_must_be_non_negative"):
            request_class(-1)

    def test_boolean_request_index_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "request_index_must_be_integer"):
            request_class(True)

    def test_boolean_seed_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "workload_seed_must_be_integer"):
            request_class(0, seed=True)

    def test_mix_counts_distinguishes_type_and_range_errors(self):
        with self.assertRaisesRegex(TypeError, "requests_must_be_integer"):
            mix_counts(True)
        with self.assertRaisesRegex(ValueError, "requests_must_be_non_negative"):
            mix_counts(-1)


if __name__ == "__main__":
    unittest.main()
