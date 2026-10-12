import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pyarrow as pa

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("prepare_dataset",ROOT/"tools/prepare_dataset.py")
prepare=importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class ConverterTests(unittest.TestCase):
    def test_multibatch_conversion_and_official_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/"input.feather"
            output=Path(temporary)/"output.bin"
            schema=pa.schema([(name,pa.int64() if name.startswith("body") else pa.int32()) for name in prepare.REQUIRED_COLUMNS])
            with pa.OSFile(str(source),"wb") as file, pa.ipc.new_file(file,schema) as writer:
                for i in range(2):
                    writer.write_batch(pa.record_batch([pa.array([i+offset],type=field.type) for offset,field in enumerate(schema)],schema=schema))
            blocked=subprocess.run([sys.executable,str(ROOT/"tools/prepare_dataset.py"),"--input",str(source),"--output",str(output)],capture_output=True,text=True)
            self.assertNotEqual(blocked.returncode,0)
            self.assertFalse(output.exists())
            result=subprocess.run([sys.executable,str(ROOT/"tools/prepare_dataset.py"),"--input",str(source),"--output",str(output),"--skip-source-check"],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(output.stat().st_size,80)
            manifest=json.loads(output.with_suffix(".bin.json").read_text())
            self.assertEqual(manifest["record_count"],2)
            self.assertFalse(manifest["official_source_verified"])
            self.assertEqual(manifest["canonical_merkle_root"],prepare.dataset_merkle_root(output))

    def test_rejects_float_columns_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/"input.feather"
            output=Path(temporary)/"output.bin"
            schema=pa.schema([(name,pa.float64()) for name in prepare.REQUIRED_COLUMNS])
            with pa.OSFile(str(source),"wb") as file, pa.ipc.new_file(file,schema) as writer:
                writer.write_batch(pa.record_batch([pa.array([1.5]) for _ in schema],schema=schema))
            with self.assertRaisesRegex(ValueError,"integer Arrow type"):
                prepare.convert_feather(source,output)
            self.assertFalse(output.exists())
            output.write_bytes(b"preserve-me")
            result=subprocess.run([sys.executable,str(ROOT/"tools/prepare_dataset.py"),"--input",str(source),"--output",str(output),"--skip-source-check"],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(output.read_bytes(),b"preserve-me")


if __name__=="__main__":
    unittest.main()
