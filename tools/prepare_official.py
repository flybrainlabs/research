"""Wait for the explicitly started official download, then prepare the data."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data/raw/syn-partners-male-cns-v1.0-minconf-0.5.feather"
CONTROL = SOURCE.with_suffix(".feather.aria2")
OUTPUT = ROOT / "data/prepared/malecns-v1.synapses.bin"
STATUS = ROOT / "data/runtime/prepare.json"


def report(stage, message):
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps({"stage": stage, "message": message,
                                     "completed": 0, "total": 0}), encoding="utf-8")
    temporary.replace(STATUS)


def main():
    if OUTPUT.with_suffix(".bin.json").exists():
        return
    report("downloading", "正在从 HHMI Janelia 官方公开存储下载突触数据")
    while True:
        if SOURCE.exists() and SOURCE.stat().st_size == 6_777_179_098 and not CONTROL.exists():
            break
        state = subprocess.run(["systemctl", "--user", "show", "flypow-download", "-p", "ActiveState", "--value"],
                               capture_output=True, text=True, check=True).stdout.strip()
        if state == "failed":
            raise RuntimeError("官方数据下载失败，请检查 flypow-download 日志")
        time.sleep(2)
    subprocess.run([sys.executable, str(ROOT / "tools/prepare_dataset.py"),
                    "--input", str(SOURCE), "--output", str(OUTPUT), "--progress", str(STATUS)], check=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        report("error", str(error))
        raise
