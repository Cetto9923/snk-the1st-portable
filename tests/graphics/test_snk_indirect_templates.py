import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class FalcomIndirectTemplateTests(unittest.TestCase):
    def test_outdoor_cull_metadata_exceeds_one_megabyte(self):
        engine = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = engine.index('        if(exclusive && i.params_valid && metadata_bytes')
        begin = engine.index('(', start) + 1
        end = engine.index('){', begin)
        condition = engine[begin:end]
        program = r'''
#include "xbg_indirect_template.h"
#include <cassert>
#include <vector>
int main(){
    const uint32_t active=19526;
    const uint64_t metadata_bytes=uint64_t(active)*80;
    assert(metadata_bytes>1024*1024);
    bool exclusive=true,indices_readable=true;
    struct {bool params_valid=true;uint64_t metadata_bytes=4000000;} i;
    auto qualified=[&](){return CONDITION;};
    assert(qualified());
    i.metadata_bytes=metadata_bytes-1;assert(!qualified());i.metadata_bytes=4000000;
    exclusive=false;assert(!qualified());exclusive=true;
    indices_readable=false;assert(!qualified());indices_readable=true;
    i.params_valid=false;assert(!qualified());i.params_valid=true;
    std::vector<uint32_t> records(size_t(active)*20);
    for(uint32_t record=0;record<active;++record)records[size_t(record)*20+1]=record%630;
    assert(xbg_snk_instance_writeback_bytes(records.data(),records.size(),active,20,12608)==12600);
    records[size_t(active-1)*20+1]=630;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),active,20,12608));
    records[size_t(active-1)*20+1]=629;records[size_t(active-1)*20+2]=0x100;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),active,20,12608));
    records[size_t(active-1)*20+2]=0;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),active,19,12608));
}
'''.replace('CONDITION', condition)
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'outdoor_metadata.cpp'
            source.write_text(program)
            executable = source.with_suffix('')
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', '-I',
                            str(ROOT / 'src/graphics/nvn_vulkan/engine'), str(source),
                            '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_grass_counter_static_arguments_and_row_bounds(self):
        program = r'''
#include "xbg_indirect_template.h"
#include <cassert>
#include <cstdint>
#include <vector>
int main(){
    std::vector<uint32_t> records(3*12);
    records[1]=0;records[13]=2;records[25]=0;
    assert(xbg_snk_grass_argument_rows(records.data(),records.size(),80));
    std::vector<uint32_t> arguments={720,33,0,0,0,720,7,0,0,0,
        216,1234,18,0,0,216,0,18,0,0};
    const auto before=arguments;
    std::vector<XbgIndirectTemplateRow> rows;
    assert(xbg_snk_instance_templates(rows,arguments,0x1000,80));
    assert(rows.size()==4 && rows[0].index_count==720);
    assert(rows[2].first_index==18 && rows[3].address==0x103c);
    assert(arguments==before);
    records[13]=3;
    assert(!xbg_snk_grass_argument_rows(records.data(),records.size(),80));
    records[13]=UINT32_MAX;
    assert(!xbg_snk_grass_argument_rows(records.data(),records.size(),80));
    records[13]=2;
    assert(!xbg_snk_grass_argument_rows(records.data(),11,80));
    assert(!xbg_snk_grass_argument_rows(nullptr,records.size(),80));
    assert(!xbg_snk_grass_argument_rows(records.data(),262145,80));
    assert(!xbg_snk_grass_argument_rows(records.data(),records.size(),39));
    assert(!xbg_snk_grass_argument_rows(records.data(),records.size(),81));
    assert(!xbg_snk_grass_argument_rows(records.data(),records.size(),65540));
    assert(xbg_snk_grass_argument_rows(records.data(),12,40));
    records[1]=1;
    assert(!xbg_snk_grass_argument_rows(records.data(),12,40));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            source = path / 'grass_arguments.cpp'
            source.write_text(program)
            executable = source.with_suffix('')
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined',
                            '-I', str(ROOT / 'src/graphics/nvn_vulkan/engine'),
                            str(source), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_depth_only_resident_draw_state(self):
        engine = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = engine.index('bool indexed_graphics_ready(')
        end = engine.index('    if(!indexed_range_ready(', start)
        state_guard = engine[start:end] + '    return true;\n}\n'
        program = r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
struct p_draw_idx {};
struct IndexedInputFailure {
    const char *why="none";
    uint32_t stage=UINT32_MAX,binding=UINT32_MAX;
    uint64_t address=0,bytes=0;
};
bool read_preflight=false,pass_prof_enabled=false,draw_detail=false;
struct {bool active=false,probe=false;} capture;
void *provenance_file=nullptr;
namespace warm {bool async_on=false;}
struct {
    bool rast_discard=false,tf_on=false;
    void *shader[5]{};
    struct {void *depth=nullptr;} rt;
} state;
''' + state_guard + r'''
int main(){
    p_draw_idx draw;
    IndexedInputFailure failure;
    int vertex,fragment,depth;
    assert(!indexed_graphics_ready(draw,144,&failure));
    state.shader[0]=&vertex;
    assert(!indexed_graphics_ready(draw,144));
    state.rt.depth=&depth;
    assert(indexed_graphics_ready(draw,144));
    state.shader[4]=&fragment;
    assert(indexed_graphics_ready(draw,144));
    state.rt.depth=nullptr;
    assert(indexed_graphics_ready(draw,144));
    state.shader[4]=nullptr;state.rt.depth=&depth;
    bool *guards[]={&read_preflight,&capture.active,&capture.probe,
        &pass_prof_enabled,&draw_detail,&warm::async_on,
        &state.rast_discard,&state.tf_on};
    for(auto guard:guards){
        *guard=true;assert(!indexed_graphics_ready(draw,144));*guard=false;
    }
    provenance_file=&depth;assert(!indexed_graphics_ready(draw,144));
    provenance_file=nullptr;
    for(unsigned stage=1;stage<4;++stage){
        state.shader[stage]=&vertex;
        assert(!indexed_graphics_ready(draw,144));
        state.shader[stage]=nullptr;
    }
    state.shader[0]=nullptr;
    assert(!indexed_graphics_ready(draw,144));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            source = path / 'indexed_depth.cpp'
            source.write_text(program)
            executable = source.with_suffix('')
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', str(source), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_completed_writeback_copies_only_audited_prefix(self):
        engine = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = engine.index('void apply_writeback(PendingWriteback &write){')
        end = engine.index('\n}', start) + 2
        function = engine[start:end]
        program = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
struct Image {};
bool image_alias=false;
uint64_t writeback_bytes=0,invalidated=0,cache_invalidated=0,cache_invalidations=0;
struct Buffer {void *mapped;size_t size;void invalidate(){++cache_invalidations;cache_invalidated=size;}};
struct PendingWriteback {uint64_t addr,bytes,modified_bytes;Buffer buffer;};
template<class F> void for_images_overlapping(uint64_t,uint64_t,F callback){
    if(image_alias){Image image;callback(image);}
}
void invalidate_cpu_range(uint64_t,uint64_t bytes){invalidated=bytes;}
''' + function + r'''
int main(){
    std::array<uint8_t,96> cpu,gpu;
    gpu.fill(0x31);cpu.fill(0x79);
    PendingWriteback write{uint64_t(cpu.data()),cpu.size(),32,{gpu.data(),gpu.size()}};
    apply_writeback(write);
    assert(write.bytes==96 && invalidated==32 && writeback_bytes==32);
    assert(cache_invalidations==1 && cache_invalidated==32 && write.buffer.size==96);
    for(size_t i=0;i<cpu.size();++i)assert(cpu[i]==(i<32?0x31:0x79));
    // An earlier full result followed by a partial result retains its tail.
    write.modified_bytes=0;apply_writeback(write);gpu.fill(0x55);
    write.modified_bytes=32;apply_writeback(write);
    for(size_t i=0;i<cpu.size();++i)assert(cpu[i]==(i<32?0x55:0x31));
    cpu.fill(0x79);write.modified_bytes=97;apply_writeback(write);
    assert(cpu==gpu && invalidated==96 && cache_invalidated==96);
    cpu.fill(0x79);write.modified_bytes=32;image_alias=true;apply_writeback(write);
    assert(cpu==gpu && invalidated==96 && cache_invalidated==96);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            source = path / 'writeback.cpp'
            source.write_text(program)
            executable = path / 'writeback'
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', str(source), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)
        self.assertIn('for(auto &w:writebacks)apply_writeback(w);', engine)
        self.assertIn('if(pending_writebacks[j].modified_bytes)return false;', engine)

    def test_cull_write_bounds_require_all_metadata_rows(self):
        program = r'''
