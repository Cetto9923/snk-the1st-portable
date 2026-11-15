import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class VertexRangeTests(unittest.TestCase):
    def test_used_attributes_indices_instances_and_gpu_fallback(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('    uint64_t maximum_vertex=0;')
        end = source.index('    if(indexed){need(', start)
        implementation = source[start:end]
        program = r'''
#include "xbg_vertex.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <vector>

enum {VK_VERTEX_INPUT_RATE_VERTEX, VK_VERTEX_INPUT_RATE_INSTANCE};
struct Binding {uint32_t binding, stride, inputRate;};
struct Range {uint64_t address, size;};
struct Buffer {uint64_t address, size;};
struct Draw {int itype, base_vertex, instances, base_instance;uint64_t ibuf;};
static struct {Range vb[16];} state;
static struct {uint64_t vertex_prefix_bindings,vertex_prefix_saved_bytes;} perf;
static std::vector<Binding> bindings;
static uint32_t attribute_end[16],unknown_attribute_size;
static bool vertex_prefix_enabled=true,clean=true;
static const void *registered;
static size_t available;
static int cpu_reads,snap_site;
static void *nvn_memory_pool_resolve_address(uint64_t address,size_t *bytes) {
    *bytes=available;
    return address==uint64_t(registered)?const_cast<void*>(registered):nullptr;
}
static bool indirect_cpu_clean(uint64_t,size_t) {return clean;}
namespace evguard {
struct EngineRead {
    EngineRead(const void *source,size_t bytes) {
        assert(clean && source==registered && bytes<=available);
        ++cpu_reads;
    }
};
}
static void need(bool value,const char *) {assert(value);}
static Buffer snapshot(uint64_t address,uint64_t bytes) {return {address,bytes};}
static Buffer stream_buffer(size_t bytes,const void *,size_t) {return {0,bytes};}
static std::vector<Buffer> prepare(const Draw *indexed,const void *gpu_args,
    uint32_t instances,uint32_t first_instance,int first,int count) {
    const int zero_binding=-1;
    struct Descriptors {
        std::deque<Buffer> buffers;
        Buffer *keep(Buffer value) {buffers.push_back(value);return &buffers.back();}
    } d;
    std::vector<std::pair<uint32_t,Buffer*>> vertex_buffers;
''' + implementation + r'''
    std::vector<Buffer> result;
    for(const auto &binding:vertex_buffers)result.push_back(*binding.second);
    return result;
}
int main() {
    uint64_t maximum=99;
    const uint8_t byte_indices[]={1,7,3};
    const uint16_t short_indices[]={1,4,2};
    const uint32_t wide_indices[]={2,0xffffffffu,3};
    assert(!xbg_vertex_max_index(byte_indices,sizeof(byte_indices),0,2,&maximum) && maximum==9);
    assert(!xbg_vertex_max_index(short_indices,sizeof(short_indices),1,-2,&maximum) && maximum==2);
    assert(!xbg_vertex_max_index(wide_indices,sizeof(wide_indices),2,7,&maximum) && maximum==uint64_t(UINT32_MAX)+7);
    assert(xbg_vertex_max_index(nullptr,2,1,0,&maximum));
    assert(xbg_vertex_max_index(short_indices,3,1,0,&maximum));
    assert(xbg_vertex_max_index(short_indices,sizeof(short_indices),3,0,&maximum));
    assert(xbg_vertex_max_index(byte_indices,sizeof(byte_indices),0,-100,&maximum));
    assert(xbg_vertex_prefix_bytes(1024,32,12,4)==140);
    assert(xbg_vertex_prefix_bytes(1024,0,12,UINT64_MAX)==12);
    assert(xbg_vertex_prefix_bytes(1024,4,48,3)==60);
    assert(xbg_vertex_prefix_bytes(10,32,12,4)==10);
    assert(xbg_vertex_prefix_bytes(1024,UINT32_MAX,12,UINT64_MAX)==1024);
    assert(xbg_vertex_prefix_bytes(1024,32,0,4)==1024);

    state.vb[0]={0x1000,1024};state.vb[1]={0x2000,2048};
    bindings={{0,32,VK_VERTEX_INPUT_RATE_VERTEX},{1,64,VK_VERTEX_INPUT_RATE_INSTANCE}};
    attribute_end[0]=12;attribute_end[1]=16;
    auto r=prepare(nullptr,nullptr,2,3,2,3);
    assert(r[0].size==140 && r[1].size==272);
    registered=short_indices;available=sizeof(short_indices);
    Draw draw{1,3,3,2,uint64_t(short_indices)};
    r=prepare(&draw,nullptr,1,0,0,3);
    assert(r[0].size==236 && r[1].size==272 && cpu_reads==1);
    clean=false;
    r=prepare(&draw,nullptr,1,0,0,3);
    assert(r[0].size==1024 && r[1].size==272 && cpu_reads==1);
    clean=true;
    r=prepare(&draw,&draw,1,0,0,3);
    assert(r[0].size==1024 && r[1].size==2048 && cpu_reads==1);
    vertex_prefix_enabled=false;
    r=prepare(&draw,nullptr,1,0,0,3);
    assert(r[0].size==1024 && r[1].size==2048 && cpu_reads==1);
    vertex_prefix_enabled=true;
    unknown_attribute_size=1;
    r=prepare(&draw,nullptr,1,0,0,3);
    assert(r[0].size==1024 && r[1].size==272);
    unknown_attribute_size=0;
    available=1;
    r=prepare(&draw,nullptr,1,0,0,3);
    assert(r[0].size==1024 && r[1].size==272);
    available=sizeof(short_indices);
    int reads_before=cpu_reads;
    bindings.clear();
    r=prepare(&draw,nullptr,1,0,0,3);
    assert(r.empty() && cpu_reads==reads_before);

    // Every originally bound attribute fetch stays within the retained prefix.
    uint32_t seed=13;
    for(unsigned i=0;i<10000;++i) {
        seed=seed*1664525u+1013904223u;
        uint32_t stride=seed%128;
        seed=seed*1664525u+1013904223u;
        uint32_t end=1+seed%256;
        uint64_t last=i%100;
        uint64_t full=last*stride+end+4096;
        uint64_t prefix=xbg_vertex_prefix_bytes(full,stride,end,last);
        assert(prefix<=full && prefix>=last*stride+end);
        for(uint64_t vertex=0;vertex<=last;++vertex)
            assert(vertex*stride+end<=prefix);
    }
    assert(perf.vertex_prefix_bindings && perf.vertex_prefix_saved_bytes);
    puts("vertex_range_contract fetch_cases=10000 gpu_pending_fallback=1 errors=0");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'vertex_ranges.cpp').write_text(program)
            cflags = ['-fsanitize=address,undefined', '-I',
                      str(ROOT / 'src/graphics/nvn_vulkan/engine')]
            subprocess.run([
                shutil.which('clang') or 'cc', '-std=c11', *cflags, '-c',
                str(ROOT / 'src/graphics/nvn_vulkan/engine/xbg_vertex.c'),
                '-o', str(path / 'vertex.o'),
            ], check=True, capture_output=True)
            executable = path / 'vertex_ranges'
            subprocess.run([
                shutil.which('clang++') or 'c++', '-std=c++17', *cflags,
                str(path / 'vertex_ranges.cpp'), str(path / 'vertex.o'),
                '-o', str(executable),
            ], check=True, capture_output=True)
            result = subprocess.run([str(executable)], check=True,
                                    capture_output=True, text=True)
            self.assertIn('errors=0', result.stdout)


if __name__ == '__main__':
    unittest.main()
