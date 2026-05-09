from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.providers.asr import asr_health, transcribe_wav


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav_path", nargs="?")
    args = parser.parse_args()

    if not args.wav_path:
        print(asr_health())
        return

    text, error_code = transcribe_wav(args.wav_path)
    print({"health": asr_health(), "text": text, "error_code": error_code})


if __name__ == "__main__":
    main()
