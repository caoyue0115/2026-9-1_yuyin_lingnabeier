#!/usr/bin/env python3
import subprocess
import sys

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
    "0x0", "build/bootloader/bootloader.bin",
    "0x8000", "build/partition_table/partition-table.bin",
    "0x10000", "build/esp_idf_demo.bin",
    "0x210000", "build/storage.bin",
]

print("执行命令：")
print(" ".join(cmd))
print()

sys.exit(subprocess.run(cmd).returncode)

