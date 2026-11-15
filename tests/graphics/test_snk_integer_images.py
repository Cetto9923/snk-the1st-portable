import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
KEY = '183334461b277951'


def instruction(opcode, *operands):
    return [(len(operands) + 1) << 16 | opcode, *operands]


def instructions(words):
    offset = 5
    while offset < len(words):
        count = words[offset] >> 16
        yield words[offset] & 65535, words[offset + 1:offset + count]
        offset += count


def fragment(typed_bindings=(), signed=False):
    words = [0x07230203, 0x00010300, 0, 1000, 0]
    emit = lambda opcode, *operands: words.extend(instruction(opcode, *operands))
    emit(17, 1)
    emit(14, 0, 1)
    emit(15, 4, 200, 0x6E69616D, 0, 104)
    emit(16, 200, 7)
    for binding, variable in ((10, 101), (16, 102), (22, 103)):
        emit(71, variable, 34, 0)
        emit(71, variable, 33, binding)
    emit(71, 104, 30, 0)
    emit(19, 1)
    emit(21, 2, 32, 0)
    emit(21, 3, 32, 1)
    emit(22, 4, 32)
    emit(23, 5, 4, 4)
    emit(23, 6, 2, 4)
    emit(23, 7, 3, 2)
    emit(23, 24, 3, 4)
    for image, sampled, pointer, scalar in ((8, 9, 10, 4), (18, 19, 20, 2),
                                             (21, 22, 23, 3)):
        emit(25, image, scalar, 1, 0, 0, 0, 1, 0)
        emit(27, sampled, image)
        emit(32, pointer, 0, sampled)
    emit(32, 11, 3, 5)
    emit(33, 12, 1)
    emit(43, 3, 13, 0)
    emit(44, 7, 14, 13, 13)
    for binding, variable in ((10, 101), (16, 102), (22, 103)):
        pointer = 23 if signed else 20 if binding in typed_bindings else 10
        emit(59, pointer, variable, 0)
    emit(59, 11, 104, 3)
    emit(54, 1, 200, 0, 12)
    emit(248, 201)
    for index, binding in enumerate((10, 16, 22)):
        typed = binding in typed_bindings or signed
        image, sampled, vector = ((21, 22, 24) if signed else (18, 19, 6)) if typed else (8, 9, 5)
        load, plain_image, fetched = 300 + index, 310 + index, 400 + index
        emit(61, sampled, load, 101 + index)
        emit(100, image, plain_image, load)
        emit(95, vector, fetched, plain_image, 14, 2, 13)
        if typed:
            emit(124, 5, 500 + index, fetched)
    emit(62, 104, 502 if (22 in typed_bindings or signed) else 402)
    emit(253)
    emit(56)
    return words


class IntegerImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++') or shutil.which('c++')
        if compiler is None:
            raise unittest.SkipTest('a C++ compiler is required')
        cls.directory = tempfile.TemporaryDirectory()
        directory = pathlib.Path(cls.directory.name)
        source = directory / 'integer_images.cpp'
        source.write_text('''
#include <iostream>
#include <iterator>
#include "xbg_spirv_stencil.h"
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    std::vector<char> bytes((std::istreambuf_iterator<char>(std::cin)), {});
    if (bytes.size() % 4) return 2;
    std::vector<uint32_t> words(bytes.size() / 4);
    std::memcpy(words.data(), bytes.data(), bytes.size());
    int changed = xbg_spirv_ffrs_stencil(words, 4, argv[1]);
    std::cerr << "changed=" << changed << " facts=";
    for (unsigned binding : {10u, 16u, 22u})
        std::cerr << xbg_ffrs_integer_fact(4, argv[1], binding);
    if (changed < 0) return 3;
    std::cout.write(reinterpret_cast<const char *>(words.data()), words.size() * 4);
}
''')
        cls.executable = directory / 'integer_images'
        subprocess.run([compiler, '-std=c++17', '-O0', '-I',
                        str(ROOT / 'src/graphics/nvn_vulkan/engine'), str(source),
                        '-o', str(cls.executable)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def rewrite(self, words, key=KEY):
        result = subprocess.run([str(self.executable), key],
                                input=struct.pack('<%dI' % len(words), *words),
                                capture_output=True)
        return result, list(struct.unpack('<%dI' % (len(result.stdout) // 4), result.stdout))

    def test_specializes_only_three_uint_fetches_and_exposes_flags(self):
        before = fragment()
        result, after = self.rewrite(before)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b'changed=3 facts=111')
        parsed = list(instructions(after))
        fetches = [operands for opcode, operands in parsed if opcode == 95]
        self.assertEqual(len(fetches), 3)
        self.assertTrue(all(operands[0] == 6 for operands in fetches))
        # The old result IDs keep their FP32 register-bit representation.
        bitcasts = {operands[1]: operands for opcode, operands in parsed if opcode == 124}
        for index in range(3):
            self.assertEqual(bitcasts[400 + index][0], 5)
            self.assertEqual(bitcasts[400 + index][2], fetches[index][1])

    def test_accepts_already_typed_diagnostic_bundle_without_changes(self):
        before = fragment((10, 16, 22))
        result, after = self.rewrite(before)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b'changed=0 facts=111')
        self.assertEqual(after, before)

    def test_rewrite_is_idempotent(self):
        _, once = self.rewrite(fragment())
        result, twice = self.rewrite(once)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b'changed=0 facts=111')
        self.assertEqual(twice, once)

    def test_preserves_typed_bindings_while_specializing_remaining_fetches(self):
        result, _ = self.rewrite(fragment((10,)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b'changed=2 facts=111')

    def test_unrelated_shader_is_unchanged(self):
        before = fragment()
        result, after = self.rewrite(before, '0000000000000000')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b'changed=0 facts=000')
        self.assertEqual(after, before)

    def test_rejects_unexpected_signed_sampled_type(self):
        result, _ = self.rewrite(fragment(signed=True))
        self.assertEqual(result.returncode, 3)
        self.assertIn(b'changed=-1', result.stderr)

    def test_rejects_truncated_module(self):
        result, _ = self.rewrite([0x07230203, 0x00010300, 0, 1000, 0, 4 << 16 | 32])
        self.assertEqual(result.returncode, 3)


if __name__ == '__main__':
    unittest.main()
