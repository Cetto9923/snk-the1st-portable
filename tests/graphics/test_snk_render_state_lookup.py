import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class RenderStateLookupTests(unittest.TestCase):
    def test_growth_raw_copies_families_collisions_and_reuse(self):
        source = (ROOT / 'src/graphics/nvn_device/nvn_render_state.c').read_text()
        begin = source.index('/* The enumeration values')
        end = source.index('/* The boilerplate the setters share.', begin)
        program = r'''
#include "nvn_render_state.h"
#include "nvn_object_table.h"
#include "nvn_packed_state.h"
#include <stdint.h>
#include <pthread.h>
#include <assert.h>
''' + source[begin:end] + r'''
static uint64_t objects[4002][2];
static unsigned bucket(unsigned i,int family){
    uintptr_t key=(uintptr_t)objects[i];
    return ((key>>4)^(key>>13)^(uint32_t)family)&1023u;
}
static void check_attribute(unsigned i){
    ffrs_va_st raw;memcpy(&raw,objects[i],sizeof(raw));
    nvn_rs_value *v=state_find(objects[i],NVN_RS_VERTEX_ATTRIB,0);
    assert(v && v->object==objects[i] && v->family==NVN_RS_VERTEX_ATTRIB);
    assert(v->va_format==raw.fmt && v->va_offset==raw.offset && v->va_stream_index==raw.stream);
}
int main(void){
    assert(!state_find(NULL,NVN_RS_VERTEX_ATTRIB,1));
    nvn_rs_value *metadata=state_find(objects[10],NVN_RS_MULTISAMPLE,1);
    metadata->ms_sample_locations_count=2;metadata->ms_sample_locations[0][0]=0.25f;
    for(unsigned i=1;i<=3000;++i){
        ffrs_va_st raw={i%255,i*4,i%32};memcpy(objects[i],&raw,sizeof(raw));
        check_attribute(i);
    }
    for(unsigned pass=0;pass<3;++pass)for(unsigned i=1;i<=3000;++i)check_attribute(i);
    // Shadow-only auxiliary fields survive table growth and cache hits.
    metadata=state_find(objects[10],NVN_RS_MULTISAMPLE,0);
    assert(metadata->ms_sample_locations_count==2 && metadata->ms_sample_locations[0][0]==0.25f);
    nvn_rs_value *attribute=state_find(objects[10],NVN_RS_VERTEX_ATTRIB,0);
    assert(attribute!=metadata && attribute->family==NVN_RS_VERTEX_ATTRIB);
    // Ordinary guest copies remain the source for packed value fields.
    ffrs_va_st changed={87,1234,9};memcpy(objects[10],&changed,sizeof(changed));
    check_attribute(10);
    attribute=state_find(objects[10],NVN_RS_VERTEX_ATTRIB,0);
    assert(attribute->va_format==87 && attribute->va_offset==1234);
    unsigned a=1,b=2;
    for(;b<=3000 && bucket(a,NVN_RS_VERTEX_ATTRIB)!=bucket(b,NVN_RS_VERTEX_ATTRIB);++b){}
    assert(b<=3000);
    for(unsigned i=0;i<100;++i){check_attribute(a);check_attribute(b);}
    nvn_rs_value *old=state_find(objects[a],NVN_RS_VERTEX_ATTRIB,0);old->in_use=0;
    changed.fmt=33;memcpy(objects[4000],&changed,sizeof(changed));
    // The original read path creates a record even with create=0.
    nvn_rs_value *reused=state_find(objects[4000],NVN_RS_VERTEX_ATTRIB,0);
    assert(reused==old && reused->va_format==33);
    nvn_rs_value *again=state_find(objects[a],NVN_RS_VERTEX_ATTRIB,0);
    assert(again && again!=old);check_attribute(a);
    nvn_object_table_free(&s_states);
    check_attribute(4000);
    assert(s_states.count==1);
    nvn_object_table_free(&s_states);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            source_path = path / 'state.c'
            source_path.write_text(program)
            executable = path / 'state'
            build = subprocess.run([shutil.which('clang') or 'cc', '-std=c11',
                                    '-fsanitize=address,undefined', '-pthread', '-I',
                                    str(ROOT / 'src/graphics/nvn_device'), str(source_path),
                                    '-o', str(executable)], capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr.decode())
            result = subprocess.run([str(executable)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
