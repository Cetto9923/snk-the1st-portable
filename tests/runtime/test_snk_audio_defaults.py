import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class AudioDefaultTests(unittest.TestCase):
    def test_fresh_install_and_explicit_disable(self):
        source = (ROOT / 'src/runtime/hle/snk_hle_media.c').read_text()
        start = source.index('static int snk_mix_probe(void) {')
        end = source.index('\nstatic int snk_mix_open_output', start)
        program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <limits.h>
#include <string.h>
#include <unistd.h>
static struct { int state; } s_mix;
static uint64_t (*s_mix_open)(void *, void *, const void *);
static uint64_t (*s_mix_start)(void *);
static uint64_t (*s_mix_append)(void *, void *);
static void *(*s_mix_released)(void *);
static const char *directory;
static int bridge_available = 1;
static const char *ffrs_audio_platform_directory(void) { return directory; }
static uint64_t ffrs_audio_lookup(const char *name, unsigned *args, unsigned *rets) {
    (void)name; (void)args; (void)rets;
    return bridge_available ? 1 : 0;
}
''' + source[start:end] + r'''
int main(int argc, char **argv) {
    assert(argc == 2);
    directory = argv[1];
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "%s/snk-audio-mix", directory);
    assert(snk_mix_probe() == 1);
    const char *values[] = {"0", "1", ""};
    for (unsigned i = 0; i < 3; ++i) {
        FILE *file = fopen(path, "wb"); assert(file);
        fputs(values[i], file); fclose(file);
        s_mix.state = 0;
        assert(snk_mix_probe() == (i != 0));
    }
    unlink(path);
    directory = NULL; s_mix.state = 0;
    assert(snk_mix_probe() == 1);
    bridge_available = 0; s_mix.state = 0;
    assert(snk_mix_probe() == 0);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'test.c').write_text(program)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            str(root / 'test.c'), '-o', str(root / 'test')], check=True)
            subprocess.run([str(root / 'test'), directory], check=True)
