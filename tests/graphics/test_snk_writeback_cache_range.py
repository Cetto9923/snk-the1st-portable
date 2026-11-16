import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def block(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class WritebackCacheRangeTests(unittest.TestCase):
    def test_actual_buffer_invalidation_copy_extent_atoms_and_original_metadata(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        buffer = block(source, 'struct Buffer {') + ';'
        apply = block(source, 'void apply_writeback(PendingWriteback &write){')
        program = r'''
#include <algorithm>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>
using VkBuffer=uint64_t;
using VkDeviceMemory=uint64_t;
using VkDeviceSize=uint64_t;
constexpr uint64_t VK_WHOLE_SIZE=UINT64_MAX;
constexpr int VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE=6;
struct VkMappedMemoryRange {
    int sType;void *pNext=nullptr;VkDeviceMemory memory=0;
    VkDeviceSize offset=0,size=0;
};
static struct {struct {VkDeviceSize nonCoherentAtomSize;} limits;} properties;
static struct {uint64_t device=19;} cfg;
static unsigned cache_calls,flush_calls;
static VkMappedMemoryRange captured{};
static int vkInvalidateMappedMemoryRanges(uint64_t device,unsigned count,const VkMappedMemoryRange *range) {
    assert(device==cfg.device && count==1 && range->sType==VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE);
    captured=*range;++cache_calls;return 0;
}
static int vkFlushMappedMemoryRanges(uint64_t,unsigned,const VkMappedMemoryRange *) {
    ++flush_calls;return 0;
}
static void need(bool value,const char *) {assert(value);}
#define VK(call) assert((call)==0)
''' + buffer + r'''
struct Image {};
struct PendingWriteback {uint64_t addr,bytes,modified_bytes;Buffer buffer;};
static bool image_alias;
static uint64_t writeback_bytes,cpu_dirty_address,cpu_dirty_bytes;
template<class F>static void for_images_overlapping(uint64_t,uint64_t,F callback) {
    if(image_alias){Image image;callback(image);}
}
static void invalidate_cpu_range(uint64_t address,uint64_t bytes) {
    cpu_dirty_address=address;cpu_dirty_bytes=bytes;
}
''' + apply + r'''
static void run_case(size_t total,uint64_t modified,bool alias,bool coherent,
                     uint64_t atom,uint64_t offset,uint64_t allocation) {
    std::vector<uint8_t> gpu(total+16,0x31),cpu(total+16,0x79);
    const size_t copied=modified && modified<=total && !alias?size_t(modified):total;
    Buffer original;
    original.buffer=7;original.memory=11;original.offset=offset;original.size=total;
    original.mapped=gpu.data();original.coherent=coherent;original.allocation_size=allocation;
    PendingWriteback write{uint64_t(cpu.data()),total,modified,original};
    properties.limits.nonCoherentAtomSize=atom;image_alias=alias;
    cache_calls=flush_calls=0;writeback_bytes=cpu_dirty_address=cpu_dirty_bytes=0;
    apply_writeback(write);
    assert(writeback_bytes==copied && cpu_dirty_bytes==copied && cpu_dirty_address==write.addr);
    assert(flush_calls==0 && cache_calls==unsigned(!coherent));
    if(!coherent) {
        assert(captured.memory==original.memory);
        if(allocation) {
            const uint64_t begin=offset-offset%atom;
            const uint64_t end=std::min(allocation,((offset+copied+atom-1)/atom)*atom);
            assert(captured.offset==begin && captured.size==end-begin);
            assert(captured.offset<=offset && captured.offset+captured.size>=offset+copied);
            assert(captured.offset+captured.size<=allocation);
        } else assert(captured.offset==0 && captured.size==VK_WHOLE_SIZE);
    }
    assert(write.bytes==total && write.modified_bytes==modified);
    assert(write.buffer.buffer==original.buffer && write.buffer.memory==original.memory);
    assert(write.buffer.offset==original.offset && write.buffer.size==original.size);
    assert(write.buffer.mapped==original.mapped && write.buffer.coherent==original.coherent);
    assert(write.buffer.allocation_size==original.allocation_size);
    for(size_t i=0;i<cpu.size();i++)assert(cpu[i]==(i<copied?0x31:0x79));
}
int main() {
    // The audited instance output keeps a much larger registered parent view.
    run_case(12800000,552960,false,false,64,1048576,33554432);
    run_case(192,31,false,false,64,13,1000);
    run_case(192,0,false,false,64,13,1000);
    run_case(192,193,false,false,64,13,1000);
    run_case(192,31,true,false,64,13,1000);
    run_case(192,31,false,true,64,13,1000);
    run_case(192,31,false,false,64,13,0);
    run_case(200,193,false,false,64,800,1000);
    run_case(200,3,false,false,64,800,1000);
    for(uint64_t atom:{64,128,256})
        for(uint64_t offset:{0,1,63,64,255})
            for(uint64_t bytes:{1,31,64,65,127,192})
                run_case(192,bytes,false,false,atom,offset,1024);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'range.cpp').write_text(program)
            executable = path / 'range'
            built = subprocess.run([
                'clang++', '-std=c++17', '-fsanitize=address,undefined',
                str(path / 'range.cpp'), '-o', str(executable),
            ], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
