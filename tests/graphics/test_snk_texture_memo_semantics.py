import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def block(source, signature):
    begin = source.index(signature)
    opening = source.index('{', begin)
    end = opening + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[begin:end]


class TextureMemoSemanticsTests(unittest.TestCase):
    def test_actual_memo_validation_accepts_equivalent_rebinding_and_rejects_changes(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        begin = source.index('struct RegisteredTexture{')
        end = source.index('\nusing PoolKey=', begin)
        definitions = source[begin:end]
        validation = block(source, 'if(same && (m.checked_gen!=memo_check_gen || ab_off("hitgen")))')
        program = r'''
#include "nvn_obj.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <utility>
#include <vector>
struct Image {};
''' + definitions + r'''
struct Memo {
    std::vector<MemoImage> images;
    std::vector<std::pair<uint64_t,const void *>> tex_ids;
    uint64_t checked_gen=0;
};
static Image image, replacement;
static Image *live_image=&image;
static Image *find_image(uint64_t){return live_image;}
static bool ab_off(const char *){return false;}

static bool validate(Memo &m){bool same=true;
''' + validation + r'''
return same;}

int main(){
    tex_t texture{};
    texture.serial=17;
    texture.mem=reinterpret_cast<uint8_t *>(0x10000);
    texture.pool=reinterpret_cast<pool_t *>(0x20000);
    texture.off=64;
    texture.d.width=64;texture.d.height=64;texture.d.depth=1;texture.d.levels=4;
    texture.d.target=1;texture.d.format=0x37;
    texture.L.size=16384;texture.L.layer_size=16384;texture.L.layers=1;
    texture.L.align=512;texture.L.bpb=4;texture.L.tileH=1;texture.L.tileD=1;
    view_t first{};first.set_levels=1;first.base_level=0;first.nlevels=1;
    RegisteredTexture record;
    assert(register_texture_record(record,texture,&first));
    uint64_t version=record.revision;
    assert(!register_texture_record(record,texture,&first) && record.revision==version);
    Memo memo;
    memo.images.push_back({&record.texture,&image,&record,record.revision});
    memo.tex_ids.push_back({record.texture.serial,record.texture.mem});
    assert(validate(memo));
    view_t second=first;second.base_level=1;
    assert(register_texture_record(record,texture,&second));
    assert(!validate(memo));
    assert(memo.images[0].definition.view.base_level==0);
    assert(register_texture_record(record,texture,&first));
    assert(record.revision>version);
    assert(validate(memo));
    assert(memo.images[0].revision==record.revision);
    assert(memo.checked_gen==memo_check_gen);

    // A new physical image still invalidates a semantically identical record.
    live_image=&replacement;++memo_check_gen;
    assert(!validate(memo));
    live_image=&image;++memo_check_gen;
    assert(validate(memo));

    const RegisteredTexture original=record;
    auto difference=[&](auto mutate){
        RegisteredTexture changed=original;mutate(changed);
        assert(!registered_texture_equal(original,changed));
    };
    difference([](auto &r){++r.texture.serial;});
    difference([](auto &r){r.texture.mem=reinterpret_cast<uint8_t *>(0x30000);});
    difference([](auto &r){r.texture.pool=reinterpret_cast<pool_t *>(0x40000);});
    difference([](auto &r){++r.texture.off;});
    difference([](auto &r){++r.texture.d.target;});
    difference([](auto &r){++r.texture.d.format;});
    difference([](auto &r){++r.texture.d.flags;});
    difference([](auto &r){++r.texture.d.samples;});
    difference([](auto &r){++r.texture.d.width;});
    difference([](auto &r){++r.texture.d.height;});
    difference([](auto &r){++r.texture.d.depth;});
    difference([](auto &r){++r.texture.d.levels;});
    difference([](auto &r){++r.texture.d.stride;});
    difference([](auto &r){++r.texture.d.pkg_block_h;});
    difference([](auto &r){++r.texture.L.size;});
    difference([](auto &r){++r.texture.L.layer_size;});
    difference([](auto &r){++r.texture.L.align;});
    difference([](auto &r){++r.texture.L.layers;});
    difference([](auto &r){++r.texture.L.bpb;});
    difference([](auto &r){++r.texture.L.tileH;});
    difference([](auto &r){++r.texture.L.tileD;});
    difference([](auto &r){r.texture.has_layout=1;});
    difference([](auto &r){r.texture.set_swz=1;});
    difference([](auto &r){r.texture.stencil=1;});
    difference([](auto &r){r.has_view=false;});
    difference([](auto &r){++r.view.base_level;});
    difference([](auto &r){++r.view.nlevels;});
    difference([](auto &r){r.view.set_layers=1;});
    difference([](auto &r){r.view.set_format=1;});
    difference([](auto &r){r.view.set_target=1;});
    difference([](auto &r){r.view.set_dsmode=1;});
    difference([](auto &r){r.view.set_swizzle=1;});

    RegisteredTexture unused=original;
    unused.view.min_layer=3;unused.view.nlayers=5;unused.view.format=7;
    unused.view.target=9;unused.view.dsmode=1;unused.view.swz[0]=5;
    unused.texture.swz=0xfff;
    assert(registered_texture_equal(original,unused));
    RegisteredTexture active=original;
    active.texture.has_layout=1;active.texture.set_swz=1;
    active.view.set_layers=active.view.set_format=active.view.set_target=1;
    active.view.set_dsmode=active.view.set_swizzle=1;
    auto active_difference=[&](auto mutate){
        RegisteredTexture changed=active;mutate(changed);
        assert(!registered_texture_equal(active,changed));
    };
    active_difference([](auto &r){++r.texture.layout[0];});
    active_difference([](auto &r){++r.texture.swz;});
    active_difference([](auto &r){++r.view.min_layer;});
    active_difference([](auto &r){++r.view.nlayers;});
    active_difference([](auto &r){++r.view.format;});
    active_difference([](auto &r){++r.view.target;});
    active_difference([](auto &r){r.view.dsmode=1;});
    active_difference([](auto &r){++r.view.swz[0];});

    // Existing semantic comparison ignores revision numbers and inactive payload.
    RegisteredTexture identical=original;identical.revision+=1000;
    assert(registered_texture_equal(original,identical));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            code = path / 'memo.cpp'
            code.write_text(program)
            executable = path / 'memo'
            result = subprocess.run([
                shutil.which('clang++') or 'c++', '-std=c++17',
                '-fsanitize=address,undefined',
                '-I', str(ROOT / 'src/graphics/nvn_vulkan/nvn'),
                str(code), '-o', str(executable),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
