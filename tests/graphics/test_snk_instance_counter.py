import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def instruction(op, *args):
    return [((len(args) + 1) << 16) | op, *args]


def module(result=6985, predicate=6984):
    words = [0x07230203, 0x00010300, 0, 7000, 0]
    words += instruction(20, 1)
    words += instruction(21, 2, 32, 0)
    words += instruction(42, 1, 3)
    words += instruction(43, 2, 4, 3)
    words += instruction(334, 1, result, 4, predicate)
    return words


class InstanceCounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.directory.name)
        source = root / 'counter.cpp'
        source.write_text('''
#include <iostream>
#include <iterator>
#include "xbg_spirv_stencil.h"
int main(int argc,char **) {
    std::vector<char> input((std::istreambuf_iterator<char>(std::cin)), {});
    if (input.size() % 4) return 2;
    std::vector<uint32_t> words(input.size() / 4);
    std::memcpy(words.data(), input.data(), input.size());
    std::cerr << (argc>1?xbg_snk_scalar_instance_counter(words,6958,6957):xbg_snk_scalar_instance_counter(words));
    std::cout.write(reinterpret_cast<const char *>(words.data()), words.size() * 4);
}
''')
        cls.executable = root / 'counter'
        subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17', '-I',
                        str(ROOT / 'src/graphics/nvn_vulkan/engine'), str(source),
                        '-o', str(cls.executable)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def rewrite(self, words, grass=False):
        result = subprocess.run([str(self.executable)] + (["grass"] if grass else []),
                                input=struct.pack('<%dI' % len(words), *words),
                                capture_output=True, check=True)
        after = list(struct.unpack('<%dI' % (len(result.stdout) // 4), result.stdout))
        return result.stderr, after

    def test_grass_uses_its_existing_scalar_branch(self):
        before = module(result=6958, predicate=6957)
        changed, after = self.rewrite(before, grass=True)
        self.assertEqual(changed, b'1')
        self.assertEqual(after[:-4], before[:-5])
        self.assertEqual(after[-4:], instruction(83, 1, 6958, 3))
        self.assertEqual(self.rewrite(after, grass=True), (b'0', after))
        self.assertEqual(self.rewrite(before), (b'0', before))
        for words in [module(result=6959, predicate=6957),
                      module(result=6958, predicate=6956), before[:-1],
                      before + instruction(334, 1, 6990, 4, 6957)]:
            self.assertEqual(self.rewrite(words, grass=True), (b'0', words))

    def test_selects_existing_scalar_branch(self):
        before = module()
        changed, after = self.rewrite(before)
        self.assertEqual(changed, b'1')
        self.assertEqual(after[:-4], before[:-5])
        self.assertEqual(after[-4:], instruction(83, 1, 6985, 3))
        self.assertEqual(after[3], before[3])

    def test_repeated_processing_is_identical(self):
        _, after = self.rewrite(module())
        changed, twice = self.rewrite(after)
        self.assertEqual(changed, b'0')
        self.assertEqual(twice, after)

    def test_other_result_and_predicate_are_preserved(self):
        for words in [module(result=6986), module(predicate=6983)]:
            changed, after = self.rewrite(words)
            self.assertEqual((changed, after), (b'0', words))

    def test_truncation_and_multiple_votes_are_preserved(self):
        before = module()
        for words in [before[:-1], before + instruction(334, 1, 6990, 4, 6984)]:
            changed, after = self.rewrite(words)
            self.assertEqual((changed, after), (b'0', words))


if __name__ == '__main__':
    unittest.main()
