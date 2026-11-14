#!/usr/bin/env python3
import struct
from pathlib import Path

# Load CRC table from main.bin
MAIN_BIN = Path('/Users/yuyan9923/GitHub/snk-the1st-honor-gtpro/.local/nca/nso/main.bin')
with open(MAIN_BIN, 'rb') as f:
    f.seek(0x10 + 1 * 0x10)
    ro_off, ro_dst, ro_sz = struct.unpack('<III', f.read(12))
    f.seek(ro_off + (0x52d1fc - ro_dst))
    crc_table = list(struct.unpack('<256I', f.read(256 * 4)))

def calc_crc(s: bytes):
    if not s:
        return 0xffffffff
    w8 = 0xffffffff
    for b in s:
        idx = (w8 ^ b) & 0xff
        w8 = crc_table[idx] ^ (w8 >> 8)
    return w8

class BJSONBuilder:
    def __init__(self):
        self.buf = bytearray(16)
        self.buf[0:4] = b'JSON'
        self.key_cache = {}

    def get_or_add_key(self, key_str: str) -> int:
        kb = key_str.encode('ascii')
        if kb in self.key_cache:
            return self.key_cache[kb]
        off = len(self.buf)
        crc = calc_crc(kb)
        self.buf.extend(struct.pack('<I', crc))
        self.buf.extend(kb + b'\x00')
        while len(self.buf) % 4 != 0:
            self.buf.append(0)
        self.key_cache[kb] = off
        return off

    def build_value(self, val, key_str=None) -> int:
        key_off = self.get_or_add_key(key_str) if key_str is not None else None
        node_off = len(self.buf)
        has_key = key_off is not None

        if isinstance(val, (int, float)):
            tag = 0x02 if has_key else 0x12
            self.buf.append(tag)
            if has_key:
                self.buf.extend(struct.pack('<I', key_off))
            # Critical: BJSONNode::GetInt and GetFloat read 8-byte IEEE 754 double!
            d_val = float(val)
            self.buf.extend(struct.pack('<d', d_val))

        elif isinstance(val, str):
            tag = 0x06 if has_key else 0x16
            self.buf.append(tag)
            if has_key:
                self.buf.extend(struct.pack('<I', key_off))
            sb = val.encode('utf-8') + b'\x00'
            self.buf.extend(sb)
            while len(self.buf) % 4 != 0:
                self.buf.append(0)

        elif isinstance(val, list):
            elem_offsets = []
            for item in val:
                elem_offsets.append(self.build_value(item, key_str=None))
            node_off = len(self.buf)
            tag = 0x05 if has_key else 0x15
            self.buf.append(tag)
            if has_key:
                self.buf.extend(struct.pack('<I', key_off))
            self.buf.extend(struct.pack('<I', len(elem_offsets)))
            for off in elem_offsets:
                self.buf.extend(struct.pack('<I', off))

        elif isinstance(val, dict):
            items = []
            for k, v in val.items():
                crc = calc_crc(k.encode('ascii'))
                items.append((crc, k, v))
            # Sort keys by unsigned CRC for binary search
            items.sort(key=lambda x: x[0])

            elem_offsets = []
            for crc, k, v in items:
                elem_offsets.append(self.build_value(v, key_str=k))

            node_off = len(self.buf)
            tag = 0x04 if has_key else 0x14
            self.buf.append(tag)
            if has_key:
                self.buf.extend(struct.pack('<I', key_off))
            self.buf.extend(struct.pack('<I', len(elem_offsets)))
            for off in elem_offsets:
                self.buf.extend(struct.pack('<I', off))

        return node_off

    def finish(self, root_dict: dict) -> bytes:
        root_off = self.build_value(root_dict, key_str=None)
        self.buf[8:12] = struct.pack('<I', root_off)
        return bytes(self.buf)

def to_signed_int32(u: int) -> int:
    return struct.unpack('<i', struct.pack('<I', u))[0]

TID_NULL   = to_signed_int32(0xa5030f94)
TID_SPRITE = to_signed_int32(0xcd4e7557)
TID_TEXT   = to_signed_int32(0x6446f706)
TID_WINDOW = to_signed_int32(0x73b70314)
TID_NUMBER = to_signed_int32(0x6ec3e59d)
TID_CIRCLE = to_signed_int32(0x2ce49fb0)
TID_VSPRITE= to_signed_int32(0xede320e2)

def generate_loading():
    doc = {
        'Layout': {
            'mode': 1,
            'width': 1920,
            'height': 1080,
            'Root': {
                'name': 'Root',
                'type': TID_NULL,
                'children': [
                    {
                        'name': 'tips',
                        'type': TID_NULL,
                        'children': [
                            {
                                'name': 'title',
                                'type': TID_TEXT
                            }
                        ]
                    },
                    {
                        'name': 'icon',
                        'type': TID_NULL,
                        'children': [
                            {
                                'name': 'chr0',
                                'type': TID_SPRITE
                            }
                        ]
                    },
                    {
                        'name': 'gear',
                        'type': TID_SPRITE
                    },
                    {
                        'name': 'text',
                        'type': TID_TEXT
                    }
                ]
            }
        }
    }
    return BJSONBuilder().finish(doc)

def generate_title():
    doc = {
        'Layout': {
            'mode': 1,
            'width': 1920,
            'height': 1080,
            'Root': {
                'name': 'Root',
                'type': TID_NULL,
                'children': [
                    {
                        'name': 'continue',
                        'type': TID_NULL,
                        'children': [{'name': 'base', 'type': TID_SPRITE}]
                    },
                    {
                        'name': 'new_game',
                        'type': TID_NULL,
                        'children': [{'name': 'base', 'type': TID_SPRITE}]
                    },
                    {
                        'name': 'load_game',
                        'type': TID_NULL,
                        'children': [{'name': 'base', 'type': TID_SPRITE}]
                    },
                    {
                        'name': 'system',
                        'type': TID_NULL,
                        'children': [{'name': 'base', 'type': TID_SPRITE}]
                    },
                    {
                        'name': 'exit',
                        'type': TID_NULL,
                        'children': [{'name': 'base', 'type': TID_SPRITE}]
                    }
                ]
            }
        }
    }
    return BJSONBuilder().finish(doc)

if __name__ == '__main__':
    out_dir = Path('/Users/yuyan9923/GitHub/snk-the1st-honor-gtpro/.local/romfs_tree/layout')
    out_dir.mkdir(parents=True, exist_ok=True)
    loading_bytes = generate_loading()
    title_bytes = generate_title()
    (out_dir / 'loading.lay').write_bytes(loading_bytes)
    (out_dir / 'title.lay').write_bytes(title_bytes)
    print(f'Wrote {len(loading_bytes)} bytes to {out_dir / "loading.lay"}')
    print(f'Wrote {len(title_bytes)} bytes to {out_dir / "title.lay"}')
