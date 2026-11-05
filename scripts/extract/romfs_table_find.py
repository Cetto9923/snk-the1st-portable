#!/usr/bin/env python3
"""Locate a RomFS file metadata table inside a decrypted NCA section.

The RomFS file table stores, for every file, a 32 byte header followed by the
file name:

    u32 parent_dir_offset
    u32 sibling_file_offset
    u64 data_offset
    u64 data_size
    u32 hash_sibling_offset
    u32 name_size
    char name[]

The two 64 bit fields stay below the image size, so their high halves are
zero. That makes the record easy to recognise with a regular expression,
which is far faster than walking candidate tables blindly.

Usage:
  python3 scripts/extract/romfs_table_find.py --nsp <path> --keys <path> \\
      --titlekey <hex> [--start 0] [--limit 0]
"""
import argparse
import re
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nsp_extract import Nsp, load_keyset  # noqa: E402

CHUNK = 0x2000000

# parent, sibling, data_offset(8), data_size(8), hash_sibling, name_size, name
RECORD = re.compile(rb".{4}.{4}\x00{8}\x00{8}.{4}[\x01-\xc8]\x00\x00\x00", re.S)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nsp", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--titlekey", required=True)
    parser.add_argument("--section", type=int, default=1)
    parser.add_argument("--start", type=lambda v: int(v, 0), default=0)
    parser.add_argument("--limit", type=lambda v: int(v, 0), default=0)
    parser.add_argument("--max-hits", type=int, default=20)
    args = parser.parse_args()

    nsp = Nsp(args.nsp, load_keyset(args.keys))
    titlekey = bytes.fromhex(args.titlekey)
    section = nsp.sections[args.section]
    total = max(0, section["media_end"] - section["media_start"]) * 0x200
    start = args.start
    end = total if not args.limit else min(total, args.start + args.limit)
    print("[+] scanning section %d [0x%x, 0x%x)" % (args.section, start, end))

    hits = []
    offset = start
    tail = b""
    began = time.time()
    while offset < end and len(hits) < args.max_hits:
        want = min(CHUNK, end - offset)
        blob = nsp.section_bytes(section, titlekey, offset, want)
        if not blob:
            break
        window = tail + blob
        base = offset - len(tail)
        for match in RECORD.finditer(window):
            at = match.start()
            name_len = struct.unpack_from("<I", window, at + 28)[0]
            if name_len > 200 or at + 32 + name_len > len(window):
                continue
            name = window[at + 32:at + 32 + name_len]
            if not all(33 <= c < 127 for c in name):
                continue
            parent, sibling = struct.unpack_from("<II", window, at)
            data_offset, data_size = struct.unpack_from("<QQ", window, at + 8)
            hash_sibling = struct.unpack_from("<I", window, at + 24)[0]
            hits.append((base + at, parent, sibling, data_offset, data_size, hash_sibling, name))
            if len(hits) >= args.max_hits:
                break
        tail = window[-0x200:]
        offset += want
        sys.stdout.write("\r[+] 0x%x/0x%x  hits=%d  %.0f MB/s" % (
            offset, end, len(hits), offset / 1048576.0 / max(0.001, time.time() - began)))
        sys.stdout.flush()
    print()
    for at, parent, sibling, data_offset, data_size, hash_sibling, name in hits:
        print("  0x%09x parent=%u sibling=%u data_offset=0x%x data_size=%u hash_sibling=0x%x name=%r" % (
            at, parent, sibling, data_offset, data_size, hash_sibling, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())