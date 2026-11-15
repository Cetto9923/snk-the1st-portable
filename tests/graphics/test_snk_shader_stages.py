import importlib.util
import pathlib
import struct
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'snk_stages', ROOT / 'scripts/graphics/extract_snk_shader_stages.py')
STAGES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGES)


def container(code=b'\x78\x56\x34\x12payload'):
    data = bytearray(0xb50 + len(code))
    data[:4] = b'\x91\x68\x86\x19'
    offset = 0x2d0
    data[offset:offset + 4] = STAGES.CONTROL_MAGIC
    struct.pack_into('<II', data, offset + 4, 1, 16)
    struct.pack_into('<Q', data, offset + 0x6f0, 0x880)
    struct.pack_into('<II', data, offset + 0x700, len(code), len(code))
    data[0xb50:] = code
    return bytes(data)


class ShaderStageTests(unittest.TestCase):
    def test_original_bytes_and_range_validation(self):
        data = container()
        key, control, code = STAGES.extract_stage(data)
        self.assertEqual(len(key), 16)
        self.assertEqual(control, data[0x2d0:0xb50])
        self.assertEqual(code, data[0xb50:])
        for invalid in (data[:-1], data[:0xb40], container(b'bad!')):
            with self.assertRaises(ValueError):
                STAGES.extract_stage(invalid)
        invalid = bytearray(data)
        struct.pack_into('<Q', invalid, 0x2d0 + 0x6f0, 0xffffffffffffffff)
        with self.assertRaises(ValueError):
            STAGES.extract_stage(invalid)

    def test_overlay_and_duplicate_content_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            base, patch = root / 'base', root / 'patch'
            for folder in (base, patch):
                (folder / 'asset/nx/shader').mkdir(parents=True)
            (base / 'asset/nx/shader/a.nvn').write_bytes(container())
            (base / 'asset/nx/shader/b.nvn').write_bytes(container())
            # The patch changes the code while retaining an identical control.
            changed = container(b'\x78\x56\x34\x12changed')
            self.assertEqual(len(changed), len(container()))
            (patch / 'asset/nx/shader/a.nvn').write_bytes(changed)
            with self.assertRaises(ValueError):
                STAGES.collect_stages(base, patch)
            (patch / 'asset/nx/shader/b.nvn').write_bytes(changed)
            stages = STAGES.collect_stages(base, patch)
            self.assertEqual(len(stages), 1)
            output = root / 'stages'
            records = STAGES.write_stages(stages, output)
            self.assertEqual(len(records[0]['sources']), 2)
            self.assertEqual(STAGES.write_stages(stages, output), records)
            (output / (records[0]['key'] + '.code.bin')).write_bytes(b'preserve')
            with self.assertRaises(ValueError):
                STAGES.write_stages(stages, output)
