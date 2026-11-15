import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class DockedBootTests(unittest.TestCase):
    def test_boot_forces_docked_independently_of_render_height_and_tablet(self):
        source = (ROOT / 'src/android/native/guest_boot_jni.cpp').read_text()
        start = source.index('        // All device tiers use the requested docked game mode.')
        boot = source[start:source.index('        const std::string pointer_marker', start)]
        start = source.index('Java_org_snk_the1st_GameWindowNative_setProfileRenderHeight(')
        start = source.index('{', start) + 1
        render = source[start:source.index('\n}', start)]
        host = (ROOT / 'src/runtime/hle/nso_host.c').read_text()
        start = host.index('static uint32_t s_oe_operation_mode =')
        end = host.index('\n/* ===', start)
        program = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#define fopen foreign_package_file_reads_are_forbidden
''' + host[start:end] + r'''
#undef fopen
void configure_render(int height) {
''' + render + r'''
}
void boot() {
''' + boot + r'''
}
int main() {
    // Standalone HLE diagnostics keep an explicit mode override.
    setenv("FFRS_OPERATION_MODE","0",1);assert(nso_host_oe_get_operation_mode()==0);
    for(const char *tablet:{"0","1"})for(int height:{0,540,720,1080,-1}) {
        setenv("FFRS_PROFILE_TABLET",tablet,1);
        setenv("FFRS_PROFILE_OPERATION_MODE","0",1);
        setenv("FFRS_OPERATION_MODE","0",1);
        configure_render(height);boot();
        assert(nso_host_oe_get_operation_mode()==1);
        assert(!strcmp(getenv("FFRS_PROFILE_TABLET"),tablet));
        const char *wanted=height==540?"540":height==720?"720":"0";
        assert(!strcmp(getenv("FFRS_PROFILE_RENDER_HEIGHT"),wanted));
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'docked.cpp').write_text(program)
            executable = path / 'docked'
            subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                            str(path / 'docked.cpp'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
