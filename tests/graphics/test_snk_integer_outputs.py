import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


def instruction(opcode, *operands):
    return [((len(operands) + 1) << 16) | opcode, *operands]


def shader_words(bits, value_kind='constant', components=4, late_types=False, late_pointers=False):
    # A fragment shader writing one component of integer attachment location 1
    # through the translator's default float output interface.
    bound = 22 if late_pointers else 20 if late_types else 19
    words = [0x07230203, 0x00010000, 0, bound, 0]
    words += instruction(17, 1)
    words += instruction(14, 0, 1)
    words += instruction(15, 4, 12, 0x6E69616D, 0, 11)
    words += instruction(16, 12, 7)
    words += instruction(71, 11, 30, 1)
    words += instruction(19, 1)
    words += instruction(21, 2, 32, 0)
    words += instruction(21, 3, 32, 1)
    words += instruction(22, 4, 32)
    words += instruction(23, 5, 4, components)
    words += instruction(32, 6, 3, 5)
    words += instruction(32, 7, 3, 4)
    words += instruction(32, 16, 7, 4)
    words += instruction(33, 8, 1)
    words += instruction(43, 2, 9, components - 1)
    words += instruction(43, 4, 10, bits)
    words += instruction(43, 3 if value_kind == 'signed_bitcast' else 2, 18, bits)
    words += instruction(59, 6, 11, 3)
    if late_types:
        # UINT-fetch rewrites can add this type after earlier globals.
        words += instruction(23, 19, 2, components)
    if late_pointers:
        words += instruction(32, 20, 3, 19)
        words += instruction(32, 21, 3, 2)
    words += instruction(54, 1, 12, 0, 8)
    words += instruction(248, 13)
    if value_kind == 'load':
        words += instruction(59, 16, 17, 7)
        words += instruction(62, 17, 10)
        words += instruction(61, 4, 15, 17)
        value = 15
    elif value_kind in ('bitcast', 'signed_bitcast'):
        words += instruction(124, 4, 15, 18)
        value = 15
    else:
        value = 10
    words += instruction(65, 7, 14, 11, 9)
    words += instruction(62, 14, value)
    words += instruction(253)
    words += instruction(56)
    return words


def instructions(words):
    offset = 5
    while offset < len(words):
        count = words[offset] >> 16
        yield words[offset] & 0xFFFF, words[offset + 1:offset + count]
        offset += count


class IntegerOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++') or shutil.which('c++')
        if compiler is None:
            raise unittest.SkipTest('a C++ compiler is required')
        cls.directory = tempfile.TemporaryDirectory()
        source_path = ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp'
        source = source_path.read_text()
        start = source.index('bool spv_integer_outputs(')
        end = source.index('// One module per (fragment shader, integer target mask)', start)
        harness = '''
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <iostream>
#include <iterator>
#include <unordered_map>
#include <utility>
#include <vector>
''' + source[start:end] + '''
int main() {
    std::vector<char> bytes((std::istreambuf_iterator<char>(std::cin)), {});
    if (bytes.size() % 4) return 2;
    std::vector<uint32_t> words(bytes.size() / 4);
    std::memcpy(words.data(), bytes.data(), bytes.size());
    if (!spv_integer_outputs(words, 4)) return 3;
    std::cout.write(reinterpret_cast<const char *>(words.data()), words.size() * 4);
}
'''
        path = pathlib.Path(cls.directory.name)
        source_file = path / 'integer_outputs.cpp'
        source_file.write_text(harness)
        cls.executable = path / 'integer_outputs'
        subprocess.run([compiler, '-std=c++17', '-O0', str(source_file),
                        '-o', str(cls.executable)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def rewrite(self, words):
        result = subprocess.run([str(self.executable)],
                                input=struct.pack('<%dI' % len(words), *words),
                                check=True, capture_output=True)
        return list(struct.unpack('<%dI' % (len(result.stdout) // 4), result.stdout))

    def stored_value(self, words):
        definitions = {}
        stored = None
        for opcode, operands in instructions(words):
            if opcode in (43, 61, 124):
                definitions[operands[1]] = (opcode, operands)
            if opcode == 62 and operands[0] == 14:
                stored = operands[1]
        return stored, definitions.get(stored)

    def test_preserves_packed_material_constant(self):
        # Actual Falcom shaders use float bits 0x28 for uint material flags 40.
        words = self.rewrite(shader_words(0x28))
        _, (opcode, operands) = self.stored_value(words)
        self.assertEqual((opcode, operands[0], operands[2]), (43, 2, 40))

    def test_preserves_float_constant_bits(self):
        for bits in (0, 1, 0x3F800000, 0xBF800000, 0x7FC00000):
            with self.subTest(bits=bits):
                words = self.rewrite(shader_words(bits))
                _, (opcode, operands) = self.stored_value(words)
                self.assertEqual((opcode, operands[0], operands[2]), (43, 2, bits))

    def test_reinterprets_float_load(self):
        words = self.rewrite(shader_words(0x28, 'load'))
        _, (opcode, operands) = self.stored_value(words)
        self.assertEqual((opcode, operands[0], operands[2]), (124, 2, 15))
        self.assertFalse(any(opcode == 109 for opcode, _ in instructions(words)))

    def test_keeps_direct_integer_source(self):
        words = self.rewrite(shader_words(0x28, 'bitcast'))
        stored, _ = self.stored_value(words)
        self.assertEqual(stored, 18)

    def assert_declaration_dependencies(self, words):
        defined = set()
        for opcode, operands in instructions(words):
            if opcode == 23:  # OpTypeVector needs its component type.
                self.assertIn(operands[1], defined)
                defined.add(operands[0])
            elif opcode == 32:  # OpTypePointer needs its pointee type.
                self.assertIn(operands[2], defined)
                defined.add(operands[0])
            elif opcode == 59:  # OpVariable needs its pointer type.
                self.assertIn(operands[0], defined)
            elif 19 <= opcode <= 33:
                defined.add(operands[0])

    def validate(self, words):
        validator = shutil.which('spirv-val')
        if validator is None:
            return
        path = pathlib.Path(self.directory.name) / 'rewritten.spv'
        path.write_bytes(struct.pack('<%dI' % len(words), *words))
        result = subprocess.run([validator, '--target-env', 'vulkan1.1', str(path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_late_integer_vector_precedes_new_output_pointer(self):
        words = self.rewrite(shader_words(0x28, late_types=True))
        self.assert_declaration_dependencies(words)
        self.validate(words)

    def test_late_integer_pointers_precede_rewritten_output_variable(self):
        words = self.rewrite(shader_words(0x28, late_types=True, late_pointers=True))
        self.assert_declaration_dependencies(words)
        self.validate(words)

    def test_late_types_preserve_all_supported_store_forms(self):
        for components in (2, 3, 4):
            for late_pointers in (False, True):
                for value_kind in ('constant', 'load', 'bitcast', 'signed_bitcast'):
                    with self.subTest(components=components, pointers=late_pointers, value=value_kind):
                        words = self.rewrite(shader_words(0xFFFFFFFE, value_kind,
                            components=components, late_types=True, late_pointers=late_pointers))
                        self.assert_declaration_dependencies(words)
                        self.validate(words)

    def test_signed_integer_source_keeps_original_bits(self):
        words = self.rewrite(shader_words(0xFFFFFFFE, 'signed_bitcast'))
        _, (opcode, operands) = self.stored_value(words)
        self.assertEqual((opcode, operands[0], operands[2]), (124, 2, 18))
        self.validate(words)

    def test_actual_uint_fetch_candidate_has_valid_output_declarations(self):
        path = ROOT / '.local/graphics-t10/gbuffer-uint/183334461b277951.spv'
        if not path.is_file():
            self.skipTest('the local Falcom UINT-fetch input is unavailable')
        data = path.read_bytes()
        original = list(struct.unpack('<%dI' % (len(data) // 4), data))
        words = self.rewrite(original)
        self.assert_declaration_dependencies(words)
        self.validate(words)


if __name__ == '__main__':
    unittest.main()
