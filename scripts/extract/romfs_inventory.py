#!/usr/bin/env python3
"""Locate the RomFS file tree of a Switch title by scanning the decrypted section.

The RomFS level-5 image of a retail NCA carries a header whose offsets are
relative to the image base. Some titles ship their data with a different
hash layout, so the image base cannot be derived from the IVFC header alone.
This tool therefore scans the decrypted section for a structurally valid RomFS
header and reports the file tree it describes.

Only metadata blocks are read; file payloads stay in the package.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nsp_extract import Nsp, load_keyset  # noqa: E402

CHUNK = 0x4000000  # 64 MiB scan window


def parse_header_at(window, offset):
    if offset + 0x50 > len(window):
        return None
    values = struct.unpack_from("<10Q", window, offset)
    (header_size, dir_hash_ofs, dir_hash_sz, dir_meta_ofs, dir_meta_sz,
     file_hash_ofs, file_hash_sz, file_meta_ofs, file_meta_sz, data_ofs) = values
    if header_size != 0x50:
        return None
    if not (0 < dir_hash_sz < 0x10000 and 0 < dir_meta_sz < 0x100000):
        return None
    if not (0 < file_hash_sz < 0x400000 and 0 < file_meta_sz < 0x2000000):
        return None
    if not (0 < data_ofs < 0x1000):
        return None
    if not (dir_hash_ofs <= dir_meta_ofs <= file_hash_ofs <= file_meta_ofs):
        return None
    return {"values": values, "dir_hash_ofs": dir_hash_ofs, "dir_hash_sz": dir_hash_sz,
            "dir_meta_ofs": dir_meta_ofs, "dir_meta_sz": dir_meta_sz,
            "file_hash_ofs": file_hash_ofs, "file_hash_sz": file_hash_sz,
            "file_meta_ofs": file_meta_ofs, "file_meta_sz": file_meta_sz,
            "data_ofs": data_ofs}


def scan_for_header(nsp, section, titlekey, limit):
    """Return the first candidate whose metadata blocks are physically readable.

    A header whose offsets point past the end of the section is not a file
    tree of this package, so the scan continues instead of accepting it.
    """
    pattern = struct.pack("<Q", 0x50)
    section_size = max(0, (section["media_end"] - section["media_start"])) * 0x200
    scanned = 0
    while scanned < limit:
        window = nsp.section_bytes(section, titlekey, scanned, CHUNK)
        if not window:
            break
        index = 0
        while True:
            found = window.find(pattern, index)
            if found < 0:
                break
            index = found + 1
            header = parse_header_at(window, found)
            if not header:
                continue
            base = scanned + found
            header["base_in_section"] = base
            if base + header["file_meta_ofs"] + header["file_meta_sz"] > section_size:
                continue
            if base + header["dir_meta_ofs"] + header["dir_meta_sz"] > section_size:
                continue
            try:
                dirs, files = read_tree(nsp, section, titlekey, header)
            except Exception:
                continue
            if len(files) < 5:
                continue
            printable = [f for f in files if f["path"] and all(32 <= ord(c) < 127 for c in f["path"])]
            if len(printable) < len(files) * 0.9:
                continue
            header["dirs"], header["files"] = dirs, files
            return header
        scanned += CHUNK - 0x1000
    return None


def read_tree(nsp, section, titlekey, header):
    base = header["base_in_section"]

    def read_at(offset, size):
        return nsp.section_bytes(section, titlekey, base + offset, size)

    dir_meta = read_at(header["dir_meta_ofs"], header["dir_meta_sz"])
    file_meta = read_at(header["file_meta_ofs"], header["file_meta_sz"])

    dirs = {}
    cur = 0
    while cur + 24 <= len(dir_meta):
        p_dir, s_dir, c_dir, c_file, h_sib, name_len = struct.unpack_from("<IIIIII", dir_meta, cur)
        if name_len > 1024 or cur + 24 + name_len > len(dir_meta):
            cur += 4
            continue
        name = dir_meta[cur + 24:cur + 24 + name_len].decode("utf-8", "replace")
        dirs[cur] = {"name": name, "p_dir": p_dir}
        cur += (24 + name_len + 3) & ~3

    def dir_path(offset):
        parts = []
        current = offset
        seen = 0
        while current != 0 and current in dirs and seen < 64:
            parts.append(dirs[current]["name"])
            current = dirs[current]["p_dir"]
            seen += 1
        return "/".join(reversed(parts))

    files = []
    cur = 0
    while cur + 32 <= len(file_meta):
        p_dir, s_file = struct.unpack_from("<II", file_meta, cur)
        d_ofs, d_sz = struct.unpack_from("<QQ", file_meta, cur + 8)
        h_sib, name_len = struct.unpack_from("<II", file_meta, cur + 24)
        if name_len > 1024 or cur + 32 + name_len > len(file_meta):
            cur += 4
            continue
        name = file_meta[cur + 32:cur + 32 + name_len].decode("utf-8", "replace")
        parent = dir_path(p_dir) if p_dir in dirs else ""
        files.append({"path": f"{parent}/{name}" if parent else name,
                      "size": d_sz, "data_offset": header["data_ofs"] + d_ofs})
        cur += (32 + name_len + 3) & ~3
    return dirs, files


def main():
    parser = argparse.ArgumentParser(description="Locate and inventory the RomFS file tree")
    parser.add_argument("--nsp", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--titlekey", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scan-limit", type=int, default=0x20000000,
                        help="how much of section 1 to scan (default 512 MiB)")
    args = parser.parse_args()

    nsp = Nsp(args.nsp, load_keyset(args.keys))
    titlekey = bytes.fromhex(args.titlekey)
    section = nsp.sections[1]
    header = scan_for_header(nsp, section, titlekey, args.scan_limit)
    if header is None:
        print("FAILED: no structurally valid RomFS header found", file=sys.stderr)
        return 1
    print(f"[+] RomFS header at section+{header['base_in_section']:#x}")
    print(f"    values={header['values']}")
    dirs, files = header.pop("dirs"), header.pop("files")
    total = sum(item["size"] for item in files)
    print(f"[+] directories={len(dirs)} files={len(files)} total_bytes={total}")
    for item in sorted(files, key=lambda x: -x["size"])[:12]:
        print(f"    {item['size']:>12}  {item['path']}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"header": {k: v for k, v in header.items() if k != "values"} |
                                    {"header_values": header["values"]},
                                    "file_count": len(files),
                                    "total_bytes": total, "files": files},
                                   indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
