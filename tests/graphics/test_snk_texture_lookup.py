import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class TextureLookupTests(unittest.TestCase):
    def test_growth_collisions_real_initialize_finalize_and_reuse(self):
        source = (ROOT / 'src/graphics/nvn_device/nvn_texture.c').read_text()
        begin = source.index('typedef struct {\n    void *texture;')
        end = source.index('/* Mark a name as logged', begin)
        state = source[begin:end]
        functions = ''
        for signature in ('int nvnTextureInitialize(', 'void nvnTextureFinalize(',
                          'int nvn_texture_info_of('):
            begin = source.index(signature)
            # Function bodies include comments. Extract by brace balance.
            opening = source.index('{', begin)
            depth = 1
            end = opening + 1
            while depth:
                depth += (source[end] == '{') - (source[end] == '}')
                end += 1
            functions += source[begin:end] + '\n'
        program = r'''
#include "nvn_texture.h"
#include "nvn_device.h"
#include "../nvn/include/nvn/nvn.h"
#include "nvn_texture_builder.h"
#include "nvn_object_table.h"
#include "nvn_obj_ffrs.h"
#include <pthread.h>
#include <inttypes.h>
#include <stdio.h>
#include <assert.h>
static unsigned table_reads;
static void *counted_table_at(nvn_object_table *table,size_t index){
    ++table_reads;return nvn_object_table_at(table,index);
}
#define nvn_object_table_at counted_table_at
''' + state + r'''
static int mark_logged(int index){(void)index;return 0;}
static int snapshot_builder(nvn_texture_state *state,const void *builder){
    state->width=37;return builder!=NULL;
}
int nvn_texture_builder_layout_of(const void *builder,uint64_t *size,uint32_t *alignment,int *height){
    (void)size;(void)alignment;*height=0;return builder!=NULL;
}
uint32_t nvn_device_generate_debug_domain_id(void *device,const char *label){
    (void)device;(void)label;return 9;
}
static unsigned ended;
void nvn_bridge_texture_end(const void *,uint64_t) __attribute__((weak));
void nvn_bridge_texture_end(const void *texture,uint64_t serial){
    assert(texture && serial);++ended;
}
''' + functions + r'''
static void *key(unsigned i){return (void*)(uintptr_t)(0x100000+i*160);}
static unsigned bucket(unsigned i){
    return ((((uint64_t)(uintptr_t)key(i)>>4)*UINT64_C(11400714819323198485))>>55);
}
static void check(unsigned i){
    nvn_texture_info info;
    assert(nvn_texture_info_of(key(i),&info));
    assert(info.d.width==37 && info.serial);
    assert(texture_find(key(i),0)->texture==key(i));
}
int main(void){
    assert(!texture_find(NULL,1));assert(!texture_find(key(1),0));
    for(unsigned i=1;i<=3000;++i)assert(nvnTextureInitialize(key(i),(void*)1));
    table_reads=0;
    for(unsigned pass=0;pass<3;++pass)for(unsigned i=1;i<=3000;++i)check(i);
    assert(table_reads<18000*32);
    check(1);table_reads=0;
    for(unsigned pass=0;pass<100;++pass)check(1);
    assert(table_reads==200);
    unsigned a=1,b=2;
    for(;b<=3000 && bucket(a)!=bucket(b);++b){}
    assert(b<=3000);
    // Publishing a real initialization must preserve the collision link.
    uint64_t old_serial=texture_find(key(b),0)->serial;
    assert(nvnTextureInitialize(key(b),(void*)1));
    assert(texture_find(key(b),0)->serial>old_serial && ended);
    for(unsigned i=1;i<=3000;++i)check(i);
    nvn_texture_state *old=texture_find(key(a),0);
    nvnTextureFinalize(key(a));assert(!texture_find(key(a),0));
    nvn_texture_info missing;
    assert(!nvn_texture_info_of(key(a),&missing));
    assert(nvnTextureInitialize(key(4000),(void*)1));
    assert(texture_find(key(4000),0)==old);check(4000);
    assert(nvnTextureInitialize(key(a),(void*)1));check(a);
    for(unsigned i=1;i<=1000;++i)nvnTextureFinalize(key(i));
    for(unsigned i=1;i<=1000;++i)assert(nvnTextureInitialize(key(6000+i),(void*)1));
    for(unsigned i=1;i<=1000;++i){assert(!texture_find(key(i),0));check(6000+i);}
    for(unsigned i=1001;i<=3000;++i)check(i);
    nvn_object_table_free(&s_textures);
    assert(!texture_find(key(4000),0));
    assert(nvnTextureInitialize(key(4000),(void*)1));check(4000);
    nvn_object_table_free(&s_textures);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            source_path = path / 'texture.c'
            source_path.write_text(program)
            executable = path / 'texture'
            build = subprocess.run([
                shutil.which('clang') or 'cc', '-std=c11',
                '-fsanitize=address,undefined', '-pthread', '-I',
                str(ROOT / 'src/graphics/nvn_device'), str(source_path),
                '-o', str(executable),
            ], capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr.decode())
            result = subprocess.run([str(executable)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
