#!/usr/bin/env python3
"""Batch extractor for the full RomFS tree from the decrypted NSP.

Reads the verified manifest and extracts files in sequential order.
Supports resuming: skips existing files that match the expected byte size.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add script directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nca_romfs import NcaRomFS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nsp", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--titlekey-file", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", type=str, default="", help="Optional subpath prefix to extract")
    parser.add_argument("--pattern", type=str, default="", help="Optional regex pattern to filter paths")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit on file count")
    args = parser.parse_args()

    key = json.loads(args.titlekey_file.read_text())["titlekey"]
    print(f"Loading RomFS from {args.nsp}...")
    rom = NcaRomFS(args.nsp, args.keys, key)
    print(f"RomFS ready. Virtual size: {rom.virtual_size / (1024**3):.2f} GB")

    manifest = json.loads(args.manifest.read_text())
    files = manifest["files"]
    if args.prefix:
        files = [f for f in files if f["path"].startswith(args.prefix)]
    if args.pattern:
        import re
        pat = re.compile(args.pattern)
        files = [f for f in files if pat.search(f["path"])]
    if args.limit > 0:
        files = files[:args.limit]

    print(f"Extracting {len(files)} files to {args.output_dir}...")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    extracted_count = 0
    skipped_count = 0
    extracted_bytes = 0
    start_time = time.time()
    last_log_time = start_time

    for i, item in enumerate(files):
        rel_path = item["path"]
        size = item["size"]
        dest = args.output_dir / rel_path

        # Check if already extracted
        if dest.is_file() and dest.stat().st_size == size:
            skipped_count += 1
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = rom.read_virtual(item["offset"], size)
            dest.write_bytes(data)
            extracted_count += 1
            extracted_bytes += len(data)

        # Progress update every 5 seconds
        now = time.time()
        if now - last_log_time >= 5.0 or i == len(files) - 1:
            elapsed = now - start_time
            rate = extracted_bytes / (1024 * 1024 * max(elapsed, 0.001))
            percent = (i + 1) / len(files) * 100.0
            print(f"[{percent:5.1f}%] {i + 1}/{len(files)} files processed "
                  f"({extracted_count} extracted, {skipped_count} skipped, "
                  f"{extracted_bytes / (1024**2):.1f} MB, {rate:.1f} MB/s)")
            last_log_time = now

    total_time = time.time() - start_time
    print(f"Extraction complete in {total_time:.1f}s. "
          f"Extracted {extracted_count} files ({extracted_bytes / (1024**2):.1f} MB), "
          f"skipped {skipped_count} files.")


if __name__ == "__main__":
    main()
