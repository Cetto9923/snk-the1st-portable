import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class MaliDefaultsTests(unittest.TestCase):
    def test_defaults_and_explicit_overrides(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('     auto dm=')
        dm = source[start:source.index('\n', start)]
        start = source.index('     ldc_fold=dm(')
        translator = source[start:source.index('\n', start)]
        start = source.index('{const int cached_marker=')
        cached = source[start:source.index(';}', start) + 2]
        start = source.index('     FILE *async_marker=')
        asynchronous = source[start:source.index('     if(gfx_async)gfx_worker', start)]
        start = source.index('wtrack::marker=properties.vendorID')
        tracker = source[start:source.index('}{FILE *w=', start)]
        program = r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <string>
struct { uint32_t vendorID; } properties;
namespace wtrack { int marker; bool enabled; }
bool ldc_fold,forward_temps,nan_minmax,readback_cached,gfx_async,sync_submit_enabled;
std::string base,dir;size_t cut=std::string::npos;
void configure() {
    auto marker=[&](const char *name){FILE *f=fopen((base+name).c_str(),"rb");if(!f)return -1;int c=fgetc(f);fclose(f);return c;};
''' + dm + translator + cached + asynchronous + r'''
    FILE *w=fopen((base+"/gfx-wtrack").c_str(),"rb");
''' + tracker + r'''
}
int main(int argc,char **argv) {
    assert(argc==2);base=argv[1];dir=base+"/shaders";cut=dir.find_last_of('/');
    for(uint32_t vendor:{0x13b5u,0x5143u,0x10deu,0u}) {
        properties.vendorID=vendor;configure();bool mali=vendor==0x13b5;
        assert(ldc_fold==mali && forward_temps==mali && !nan_minmax);
        assert(readback_cached==mali && gfx_async==!mali);
        assert(wtrack::marker==(mali?0:-1));
        for(char value:{'0','1'}) {
            for(const char *name:{"/gfx-ldc-fold","/gfx-forward-temps","/gfx-readback-cached","/gfx-async-submit","/gfx-wtrack"}) {
                FILE *f=fopen((base+name).c_str(),"wb");assert(f);fputc(value,f);fclose(f);
            }
            configure();bool enabled=value=='1';
            assert(ldc_fold==enabled && forward_temps==enabled && readback_cached==enabled && gfx_async==enabled);
            assert(wtrack::marker==int(enabled));
            sync_submit_enabled=true;configure();assert(!gfx_async);sync_submit_enabled=false;
        }
        for(const char *name:{"/gfx-ldc-fold","/gfx-forward-temps","/gfx-readback-cached","/gfx-async-submit","/gfx-wtrack"})remove((base+name).c_str());
        setenv("DM_GFX_LDC_FOLD","0",1);setenv("DM_GFX_FORWARD_TEMPS","0",1);setenv("DM_GFX_READBACK_CACHED","0",1);
        configure();assert(!ldc_fold && !forward_temps && !readback_cached);
        unsetenv("DM_GFX_LDC_FOLD");unsetenv("DM_GFX_FORWARD_TEMPS");unsetenv("DM_GFX_READBACK_CACHED");
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
