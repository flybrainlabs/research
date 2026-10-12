"""Synthetic fixtures test exact coverage accounting, not biological validity."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import inspect_connectome_weights as coverage


class CoverageTests(unittest.TestCase):
    def test_distinct_across_batches_and_merge_rounds(self):
        with tempfile.TemporaryDirectory() as temp:
            distinct = coverage.DistinctBodies(Path(temp), 1)
            distinct.run_rows = 3  # Force more than sixteen sorted runs.
            for i in range(40):
                distinct.add(np.array([i % 7, 100, 2**63 - 1], dtype=np.int64))
            self.assertEqual(list(distinct.values()), list(range(7)) + [100, 2**63 - 1])

    def test_no_unmapped_endpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            distinct = coverage.DistinctBodies(Path(temp), 1)
            distinct.add(np.array([], dtype=np.int64))
            self.assertEqual(list(distinct.values()), [])
            with self.assertRaisesRegex(ValueError, "at least 1"):
                coverage.DistinctBodies(Path(temp), 0)

    def fixtures(self, root):
        registry = root / "registry.bin"
        registry.write_bytes(b"FBRG1\0\0\0" + struct.pack("<Q", 3)
                             + b"".join(struct.pack("<QBH", body, 0, 0) for body in [10, 20, 30]))
        annotation = root / "annotations.feather"
        feather.write_feather(pa.table({"bodyId": [10, 20, 30, 40, 50],
                                       "status": ["Traced", "Traced", "Traced", "Untraced", "Untraced"]}), annotation)
        source = root / "weights.feather"
        feather.write_feather(pa.table({"body_pre": [10, 10, 40, 60, 40, 60, 2**63 - 1],
                                       "body_post": [20, 40, 20, 40, 60, 60, 10],
                                       "weight": [2, 3, 4, 5, 6, 7, 8]}), source, chunksize=2)
        return source, registry, annotation

    def test_exact_fragment_union_and_annotation_categories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, registry, annotation = self.fixtures(root)
            with patch.multiple(coverage, EXPECTED_BYTES=source.stat().st_size,
                                EXPECTED_SHA256=coverage.digest_file(source),
                                ANNOTATION_SHA256=coverage.digest_file(annotation)):
                report = coverage.inspect(source, registry, annotation, 1, root)
            expected = {"source_rows": 7, "both_mapped_rows": 1, "pre_only_rows": 1,
                        "post_only_rows": 2, "neither_mapped_rows": 3,
                        "both_mapped_weight_sum": 2, "unmapped_unique_body_ids": 3,
                        "unmapped_annotated_body_ids": 1, "unmapped_without_annotation_body_ids": 2,
                        "registry_neurons_with_connections": 2, "registry_neurons_without_connections": 1}
            self.assertEqual({key: report[key] for key in expected}, expected)
            self.assertEqual(report["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(list(root.glob("flypow-coverage-*")), [])

    def test_same_size_source_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source, registry, _ = self.fixtures(Path(temp))
            with patch.multiple(coverage, EXPECTED_BYTES=source.stat().st_size,
                                EXPECTED_SHA256="00" * 32):
                with self.assertRaisesRegex(ValueError, "weight SHA-256"):
                    coverage.inspect(source, registry)

    def test_changed_inclusion_rule_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source, registry, annotation = self.fixtures(Path(temp))
            registry.write_bytes(b"FBRG1\0\0\0" + struct.pack("<Q", 1) + struct.pack("<QBH", 10, 0, 0))
            with patch.multiple(coverage, EXPECTED_BYTES=source.stat().st_size,
                                EXPECTED_SHA256=coverage.digest_file(source),
                                ANNOTATION_SHA256=coverage.digest_file(annotation)):
                with self.assertRaisesRegex(ValueError, "inclusion rule"):
                    coverage.inspect(source, registry, annotation)


if __name__ == "__main__":
    unittest.main()
