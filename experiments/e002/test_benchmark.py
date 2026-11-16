import unittest

from benchmark import valid_measurement_response


class BenchmarkResponseGateTests(unittest.TestCase):
    def test_only_expected_success_responses_are_counted_as_valid(self):
        self.assertTrue(valid_measurement_response({
            "status": 200, "body": "completed:0", "error": None
        }))

    def test_http_errors_wrong_bodies_and_transport_failures_are_rejected(self):
        invalid = [
            {"status": 500, "body": "completed:0", "error": None},
            {"status": 200, "body": "wrong", "error": None},
            {"status": None, "body": "", "error": "TimeoutError()"},
            {"status": 200, "body": "completed:0"},
        ]
        for item in invalid:
            with self.subTest(item=item):
                self.assertFalse(valid_measurement_response(item))


if __name__ == "__main__":
    unittest.main()
