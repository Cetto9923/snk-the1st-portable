#!/usr/bin/env python3
"""Read a sparse/compressed NCA3 RomFS section through its BKTR bucket tree.

A retail NCA3 section is a HierarchicalIntegrity container: a stack of hash
layers followed by the payload. Large titles store the payload in a sparse or
compressed form, so the bytes the game sees (the virtual image) are not the
bytes stored in the section (the source image). The FsHeader describes the
mapping with a BKTR bucket tree that lives at the very end of the section:

    u32 padding
    u32 bucket_count
    u64 virtual_size
    u64 base_virtual_offset[bucket_count]   (padded to 0x4000)
    bucket[0x4000] * bucket_count

Each bucket holds relocation entries of

    u64 address_in_virtual_image
    u64 address_in_source_image
    u32 flags

This module turns that table into a reader for the virtual image, which is
what the RomFS header describes. Nothing is written to disk.

Usage:
  python3 scripts/extract/nca_romfs.py --nsp <path> --keys <path> \
      --titlekey <hex> [--list] [--extract <virtual-offset> --size <n> --out <file>]
"""
import argparse
import bisect
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nsp_extract import Nsp, load_keyset  # noqa: E402


class NcaRomFS:
    """Virtual image reader for an NCA3 RomFS section."""

    def __init__(self, nsp_path, keys_path, titlekey_hex, section_index=1):
        self.nsp = Nsp(nsp_path, load_keyset(keys_path))
        self.titlekey = bytes.fromhex(titlekey_hex)
        self.section = self.nsp.sections[section_index]
        self.section_index = section_index
        self.section_size = (self.section["media_end"] - self.section["media_start"]) * 0x200
        self._read_header()
        self._read_bucket_tree()

    def _read_header(self):
        header = self.nsp.header
        base = 0x400 + self.section_index * 0x200
        fs = header[base:base + 0x200]
        if fs[8:12] != b"IVFC":
            raise ValueError("section %d is not a HierarchicalIntegrity container" % self.section_index)
        self.master_hash_size = struct.unpack_from("<I", fs, 0x10)[0]
        self.max_layers = struct.unpack_from("<I", fs, 0x14)[0]
        self.levels = []
        for i in range(self.max_layers):
            off = 0x18 + i * 24
            logical, hash_data_size, block_log2 = struct.unpack_from("<QQI", fs, off)
            self.levels.append({"logical_offset": logical,
                                "hash_data_size": hash_data_size,
                                "block_size": (1 << block_log2) if block_log2 else 0})
        payload = None
        for level in self.levels:
            if level["hash_data_size"]:
                payload = level
        if payload is None:
            raise ValueError("no payload level in the section header")
        self.payload_offset = payload["logical_offset"]
        self.table_offset = struct.unpack_from("<Q", fs, 0x178)[0]
        self.table_size = struct.unpack_from("<Q", fs, 0x180)[0]

    def _read_bucket_tree(self):
        table = self.section_size - self.table_size
        blob = self._read_section(table, 0x4000)
        self.bucket_count = struct.unpack_from("<I", blob, 4)[0]
        self.virtual_size = struct.unpack_from("<Q", blob, 8)[0]
        self.bucket_virtual_base = []
        for i in range(self.bucket_count):
            self.bucket_virtual_base.append(struct.unpack_from("<Q", blob, 0x10 + i * 8)[0])
        self.relocations = []
        for i in range(self.bucket_count):
            chunk = self._read_section(table + 0x4000 + i * 0x4000, 0x4000)
            count = struct.unpack_from("<I", chunk, 4)[0]
            for e in range(count):
                off = 0x10 + e * 0x18
                virt, src, flags = struct.unpack_from("<QQI", chunk, off)
                self.relocations.append((virt, src, flags))
        self.relocations.sort()
        self._virt = [r[0] for r in self.relocations]

    def _read_section(self, offset, size):
        """Read raw section bytes; the offset is relative to the section start."""
        base = offset - (offset % 16)
        want = ((size + (offset - base)) + 15) // 16 * 16
        blob = self.nsp.section_bytes(self.section, self.titlekey, base, want)
        return blob[offset - base:offset - base + size]

    def source_for(self, virtual):
        """Map a virtual offset to its offset inside the stored source image."""
        idx = bisect.bisect_right(self._virt, virtual) - 1
        if idx < 0:
            raise ValueError("virtual offset 0x%x has no mapping" % virtual)
        virt, src, _flags = self.relocations[idx]
        return src + (virtual - virt)

    def read_virtual(self, virtual, size):
        """Read bytes of the virtual image."""
        out = bytearray()
        remaining = size
        cursor = virtual
        while remaining > 0:
            idx = bisect.bisect_right(self._virt, cursor) - 1
            virt = self.relocations[idx][0]
            nxt = self._virt[idx + 1] if idx + 1 < len(self._virt) else self.virtual_size
            span = min(remaining, nxt - cursor)
            src = self.relocations[idx][1] + (cursor - virt)
            out += self._read_section(self.payload_offset + src, span)
            cursor += span
            remaining -= span
        return bytes(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nsp", type=Path, required=True)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--titlekey", required=True)
    parser.add_argument("--section", type=int, default=1)
    parser.add_argument("--list", action="store_true", help="show the RomFS header")
    parser.add_argument("--extract", type=lambda v: int(v, 0), default=None)
    parser.add_argument("--size", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    rom = NcaRomFS(args.nsp, args.keys, args.titlekey, args.section)
    print("[+] payload offset 0x%x, virtual size 0x%x, buckets %d, relocations %d" % (
        rom.payload_offset, rom.virtual_size, rom.bucket_count, len(rom.relocations)))

    if args.extract is not None:
        data = rom.read_virtual(args.extract, args.size)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(data)
            print("[+] wrote %d bytes to %s" % (len(data), args.out))
        else:
            sys.stdout.buffer.write(data)
        return 0

    if args.list:
        head = rom.read_virtual(0, 0x50)
        values = struct.unpack("<10Q", head)
        print("[+] romfs header: %s" % [hex(v) for v in values])
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
