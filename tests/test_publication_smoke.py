"""Packaging smoke tests; not replacements for the manuscript experiments."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("minimal_example", ROOT / "examples/minimal_quantitative_corpus.py")
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class PublicationSmokeTests(unittest.TestCase):
    def test_basic_numeric_and_evidence_correspondence(self):
        with tempfile.TemporaryDirectory() as folder:
            result = example.run(Path(folder) / "fresh")
            self.assertEqual(result["basic_records"], 4)
            self.assertEqual(result["derived_records"], 1)
            self.assertTrue(result["basic_numeric_links_verified"])
            self.assertEqual(result["physical_unit_metadata_empty"], 4)

    def test_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileExistsError):
                example.run(Path(folder))


if __name__ == "__main__":
    unittest.main()
