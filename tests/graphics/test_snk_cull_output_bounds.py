import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class CullOutputBoundsTests(unittest.TestCase):
    def test_all_lods_seed_counts_and_integer_bounds(self):
        program = r'''
#include "xbg_indirect_template.h"
#include <cassert>
int main(){
    std::vector<XbgCullIndexRecord> records={{0,0,10,100},{0,0,10,100}};
    std::vector<uint32_t> args(12); // Two indexed rows and descriptor padding.
    args[1]=3;args[6]=7;
    auto bound=[&](uint64_t bytes=12800,uint32_t mask=0){
        return xbg_snk_cull_output_writeback_bytes(records,args,1,bytes,mask);
    };
    assert(bound()==15*128);
    records[0].flags=0x100;
    assert(bound(25600)==118*128);
    records[0].index=UINT32_MAX;records[0].flags=0x20;
    assert(bound(12800,0x20)==14*128);
    assert(!bound());
    records[0]={0,0x200,10,100};
    assert(!bound(100*128));
    args[6]=UINT32_MAX;assert(!bound(25600));args[6]=7;
    records[0].output_base=UINT32_MAX;assert(!bound(UINT64_MAX-127));
    records[0]={0,0,INT32_MAX/128,0};assert(!bound(uint64_t(INT32_MAX)+1));
    records.clear();assert(!bound());records={{0,0,0,0}};
    assert(!xbg_snk_cull_output_writeback_bytes(records,args,0,12800,0));
    records.resize(1025);assert(!bound());records.resize(1);
    assert(!bound(127));
    std::vector<uint32_t> empty;
    assert(!xbg_snk_cull_output_writeback_bytes(records,empty,1,12800,0));
    // Simulate the original single atomic increment under arbitrary visibility,
    // ordering, LOD choices and nonzero seeds. Every actual store must fit.
    uint32_t random=17;
    auto next=[&](){random=random*1664525u+1013904223u;return random;};
    for(unsigned trial=0;trial<2000;++trial){
        args.assign(16*5+2,0);
        for(unsigned row=0;row<16;++row)args[row*5+1]=next()%10;
        records.clear();
        for(unsigned i=0;i<100;++i)
            records.push_back({next()%15,(next()%4)*0x100u, next()%100, next()%100});
        const uint64_t bytes=xbg_snk_cull_output_writeback_bytes(records,args,1,128000,0);
        assert(bytes);
        auto counters=args;
        for(const auto &record:records){
            if(next()&1)continue;
            const unsigned lod=(record.flags&0x300u)?next()%2:0;
            const unsigned row=record.index+lod;
            const uint64_t output=record.output_base+uint64_t(lod)*record.lod_stride+counters[row*5+1]++;
            assert((output+1)*128<=bytes);
        }
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            source = path / 'bounds.cpp'
            source.write_text(program)
            executable = path / 'bounds'
            subprocess.run([
                shutil.which('clang++') or 'c++', '-std=c++17',
                '-fsanitize=address,undefined', '-I',
                str(ROOT / 'src/graphics/nvn_vulkan/engine'),
                str(source), '-o', str(executable),
            ], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
