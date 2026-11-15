import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class TextFilterTests(unittest.TestCase):
    def test_game_function_keeps_original_instructions(self):
        source = (ROOT / 'src/runtime/hle/guest_process.c').read_text()
        start = source.index('static void guest_process_text_filter(')
        end = source.index('\nstruct nso_result guest_process_load', start)
        program = r'''
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
struct guest_tp_patch_report {size_t patched;};
static unsigned translations,registrations;
static void guest_tp_patch_text(void *text,size_t bytes,struct guest_tp_patch_report *report){
    (void)text;(void)bytes;report->patched=0;++translations;
}
static void guest_tp_register_text(void *text,size_t bytes){
    (void)text;(void)bytes;++registrations;
}
''' + source[start:end] + r'''
int main(void){
    size_t size=0x600000;
    uint32_t *text=calloc(1,size);assert(text);
    text[0x945a0/4]=0xd10183ff;
    text[0x945a4/4]=0xa9057bfd;
    guest_process_text_filter(text,size,NULL);
    assert(translations==1 && registrations==1);
    assert(text[0x945a0/4]==0xd10183ff && text[0x945a4/4]==0xa9057bfd);
    const size_t sites[]={0x56952c,0x569540,0x56955c,0x569570};
    const uint32_t original[]={0xb400064d,0xb400028e,0xb40004ed,0xb400012e};
    const uint32_t legacy[]={0xb600064d,0xb600028e,0xb60004ed,0xb600012e};
    unsetenv("SNK_ORIGINAL_POINTER_TESTS");
    for(unsigned i=0;i<4;i++)text[sites[i]/4]=original[i];
    guest_process_text_filter(text,size,NULL);
    for(unsigned i=0;i<4;i++)assert(text[sites[i]/4]==legacy[i]);
    setenv("SNK_ORIGINAL_POINTER_TESTS","1",1);
    for(unsigned i=0;i<4;i++)text[sites[i]/4]=original[i];
    guest_process_text_filter(text,size,NULL);
    for(unsigned i=0;i<4;i++)assert(text[sites[i]/4]==original[i]);
    /* Both halves are valid in the observed 12 GiB arena. */
    assert((UINT64_C(0x6bfa800000)>>32)&1);
    assert(!((UINT64_C(0x6c00785270)>>32)&1));
    free(text);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'text_filter.c').write_text(program)
            executable = path / 'text_filter'
            subprocess.run([shutil.which('clang') or 'cc', '-std=c11',
                            '-fsanitize=address,undefined', str(path / 'text_filter.c'),
                            '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
