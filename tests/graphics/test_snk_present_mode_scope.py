import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PresentModeScopeTests(unittest.TestCase):
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
