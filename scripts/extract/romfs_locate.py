#!/usr/bin/env python3
"""Locate the real RomFS image inside the RomFS section of an NCA.

The section header of a retail title carries the media range of the section,
but a title may ship the RomFS inside an IVFC container, behind a sparse
block map, or as a nested image inside its own data. This script decrypts
the section in a streaming fashion and reports every position that looks
like a RomFS level 5 header, so the real one can be told apart from a
coincidental match. Nothing is written to disk.

Usage:
  python3 scripts/extract/romfs_locate.py --nsp <path> --keys <path> \\
      --titlekey <hex> [--chunk-size 0x2000000]
"""
import argparse
import importlib.util
import struct
import sys
from pathlib import Path


def load_extractor(path):
    spec = importlib.util.spec_from_file_location("nx", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nsp", type=Path, required=True)
    ap.add_argument("--keys", type=Path, required=True)
    ap.add_argument("--titlekey", required=True)
    ap.add_argument("--extractor", type=Path, default=Path("scripts/extract/nsp_extract.py"))
    ap.add_argument("--chunk-size", type=lambda v: int(v, 0), default=0x2000000)
    ap.add_argument("--limit", type=lambda v: int(v, 0), default=0)
    ap.add_argument("--names", action="store_true", help="look for file names instead")
    args = ap.parse_args()

    nx = load_extractor(args.extractor)
    keys = nx.load_keyset(args.keys)
    nsp = nx.Nsp(args.nsp, keys)
    titlekey = bytes.fromhex(args.titlekey)
    section = nsp.sections[1]
    size = (section["media_end"] - section["media_start"]) * nx.SECTOR
    if args.limit:
        size = min(size, args.limit)
    print("section 1 media size = %d (0x%x)" % (size, size))

    needles = [b"IVFC", b"ROFS", b"asset_config.json", b".nvn"]
    hits = []
    offset = 0
    tail = b""
    while offset < size:
        want = min(args.chunk_size, size - offset)
        blob = nsp.section_bytes(section, titlekey, offset, want)
        window = tail + blob
        base = offset - len(tail)
        if args.names:
            for needle in needles:
                index = 0
                while True:
                    found = window.find(needle, index)
                    if found < 0:
                        break
                    index = found + 1
                    hits.append((base + found, needle.decode("ascii", "replace")))
        else:
            index = 0
            while True:
                found = window.find(struct.pack("<Q", 0x50), index)
                if found < 0 or found + 0x50 > len(window):
                    break
                index = found + 1
                values = struct.unpack("<10Q", window[found:found + 0x50])
                if values[4] < 0x1000000 and values[8] < 0x1000000 and values[3] < values[7]:
                    hits.append((base + found, values))
        tail = window[-0x100:]
        offset += want
        sys.stdout.write("\rscanned 0x%x / 0x%x" % (offset, size))
        sys.stdout.flush()
    print()
    print("hits:", len(hits))
    for item in hits[:40]:
        if args.names:
            print("  0x%09x %s" % item)
        else:
            values = item[1]
            print("  0x%09x dir_hash=0x%x dir_meta=0x%x/%d file_meta=0x%x/%d data=0x%x" % (
                item[0], values[1], values[3], values[4], values[7], values[8], values[9]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
