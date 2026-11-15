import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class LightEventClockTests(unittest.TestCase):
    def test_timeout_signal_and_clear_modes(self):
        source = (ROOT / 'src/runtime/hle/snk_hle.c').read_text()
        start = source.index('enum snk_sync_kind ')
        end = source.index('/* nn::os::InitializeLightSemaphore', start)
        implementation = source[start:end]
        program = r'''
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <assert.h>
''' + implementation + r'''
static double now_ms(void) {
    struct timespec value;clock_gettime(CLOCK_MONOTONIC,&value);
    return value.tv_sec*1000.0+value.tv_nsec/1000000.0;
}
static void *signal_later(void *object) {
    struct timespec delay={0,20000000};nanosleep(&delay,NULL);
    snk_signal_light_event(object);return NULL;
}
int main(void) {
    int automatic=0,manual=0;
    snk_initialize_light_event(&automatic,false,1);
    double start=now_ms();
    assert(!snk_timed_wait_light_event(&automatic,80000000));
    double elapsed=now_ms()-start;
    assert(elapsed>=60.0 && elapsed<1000.0);
    pthread_t worker;
    assert(!pthread_create(&worker,NULL,signal_later,&automatic));
    start=now_ms();
    assert(snk_timed_wait_light_event(&automatic,1000000000));
    elapsed=now_ms()-start;
    assert(elapsed>=10.0 && elapsed<900.0);
    pthread_join(worker,NULL);
    assert(!snk_timed_wait_light_event(&automatic,0));
    snk_initialize_light_event(&manual,true,0);
    assert(snk_timed_wait_light_event(&manual,0));
    assert(snk_timed_wait_light_event(&manual,0));
    snk_clear_light_event(&manual);
    assert(!snk_timed_wait_light_event(&manual,0));
    snk_finalize_light_event(&manual);
    snk_finalize_light_event(&automatic);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'light_event.c').write_text(program)
            executable = path / 'light_event'
            subprocess.run([shutil.which('clang') or 'cc', '-std=c11',
                            '-D_DARWIN_C_SOURCE', '-D_POSIX_C_SOURCE=200809L',
                            '-fsanitize=address,undefined', '-pthread',
                            str(path / 'light_event.c'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
