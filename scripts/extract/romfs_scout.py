#!/usr/bin/env python3
"""Scout an NCA section for RomFS headers, IVFC containers and hash trees.

A retail NCA3 section is an IVFC container: a run of hash layers followed by
the level 5 payload (here the RomFS image). The hash layer sizes live in the
NCA FsHeader, but the payload may be stored sparsely, so the RomFS header
inside the section is not necessarily at the start of the level 5 region.

This tool streams the decrypted section and reports every plausible RomFS
header, every IVFC magic and every RomFS root directory entry it can see.
Nothing is written to disk.

Usage:
  python3 scripts/extract/romfs_scout.py --nsp <path> --keys <path> \\
      --titlekey <hex> [--section 1]
"""
import argparse
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nsp_extract import Nsp, load_keyset  # noqa: E402

CHUNK = 0x2000000


def plausible(values):
    (header_size, dir_hash_ofs, dir_hash_sz, dir_meta_ofs, dir_meta_sz,
     file_hash_ofs, file_hash_sz, file_meta_ofs, file_meta_sz,
     data_ofs) = values
    if header_size != 0x50:
        return False
    if not (0 < dir_hash_sz < 0x10000 and 0 < dir_meta_sz < 0x1000000):
        return False
    if not (0 < file_hash_sz < 0x10000000 and 0 < file_meta_sz < 0x10000000):
        return False
    if not (0 < data_ofs < 0x1000):
        return False
    if not (dir_hash_ofs <= dir_meta_ofs <= file_hash_ofs <= file_meta_ofs):
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nsp", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--titlekey", required=True)
    parser.add_argument("--section", type=int, default=1)
    parser.add_argument("--limit", type=lambda v: int(v, 0), default=0)
    args = parser.parse_args()

    nsp = Nsp(args.nsp, load_keyset(args.keys))
    titlekey = bytes.fromhex(args.titlekey)
    section = nsp.sections[args.section]
    size = max(0, section["media_end"] - section["media_start"]) * 0x200
    if args.limit:
        size = min(size, args.limit)
    print("[+] section %d size=0x%x bytes" % (args.section, size))

    pattern = struct.pack("<Q", 0x50)
    root_pattern = b"\x00\x00\x00\x00\xff\xff\xff\xff"
    headers = []
    ivfc = []
    roots = []
    tail = b""
    offset = 0
    started = time.time()
    while offset < size:
        want = min(CHUNK, size - offset)
        blob = nsp.section_bytes(section, titlekey, offset, want)
        if not blob:
            break
        window = tail + blob
        base = offset - len(tail)

        index = 0
        while len(headers) < 64:
            found = window.find(pattern, index)
            if found < 0:
                break
            index = found + 1
            if found + 0x50 > len(window):
                continue
            values = struct.unpack_from("<10Q", window, found)
            if plausible(values):
                headers.append((base + found, values))

        index = 0
        while len(ivfc) < 32:
            found = window.find(b"IVFC", index)
            if found < 0:
                break
            index = found + 1
            ivfc.append(base + found)

        index = 0
        while len(roots) < 32:
            found = window.find(root_pattern, index)
            if found < 0:
                break
            index = found + 1
            if found + 24 <= len(window):
                tail24 = window[found:found + 24]
                if tail24[20:24] == b"\xff\xff\xff\xff" and tail24[24:28] == b"\x00\x00\x00\x00" if found + 28 <= len(window) else False:
                    roots.append((base + found, tail24.hex()))

        tail = window[-0x40:]
        offset += want
        sys.stdout.write("\r[+] scanned 0x%x/0x%x (%.0f MB/s) headers=%d ivfc=%d roots=%d" % (
            offset, size, offset / 1048576.0 / max(0.001, time.time() - started), len(headers), len(ivfc), len(roots)))
        sys.stdout.flush()
    print()

    print("[+] RomFS header candidates: %d" % len(headers))
    for off, v in headers:
        print("    0x%09x  dir_hash=0x%x/%x dir_meta=0x%x/%x file_hash=0x%x/%x file_meta=0x%x/%x data=0x%x" % (
            off, v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9]))
    print("[+] IVFC magic at: %s" % [hex(x) for x in ivfc])
    print("[+] RomFS root dir entries: %d" % len(roots))
    for off, hx in roots:
        print("    0x%09x  %s" % (off, hx))
    return 0


if __name__ == "__main__":
    sys.exit(main())