#!/usr/bin/env python3
"""Extract original Falcom NVN stages for the existing XGS compiler."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL_BYTES = 0x880
CONTROL_MAGIC = b'\x34\x12\x76\x98'
CODE_MAGICS = (b'\x78\x56\x34\x12', b'\x79\x56\x34\x12')


def extract_stage(data):
    if data[:4] != b'\x91\x68\x86\x19':
        raise ValueError('unsupported Falcom NVN container')
    controls = []
    offset = data.find(CONTROL_MAGIC)
    while offset >= 0:
        if (offset + CONTROL_BYTES <= len(data) and
                struct.unpack_from('<II', data, offset + 4) == (1, 16)):
            controls.append(offset)
        offset = data.find(CONTROL_MAGIC, offset + 4)
    if len(controls) != 1:
        raise ValueError('expected exactly one complete NVN control segment')
    offset = controls[0]
    control = data[offset:offset + CONTROL_BYTES]
    relative = struct.unpack_from('<Q', control, 0x6f0)[0]
    c1_offset, code_bytes = struct.unpack_from('<II', control, 0x700)
    start = offset + relative
    if (not code_bytes or relative < CONTROL_BYTES or start > len(data) or
            code_bytes > len(data) - start or c1_offset > code_bytes):
        raise ValueError('shader code or constant segment outside container')
    code = data[start:start + code_bytes]
    if code[:4] not in CODE_MAGICS:
        raise ValueError('unsupported NVN shader code header')
    return hashlib.sha256(control).hexdigest()[:16], control, code


def collect_stages(romfs, overlay=None):
    sources = {p.relative_to(romfs).as_posix(): p
               for p in (romfs / 'asset/nx/shader').glob('*.nvn')}
    if overlay:
        sources.update({p.relative_to(overlay).as_posix(): p
                        for p in (overlay / 'asset/nx/shader').glob('*.nvn')})
    if not sources:
        raise ValueError('no Falcom NVN shader containers found')
    stages = {}
    for relative, source in sorted(sources.items()):
        try:
            key, control, code = extract_stage(source.read_bytes())
        except ValueError as error:
            raise ValueError(f'{relative}: {error}') from error
        if key in stages:
            if stages[key]['control'] != control or stages[key]['code'] != code:
                raise ValueError(f'conflicting shader content for key {key}')
            stages[key]['sources'].append(relative)
        else:
            stages[key] = {'control': control, 'code': code, 'sources': [relative]}
    return stages


def write_stages(stages, output):
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for key, stage in sorted(stages.items()):
        record = {'key': key, 'sources': stage['sources']}
        for kind in ('control', 'code'):
            data = stage[kind]
            path = output / f'{key}.{kind}.bin'
            if path.exists():
                if path.read_bytes() != data:
                    raise ValueError(f'existing stage differs: {path.name}')
            else:
                with path.open('xb') as stream:
                    stream.write(data)
            record[kind + '_bytes'] = len(data)
            record[kind + '_sha256'] = hashlib.sha256(data).hexdigest()
        records.append(record)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--romfs', type=Path, required=True)
    parser.add_argument('--overlay', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    if not output.is_relative_to((ROOT / '.local').resolve()):
        parser.error('generated stages must be under this repository .local directory')
    stages = collect_stages(args.romfs.resolve(), args.overlay.resolve() if args.overlay else None)
    records = write_stages(stages, output)
    manifest = {'containers': sum(len(row['sources']) for row in records),
                'unique_stages': len(records), 'stages': records}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'containers': manifest['containers'], 'unique_stages': len(records),
                      'status': 'EXTRACTED_NOT_COMPILED_OR_DEVICE_ACCEPTED'}))


if __name__ == '__main__':
    main()
