import unittest

from scripts.benchmark_open_rag_runtime import estimate_duration, repository_root, sample_by_length_quantiles


class EstimateDurationTests(unittest.TestCase):
    def test_scales_sample_duration_by_total_work_and_concurrency(self):
        estimate = estimate_duration(sample_seconds=12.0, sample_count=3, total_count=3045, concurrency=5)

        self.assertEqual(estimate["seconds"], 2436.0)
        self.assertEqual(estimate["sample_per_item_seconds"], 4.0)
        self.assertEqual(estimate["concurrency"], 5)

    def test_repository_root_is_the_project_directory(self):
        self.assertTrue((repository_root() / "manage.py").is_file())

    def test_length_quantile_sample_includes_long_input_regardless_of_corpus_order(self):
        values = ["x" * 10, "x", "x" * 100, "x" * 5]

        sample = sample_by_length_quantiles(values, 3)

        self.assertEqual(max(map(len, sample)), 100)


if __name__ == "__main__":
    unittest.main()
