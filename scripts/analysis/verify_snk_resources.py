#!/usr/bin/env python3
"""Validate recovered configuration, layouts and OpenType table checksums."""
import argparse
import hashlib
import struct
import zlib
from pathlib import Path


def bjson(data):
    if len(data) < 16 or data[:4] != b'JSON':
        raise ValueError('invalid BJSON header')
    root = struct.unpack_from('<I', data, 8)[0]
    tag = data[root]
    if tag & 15 != 4:
        raise ValueError('invalid root type')
    pos = root + (1 if tag & 16 else 5)
    count = struct.unpack_from('<I', data, pos)[0]
    crc_values = []
    for i in range(count):
        node = struct.unpack_from('<I', data, pos + 4 + i * 4)[0]
        key = struct.unpack_from('<I', data, node + 1)[0]
        end = data.index(0, key + 4)
        actual = struct.unpack_from('<I', data, key)[0]
        if actual != (zlib.crc32(data[key + 4:end]) ^ 0xffffffff):
            raise ValueError('key CRC mismatch')
        crc_values.append(actual)
    if crc_values != sorted(crc_values):
        raise ValueError('unordered BJSON keys')
    return count


def font(data):
    magic, count = struct.unpack_from('>4sH', data)
    if magic != b'OTTO' or not count:
        raise ValueError('invalid OpenType header')
    for i in range(count):
        tag, checksum, offset, size = struct.unpack_from('>4sIII', data, 12 + i * 16)
        if offset + size > len(data):
            raise ValueError('font table outside file')
        buf = bytearray(data[offset:offset + size])
        if tag == b'head':
            if len(buf) < 12:
                raise ValueError('short font head')
            buf[8:12] = b'\0' * 4
        buf.extend(bytes((-len(buf)) % 4))
        value = sum(struct.unpack('>%dI' % (len(buf) // 4), buf)) & 0xffffffff
        if value != checksum:
            raise ValueError('font checksum mismatch: ' + repr(tag))
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    for path in ('asset/asset_config.json', 'layout/loading.lay', 'layout/title.lay', 'asset/common/font/dev_font.otf'):
        data = (args.root / path).read_bytes()
        count = font(data) if path.endswith('.otf') else bjson(data)
        print(path, 'bytes', len(data), 'entries', count, 'sha256', hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    main()
