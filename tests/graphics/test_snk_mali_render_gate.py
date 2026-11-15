import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class MaliRenderGateTests(unittest.TestCase):
    def test_marker_is_confined_to_arm_device(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('    mali_render_height=0;')
        end = source.index('    VkPhysicalDeviceProperties2 pp', start)
        gate = source[start:end]
        start = source.index('extern "C" void xbg_present_texture(')
        present = source[source.index('\n', start):source.index('    if(!gfx_async)', start)]
        program = r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <string>
struct { uint32_t vendorID; } properties;
static std::string shader_path;
struct { const char *shader_directory; } cfg;
static unsigned mali_render_height, calls, requested;
extern "C" void guest_process_apply_snk_render_height(unsigned height) { ++calls; requested=height; }
static void configure() {
''' + gate + r'''
}
static void present_boundary() {
''' + present + r'''
}
int main(int argc,char **argv) {
    assert(argc==2);shader_path=std::string(argv[1])+"/shaders";cfg.shader_directory=shader_path.c_str();
    std::string marker=std::string(argv[1])+"/gfx-mali-render-height";
    for(unsigned height:{540u,720u,900u,0u}) {
        FILE *f=fopen(marker.c_str(),"wb");assert(f);fprintf(f,"%u",height);fclose(f);
        for(uint32_t vendor:{0x13b5u,0x5143u,0x10deu,0u}) {
            properties.vendorID=vendor;calls=0;configure();present_boundary();
            bool enabled=vendor==0x13b5 && (height==540 || height==720);
            assert(mali_render_height==(enabled?height:0));assert(calls==unsigned(enabled));
            if(enabled)assert(requested==height);
        }
    }
    remove(marker.c_str());
    for(uint32_t vendor:{0x13b5u,0x5143u,0x10deu,0u}) {
        properties.vendorID=vendor;calls=0;configure();present_boundary();
        assert(mali_render_height==(vendor==0x13b5?540u:0u));
        assert(calls==unsigned(vendor==0x13b5));
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'gate.cpp').write_text(program)
            executable = path / 'gate'
            subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                            str(path / 'gate.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable), directory], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
