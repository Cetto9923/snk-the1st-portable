import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PresentModeScopeTests(unittest.TestCase):
    def test_actual_rg477m_default_and_explicit_mode_precedence(self):
        source = (ROOT / 'src/graphics/nvn_device/nvn_backend_vulkan.c').read_text()
        begin = source.index('static int nvn_vulkan_rg477m_profile(void)')
        end = source.index('static int nvn_vulkan_present_timing_requested(void)', begin)
        profile = source[begin:end]
        begin = source.index('static FILE *nvn_vulkan_present_mode_marker(void)')
        end = source.index('\ntypedef struct {', begin)
        marker = source[begin:end]
        begin = source.index('                if (has_mailbox) present_mode =')
        end = source.index('                fprintf(stderr, "[nvn] vulkan: selected present mode', begin)
        selection = source[begin:end]
        program = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <string.h>
enum {VK_PRESENT_MODE_IMMEDIATE_KHR=0,VK_PRESENT_MODE_MAILBOX_KHR=1,
      VK_PRESENT_MODE_FIFO_KHR=2,VK_PRESENT_MODE_FIFO_RELAXED_KHR=3};
''' + profile + marker + r'''
static int select_mode(void){
    int has_mailbox=1,has_relaxed=1,has_immediate=1,present_mode=2;
''' + selection + r'''
    return present_mode;
}
int main(int argc,char **argv){
    assert(argc==2);setenv("FFRS_APP_FILES_DIR",argv[1],1);
    unsetenv("FFRS_PRESENT_MODE");unsetenv("FFRS_PROFILE_RG477M");assert(select_mode()==1);
    setenv("FFRS_PROFILE_RG477M","1",1);assert(select_mode()==2);
    setenv("FFRS_PRESENT_MODE","mailbox",1);assert(select_mode()==1);
    char path[PATH_MAX];snprintf(path,sizeof(path),"%s/gfx-present-mode",argv[1]);
    FILE *file=fopen(path,"wb");assert(file);fputs("0",file);fclose(file);
    assert(select_mode()==2);
    unsetenv("FFRS_PRESENT_MODE");
    file=fopen(path,"wb");assert(file);fputs("2",file);fclose(file);
    assert(select_mode()==1);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'mode.c').write_text(program)
            built = subprocess.run(['clang', '-std=c11', '-D_POSIX_C_SOURCE=200809L',
                                    '-fsanitize=address,undefined', str(path / 'mode.c'),
                                    '-o', str(path / 'mode')], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(path / 'mode'), str(path)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_actual_marker_reader_uses_application_directory(self):
        source = (ROOT / 'src/graphics/nvn_device/nvn_backend_vulkan.c').read_text()
        begin = source.index('static FILE *nvn_vulkan_present_mode_marker(void)')
        end = source.index('\ntypedef struct {', begin)
        program = r'''
#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <string.h>
#include <assert.h>
''' + source[begin:end] + r'''
int main(int argc,char **argv){
    assert(argc==2);
    unsetenv("FFRS_APP_FILES_DIR");assert(!nvn_vulkan_present_mode_marker());
    setenv("FFRS_APP_FILES_DIR","",1);assert(!nvn_vulkan_present_mode_marker());
    setenv("FFRS_APP_FILES_DIR",argv[1],1);
    FILE *file=nvn_vulkan_present_mode_marker();assert(file);
    assert(fgetc(file)=='0');fclose(file);
    setenv("FFRS_APP_FILES_DIR","/nonexistent-snk-test-directory",1);
    assert(!nvn_vulkan_present_mode_marker());
    char long_path[PATH_MAX+1];memset(long_path,'a',PATH_MAX);long_path[PATH_MAX]=0;
    setenv("FFRS_APP_FILES_DIR",long_path,1);assert(!nvn_vulkan_present_mode_marker());
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            own = path / 'own'
            own.mkdir()
            (own / 'gfx-present-mode').write_bytes(b'0')
            # A cwd file is never a substitute for the supplied app directory.
            (path / 'gfx-present-mode').write_bytes(b'2')
            code = path / 'scope.c'
            code.write_text(program)
            executable = path / 'scope'
            subprocess.run([
                shutil.which('clang') or 'cc', '-std=c11',
                '-D_POSIX_C_SOURCE=200809L', '-fsanitize=address,undefined',
                str(code), '-o', str(executable),
            ], check=True, capture_output=True)
            subprocess.run([str(executable), str(own)], cwd=path,
                           check=True, capture_output=True)
        self.assertIn('FILE *pm_f = nvn_vulkan_present_mode_marker();', source)
        self.assertNotIn('fopen("/sdcard/Android/data/org.ffrs.', source)
        self.assertNotIn('fopen("/data/data/org.ffrs.', source)
        boot = (ROOT / 'src/android/native/guest_boot_jni.cpp').read_text()
        self.assertIn('setenv("FFRS_APP_FILES_DIR", path.c_str(), 1);', boot)


if __name__ == '__main__':
    unittest.main()
