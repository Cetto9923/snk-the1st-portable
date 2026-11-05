#!/usr/bin/env python3
"""Decompress a Switch NSO0 module stored inside ExeFS.

Retail NSOs keep the static header, then the module name, then LZ4 block
compressed text/rodata/data segments. The uncompressed image is rebuilt with
the segment file offsets that the loader expects (memory offset + 0x100).

The LZ4 block decoder is implemented here so the project does not depend on
an optional native module.
"""
import argparse
import struct
import sys
from pathlib import Path

NSO_HEADER_SIZE = 0x100


def lz4_block_decompress(data: bytes, expected: int) -> bytes:
    out = bytearray()
    pos = 0
    end = len(data)
    while pos < end:
        token = data[pos]
        pos += 1
        literal_len = token >> 4
        if literal_len == 15:
            while True:
                byte = data[pos]
                pos += 1
                literal_len += byte
                if byte != 255:
                    break
        out += data[pos:pos + literal_len]
        pos += literal_len
        if pos >= end:
            break
        offset = data[pos] | (data[pos + 1] << 8)
        pos += 2
        if offset == 0:
            raise ValueError("invalid LZ4 match offset")
        match_len = token & 0x0F
        if match_len == 15:
            while True:
                byte = data[pos]
                pos += 1
                match_len += byte
                if byte != 255:
                    break
        match_len += 4
        start = len(out) - offset
        if start < 0:
            raise ValueError("LZ4 match before start of output")
        for i in range(match_len):
            out.append(out[start + i])
    if expected and len(out) != expected:
        raise ValueError(f"decompressed size {len(out)} != expected {expected}")
    return bytes(out)


def parse_header(data: bytes):
    if data[:4] != b"NSO0":
        raise ValueError("not an NSO0 module")
    segments = []
    for index in range(3):
        file_offset, memory_offset, size, aux = struct.unpack_from("<IIII", data, 0x10 + index * 0x10)
        segments.append({"file": file_offset, "mem": memory_offset, "size": size, "aux": aux})
    return segments


def decompress_module(source: Path, out_path: Path) -> dict:
    data = source.read_bytes()
    segments = parse_header(data)
    name_end = data.index(b"\x00", NSO_HEADER_SIZE)
    module_name = data[NSO_HEADER_SIZE:name_end].decode("utf-8", "replace")
    bounds = [segments[i]["file"] for i in range(3)] + [len(data)]
    blobs = []
    for index, segment in enumerate(segments):
        blob = data[bounds[index]:bounds[index + 1]]
        blobs.append(lz4_block_decompress(blob, segment["size"]))

    image = bytearray(segments[2]["mem"] + segments[2]["size"] + NSO_HEADER_SIZE)
    header = bytearray(data[:NSO_HEADER_SIZE])
    struct.pack_into("<I", header, 0x0C, 0x38)
    for index, segment in enumerate(segments):
        file_offset = segment["mem"] + NSO_HEADER_SIZE
        struct.pack_into("<IIII", header, 0x10 + index * 0x10,
                         file_offset, segment["mem"], segment["size"], segment["aux"])
        image[file_offset:file_offset + len(blobs[index])] = blobs[index]
    struct.pack_into("<III", header, 0x60,
                     segments[0]["size"], segments[1]["size"], segments[2]["size"])
    image[:NSO_HEADER_SIZE] = header

    module_offset = segments[2]["aux"]
    name_file_offset = segments[0]["mem"] + NSO_HEADER_SIZE + module_offset
    encoded = module_name.encode("utf-8") + b"\x00"
    if name_file_offset + len(encoded) <= len(image):
        image[name_file_offset:name_file_offset + len(encoded)] = encoded

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(image))
    return {"module_name": module_name,
            "segments": [{"mem": s["mem"], "size": s["size"], "aux": s["aux"]} for s in segments],
            "output": str(out_path), "output_size": len(image)}


def main():
    parser = argparse.ArgumentParser(description="Decompress an ExeFS NSO0 module")
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        info = decompress_module(args.input, args.out)
    except Exception as exc:
        print(f"FAILED: {exc!r}", file=sys.stderr)
        return 1
    print(f"[+] {args.input.name}: module={info['module_name']!r} "
          f"segments={[s['size'] for s in info['segments']]} -> {info['output_size']} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
