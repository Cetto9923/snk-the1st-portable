#!/usr/bin/env python3
"""Stream a decrypted NCA section and search it for byte patterns.

The RomFS image of this title is not stored as a plain image: the section is
9.79 GB while the RomFS header describes a 14.9 GB image, so the payload is
kept in a sparse form whose logical-to-physical mapping is not implied by
the header offsets. Searching the decrypted stream for known file names is
the cheapest way to learn where the metadata really lives.

Nothing is written to disk; the section is decrypted chunk by chunk.

Usage:
  python3 scripts/extract/romfs_search.py --nsp <path> --keys <path> \\
      --titlekey <hex> [--section 1] --needle <text> [--needle <text>]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nsp_extract import Nsp, load_keyset  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nsp", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--titlekey", required=True)
    parser.add_argument("--extractor", type=Path, default=Path("scripts/extract/nsp_extract.py"))
    parser.add_argument("--section", type=int, default=1)
    parser.add_argument("--needle", action="append", default=[])
    parser.add_argument("--chunk-size", type=lambda v: int(v, 0), default=0x2000000)
    parser.add_argument("--limit", type=lambda v: int(v, 0), default=0)
    parser.add_argument("--max-hits", type=int, default=40)
    args = parser.parse_args()

    sys.path.insert(0, str(args.extractor.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("nxe", args.extractor)
    nxe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nxe)

    keys = nxe.load_keyset(args.keys)
    nsp = nxe.Nsp(args.nsp, keys)
    titlekey = bytes.fromhex(args.titlekey)
    section = nsp.sections[args.section]
    size = max(0, section["media_end"] - section["media_start"]) * nxe.SECTOR
    if args.limit:
        size = min(size, args.limit)
    needles = [n.encode("utf-8") if isinstance(n, str) else n for n in args.needle]
    print("[+] section %d size=0x%x bytes" % (args.section, size))
    for needle in needles:
        print("[+] needle %r" % needle)

    overlap = max((len(n) for n in needles), default=1)
    hits = []
    tail = b""
    offset = 0
    started = time.time()
    while offset < size:
        want = min(args.chunk_size, size - offset)
        blob = nsp.section_bytes(section, titlekey, offset, want)
        if not blob:
            break
        window = tail + blob
        base = offset - len(tail)
        for needle in needles:
            index = 0
            while len(hits) < args.max_hits * 8:
                found = window.find(needle, index)
                if found < 0:
                    break
                index = found + 1
                hits.append((base + found, needle))
        tail = window[-overlap:] if overlap else b""
        offset += want
        rate = offset / max(0.001, time.time() - started)
        sys.stdout.write("\r[+] scanned 0x%x/0x%x  %.1f MB/s" % (offset, size, rate / 1048576.0))
        sys.stdout.flush()
    print()
    print("[+] hits: %d" % len(hits))
    for hit_offset, needle in hits[:args.max_hits]:
        print("    0x%09x  %r" % (hit_offset, needle))
    return 0


if __name__ == "__main__":
    sys.exit(main())