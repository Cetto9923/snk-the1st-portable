import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class RenderProfileTests(unittest.TestCase):
    def test_audited_native_selector_and_rejection_paths(self):
        source = (ROOT / 'src/runtime/hle/guest_process.c').read_text()
        start = source.index('void guest_process_apply_snk_render_height(')
        end = source.index('\nstatic struct guest_os_tls_invoke_result', start)
        program = r'''
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
struct nso_module {uint8_t *image; size_t size; const char *build;};
typedef struct {struct nso_module *module; int snk_render_profile_applied;} guest_process;
static guest_process *current_process;
static void nso_build_id(struct nso_module *m,char out[33]){memcpy(out,m->build,33);}
static size_t nso_image_size(struct nso_module *m){return m->size;}
static uint64_t nso_base(struct nso_module *m){return (uintptr_t)m->image;}
''' + source[start:end] + r'''
int main(void){
    struct nso_module m={calloc(1,0x726000),0x726000,"4f4fd1aed39eb96a649aba489ad3767d"};
    assert(m.image);
    guest_process p={&m,0};
    guest_process_apply_snk_render_height(540);
    current_process=&p;
    uint8_t *config=m.image+0x7251b0;
    uint32_t width=1600,height=900,index=5;
    memcpy(config+0x1b4,&width,4);memcpy(config+0x1b8,&height,4);
    memcpy(config+0x1e8,&index,4);
    uint8_t before[0x224];memcpy(before,config,sizeof(before));
    guest_process_apply_snk_render_height(540);
    assert(!p.snk_render_profile_applied && !memcmp(before,config,sizeof(before)));
    config[0x1f0]=1;memcpy(before,config,sizeof(before));
    guest_process_apply_snk_render_height(1080);
    assert(!p.snk_render_profile_applied && !memcmp(before,config,sizeof(before)));
    m.build="00000000000000000000000000000000";
    guest_process_apply_snk_render_height(540);
    assert(!p.snk_render_profile_applied && !memcmp(before,config,sizeof(before)));
    m.build="4f4fd1aed39eb96a649aba489ad3767d";m.size=0x7253d3;
    guest_process_apply_snk_render_height(540);
    assert(!p.snk_render_profile_applied && !memcmp(before,config,sizeof(before)));
    m.size=0x726000;config[0x1b4]=0;
    guest_process_apply_snk_render_height(540);
    assert(!p.snk_render_profile_applied);memcpy(config,before,sizeof(before));
    guest_process_apply_snk_render_height(540);
    memcpy(&index,config+0x1e8,4);
    assert(p.snk_render_profile_applied && index==2 && config[0x1f1]==1 && config[0x1f2]==1);
    for(size_t i=0;i<sizeof(before);i++){
        if((i>=0x1e8 && i<0x1ec) || i==0x1f1 || i==0x1f2)continue;
        assert(config[i]==before[i]);
    }
    guest_process_apply_snk_render_height(720);memcpy(&index,config+0x1e8,4);assert(index==2);
    p.snk_render_profile_applied=0;
    guest_process_apply_snk_render_height(720);memcpy(&index,config+0x1e8,4);assert(index==3);
    p.snk_render_profile_applied=0;
    memcpy(before,config,sizeof(before));
    guest_process_apply_snk_render_height(480);
    assert(!p.snk_render_profile_applied && !memcmp(before,config,sizeof(before)));
    guest_process_apply_snk_render_height(450);memcpy(&index,config+0x1e8,4);
    assert(p.snk_render_profile_applied && index==1 && config[0x1f1]==1 && config[0x1f2]==1);
    for(size_t i=0;i<sizeof(before);i++){
        if(i>=0x1e8 && i<0x1ec)continue;
        assert(config[i]==before[i]);
    }
    free(m.image);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'render_profile.c').write_text(program)
            executable = path / 'render_profile'
            subprocess.run([shutil.which('clang') or 'cc', '-std=c11',
                            '-fsanitize=address,undefined', str(path / 'render_profile.c'),
                            '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
