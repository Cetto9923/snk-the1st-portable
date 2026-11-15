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
