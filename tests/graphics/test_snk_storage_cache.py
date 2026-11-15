import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'src/graphics/nvn_vulkan/engine'


class StorageCacheTests(unittest.TestCase):
    def test_real_cache_page_updates_and_gpu_reader_lifetime(self):
        source = (ENGINE / 'xbg_game.cpp').read_text()
        start = source.index('namespace storage_cache {\nint mode=0;')
        end = source.index('Buffer snapshot_slow(', start)
        cache = source[start:end]
        program = r'''
#include "xbg_writeback_policy.h"
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <memory>
#include <vector>
#include <unistd.h>
struct Buffer {void *mapped=nullptr;size_t size=0;void flush(){}};
struct OwnedIndirectBuffer {
    std::vector<uint8_t> memory;Buffer view;
    explicit OwnedIndirectBuffer(size_t bytes):memory(bytes),view{memory.data(),bytes}{}
};
struct Slot {struct {std::vector<std::shared_ptr<void>> objects;} retire;};
Slot reader;
uint64_t memo_epoch=1;
Slot &recording_slot(){return reader;}
namespace evguard {bool enabled=false;struct EngineRead {EngineRead(const void*,size_t){}};}
namespace vcache {bool overlap=false;bool overlaps_wtrack(uint64_t,size_t){return overlap;}}
void xbg_logf(const char*,...){}
size_t page_size=4096;
uint64_t tracked_address=0,tracked_bytes=0,generation=1;
bool tracking=true,fail_protect=false,write_during_protect=false;
std::vector<uint64_t> page_generation;
uint64_t page_base(){return tracked_address-tracked_address%page_size;}
long task_sysconf(int){return long(page_size);}
bool nvn_dirty_tracked(const void *address,size_t bytes){
    return tracking && xbg_wb_contains(tracked_address,tracked_bytes,uint64_t(address),bytes);
}
uint64_t nvn_dirty_now(){return generation;}
int nvn_dirty_since(const void *address,size_t bytes,uint64_t stamp){
    if(!nvn_dirty_tracked(address,bytes))return 1;
    if(bytes<tracked_bytes){
        const uint64_t value=uint64_t(address);
        assert(value==tracked_address || value%page_size==0);
        assert(bytes==std::min<uint64_t>(page_size-value%page_size,tracked_address+tracked_bytes-value));
    }
    const auto begin=(uint64_t(address)-page_base())/page_size;
    const auto end=(uint64_t(address)+bytes-1-page_base())/page_size;
    for(size_t i=begin;i<=end;++i)if(page_generation[i]>stamp)return 1;
    return 0;
}
void dirty(size_t offset,uint8_t value){
    reinterpret_cast<uint8_t*>(tracked_address)[offset]=value;
    page_generation[(tracked_address+offset-page_base())/page_size]=++generation;
}
void nvn_dirty_protect(const void*,size_t){
    if(fail_protect)tracking=false;
    if(write_during_protect){write_during_protect=false;dirty(17,0xa5);}
}
#define sysconf task_sysconf
''' + cache + r'''
#undef sysconf
void reset(){
    reader.retire.objects.clear();storage_cache::release();storage_cache::mode=1;
    storage_cache::copied_bytes=storage_cache::hits=storage_cache::hit_bytes=0;
    storage_cache::mismatches=storage_cache::verified=storage_cache::fallbacks=0;
    tracking=true;fail_protect=write_during_protect=false;
    evguard::enabled=false;vcache::overlap=false;
}
void register_source(std::vector<uint8_t> &backing,size_t bytes){
    tracked_address=uint64_t(backing.data()+137);tracked_bytes=bytes;
    page_generation.assign(size_t((tracked_address-page_base()+bytes+page_size-1)/page_size),++generation);
}
void test_pages(size_t native_page){
    reset();page_size=native_page;
    const size_t bytes=(1u<<20)+153;
    std::vector<uint8_t> backing(bytes+page_size*2,0x31);register_source(backing,bytes);
    Buffer a,b,updated;
    assert(storage_cache::snapshot(tracked_address,bytes,a));
    assert(std::memcmp(a.mapped,reinterpret_cast<void*>(tracked_address),bytes)==0);
    auto weak=std::weak_ptr<OwnedIndirectBuffer>(storage_cache::entries.begin()->second.versions[0].owner);
    dirty(0,0x42);dirty(bytes-1,0x51);
    assert(storage_cache::snapshot(tracked_address,bytes,b));assert(a.mapped!=b.mapped);
    assert(static_cast<uint8_t*>(a.mapped)[0]==0x31);
    dirty(page_size+7,0x63);
    assert(!storage_cache::snapshot(tracked_address,bytes,updated));
    assert(static_cast<uint8_t*>(a.mapped)[0]==0x31 && static_cast<uint8_t*>(b.mapped)[page_size+7]==0x31);
    reader.retire.objects.clear();
    auto copied=storage_cache::copied_bytes;
    assert(storage_cache::snapshot(tracked_address,bytes,updated));
    assert(std::memcmp(updated.mapped,reinterpret_cast<void*>(tracked_address),bytes)==0);
    assert(storage_cache::copied_bytes-copied<=native_page*3);
    copied=storage_cache::copied_bytes;
    Buffer same;assert(storage_cache::snapshot(tracked_address,bytes,same));
    assert(same.mapped==updated.mapped && storage_cache::copied_bytes==copied);
    assert(storage_cache::allocated_bytes==2*bytes);
    const auto old_epoch=memo_epoch;
    storage_cache::drop_pool(tracked_address,bytes);
    assert(memo_epoch>old_epoch);
    assert(storage_cache::live()==0 && storage_cache::allocated_bytes==0 && !weak.expired());
    reader.retire.objects.clear();assert(weak.expired());
    // Protection fails conservatively before publishing an invalid version.
    reset();register_source(backing,bytes);fail_protect=true;
    assert(!storage_cache::snapshot(tracked_address,bytes,a));
    reset();register_source(backing,bytes);tracking=false;
    assert(!storage_cache::snapshot(tracked_address,bytes,a) && storage_cache::live()==0);
    tracking=true;vcache::overlap=true;assert(!storage_cache::snapshot(tracked_address,bytes,a));vcache::overlap=false;
    evguard::enabled=true;assert(!storage_cache::snapshot(tracked_address,bytes,a));evguard::enabled=false;
    assert(!storage_cache::snapshot(tracked_address,(1u<<20)-1,a));
    assert(!storage_cache::snapshot(tracked_address,(32u<<20)+1,a));
    // A write at protection is newer than the copy stamp, so the next read
    // obtains a separate version even when its bytes happen to match already.
    reset();register_source(backing,bytes);write_during_protect=true;
    assert(storage_cache::snapshot(tracked_address,bytes,a));
    assert(storage_cache::snapshot(tracked_address,bytes,b));assert(a.mapped!=b.mapped);
    // Validation rejects an unreported write without editing a GPU reader.
    reset();register_source(backing,bytes);storage_cache::mode=2;
    assert(storage_cache::snapshot(tracked_address,bytes,a));
    static_cast<uint8_t*>(reinterpret_cast<void*>(tracked_address))[11]=0xee;
    const auto previous=static_cast<uint8_t*>(a.mapped)[11];
    assert(!storage_cache::snapshot(tracked_address,bytes,b));
    assert(storage_cache::mismatches==1 && static_cast<uint8_t*>(a.mapped)[11]==previous);
    assert(!storage_cache::snapshot(tracked_address,bytes,b));
}
void test_budget(){
    reset();page_size=4096;
    const size_t bytes=32u<<20;
    std::vector<std::vector<uint8_t>> backings;
    for(unsigned i=0;i<5;++i){
        backings.emplace_back(bytes+page_size,0x41);register_source(backings.back(),bytes);Buffer output;
        bool accepted=storage_cache::snapshot(tracked_address,bytes,output);
        assert(accepted==(i<4));assert(storage_cache::allocated_bytes<=storage_cache::budget);
    }
    assert(storage_cache::allocated_bytes==storage_cache::budget);
    reset();
    backings.clear();
    for(unsigned i=0;i<9;++i){
        backings.emplace_back((1u<<20)+page_size,0x41);register_source(backings.back(),1u<<20);Buffer output;
        assert(storage_cache::snapshot(tracked_address,1u<<20,output)==(i<8));
    }
    assert(storage_cache::live()==8);reset();
}
int main(){test_pages(4096);test_pages(16384);test_budget();}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'storage_cache.cpp'
            path.write_text(program)
            executable = path.with_suffix('')
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', '-I', str(ENGINE),
                            str(path), '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_normal_snapshot_pool_and_shutdown_entry_points(self):
        source = (ENGINE / 'xbg_game.cpp').read_text()
        start = source.index('Buffer snapshot_slow(uint64_t address,size_t bytes,VkDeviceSize align){')
        end = source.index('struct Commands {', start)
        snapshot = source[start:end]
        self.assertLess(snapshot.index('pending_view('), snapshot.index('storage_cache::snapshot('))
        self.assertLess(snapshot.index('cpu_access(address,bytes,1)'), snapshot.index('storage_cache::snapshot('))
        self.assertIn('storage_cache::drop_pool(uintptr_t(p),pit->second)', source)
        self.assertIn('vcache::release();storage_cache::release();wtrack::release()', source)
        self.assertIn('xbg_dirty_enable(properties.vendorID==0x13b5 && (vcache::enabled || storage_cache::mode))', source)


if __name__ == '__main__':
    unittest.main()
