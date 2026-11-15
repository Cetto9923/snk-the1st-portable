import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


def instructions(data):
    words = struct.unpack('<' + 'I' * (len(data) // 4), data)
    offset = 5
    while offset < len(words):
        count = words[offset] >> 16
        yield words[offset] & 65535, words[offset + 1:offset + count]
        offset += count


def input_types(data):
    parsed = list(instructions(data))
    locations = {args[0]: args[2] for op, args in parsed if op == 71 and args[1] == 30}
    pointers = {args[0]: args[2] for op, args in parsed if op == 32}
    vectors = {args[0]: args[1] for op, args in parsed if op == 23}
    scalars = {args[0]: (op, args[1:]) for op, args in parsed if op in (21, 22)}
    return {locations[args[1]]: scalars[vectors.get(pointers[args[0]], pointers[args[0]])]
            for op, args in parsed if op == 59 and args[2] == 1 and args[1] in locations}


class IntegerVertexInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('glslc')
        if not compiler:
            candidates = sorted((pathlib.Path.home() / 'Library/Android/sdk/ndk').glob('*/shader-tools/darwin-x86_64/glslc'))
            compiler = str(candidates[-1]) if candidates else None
        if not compiler or not shutil.which('spirv-val'):
            raise unittest.SkipTest('glslc and spirv-val are required')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = pathlib.Path(cls.temporary.name)
        cls.addClassCleanup(cls.temporary.cleanup)
        source = cls.directory / 'input.vert'
        source.write_text('''#version 450
layout(location=5) in vec4 raw;
layout(location=6) in vec4 signedRaw;
layout(location=0) in vec4 ordinary;
void main() {
    gl_Position = vec4(raw.x, raw.y, raw.z, raw.w) + signedRaw + ordinary;
}
''')
        cls.original = cls.directory / 'original.spv'
        subprocess.run([compiler, '--target-env=vulkan1.1', str(source), '-o', str(cls.original)], check=True)
        driver = cls.directory / 'patch.cpp'
        driver.write_text(r'''
#include "src/graphics/nvn_vulkan/engine/xbg_spirv_vertex.h"
#include <cassert>
#include <cstdlib>
#include <fstream>
#include <iostream>
int main(int argc, char **argv) {
    assert(argc == 4);
    std::ifstream stream(argv[1], std::ios::binary | std::ios::ate);
    size_t bytes = stream.tellg(); stream.seekg(0);
    std::vector<uint32_t> words(bytes / 4);
    stream.read(reinterpret_cast<char *>(words.data()), bytes);
    auto original = words;
    int changed = xbg_spirv_integer_vertex_inputs(words, std::strtoul(argv[2], nullptr, 0));
    if (changed < 0) { assert(words == original); return 4; }
    std::ofstream output(argv[3], std::ios::binary);
    output.write(reinterpret_cast<const char *>(words.data()), words.size() * 4);
    std::cout << changed;
}
''')
        cls.executable = cls.directory / 'patch'
        subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(ROOT),
                        str(driver), '-o', str(cls.executable)], check=True)

    def patch(self, source, mask, leaf):
        output = self.directory / leaf
        result = subprocess.run([str(self.executable), str(source), str(mask), str(output)],
                                check=True, capture_output=True, text=True)
        subprocess.run(['spirv-val', '--target-env', 'vulkan1.1', str(output)], check=True)
        return output, int(result.stdout)

    def test_component_and_vector_loads_keep_register_bits(self):
        mask = (1 << 10) | (2 << 12)
        output, changed = self.patch(self.original, mask, 'integer.spv')
        self.assertEqual(changed, 2)
        types = input_types(output.read_bytes())
        self.assertEqual(types[5], (21, (32, 0)))
        self.assertEqual(types[6], (21, (32, 1)))
        self.assertEqual(types[0], (22, (32,)))
        before = [op for op, _ in instructions(self.original.read_bytes())]
        after = [op for op, _ in instructions(output.read_bytes())]
        self.assertGreater(after.count(124), before.count(124))
        self.assertEqual(after.count(111) + after.count(112), before.count(111) + before.count(112))
        again, changed = self.patch(output, mask, 'again.spv')
        self.assertEqual(changed, 0)
        self.assertEqual(again.read_bytes(), output.read_bytes())

    def test_zero_mask_and_unselected_inputs_remain_exact(self):
        unchanged, changed = self.patch(self.original, 0, 'unchanged.spv')
        self.assertEqual(changed, 0)
        self.assertEqual(unchanged.read_bytes(), self.original.read_bytes())
        selected, changed = self.patch(self.original, 1 << 10, 'selected.spv')
        self.assertEqual(changed, 1)
        self.assertEqual(input_types(selected.read_bytes())[6], (22, (32,)))

    def test_truncated_instruction_is_rejected_without_mutation(self):
        path = self.directory / 'truncated.spv'
        path.write_bytes(self.original.read_bytes() + struct.pack('<I', 4 << 16 | 43))
        output = self.directory / 'invalid-output.spv'
        result = subprocess.run([str(self.executable), str(path), '1024', str(output)], capture_output=True)
        self.assertEqual(result.returncode, 4)
        self.assertFalse(output.exists())
