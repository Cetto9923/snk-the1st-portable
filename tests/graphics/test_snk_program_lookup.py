import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class ProgramLookupTests(unittest.TestCase):
    def test_growth_collisions_finalize_reuse_and_reset(self):
        source = (ROOT / 'src/graphics/nvn_device/nvn_program.c').read_text()
        begin = source.index('typedef struct {\n    void *program;')
        end = source.index('/* Take one stage', begin)
        program = r'''
#include "nvn_program.h"
#include "nvn_object_table.h"
#include <stdint.h>
#include <pthread.h>
#include <assert.h>
#define NVN_PROGRAM_MAX_STAGES 6
#define NVN_PROGRAM_CONTROL_SIZE 0x880
#define NVN_PROGRAM_MAX_OBJECTS 4096
''' + source[begin:end] + r'''
static void *key(unsigned i){return (void*)(uintptr_t)(0x100000+i*160);}
int main(void){
    assert(!program_find(NULL,1));
    assert(!program_find(key(1),0));
    for(unsigned i=1;i<=3000;++i){
        nvn_program_state *p=program_find(key(i),1);assert(p);
        p->serial=i;
    }
    for(unsigned pass=0;pass<3;++pass)for(unsigned i=1;i<=3000;++i){
        nvn_program_state *p=program_find(key(i),0);
        assert(p && p->serial==i && p->program==key(i));
    }
    // Find two distinct keys mapping to the same direct-mapped slot.
    unsigned a=1,b=2;
    uintptr_t target=((uintptr_t)key(a)>>4)^((uintptr_t)key(a)>>13);
    for(;b<3000;++b){uintptr_t hash=((uintptr_t)key(b)>>4)^((uintptr_t)key(b)>>13);
        if((hash&255)==(target&255))break;}
    assert(b<3000);
    for(unsigned n=0;n<100;++n){assert(program_find(key(a),0)->serial==a);assert(program_find(key(b),0)->serial==b);}
    nvn_program_state *old=program_find(key(a),0);old->in_use=0;
    assert(!program_find(key(a),0));
    nvn_program_state *reused=program_find(key(4000),1);assert(reused==old);
    reused->serial=4000;
    assert(!program_find(key(a),0));
    assert(program_find(key(4000),0)->serial==4000);
    nvn_program_state *again=program_find(key(a),1);assert(again && again!=old);
    assert(again->serial==0);again->serial=9999;
    assert(program_find(key(a),0)->serial==9999);
    // Index validation must reject a stale cache entry after freeing the table.
    nvn_object_table_free(&s_programs);
    assert(!program_find(key(4000),0));
    nvn_program_state *fresh=program_find(key(4000),1);
    assert(fresh && fresh->serial==0);
    nvn_object_table_free(&s_programs);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'program.c').write_text(program)
            executable = path / 'program'
            subprocess.run([shutil.which('clang') or 'cc', '-std=c11',
                            '-fsanitize=address,undefined', '-pthread', '-I',
                            str(ROOT / 'src/graphics/nvn_device'), str(path / 'program.c'),
                            '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
