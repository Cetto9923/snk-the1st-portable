import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class ProbePollTests(unittest.TestCase):
    def test_reads_marker_once_per_frame_and_observes_next_frame_changes(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_probe.inc').read_text()
        start = source.index('int probe_request(){')
        end = source.index('// Short, opt-in CPU-uniform trace.', start)
        program = r'''
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <string>
struct { std::atomic<uint64_t> presents{0}; } stats;
struct { int request='0';uint64_t request_frame=UINT64_MAX;std::string base; } probe;
static unsigned opens;
FILE *counted_open(const char *path,const char *mode) {++opens;return fopen(path,mode);}
#define fopen counted_open
''' + source[start:end] + r'''
#undef fopen
int main(int argc,char **argv) {
    assert(argc==2);probe.base=argv[1];std::string marker=probe.base+"/gfx-codex-probe";
    for(unsigned i=0;i<1000;i++)assert(probe_request()=='0');assert(opens==1);
    FILE *f=fopen(marker.c_str(),"wb");assert(f);fputc('3',f);fclose(f);
    assert(probe_request()=='0' && opens==1);
    ++stats.presents;
    for(unsigned i=0;i<1000;i++)assert(probe_request()=='3');assert(opens==2);
    remove(marker.c_str());assert(probe_request()=='3' && opens==2);
    ++stats.presents;assert(probe_request()=='0' && opens==3);
    f=fopen(marker.c_str(),"wb");assert(f);fputc('1',f);fclose(f);
    probe.request_frame=UINT64_MAX;assert(probe_request()=='1' && opens==4);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'poll.cpp').write_text(program)
            executable = path / 'poll'
            subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                            str(path / 'poll.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable), directory], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
