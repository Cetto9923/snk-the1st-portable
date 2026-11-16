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


class TextureDescriptorIndexTests(unittest.TestCase):
    def test_actual_registration_lookup_growth_and_stable_memo_references(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('struct RegisteredTexture{')
        end = source.index('struct HostSegment{', start)
        definitions = source[start:end]
        registration = '\n'.join(block(source, name) for name in [
            'static void xbg_register_texture_now(',
            'extern "C" void xbg_legacy_register_texture(',
        ])
        lookup = block(source, 'else{PoolKey pk=pool_key(&state.texture_pool);')[4:]
        start = source.index('auto pool=textures.find(pool_key(&state.texture_pool));',
                             source.index('bool indexed_graphics_ready('))
        eligibility = source[start:source.index('\n', start)]
        program = r'''
#include "nvn_obj.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <map>
#include <mutex>
#include <unordered_map>
#include <vector>
struct Image {};
static std::recursive_mutex mutex;
static uint64_t memo_bump[5]{};
static void need(bool value,const char *) { assert(value); }
template<class... T> static void xbg_fatalf(const char *,T...) { std::abort(); }
''' + definitions + registration + r'''
static struct { dpool_t texture_pool; } state;
static const RegisteredTexture *resolve(const dpool_t &bound_pool,int id) {
    state.texture_pool=bound_pool;
    const RegisteredTexture *record=nullptr;
    unsigned ns=0,slot=0;
''' + lookup + r'''
    return record;
}
static bool eligible(const dpool_t &bound_pool,int id,uint64_t expected_serial) {
    state.texture_pool=bound_pool;
''' + eligibility + r'''
    return t.serial==expected_serial;
}
int main() {
    pool_t memory[2]{};
    memory[0].mem=reinterpret_cast<uint8_t *>(0x10000);
    memory[1].mem=reinterpret_cast<uint8_t *>(0x20000);
    dpool_t a{&memory[0],0,1<<20}, b{&memory[0],4096,1<<20};
    dpool_t c{&memory[1],0,1<<20}, legacy{&memory[1],8192,1<<20};
    tex_t texture{}; texture.serial=17;texture.mem=memory[0].mem;
    view_t view{};view.set_levels=1;view.nlevels=1;
    constexpr int id=10240;
    xbg_register_texture_now(&a,id,&texture,&view);
    const RegisteredTexture *record=resolve(a,id);
    const tex_t *saved_texture=&record->texture;
    Image image;
    MemoImage memo(saved_texture,&image,record,record->revision);
    uint64_t generation=memo_check_gen;
    xbg_register_texture_now(&a,id,&texture,&view);
    assert(memo_check_gen==generation && resolve(a,id)==record);
    texture.serial=23;
    xbg_register_texture_now(&b,id,&texture,nullptr);
    texture.serial=31;
    xbg_register_texture_now(&c,id,&texture,nullptr);
    texture.serial=47;
    xbg_legacy_register_texture(id,&texture,&view);
    assert(resolve(b,id)->texture.serial==23);
    assert(resolve(c,id)->texture.serial==31);
    assert(resolve(legacy,id)->texture.serial==47);
    assert(resolve(a,id)==record && record->texture.serial==17);
    assert(eligible(a,id,17) && eligible(b,id,23));
    assert(eligible(c,id,31) && eligible(legacy,id,47));
    assert(!eligible(a,id+1,0) && !eligible(legacy,id+1,0));
    std::vector<const RegisteredTexture *> records;
    for (int i=0;i<16384;i++) {
        texture.serial=1000+i;
        xbg_register_texture_now(&a,32768+i,&texture,nullptr);
        records.push_back(resolve(a,32768+i));
    }
    auto &table=textures.at(pool_key(&a));
    table.rehash(table.bucket_count()*3+1);
    assert(resolve(a,id)==record && &record->texture==saved_texture);
    assert(memo.first==saved_texture && memo.record==record);
    assert(memo.definition.texture.serial==17 && record->texture.serial==17);
    for (int i=0;i<16384;i++) {
        assert(resolve(a,32768+i)==records[i]);
        assert(records[i]->texture.serial==uint64_t(1000+i));
    }
    texture.serial=71;view.base_level=2;
    xbg_register_texture_now(&a,id,&texture,&view);
    assert(resolve(a,id)==record && record->texture.serial==71);
    assert(record->revision>memo.revision && record->view.base_level==2);
    assert(!registered_texture_equal(memo.definition,*record));
    assert(resolve(b,id)->texture.serial==23 && resolve(c,id)->texture.serial==31);
    assert(resolve(legacy,id)->texture.serial==47);
    textures.clear();legacy_textures.clear();texture_pool_cache=nullptr;
    texture.serial=99;
    xbg_register_texture_now(&a,id,&texture,nullptr);
    assert(resolve(a,id)->texture.serial==99 && eligible(a,id,99));
    textures.clear();legacy_textures.clear();texture_pool_cache=nullptr;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'index.cpp').write_text(program)
            executable = path / 'index'
            built = subprocess.run([
                'clang++', '-std=c++17', '-fsanitize=address,undefined',
                '-I', str(ROOT / 'src/graphics/nvn_vulkan/nvn'),
                str(path / 'index.cpp'), '-o', str(executable),
            ], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
