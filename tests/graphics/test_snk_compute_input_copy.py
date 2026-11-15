import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def extract(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class ComputeInputCopyTests(unittest.TestCase):
    def test_actual_residency_copy_scope_bounds_and_shared_ownership(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        functions = '\n'.join(extract(source, signature) for signature in (
            'bool pin_pending_input(uint64_t address,uint64_t bytes){',
            'bool current_pending_range(uint64_t address,uint64_t bytes,VkDeviceSize align){',
            'bool indirect_dispatch_inputs_resident(bool pin){',
            'bool pin_indexed_input(const IndexedInputFailure &input){',
        ))
        start = source.index('        const bool can_pin=')
        end = source.index('gpu_indirect=pending_view(indirect_address,12,4,indirect);', start)
        selection = source[start:end + len('gpu_indirect=pending_view(indirect_address,12,4,indirect);')]
        program = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <set>
#include <vector>
using VkDeviceSize=uint64_t;
enum {VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER=1,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER=2,
      XBG_SOURCE_UNIFORM=1,XBG_SOURCE_STORAGE=2,XBG_SOURCE_SUPPORT=3,
      XBG_SOURCE_C1=4,XBG_SOURCE_DRIVER0=5,XBG_SOURCE_DRIVER2=6,SITE_OTHER=0};
struct Buffer { uint64_t buffer=0,offset=0,size=0; };
struct Owner { Buffer view; };
static unsigned copies;
static Buffer copied_source;
static std::vector<size_t> copied_sizes;
struct OwnedInputCopy {
    std::shared_ptr<Owner> owned=std::make_shared<Owner>();
    OwnedInputCopy(const Buffer &source,size_t bytes){++copies;copied_sizes.push_back(bytes);copied_source=source;owned->view={99,0,bytes};}
};
struct Retire { std::vector<std::shared_ptr<void>> objects; };
struct Slot { bool recording=false,pending=false;std::vector<std::shared_ptr<OwnedInputCopy>> copy_readers;Retire retire; };
static Slot slots[4];static unsigned slot_index=1;
struct Pending { uint64_t addr,bytes;Buffer buffer;const void *slot;std::shared_ptr<void> indirect,owner;uint64_t trace_id=0; };
static std::vector<Pending> pending_writebacks;
struct NVNcounterData { uint64_t value,timestamp; };
struct Report {uint64_t addr;};static std::vector<Report> pending_reports;
struct Binding { unsigned binding,type,source,slot,count=1,bytes=0; };
struct Shader { std::vector<Binding> bindings;std::set<unsigned> storage_writes; };
struct Range {uint64_t address=0,size=0;};
static struct {Shader *shader[6]={};Range sb[6][16],ub[6][16];} state;
static struct {bool active=false,probe=false;} capture;
static void *provenance_file;static bool pass_prof_enabled;static int g_ui_moff;
static struct {unsigned vendorID=0x13b5;struct {uint64_t minUniformBufferOffsetAlignment=256,minStorageBufferOffsetAlignment=256;}limits;}properties;
static unsigned nvn_stage[]={0,1,2,3,4,5};
static bool owned_input_copy_enabled=true;
static struct {unsigned submits=0;}perf;static unsigned submit_by[1];
static bool xbg_wb_overlaps(uint64_t a,uint64_t n,uint64_t b,uint64_t m){return a<b+m && b<a+n;}
static uint64_t uniform_range(uint64_t bytes){return (bytes+255)&~uint64_t(255);}
static uint64_t pool_address,pool_bytes;
static void *resolve(uint64_t address,size_t *available){
    if(address>=0x1000 && address<0x2000){*available=0x2000-address;return reinterpret_cast<void *>(address);}
    *available=pool_bytes;return address==pool_address?reinterpret_cast<void *>(address):nullptr;
}
static void *(*nvn_memory_pool_resolve_address)(uint64_t,size_t *)=resolve;
static void snapshot_invalidate(uint64_t,uint64_t){}
static uint64_t indirect_trace_record(const char*,const char*,uint64_t,uint64_t,const Buffer&,uint64_t,uint64_t){return 17;}
template<class... T>static void xbg_logf(const char*,T...){}
struct IndexedInputFailure {const char *why;unsigned stage,binding;uint64_t address,bytes;};
static unsigned begins,resolves;static bool retire_args_on_begin;
static Slot &recording_slot(){
    auto &slot=slots[slot_index];
    if(!slot.recording){
        ++begins;slot.recording=true;
        if(retire_args_on_begin){
            pending_writebacks.erase(std::remove_if(pending_writebacks.begin(),pending_writebacks.end(),
                [](const Pending &w){return w.addr==0x1100;}),pending_writebacks.end());
            pending_writebacks.shrink_to_fit();
        }
    }
    return slot;
}
static void resolve_pending(){++resolves;pending_writebacks.clear();pending_reports.clear();}
bool indirect_dispatch_inputs_resident(bool pin=false);
''' + functions + r'''
static bool picked;
static bool pending_view(uint64_t address,uint64_t bytes,uint64_t align,Buffer &out){
    assert(current_pending_range(address,bytes,align));out={7,256,12};return true;
}
static void select_dispatch(uint64_t indirect_address=0x1100){
    Buffer indirect;bool gpu_indirect=false;
''' + selection + r'''
    picked=gpu_indirect;
}
static Shader shader;
static void reset(bool written=false){
    pending_writebacks.clear();pending_reports.clear();for(auto &s:slots)s=Slot{};
    state={};capture={};provenance_file=nullptr;pass_prof_enabled=false;g_ui_moff=0;
    properties.vendorID=0x13b5;owned_input_copy_enabled=true;nvn_memory_pool_resolve_address=resolve;
    copies=0;copied_sizes.clear();begins=0;resolves=0;retire_args_on_begin=false;
    perf.submits=0;submit_by[0]=0;slot_index=1;slots[1].recording=true;slots[0].pending=true;
    shader.bindings={{11,2,2,0},{17,2,2,1},{23,2,2,2}};shader.storage_writes.clear();if(written)shader.storage_writes.insert(17);
    state.shader[5]=&shader;state.shader[0]=&shader;
    state.sb[5][0]={0x1000,16};state.sb[5][1]={0x1000000,262160};state.sb[5][2]={0x2000000,256};
    pool_address=0x1000000;pool_bytes=262160;
    pending_writebacks.push_back({0x1000,16,{1,0,16},&slots[1],{},{}});
    pending_writebacks.push_back({0x1100,3040,{2,256,3040},&slots[1],{},{}});
    pending_writebacks.push_back({pool_address,pool_bytes,{3,11796992,pool_bytes},&slots[0],{},{}});
}
static void reset_old_args(){
    reset();slots[1].recording=false;
    pending_writebacks[0].slot=&slots[0];pending_writebacks[1].slot=&slots[0];
}
int main(){
    for(bool written:{false,true}){
        reset(written);assert(current_pending_range(0x1100,12,4));
        assert(!indirect_dispatch_inputs_resident() && copies==0);
        assert(indirect_dispatch_inputs_resident(true) && copies==1);
        assert(copied_source.buffer==3 && copied_source.offset==11796992);
        assert(current_pending_range(pool_address,pool_bytes,256));
        assert(indirect_dispatch_inputs_resident() && copies==1);
        assert(perf.submits==1 && submit_by[0]==1);
        assert(slots[0].copy_readers.size()==1 && slots[1].retire.objects.size()==1);
        std::weak_ptr<OwnedInputCopy> lease=slots[0].copy_readers[0];
        slots[0].copy_readers.clear();pending_writebacks.clear();assert(!lease.expired());
        slots[1].retire.objects.clear();assert(lease.expired());
    }
    reset();properties.vendorID=0x5143;select_dispatch();assert(!picked && copies==0);
    reset();select_dispatch();assert(picked && copies==1);
    reset();properties.vendorID=0x5143;pending_writebacks.back().slot=&slots[1];select_dispatch();assert(picked && copies==0);
    reset();owned_input_copy_enabled=false;select_dispatch();assert(!picked && copies==0);
    for(unsigned bad=0;bad<12;++bad){
        reset();
        switch(bad){
        case 0:slots[1].recording=false;break;
        case 1:slots[0].pending=false;break;
        case 2:slots[0].recording=true;break;
        case 3:pool_bytes=262159;break;
        case 4:nvn_memory_pool_resolve_address=nullptr;break;
        case 5:pending_writebacks.back().buffer.offset+=1;break;
        case 6:pending_writebacks.back().bytes-=4;break;
        case 7:pending_reports.push_back({pool_address});break;
        case 8:pool_address+=4;break;
        case 9:pending_writebacks.back().slot=&slots[1];break;
        case 10:owned_input_copy_enabled=false;break;
        case 11:pending_writebacks.back().addr+=4;break;
        }
        assert(!pin_pending_input(0x1000000,262160) && copies==0);
    }
    reset();assert(!pin_pending_input(pool_address,0));assert(!pin_pending_input(pool_address,1048580));
    assert(!pin_pending_input(pool_address,15));assert(!pin_pending_input(UINT64_MAX-3,16));
    for(unsigned bad=0;bad<5;++bad){
        reset();if(bad==0)capture.active=true;if(bad==1)capture.probe=true;
        if(bad==2)provenance_file=&shader;if(bad==3)pass_prof_enabled=true;if(bad==4)g_ui_moff=1;
        assert(!indirect_dispatch_inputs_resident(true) && copies==0);
    }
    reset();shader.bindings.push_back({30,3,7,0});assert(!indirect_dispatch_inputs_resident(true) && copies==0);
    reset();state.ub[5][0]={pool_address,pool_bytes};shader.bindings={{17,1,1,0}};
    assert(!indirect_dispatch_inputs_resident(true) && copies==0);
    reset();shader.bindings.push_back({29,2,2,3});state.sb[5][3]={pool_address+16,128};
    assert(indirect_dispatch_inputs_resident(true) && copies==1);
    reset();assert(!pin_indexed_input({"storage",0,17,pool_address,pool_bytes}));
    assert(!pin_indexed_input({"texel",1,17,pool_address,pool_bytes}));
    assert(!pin_indexed_input({"texel",0,65,pool_address,pool_bytes}));
    assert(pin_indexed_input({"texel",0,17,pool_address,pool_bytes}) && copies==1);
    // Real slow-frame shape: args+132, counter and 262160-byte data all from an older slot.
    reset_old_args();select_dispatch(0x1100+132);
    assert(picked && begins==1 && copies==3 && resolves==0);
    assert((copied_sizes==std::vector<size_t>{16,262160,3040}));
    assert(slots[0].copy_readers.size()==3 && slots[1].retire.objects.size()==3);
    assert(current_pending_range(0x1100,3040,4));
    select_dispatch(0x1100+60);assert(picked && copies==3 && begins==1 && resolves==0);
    // Clean CPU parameters do not create a recording slot or any GPU copy.
    reset_old_args();pending_writebacks.erase(pending_writebacks.begin()+1);
    select_dispatch();assert(!picked && begins==0 && copies==0 && resolves==0);
    for(unsigned gate=0;gate<7;++gate){
        reset_old_args();
        if(gate==0)properties.vendorID=0x5143;if(gate==1)owned_input_copy_enabled=false;
        if(gate==2)capture.active=true;if(gate==3)capture.probe=true;
        if(gate==4)provenance_file=&shader;if(gate==5)pass_prof_enabled=true;if(gate==6)g_ui_moff=1;
        select_dispatch();assert(!picked && begins==0 && copies==0 && resolves==0);
    }
    // A partially covering newest writeback must keep the original CPU fallback.
    reset_old_args();pending_writebacks.push_back({0x1104,8,{4,0,8},&slots[0],{},{}});
    select_dispatch();assert(!picked && begins==0 && copies==0 && resolves==0);
    // Once slot acquisition changes writebacks, failed preparation explicitly synchronizes.
    reset_old_args();retire_args_on_begin=true;select_dispatch();
    assert(!picked && begins==1 && copies==2 && resolves==1);
    reset_old_args();shader.bindings.push_back({30,3,7,0});select_dispatch();
    assert(!picked && begins==1 && copies==0 && resolves==1);
    reset_old_args();shader.bindings={{17,1,1,0}};state.ub[5][0]={0x1000,16};select_dispatch();
    assert(!picked && begins==1 && copies==0 && resolves==1);
    reset_old_args();pending_reports.push_back({0x1100});select_dispatch();
    assert(!picked && begins==1 && copies==2 && resolves==1);
    reset_old_args();nvn_memory_pool_resolve_address=nullptr;select_dispatch();
    assert(!picked && begins==1 && copies==0 && resolves==1);
    reset_old_args();pending_writebacks[1].bytes=1048580;select_dispatch();
    assert(!picked && begins==1 && copies==2 && resolves==1);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            code = path / 'input.cpp'
            code.write_text(program)
            executable = path / 'input'
            compiled = subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                                       str(code), '-o', str(executable)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
