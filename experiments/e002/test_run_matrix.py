import unittest

from run_matrix import distribution


class DistributionTests(unittest.TestCase):
    def test_reports_descriptive_statistics_and_reproducible_bootstrap_interval(self):
        values = [1.0, 2.0, 3.0, 4.0]
        first = distribution(values, 20261117)
        second = distribution(values, 20261117)
        self.assertEqual(first, second)
        self.assertEqual(first["n"], 4)
        self.assertEqual(first["mean"], 2.5)
        self.assertAlmostEqual(first["sample_stddev"], 1.2909944487358056)
        self.assertEqual(first["median"], 2.5)
        self.assertEqual(first["min"], 1.0)
        self.assertEqual(first["max"], 4.0)
        self.assertEqual(len(first["bootstrap_mean_95"]), 2)

    def test_missing_measurements_are_not_zero(self):
        self.assertEqual(
            distribution([], 42),
            {
                "n": 0,
                "mean": None,
                "sample_stddev": None,
                "median": None,
                "min": None,
                "max": None,
                "bootstrap_mean_95": None,
            },
        )
        single = distribution([7.0], 42)
        self.assertEqual(single["mean"], 7.0)
        self.assertIsNone(single["sample_stddev"])
        self.assertIsNone(single["bootstrap_mean_95"])


if __name__ == "__main__":
    unittest.main()
