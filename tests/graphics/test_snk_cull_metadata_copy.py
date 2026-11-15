import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'src/graphics/nvn_vulkan/engine'


class CullMetadataCopyTests(unittest.TestCase):
    def compile_and_run(self, program):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'metadata_copy.cpp'
            source.write_text(program)
            executable = source.with_suffix('')
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', '-I', str(ENGINE),
                            str(source), '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_ordered_static_field_overlays_and_bounds(self):
        self.compile_and_run(r'''
#include "xbg_indirect_template.h"
#include <cassert>
struct Write {
    uint64_t addr,bytes;bool snk_cull_metadata=false;
    std::shared_ptr<const XbgCullMetadataPatch> snk_cull_patch;
};
int main(){
    std::vector<uint32_t> baseline(6*20);
    for(unsigned i=0;i<6;++i){baseline[i*20+1]=i;baseline[i*20+2]=0;baseline[i*20]=20+i;baseline[i*20+7]=30+i;}
    const auto before=baseline;
    auto patch=std::make_shared<XbgCullMetadataPatch>();
    patch->address=0x1000;patch->bytes=480;patch->first=2;
    patch->records={{8,0,40,50},{10,0x100,60,70}};
    std::vector<Write> writes={{0x1000,480,true,{}},{0x1000,480,false,patch},{0x1000,480,true,{}}};
    std::vector<XbgCullIndexRecord> records;
    auto snapshot=[&](){return xbg_snk_cull_index_snapshot(writes,baseline.data(),0x1000,480,records);};
    assert(snapshot());assert(baseline==before);
    assert(records.size()==6 && records[0].index==0 && records[2].index==8 && records[3].flags==0x100);
    assert(records[0].output_base==20 && records[0].lod_stride==30);
    assert(records[2].output_base==40 && records[3].lod_stride==70);
    assert(xbg_snk_copied_index_writeback_bytes(records,1,248)==240);
    records[3].index=11;assert(!xbg_snk_copied_index_writeback_bytes(records,1,248));
    records[3].flags=0x20;
    assert(xbg_snk_copied_index_writeback_bytes(records,1,248,0x20)==240);
    records[2].index=UINT32_MAX;records[2].flags=0;
    assert(!xbg_snk_copied_index_writeback_bytes(records,1,248,0x20));
    auto newer=std::make_shared<XbgCullMetadataPatch>(*patch);newer->first=3;newer->records={{7,0}};
    writes.push_back({0x1000,480,false,newer});assert(snapshot());assert(records[3].index==7 && records[3].flags==0);
    // Retiring an older producer first updates the CPU baseline. Keeping only
    // its later overlays reconstructs exactly the same logical fields.
    baseline[2*20+1]=8;baseline[3*20+1]=10;baseline[3*20+2]=0x100;
    writes.erase(writes.begin(),writes.begin()+2);assert(snapshot());assert(records[2].index==8 && records[3].index==7);
    writes.push_back({0x1000,480,false,{}});assert(!snapshot());assert(records.empty());writes.pop_back();
    newer->first=6;assert(!snapshot());newer->first=3;
    newer->address=0x1004;assert(!snapshot());newer->address=0x1000;
    newer->bytes=476;assert(!snapshot());newer->bytes=480;
    newer->records.clear();assert(!snapshot());newer->records={{7,0}};
    writes.push_back({0x1004,400,true,{}});assert(!snapshot());writes.pop_back();
    writes.push_back({0x1000,400,true,{}});assert(!snapshot());writes.pop_back();
    assert(!xbg_snk_cull_index_snapshot(writes,baseline.data(),0x1000,479,records));
    assert(!xbg_snk_cull_index_snapshot(writes,nullptr,0x1000,480,records));
    assert(!xbg_snk_cull_index_snapshot(writes,baseline.data(),UINT64_MAX-8,480,records));
    assert(!xbg_snk_cull_index_snapshot(writes,baseline.data(),0x1000,4*1024*1024+80,records));
    assert(snapshot());assert(!xbg_snk_copied_index_writeback_bytes(records,0,248));
    std::vector<XbgCullIndexRecord> many(1025,{0,0});
    assert(!xbg_snk_copied_index_writeback_bytes(many,1,248));
}
''')

    def test_real_runtime_cleanliness_alias_and_dispatch_guards(self):
        source = (ENGINE / 'xbg_game.cpp').read_text()
        start = source.index('void capture_cull_copy_indices(')
        end = source.index('std::shared_ptr<IndirectTemplateBatch> indirect_template_batch(', start)
        function = source[start:end]
        self.compile_and_run(r'''
#include "xbg_indirect_template.h"
#include <cassert>
#include <cstring>
#include <unordered_set>
struct p_dispatch {int x=1,y=1,z=1;};
constexpr unsigned VK_DESCRIPTOR_TYPE_STORAGE_BUFFER=1,XBG_SOURCE_STORAGE=2,XBG_SOURCE_UNIFORM=3;
struct Binding {unsigned binding,type,source,slot,count=1;};
struct Shader {bool snk_metadata_copy=true;std::vector<Binding> bindings;std::unordered_set<unsigned> storage_writes;};
struct Range {uint64_t address=0,size=0;};
struct {Shader *shader[6]{};Range sb[6][16]{},ub[6][16]{};} state;
unsigned nvn_stage[6]={0,1,2,3,4,5};
struct Descriptors {
    std::shared_ptr<XbgCullMetadataPatch> cull_metadata_patch;
    std::vector<std::pair<std::pair<uint64_t,uint64_t>,void*>> written;
};
struct Write {uint64_t addr,bytes;bool snk_cull_metadata;};
struct NVNcounterData {uint64_t data[2];};
struct Report {uint64_t addr;};
std::vector<Write> pending_writebacks;
std::vector<Report> pending_reports;
bool clean=true;
bool indirect_cpu_clean(uint64_t address,size_t bytes){
    if(!clean)return false;
    for(const auto &w:pending_writebacks)if(xbg_wb_overlaps(address,bytes,w.addr,w.bytes))return false;
    for(const auto &r:pending_reports)if(xbg_wb_overlaps(address,bytes,r.addr,sizeof(NVNcounterData)))return false;
    return true;
}
namespace evguard {struct EngineRead {EngineRead(const void*,size_t){}};}
void xbg_logf(const char*,...){}
''' + function + r'''
int main(){
    std::vector<uint32_t> input(2*20),output(4*20),other(4*32);
    input[0]=4;input[7]=11;input[20]=6;input[27]=17;
    input[1]=3;input[2]=0x100;input[21]=8;input[22]=0x200;
    output[21]=3;output[22]=0x100;output[41]=8;output[42]=0x200;
    uint32_t params[3]={2,1,999};
    const uint64_t src=uint64_t(input.data()),dst=uint64_t(output.data()),extra=uint64_t(other.data());
    Shader shader;shader.bindings={{11,1,2,2},{17,1,2,0},{29,1,2,1},{35,2,3,2}};
    shader.storage_writes={17,29};state.shader[5]=&shader;
    state.sb[5][0]={dst,output.size()*4};state.sb[5][1]={extra,other.size()*4};state.sb[5][2]={src,input.size()*4};
    state.ub[5][2]={uint64_t(params),sizeof(params)};
    Descriptors d;d.written={{{dst,output.size()*4},nullptr},{{extra,other.size()*4},nullptr}};
    p_dispatch p;
    auto qualify=[&](bool indirect=false){d.cull_metadata_patch.reset();capture_cull_copy_indices(d,p,indirect);return d.cull_metadata_patch && d.cull_metadata_patch->address==dst;};
    const auto before=output;
    assert(qualify());assert(output==before);
    assert(!qualify(true));
    shader.snk_metadata_copy=false;assert(!qualify());shader.snk_metadata_copy=true;
    p.y=2;assert(!qualify());p.y=1;p.z=2;assert(!qualify());p.z=1;p.x=0;assert(!qualify());p.x=1;
    clean=false;assert(!qualify());clean=true;
    params[1]=3;assert(!qualify());params[1]=1;
    state.sb[5][2].size-=4;assert(!qualify());state.sb[5][2].size+=4;
    pending_writebacks={{dst,output.size()*4,true}};assert(qualify());
    pending_writebacks.back().snk_cull_metadata=false;assert(qualify());pending_writebacks.clear();
    pending_writebacks={{src,input.size()*4,true}};assert(!qualify());pending_writebacks.clear();
    pending_reports={{dst+4}};assert(!qualify());pending_reports.clear();
    state.sb[5][1]={src,4};assert(!qualify());
    state.sb[5][1]={dst+4,4};assert(!qualify());state.sb[5][1]={extra,other.size()*4};
    d.written.push_back({{dst+4,4},nullptr});assert(!qualify());d.written.pop_back();
    output[41]=9;output[42]=0;assert(qualify());
    assert(d.cull_metadata_patch->first==1 && d.cull_metadata_patch->records.size()==2);
    assert(d.cull_metadata_patch->records[1].index==8 && d.cull_metadata_patch->records[1].flags==0x200);
    assert(d.cull_metadata_patch->records[0].output_base==1003 && d.cull_metadata_patch->records[0].lod_stride==11);
    assert(d.cull_metadata_patch->records[1].output_base==1005 && d.cull_metadata_patch->records[1].lod_stride==17);
    state.ub[5][2].size=8;assert(!qualify());state.ub[5][2].size=sizeof(params);assert(qualify());
    params[2]=UINT32_MAX;input[0]=2;assert(qualify());
    assert(d.cull_metadata_patch->records[0].output_base==1);
    input[21]=99;assert(d.cull_metadata_patch->records[1].index==8);
}
''')

    def test_exact_module_and_proof_publication(self):
        source = (ENGINE / 'xbg_game.cpp').read_text()
        start = source.index('if(h.stage==5 && key=="978a71642064cba1")')
        end = source.index('    boss_interface_rewrite(', start)
        digest = bytes(int(value, 16) for value in re.findall(r'0x([0-9a-f]{2})', source[start:end]))
        self.assertEqual(digest.hex(), '97affce7b9fc1bbbcb2935e69bc87b283484fe1564a22855db21569ef11ff899')
        self.assertIn('out.cull_metadata_patch.reset();', source)
        self.assertIn('cull_metadata_patch->address==v.first.first && cull_metadata_patch->bytes==v.first.second', source)
        self.assertIn('capture_cull_copy_indices(d,p,gpu_indirect);', source)


if __name__ == '__main__':
    unittest.main()
