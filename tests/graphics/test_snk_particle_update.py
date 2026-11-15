import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'src/graphics/nvn_vulkan/engine'


class ParticleUpdateTests(unittest.TestCase):
    def test_dispatch_rows_and_static_arguments(self):
        program = r'''
#include "xbg_indirect_template.h"
#include <cassert>
#include <climits>
int main(){
    std::vector<uint32_t> records(64*36);
    for(unsigned y=0;y<64;++y){records[y*36+1]=512;records[y*36+19]=y;}
    const auto before=records;
    assert(xbg_snk_particle_update_rows(records.data(),records.size(),64,1280));
    assert(records==before);
    records[63*36+19]=64;
    assert(!xbg_snk_particle_update_rows(records.data(),records.size(),64,1280));
    // All inactive particle counts return before any argument access.
    records[63*36+1]=0;records[63*36+19]=UINT32_MAX;
    assert(xbg_snk_particle_update_rows(records.data(),records.size(),64,1280));
    records[63*36+1]=1;
    assert(!xbg_snk_particle_update_rows(records.data(),records.size(),64,1280));
    records=before;
    assert(!xbg_snk_particle_update_rows(records.data(),records.size()-1,64,1280));
    assert(!xbg_snk_particle_update_rows(records.data(),records.size(),65,1280));
    assert(!xbg_snk_particle_update_rows(records.data(),records.size(),0,1280));
    assert(!xbg_snk_particle_update_rows(records.data(),records.size(),UINT32_MAX,1280));
    assert(!xbg_snk_particle_update_rows(nullptr,records.size(),64,1280));
    for(uint64_t bytes:{uint64_t(0),uint64_t(19),uint64_t(1281),uint64_t(65540)})
        assert(!xbg_snk_particle_update_rows(records.data(),records.size(),64,bytes));
    // Tail padding cannot hold another 20-byte indexed argument.
    records[63*36+19]=64;
    assert(!xbg_snk_particle_update_rows(records.data(),records.size(),64,1296));
    assert(xbg_snk_particle_update_rows(records.data(),records.size(),64,1300));
    std::vector<uint32_t> args(64*5);
    for(unsigned row=0;row<64;++row){args[row*5]=6;args[row*5+1]=UINT32_MAX;}
    const auto args_before=args;
    std::vector<XbgIndirectTemplateRow> rows;
    assert(xbg_snk_instance_templates(rows,args,0x1000,1280));
    assert(rows.size()==64 && rows.back().address==0x1000+63*20);
    assert(args==args_before);
}
'''
        self.compile_and_run(program)

    def test_runtime_dispatch_and_metadata_guards(self):
        source = (ENGINE / 'xbg_game.cpp').read_text()
        start = source.index('std::shared_ptr<IndirectTemplateBatch> indirect_template_batch(')
        end = source.index('Descriptors &acquire_descriptors()', start)
        function = source[start:end]
        program = r'''
#include "xbg_indirect_template.h"
#include <cassert>
#include <cstring>
#include <memory>
#include <unordered_set>
#include <string>
struct IndirectTemplateInput {
    bool snk_instance=true,snk_particle=false,snk_grass=false,snk_particle_update=true;
    bool params_valid=false,metadata_exclusive=false;
    uint64_t address=0,bytes=0,metadata_address=0,metadata_bytes=0;
    uint64_t modified_bytes=0,metadata_modified_bytes=0;
    uint32_t params[4]{};
    std::vector<uint32_t> words;
};
struct IndirectTemplateBatch {
    uint64_t address=0,bytes=0;bool snk_instance=false;
    std::vector<XbgIndirectTemplateRow> rows;
};
struct Descriptors {
    std::shared_ptr<IndirectTemplateInput> indirect_input=std::make_shared<IndirectTemplateInput>();
    std::vector<std::pair<std::pair<uint64_t,uint64_t>,void*>> written;
};
struct p_dispatch {int x=16,y=64,z=1;};
constexpr unsigned VK_DESCRIPTOR_TYPE_STORAGE_BUFFER=1,XBG_SOURCE_STORAGE=2,XBG_SOURCE_UNIFORM=3;
struct Binding {unsigned type=1,binding=29,source=2,count=1,slot=0;};
struct Shader {std::vector<Binding> bindings;std::unordered_set<unsigned> storage_writes;};
struct Range {uint64_t address=0,size=0;};
struct {Shader *shader[6]{};Range sb[6][16]{},ub[6][16]{};} state;
unsigned nvn_stage[6]={0,1,2,3,4,5};
struct Write {uint64_t addr,bytes;bool snk_cull_metadata;std::shared_ptr<const XbgCullMetadataPatch> snk_cull_patch;};
struct NVNcounterData {uint64_t data[2];};
struct Report {uint64_t addr;};
std::vector<Write> pending_writebacks;
std::vector<Report> pending_reports;
bool indirect_proof_enabled=true,clean=true;
bool indirect_cpu_clean(uint64_t,size_t){return clean;}
namespace evguard {struct EngineRead {EngineRead(const void*,size_t){}};}
void xbg_logf(const char*,...){}
''' + function + r'''
int main(){
    std::vector<uint32_t> records(64*36);
    for(unsigned y=0;y<64;++y){records[y*36+1]=512;records[y*36+19]=y;}
    Descriptors d;auto &i=*d.indirect_input;
    i.address=0x1000;i.bytes=1280;i.metadata_address=uint64_t(records.data());i.metadata_bytes=records.size()*4;
    i.words.resize(64*5);for(unsigned y=0;y<64;++y)i.words[y*5]=6;
    d.written.push_back({{i.address,i.bytes},nullptr});
    Shader shader;shader.bindings.push_back({});shader.storage_writes.insert(29);
    state.shader[5]=&shader;state.sb[5][0]={i.address,i.bytes};
    p_dispatch p;
    auto build=[&](bool indirect=false){return indirect_template_batch(d,p,indirect);};
    auto result=build();assert(result && result->rows.size()==64);
    assert(!build(true));
    i.snk_particle_update=false;assert(!build());i.snk_particle_update=true;
    p.x=0;assert(!build());p.x=16;
    p.y=0;assert(!build());p.y=64;
    p.z=2;assert(!build());p.z=1;
    clean=false;assert(!build());clean=true;
    i.metadata_bytes-=4;assert(!build());i.metadata_bytes+=4;
    records.back()=0;records[63*36+19]=64;assert(!build());records[63*36+19]=63;
    // An alias through another writable binding invalidates the static proof.
    shader.bindings.push_back({1,23,2,1,1});shader.storage_writes.insert(23);
    state.sb[5][1]={i.address+4,4};assert(!build());
    state.sb[5][1]={i.metadata_address,4};assert(!build());
    state.sb[5][1]={0x9000,4};assert(build());
    d.written.push_back({{i.address+4,4},nullptr});assert(!build());d.written.pop_back();
    i.words.clear();assert(!build());
}
'''
        self.compile_and_run(program)

    def test_exact_shader_classification_precedes_rewrites(self):
        source = (ENGINE / 'xbg_game.cpp').read_text()
        start = source.index('if(h.stage==5 && key=="342eaea42136f6fc")')
        end = source.index('\n    }', start) + len('\n    }')
        block = source[start:end]
        self.assertIn('nvn_sha256(words.data(),words.size()*4,digest)', block)
        self.assertIn('p->snk_particle_update=std::memcmp(digest,audited,sizeof(audited))==0', block)
        import re
        digest = bytes(int(value, 16) for value in re.findall(r'0x([0-9a-f]{2})', block))
        self.assertEqual(digest.hex(), 'bf83d82a4141cb02a6b6fd152ec9d6124281d6f06c716b501c8a74d3b56f9b35')
        self.assertIn('out.indirect_input->snk_particle_update=state.shader[5]->snk_particle_update', source)
        self.assertIn('out.indirect_input->snk_particle_update && b.binding==17', source)

    def compile_and_run(self, program):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'particle_update.cpp'
            source.write_text(program)
            executable = source.with_suffix('')
            subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17',
                            '-fsanitize=address,undefined', '-I', str(ENGINE),
                            str(source), '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
