import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def marker_block(source, marker):
    location = source.index('"/' + marker + '"')
    begin = source.rfind('{FILE *', 0, location)
    end = begin + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[begin:end]


class Rg477mDefaultsTests(unittest.TestCase):
    def test_actual_defaults_vendor_gate_and_explicit_marker_precedence(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        begin = source.index('    const char *rg_profile_env=')
        end = source.index('\n', source.index('const bool rg_profile=', begin))
        profile = source[begin:end]
        location = source.index('"/gfx-defer-events"')
        begin = source.rfind('FILE *m=fopen', 0, location)
        end = source.index('{FILE *eg=', begin)
        blocks = source[begin:end] + '\n'
        for marker in ['gfx-vcache', 'gfx-tex-dirty', 'gfx-storage-cache',
                       'gfx-slot-count', 'gfx-perf-sample']:
            blocks += marker_block(source, marker) + '\n'
        program = r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <string>
static struct { unsigned vendorID; } properties;
namespace vcache {static bool enabled;}
namespace storage_cache {static int mode;}
static int defer_events;static bool tex_dirty,perf_frame_timed;
static unsigned slot_count,perf_sample;static uint64_t perf_timed_frames;
static constexpr unsigned kMaxSlots=16;
static constexpr bool nvn_dirty_since=false,nvn_dirty_tracked=false,nvn_dirty_protect=false,nvn_dirty_now=false;
static void xbg_logf(const char*,...){}
static void configure(const std::string &dir,const char *profile,unsigned vendor){
    properties.vendorID=vendor;setenv("FFRS_PROFILE_RG477M",profile,1);
    size_t cut=dir.find_last_of('/');
''' + profile + '\n' + blocks + r'''
}
static void original(){
    assert(defer_events==0 && !vcache::enabled && !tex_dirty);
    assert(storage_cache::mode==0 && slot_count==16 && perf_sample==32);
}
int main(int argc,char **argv){
    assert(argc==2);std::string dir=std::string(argv[1])+"/shaders";
    configure(dir,"1",0x13b5);
    assert(defer_events==2 && vcache::enabled && tex_dirty);
    assert(storage_cache::mode==1 && slot_count==4 && perf_sample==0 && !perf_frame_timed);
    configure(dir,"0",0x13b5);original();
    configure(dir,"1",0x5143);original();
    configure(dir,"",0x13b5);original();
    configure(dir,"10",0x13b5);original();
    const char *names[]={"gfx-defer-events","gfx-vcache","gfx-tex-dirty", "gfx-storage-cache","gfx-slot-count","gfx-perf-sample"};
    const char *values[]={"0","0","0","2","8","7"};
    for(unsigned i=0;i<6;i++){
        std::string path=std::string(argv[1])+"/"+names[i];FILE *file=fopen(path.c_str(),"wb");
        assert(file);fputs(values[i],file);fclose(file);
    }
    setenv("DM_GFX_VCACHE","1",1);setenv("DM_GFX_TEX_DIRTY","1",1);
    setenv("DM_GFX_DEFER_EVENTS","1",1);setenv("DM_GFX_PERF_SAMPLE","1",1);
    configure(dir,"1",0x13b5);
    assert(defer_events==0 && !vcache::enabled && !tex_dirty);
    assert(storage_cache::mode==2 && slot_count==8 && perf_sample==7 && perf_frame_timed);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'defaults.cpp').write_text(program)
            executable = path / 'defaults'
            built = subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                                    str(path / 'defaults.cpp'), '-o', str(executable)],
                                   capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            env = os.environ.copy()
            for key in ['DM_GFX_VCACHE', 'DM_GFX_TEX_DIRTY', 'DM_GFX_DEFER_EVENTS', 'DM_GFX_PERF_SAMPLE']:
                env.pop(key, None)
            run = subprocess.run([str(executable), str(path)], env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
