import pathlib
import shutil
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


class MemoRetiredCleanupTests(unittest.TestCase):
    def test_actual_invalidation_budget_front_slots_and_shutdown_metadata(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        definitions = '\n'.join(block(source, signature) + ';' for signature in [
            'struct RegisteredTexture{', 'struct MemoImage {', 'struct DescMemo{'])
        declarations = '\n'.join(line for line in source.splitlines() if line.startswith(
            'std::unordered_map<std::vector<uint64_t>,DescMemo,SetKeyHash> desc_memo_'))
        present_start = source.index('    memo_drain_retired();\n    uint64_t pace_ns=xbg_frame_pace();')
        present = source[present_start:source.index(';int r;', present_start) + 1]
        shutdown = source[source.index('void destroy_slots(){'):source.index('    poolreset::drain();for(auto &s:active_slots())')]
        program = r'''
#include "nvn_obj.h"
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <ctime>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>
using VkDescriptorSet=uint64_t;
using VkDescriptorSetLayout=uint64_t;
using VkPipelineLayout=uint64_t;
using VkBuffer=uint64_t;
using VkDeviceSize=uint64_t;
struct LayoutEntry {uint64_t layout;};
struct Image {uint64_t marker=0x1234;};
''' + definitions + r'''
constexpr unsigned kMaxSlots=16;
struct SetKeyHash {
    size_t operator()(const std::vector<uint64_t> &key)const {
        size_t value=0;for(auto word:key)value=value*31+word;return value;
    }
};
struct PinRef {VkDescriptorSetLayout layout;uint32_t refs;};
struct Slot {std::unordered_map<VkDescriptorSetLayout,std::vector<VkDescriptorSet>> used_sets;};
Slot slots[kMaxSlots];
''' + declarations + r'''
size_t desc_memo_local[kMaxSlots]={};
uint64_t memo_mod_gen=1;
unsigned slot_index=0;
bool xmemo_enabled=true;
std::unordered_map<int,int> img_cache;
''' + block(source, 'void memo_drain_retired(){') + '\n' + block(source, 'void memo_unpin_all(unsigned si){') + '\n' + block(source, 'void desc_memo_reset(){') + r'''
struct {
    std::atomic<uint64_t> presents{0},draws{0},dispatches{0},submissions{0};
} stats;
''' + block(source, 'struct FrameTrace {') + ' frame_trace;\n' + block(source, 'void frame_trace_record(') + r'''
static unsigned pace_calls;
static uint64_t xbg_frame_pace(){++pace_calls;return 0;}
static void present_boundary(){
    struct {uint64_t serial;} texture_value{7};auto *texture=&texture_value;
    struct {uint64_t last_write;} im{11};int r=0;
''' + present + r'''
    frame_trace_record(texture->serial,im.last_write,r);
}
''' + shutdown + r'''
}
static size_t retained(){
    size_t total=0;for(auto &map:desc_memo_retired)total+=map.size();return total;
}
static void fill(unsigned si,size_t count){
    auto *image=new Image;
    auto *texture=new RegisteredTexture;
    static LayoutEntry entry{9};
    for(size_t i=0;i<count;++i){
        DescMemo value{};
        value.entry=&entry;value.set=i/2+1;value.pipeline_layout=17;value.persistent=true;
        value.dynamic_offsets.assign(8,uint32_t(i));
        value.images.emplace_back(&texture->texture,image,texture,5);
        value.dyn.push_back({1,2,3,true});
        value.tex_ids.push_back({4,image});
        value.stor.push_back({5,6,7,8});
        value.texel.push_back({texture,9,10,11,12,13});
        auto &pin=memo_pinned[si][value.set];pin.layout=value.set%3;++pin.refs;
        desc_memo_slot[si].emplace(std::vector<uint64_t>{si,i,1234},std::move(value));
    }
    // Obsolete records contain raw references whose owners can already be gone.
    // ASan checks that destroying these vectors never reads the referenced data.
    delete image;delete texture;
}
static void assert_returned(unsigned si,size_t count){
    std::unordered_set<uint64_t> sets;
    for(auto &layout:slots[si].used_sets)for(auto set:layout.second){
        assert(set%3==layout.first);assert(sets.insert(set).second);
    }
    assert(sets.size()==(count+1)/2);
}
int main(){
    fill(0,9000);fill(1,73);fill(15,1200);
    auto front=desc_memo_slot[0].begin();auto front_key=front->first;
    uint64_t front_generation=memo_mod_gen;
    desc_memo_local[0]=19;
    memo_unpin_all(0);
    assert(desc_memo_slot[0].empty() && memo_pinned[0].empty());
    assert(desc_memo_retired[0].size()==9000 && !desc_memo_local[0]);
    assert(desc_memo_slot[0].find(front_key)==desc_memo_slot[0].end());
    assert(memo_mod_gen==front_generation+1 && front_generation!=memo_mod_gen);
    assert_returned(0,9000);
    assert(desc_memo_slot[1].size()==73 && desc_memo_slot[15].size()==1200);
    assert(slots[1].used_sets.empty() && slots[15].used_sets.empty());

    memo_unpin_all(1);memo_unpin_all(15);
    assert(retained()==10273);
    uint64_t generation=memo_mod_gen;
    present_boundary(); // Actual cleanup-before-pacer calls, trace off.
    assert(pace_calls==1);
    assert(retained()==10273-512 && memo_mod_gen==generation);
    assert(desc_memo_retired[1].size()==73 && desc_memo_retired[15].size()==1200);
    for(unsigned i=0;i<30;++i)present_boundary();
    assert(!retained());assert_returned(1,73);assert_returned(15,1200);

    // Repeated invalidation retains one obsolete generation for this slot.
    slots[0].used_sets.clear();fill(0,8193);memo_unpin_all(0);
    slots[0].used_sets.clear();fill(0,35);desc_memo_local[0]=11;
    memo_unpin_all(0);
    assert(retained()==35 && desc_memo_slot[0].empty() && !desc_memo_local[0]);
    assert_returned(0,35);
    memo_unpin_all(0);assert(!retained() && memo_pinned[0].empty());

    // The actual disabled-cache submit path performs immediate invalidation.
    slot_index=3;xmemo_enabled=false;fill(3,513);img_cache[1]=2;
    desc_memo_reset();
    assert(img_cache.empty() && desc_memo_slot[3].empty());
    assert(desc_memo_retired[3].size()==513 && memo_pinned[3].empty());
    assert_returned(3,513);
    present_boundary();assert(retained()==1);
    present_boundary();assert(!retained());
    xmemo_enabled=true;

    // CPU metadata shutdown preamble releases every parked slot in full.
    for(unsigned si=0;si<kMaxSlots;++si){fill(si,513+si);memo_unpin_all(si);}
    assert(retained()>8192);
    destroy_slots();assert(!retained());
    for(unsigned si=0;si<kMaxSlots;++si){
        assert(desc_memo_slot[si].empty() && memo_pinned[si].empty());
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            code = path / 'memo.cpp'
            code.write_text(program)
            executable = path / 'memo'
            result = subprocess.run([
                shutil.which('clang++') or 'c++', '-std=c++17', '-O1',
                '-fsanitize=address,undefined',
                '-I', str(ROOT / 'src/graphics/nvn_vulkan/nvn'),
                str(code), '-o', str(executable),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
