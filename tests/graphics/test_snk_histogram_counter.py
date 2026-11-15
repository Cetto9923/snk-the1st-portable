import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def instruction(op, *args):
    return [((len(args) + 1) << 16) | op, *args]


def module(scalar=False, global_counter=False):
    words = [0x07230203, 0x00010300, 0, 901 if scalar else 900, 0]
    words += instruction(20, 83)
    words += instruction(43, 1, 464, 3)
    words += instruction(41, 83, 465)
    words += instruction(32, 589, 2, 1)
    if scalar:
        words += instruction(42, 83, 900)
    words += instruction(54, 2, 48, 0, 3)
    words += instruction(133, 4, 77, 78, 79)
    for result, predicate in [(502, 501), (617, 616)]:
        words += (instruction(83, 83, result, 900) if scalar
                  else instruction(334, 83, result, 464, predicate))
    words += (instruction(65, 589, 511, 26, 314, 510) if global_counter
              else instruction(65, 413, 511, 31, 510))
    words += (instruction(83, 83, 543, 465) if global_counter
              else instruction(168, 83, 543, 542))
    words += instruction(56)
    return words


class HistogramCounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.directory.name)
        source = root / 'histogram.cpp'
        source.write_text('''
#include <iostream>
#include <iterator>
#include "xbg_spirv_stencil.h"
int main() {
    std::vector<char> input((std::istreambuf_iterator<char>(std::cin)), {});
    if (input.size() % 4) return 2;
    std::vector<uint32_t> words(input.size() / 4);
    std::memcpy(words.data(), input.data(), input.size());
    std::cerr << xbg_snk_global_histogram(words);
    std::cout.write(reinterpret_cast<const char *>(words.data()), words.size() * 4);
}
''')
        cls.executable = root / 'histogram'
        subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                        '-fsanitize=address,undefined', '-I',
                        str(ROOT / 'src/graphics/nvn_vulkan/engine'), str(source),
                        '-o', str(cls.executable)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def rewrite(self, words):
        result = subprocess.run([str(self.executable)],
                                input=struct.pack('<%dI' % len(words), *words),
                                capture_output=True, check=True)
        after = list(struct.unpack('<%dI' % (len(result.stdout) // 4), result.stdout))
        return result.stderr, after

    def test_original_and_scalar_bundles_use_global_counter(self):
        for before in [module(), module(scalar=True)]:
            changed, after = self.rewrite(before)
            self.assertEqual(changed, b'1')
            self.assertEqual(after, module(scalar=True, global_counter=True))

    def test_repeated_processing_preserves_module(self):
        before = module(scalar=True, global_counter=True)
        changed, after = self.rewrite(before)
        self.assertEqual((changed, after), (b'0', before))

    def test_unfamiliar_sites_are_preserved(self):
        for original, replacement in [(501, 503), (616, 618), (589, 590), (542, 540)]:
            before = [replacement if value == original else value for value in module()]
            changed, after = self.rewrite(before)
            self.assertEqual((changed, after), (b'0', before))

    def test_truncation_and_extra_vote_are_preserved(self):
        before = module()
        for words in [before[:-1], before[:-1] + instruction(334, 83, 700, 464, 701) + before[-1:]]:
            changed, after = self.rewrite(words)
            self.assertEqual((changed, after), (b'0', words))


if __name__ == '__main__':
    unittest.main()
