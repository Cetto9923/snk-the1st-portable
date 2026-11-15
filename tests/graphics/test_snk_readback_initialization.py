import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class ReadbackInitializationTests(unittest.TestCase):
    def test_host_initialization_and_gpu_overwrite(self):
        engine = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = engine.index('Buffer readback_buffer(size_t n,')
        brace = engine.index('{', start)
        end, depth = brace + 1, 1
        while depth:
            depth += (engine[end] == '{') - (engine[end] == '}')
            end += 1
        function = engine[start:end]
        source_text = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
using VkDeviceSize = size_t;
uint8_t mapped[32];
unsigned flushes=0,staging_copies=0;
uint64_t xview_guarded=0,xview_guarded_bytes=0;
void need(bool condition,const char *) { assert(condition); }
struct Buffer {
    unsigned buffer=1;size_t offset=0;void *mapped=::mapped;
    void flush() { ++flushes; }
};
struct Arena { Buffer alloc(size_t n) { assert(n<=sizeof(mapped));return {}; } };
struct Guard { unsigned buffer;size_t begin,end; };
struct Copy { unsigned source,destination;size_t source_offset,dest_offset,bytes; };
struct Slot { Arena readback;std::vector<Guard> guard;std::vector<Copy> pro_ops; } slot;
Slot &recording_slot() { return slot; }
Buffer stream_buffer(size_t,const void *,size_t,bool) { ++staging_copies;return {}; }
''' + function + r'''
void reset() {
    std::fill(std::begin(mapped),std::end(mapped),0x5a);
    slot.guard.clear();slot.pro_ops.clear();flushes=staging_copies=0;
    xview_guarded=xview_guarded_bytes=0;
}
int main() {
    reset();readback_buffer(16);
    for(size_t i=0;i<32;i++)assert(mapped[i]==(i<16?0:0x5a));
    assert(flushes==1);
    reset();slot.guard.push_back({1,0,16});
    readback_buffer(16,nullptr,0,false);
    for(auto value:mapped)assert(value==0x5a);
    assert(flushes==0 && staging_copies==0 && slot.pro_ops.empty());
    const uint8_t payload[4]={1,2,3,4};
    reset();readback_buffer(16,payload,sizeof(payload));
    assert(!std::memcmp(mapped,payload,sizeof(payload)));
    for(size_t i=4;i<16;i++)assert(mapped[i]==0);
    reset();slot.guard.push_back({1,0,16});
    readback_buffer(16,payload,sizeof(payload));
    for(auto value:mapped)assert(value==0x5a);
    assert(staging_copies==1 && slot.pro_ops.size()==1 && xview_guarded==1);
    assert(slot.pro_ops[0].bytes==16);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'readback.cpp'
            source.write_text(source_text)
            executable = pathlib.Path(directory) / 'readback'
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', str(source), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
