#!/usr/bin/env python3
"""Inventory the title's decompressed RomFS without exposing keys in argv."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from nca_romfs import NcaRomFS

NONE = 0xffffffff


def records(blob, fixed, fmt):
    result = {}
    offset = 0
    while offset < len(blob):
        if offset + fixed > len(blob):
            raise ValueError('truncated metadata record')
        values = struct.unpack_from(fmt, blob, offset)
        length = values[-1]
        end = offset + fixed + length
        if end > len(blob) or length > 4096:
            raise ValueError('invalid metadata name length')
        name = blob[offset + fixed:end].decode('utf-8', 'strict')
        if '/' in name or '\\' in name or name in ('.', '..') or '\x00' in name:
            raise ValueError('unsafe metadata name')
        result[offset] = (values, name)
        offset = (end + 3) & ~3
    return result


def inventory(rom):
    h = struct.unpack('<10Q', rom.read_virtual(0, 80))
    if h[0] != 80:
        raise ValueError('invalid RomFS header')
    dirs = records(rom.read_virtual(h[3], h[4]), 24, '<6I')
    files = records(rom.read_virtual(h[7], h[8]), 32, '<IIQQII')
    def dir_path(offset):
        parts, seen = [], set()
        while offset != 0:
            if offset in seen or offset not in dirs:
                raise ValueError('invalid directory parent chain')
            seen.add(offset)
            fields, name = dirs[offset]
            parts.append(name)
            offset = fields[0]
        return '/'.join(reversed(parts))
    result = []
    for values, name in files.values():
        parent, _, off, size, _, _ = values
        if parent not in dirs or not name or h[9] + off + size > rom.virtual_size:
            raise ValueError('invalid file metadata')
        path = '/'.join(filter(None, (dir_path(parent), name)))
        result.append({'path': path, 'offset': h[9] + off, 'size': size})
    if len({f['path'] for f in result}) != len(result):
        raise ValueError('duplicate RomFS paths')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--nsp', type=Path, required=True)
    ap.add_argument('--keys', type=Path, required=True)
    ap.add_argument('--titlekey-file', type=Path, required=True)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--extract', action='append', default=[])
    ap.add_argument('--output-dir', type=Path)
    args = ap.parse_args()
    key = json.loads(args.titlekey_file.read_text())['titlekey']
    rom = NcaRomFS(args.nsp, args.keys, key)
    files = inventory(rom)
    by_path = {f['path']: f for f in files}
    if args.extract and not args.output_dir:
        ap.error('--extract requires --output-dir')
    for path in args.extract:
        if path not in by_path:
            raise ValueError('resource not found: ' + path)
        item = by_path[path]
        data = rom.read_virtual(item['offset'], item['size'])
        dest = args.output_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as out:
            out.write(data)
        item['sha256'] = hashlib.sha256(data).hexdigest()
        print('extracted', path, 'bytes', len(data), 'sha256', item['sha256'])
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open('x', encoding='utf-8') as out:
        json.dump({'file_count': len(files), 'files': files}, out, ensure_ascii=False, indent=2)
    print('files', len(files), 'manifest', args.manifest)


if __name__ == '__main__':
    main()
