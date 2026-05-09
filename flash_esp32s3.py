#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys

base = Path(__file__).resolve().parent
bin_dir = base / "bin"

files = {
    "0x0": bin_dir / "bootloader.bin",
    "0x8000": bin_dir / "partition-table.bin",
    "0x10000": bin_dir / "esp_idf_demo.bin",
    "0x210000": bin_dir / "storage.bin",
}

missing = [str(p) for p in files.values() if not p.exists()]
if missing:
    print("缺少文件：")
    for m in missing:
        print(" -", m)
    print("\n请先确认当前目录下有 bin/ 且包含4个文件。")
    sys.exit(1)

cmd = [
    sys.executable, "-m", "esptool",
    "--chip", "esp32s3",
    "-b", "460800",
    "--before", "default_reset",
    "--after", "hard_reset",
    "write_flash",
    "--flash_mode", "dio",
    "--flash_size", "16MB",
    "--flash_freq", "80m",
]

for addr, path in files.items():
    cmd.extend([addr, str(path)])

print("执行命令：")
print(" ".join(cmd))
print()

ret = subprocess.run(cmd)
sys.exit(ret.returncode)

