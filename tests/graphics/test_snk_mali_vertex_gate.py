import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class MaliVertexGate(unittest.TestCase):
    def test_live_and_warm_paths_preserve_other_vendors(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('    if(properties.vendorID==0x13b5 && state.shader[0]){')
        live = source[start:source.index('    uint32_t active_colors=', start)]
        start = source.index('    if(properties.vendorID==0x13b5){')
        warm = source[start:source.index('    VkPipelineInputAssemblyStateCreateInfo a', start)]
        program = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
using VkShaderModule = uint64_t;
constexpr unsigned VK_SHADER_STAGE_VERTEX_BIT = 1;
struct Shader { std::vector<uint32_t> inputs; VkShaderModule module; } shader;
struct { uint32_t vendorID; } properties;
struct { Shader *shader[5]; uint32_t attrib[16]; } state;
struct va_st { unsigned fmt:8, rest:24; };
static unsigned live_calls, warm_calls, live_kinds, warm_kinds;
static void need(bool value, const char *) { assert(value); }
static unsigned format(unsigned value) { return value; }
static unsigned integer_vertex_format_kind(unsigned format) { return format == 0x2f ? 1 : 0; }
static VkShaderModule mali_vertex_input_module(Shader &source, uint32_t kinds) {
    ++live_calls; live_kinds = kinds; return kinds ? 400 + kinds : source.module;
}
static VkShaderModule load_module(const std::string &key, uint32_t kinds) {
    assert(key == "vertex"); ++warm_calls; warm_kinds = kinds; return 400 + kinds;
}
static VkShaderModule modules[5];
static void live_draw() {
''' + live + r'''
}
struct Attribute { uint32_t location, format; };
static std::vector<Attribute> va;
static struct { std::vector<std::string> keys; } rec;
static unsigned ns = 2;
static struct Stage { unsigned stage; VkShaderModule module; } st[2];
static bool warm_build() {
''' + warm + r'''
    return true;
}
int main() {
    shader.inputs = {0, 5}; shader.module = 11; state.shader[0] = &shader;
    state.attrib[0] = 0x22; state.attrib[5] = 0x2f;
    rec.keys = {"vertex", "fragment"};
    va = {{0, 0x22}, {5, 0x2f}};
    for (uint32_t vendor : {0x5143u, 0x10deu, 0u, 0x13b5u}) {
        properties.vendorID = vendor;
        live_calls = warm_calls = live_kinds = warm_kinds = 0;
        modules[0] = shader.module; st[0] = {1, 11}; st[1] = {16, 22};
        live_draw(); assert(warm_build());
        bool mali = vendor == 0x13b5;
        assert(live_calls == unsigned(mali) && warm_calls == unsigned(mali));
        assert(modules[0] == (mali ? 1424u : 11u));
        assert(st[0].module == modules[0] && st[1].module == 22);
        if (mali) assert(live_kinds == 1024 && warm_kinds == 1024);
    }
    state.attrib[5] = 0x2e; va[1].format = 0x2e; modules[0] = 11;
    st[0].module = 11; warm_calls = 0;
    live_draw(); assert(warm_build());
    assert(live_kinds == 0 && modules[0] == 11 && st[0].module == 11 && !warm_calls);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'gate.cpp').write_text(program)
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            str(path / 'gate.cpp'), '-o', str(path / 'gate')], check=True)
            subprocess.run([str(path / 'gate')], check=True)
