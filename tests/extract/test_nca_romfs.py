import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/extract'))
from nca_romfs import NcaRomFS, decompress_block


class BlockTests(unittest.TestCase):
    def test_literals_and_overlap(self):
        self.assertEqual(decompress_block(b'\x40abcd', 4), b'abcd')
        self.assertEqual(decompress_block(b'\x10a\x01\x00', 5), b'aaaaa')

    def test_invalid_blocks(self):
        for data, length in ((b'\xf0', 4), (b'\x10', 1), (b'\x00\x00\x00', 4),
                             (b'\x40abcd', 3), (b'\x10a', 2)):
            with self.subTest(data=data), self.assertRaises(ValueError):
                decompress_block(data, length)

    def reader(self):
        r = NcaRomFS.__new__(NcaRomFS)
        r.virtual_size, r.section_size, r.payload_offset = 8, 9, 0
        r.relocations = [(0, 0, 0, 0), (4, 4, 3, 5)]
        r._virt = [0, 4]
        raw = b'abcd\x40efgh'
        r._read_section = lambda offset, size: raw[offset:offset + size]
        return r

    def test_cross_block_and_bounds(self):
        r = self.reader()
        self.assertEqual(r.read_virtual(2, 5), b'cdefg')
        self.assertEqual(r.read_virtual(8, 0), b'')
        for start, length in ((-1, 1), (7, 2), (0, -1)):
            with self.subTest(start=start, length=length), self.assertRaises(ValueError):
                r.read_virtual(start, length)
        with self.assertRaises(ValueError):
            r.source_for(4)

    def test_unsupported_and_truncated(self):
        r = self.reader()
        r.relocations[1] = (4, 4, 9, 5)
        with self.assertRaises(ValueError):
            r.read_virtual(4, 1)
        r.relocations[1] = (4, 4, 3, 6)
        with self.assertRaises(ValueError):
            r.read_virtual(4, 1)


if __name__ == '__main__':
    unittest.main()