#include "xbg_indirect_template.h"
#include "xbg_writeback_policy.h"
#include <cassert>
#include <cstdint>
#include <vector>
int main(){
    std::vector<uint32_t> records(452*20);
    for(size_t i=0;i<452;++i)records[i*20+1]=328;
    assert(xbg_snk_instance_writeback_bytes(records.data(),records.size(),452,1,6608)==6600);
    assert(xbg_wb_overwritten(0x1000,6600,0x1000,6608,6600));
    assert(!xbg_wb_overwritten(0x1000,6600,0x1000,6608));
    assert(!xbg_wb_overwritten(0x1000,6599,0x1000,6608,6600));
    assert(!xbg_wb_overwritten(0x1001,6600,0x1000,6608,6600));
    assert(!xbg_wb_overwritten(0x1000,6608,0x1000,6608,6609));
    assert(!xbg_wb_overwritten(UINT64_MAX-100,6600,0x1000,6608,6600));
    struct Write {uint64_t addr,bytes;bool snk_cull_metadata;};
    std::vector<Write> writes={{0x9000,452*80,true}};
    assert(xbg_snk_cull_indices_readable(writes,0x9000,452*80));
    writes.push_back({0x9000,80,false});
    assert(!xbg_snk_cull_indices_readable(writes,0x9000,452*80));
    writes.pop_back();
    assert(!xbg_snk_cull_indices_readable(writes,0x9000,453*80));
    assert(!xbg_snk_cull_indices_readable(writes,0x9004,80));
    assert(xbg_snk_instance_writeback_bytes(records.data(),records.size(),452,1,6600)==6600);
    records[451*20+1]=329;
    assert(xbg_snk_instance_writeback_bytes(records.data(),records.size(),452,1,6608)==6600);
    records[451*20+2]=0x100;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),452,1,6608));
    records[451*20+2]=0x200;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),452,1,6608));
    records[451*20+2]=0;
    records[451*20+1]=330;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),452,1,6608));
    records[451*20+1]=UINT32_MAX;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),452,1,6608));
    records[451*20+1]=328;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size()-1,452,1,6608));
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),452,0,6608));
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),0,1,6608));
    assert(!xbg_snk_instance_writeback_bytes(nullptr,records.size(),452,1,6608));
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),452,1,6609));
    records.resize(1025*20);
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),1025,1,6608));
    records.assign(2*20,0);records[1]=UINT32_MAX;records[2]=0x20;records[21]=328;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),2,1,6608));
    assert(xbg_snk_instance_writeback_bytes(records.data(),records.size(),2,1,6608,0x20)==6600);
    records[21]=329;records[22]=0x100;
    assert(!xbg_snk_instance_writeback_bytes(records.data(),records.size(),2,1,6608,0x20));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'bounds.cpp').write_text(program)
            executable = path / 'bounds'
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', '-I',
                            str(ROOT / 'src/graphics/nvn_vulkan/engine'),
                            str(path / 'bounds.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_static_metadata_uses_synchronized_guest_source(self):
        engine = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = engine.index('                if(out.indirect_input && out.indirect_input->snk_instance &&')
        brace = engine.index('{', start)
        depth = 1
        end = brace + 1
        while depth:
            depth += (engine[end] == '{') - (engine[end] == '}')
            end += 1
        block = engine[start:end]
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'snapshot.cpp'
            source.write_text(r'''#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <vector>
namespace evguard { struct EngineRead { EngineRead(const void *,size_t) {} }; }
bool cpu_clean=true;
bool indirect_cpu_clean(uint64_t,size_t) { return cpu_clean; }
constexpr unsigned XBG_SOURCE_STORAGE=1;
struct Input { bool snk_instance=true,snk_particle=false,snk_grass=false;uint64_t address=0,bytes=0;std::vector<uint32_t> words; };
struct Output { std::shared_ptr<Input> indirect_input=std::make_shared<Input>(); };
int main() {
    uint32_t actual[5]={2076,0,0,0,0},stale[5]={};
    const void *data=actual;size_t n=sizeof(actual),buffer_offset=0;
    struct Binding { unsigned binding=29,source=XBG_SOURCE_STORAGE; } b;
    struct Buffer { const void *mapped; } mapped{stale};auto *buffer=&mapped;
    bool is_storage=true;unsigned element=0;Output out;
    auto prepare=[&](){
''' + block + r'''
    };
    prepare();
    assert(out.indirect_input->words.size()==5);
    assert(out.indirect_input->words[0]==2076);
    assert(out.indirect_input->address==uint64_t(actual));
    out.indirect_input->snk_grass=true;b.binding=41;
    actual[0]=720;out.indirect_input->words.clear();prepare();
    assert(out.indirect_input->words.size()==5 && out.indirect_input->words[0]==720);
    out.indirect_input->words.clear();cpu_clean=false;prepare();
    assert(out.indirect_input->words.empty());
}
''')
            executable = pathlib.Path(directory) / 'snapshot'
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', str(source), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_real_argument_layout_and_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'templates.cpp'
            source.write_text(r'''
#include <cassert>
#include "xbg_indirect_template.h"
int main() {
    std::vector<XbgIndirectTemplateRow> rows;
    std::vector<uint32_t> words={2076,0,0,0,0,3000,37,21,0,0,0xabcdef,0xabcdef};
    assert(xbg_snk_instance_templates(rows,words,0x1000,48));
    assert(rows.size()==2);
    assert(rows[0].address==0x1000 && rows[0].index_count==2076 && rows[0].first_index==0);
    assert(rows[1].address==0x1014 && rows[1].index_count==3000 && rows[1].first_index==21);
    words[3]=4;
    assert(xbg_snk_instance_templates(rows,words,0x1000,48));
    assert(rows.size()==1 && rows[0].address==0x1014);
    words[8]=1;
    assert(!xbg_snk_instance_templates(rows,words,0x1000,48));
    words[3]=0; words[8]=0; words[9]=1;
    assert(xbg_snk_instance_templates(rows,words,0x1000,48));
    assert(rows.size()==1 && rows[0].address==0x1000);
    words[9]=0; words[0]=0x80000000;
    assert(xbg_snk_instance_templates(rows,words,0x1000,48));
    assert(rows.size()==1 && rows[0].address==0x1014);
    words[7]=0x80000000;
    assert(!xbg_snk_instance_templates(rows,words,0x1000,48));
    for(uint64_t address: {uint64_t(0),uint64_t(0x1001),UINT64_MAX-15}) {
        assert(!xbg_snk_instance_templates(rows,words,address,48));
        assert(rows.empty());
    }
    for(uint64_t bytes: {uint64_t(0),uint64_t(16),uint64_t(47),uint64_t(52),uint64_t(65540)}) {
        assert(!xbg_snk_instance_templates(rows,words,0x1000,bytes));
    }
    std::vector<uint32_t> arguments={6,99,0,0,0,12,1,0,0,0};
    std::vector<uint32_t> records(112);
    records[0]=1; records[4]=18; records[56]=0; records[60]=300;
    assert(xbg_snk_particle_templates(rows,arguments,records,2,1,0x2000,40));
    assert(rows.size()==2 && rows[0].index_count==18 && rows[1].index_count==12);
    assert(rows[1].address==0x2014);
    assert(!xbg_snk_particle_templates(rows,arguments,records,3,1,0x2000,40));
    assert(!xbg_snk_particle_templates(rows,arguments,records,2,0,0x2000,40));
    records.pop_back();
    assert(!xbg_snk_particle_templates(rows,arguments,records,2,1,0x2000,40));
}
''')
            executable = pathlib.Path(directory) / 'templates'
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', '-I',
                            str(ROOT / 'src/graphics/nvn_vulkan/engine'),
                            str(source), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
