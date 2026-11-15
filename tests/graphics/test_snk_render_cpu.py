import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class RenderCpuTests(unittest.TestCase):
    def test_reapplies_explicit_selection_after_platform_reset(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('void gfx_worker_cpu_update(){')
        end = source.index('void gfx_worker_loop(){', start)
        implementation = source[start:end]
        program = r'''
#define __ANDROID__ 1
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <cerrno>
#include <cstdlib>

using cpu_set_t = uint64_t;
#define CPU_SETSIZE 8
#define CPU_ZERO(set) (*(set) = 0)
#define CPU_SET(cpu, set) (*(set) |= uint64_t(1) << (cpu))
#define CPU_ISSET(cpu, set) ((*(set) >> (cpu)) & 1)
#define CPU_COUNT(set) __builtin_popcountll(*(set))
static cpu_set_t actual_mask = 0x7f;
static int sets, fail;
static bool gfx_async = true, gfx_is_worker = true;
static struct {const char *shader_directory;} cfg;
static int sched_getaffinity(int thread, size_t bytes, cpu_set_t *out) {
    assert(thread == 0 && bytes == sizeof(cpu_set_t));
    *out = actual_mask;
    return 0;
}
static int sched_setaffinity(int thread, size_t bytes, const cpu_set_t *mask) {
    assert(thread == 0 && bytes == sizeof(cpu_set_t));
    if (fail) return -1;
    actual_mask = *mask;
    sets++;
    return 0;
}
static void xbg_logf(const char *, ...) {}
''' + implementation + r'''
static void check() {
    for (int i = 0; i < 60; ++i) gfx_worker_cpu_update();
}
static void marker(const std::string &path, int value) {
    FILE *file = fopen(path.c_str(), "wb");
    assert(file);
    fprintf(file, "%d", value);
    fclose(file);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    std::string directory = argv[1];
    std::string shaders = directory + "/shaders";
    std::string path = directory + "/gfx-render-cpu";
    cfg.shader_directory = shaders.c_str();
    check();
    assert(sets == 0 && actual_mask == 0x7f);
    marker(path, 7);
    check();
    assert(sets == 1 && actual_mask == 0x80);
    check();
    assert(sets == 1);
    actual_mask = 0x7f;
    check();
    assert(sets == 2 && actual_mask == 0x80);
    actual_mask = 0xff;
    fail = 1;
    check();
    assert(sets == 2 && actual_mask == 0xff);
    fail = 0;
    check();
    assert(sets == 3 && actual_mask == 0x80);
    assert(!remove(path.c_str()));
    check();
    assert(sets == 4 && actual_mask == 0x7f);
    actual_mask = 0x3f;
    check();
    assert(sets == 4 && actual_mask == 0x3f);
    marker(path, 99);
    check();
    assert(sets == 4);
    marker(path, 6);
    gfx_is_worker = false;
    check();
    assert(sets == 4);
    gfx_is_worker = true;
    gfx_async = false;
    check();
    assert(sets == 4);
    gfx_async = true;
    check();
    assert(sets == 5 && actual_mask == 0x40);
    puts("render_cpu_contract platform_reset_reapplied=2 errors=0");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'render_cpu.cpp').write_text(program)
            executable = path / 'render_cpu'
            subprocess.run([
                shutil.which('clang++') or 'c++', '-std=c++17',
                '-fsanitize=address,undefined', str(path / 'render_cpu.cpp'),
                '-o', str(executable),
            ], check=True, capture_output=True)
            result = subprocess.run([str(executable), str(path)], check=True,
                                    capture_output=True, text=True)
            self.assertIn('errors=0', result.stdout)


if __name__ == '__main__':
    unittest.main()
