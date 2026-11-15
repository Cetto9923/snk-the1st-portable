import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class RecursiveMutexTests(unittest.TestCase):
    def test_recursion_collisions_reuse_and_parallel_increment(self):
        source = (ROOT / 'src/runtime/hle/snk_libcxx.c').read_text()
        start = source.index('struct snk_recursive_mutex {')
        end = source.index('/* std::__1::__shared_weak_count', start)
        block = source[start:source.rfind('/* ===', start, end)]
        program = r'''
#include <assert.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
''' + block + r'''
static unsigned char objects[4096][64];
static unsigned value;
static void *increment(void *arg) {
    (void)arg;
    for(unsigned i=0;i<20000;i++) {
        snk_recursive_mutex_lock(objects[0]);snk_recursive_mutex_lock(objects[0]);
        ++value;
        snk_recursive_mutex_unlock(objects[0]);snk_recursive_mutex_unlock(objects[0]);
    }
    return NULL;
}
static void *try_other_thread(void *arg) {
    assert(snk_recursive_mutex_try_lock(arg)==0);return NULL;
}
int main(void) {
    memset(objects,0x5a,sizeof objects);
    for(unsigned i=0;i<4096;i++) {
        snk_recursive_mutex_ctor(objects[i]);
        struct snk_recursive_mutex *entry=rmutex_entry(objects[i],false);
        snk_recursive_mutex_ctor(objects[i]);assert(rmutex_entry(objects[i],false)==entry);
        assert(snk_recursive_mutex_try_lock(objects[i]));
        assert(snk_recursive_mutex_try_lock(objects[i]));
        snk_recursive_mutex_unlock(objects[i]);snk_recursive_mutex_unlock(objects[i]);
    }
    snk_recursive_mutex_lock(objects[0]);pthread_t thread;
    assert(!pthread_create(&thread,NULL,try_other_thread,objects[0]));pthread_join(thread,NULL);
    snk_recursive_mutex_unlock(objects[0]);
    pthread_t threads[4];for(unsigned i=0;i<4;i++)assert(!pthread_create(&threads[i],NULL,increment,NULL));
    for(unsigned i=0;i<4;i++)pthread_join(threads[i],NULL);assert(value==80000);
    for(unsigned i=0;i<4096;i++) {
        snk_recursive_mutex_dtor(objects[i]);assert(!rmutex_entry(objects[i],false));
        snk_recursive_mutex_ctor(objects[i]);assert(rmutex_entry(objects[i],false));
        snk_recursive_mutex_dtor(objects[i]);
    }
    for(unsigned i=0;i<sizeof objects;i++)assert(((unsigned char*)objects)[i]==0x5a);
    for(unsigned i=0;i<SNK_RMUTEX_BUCKETS;i++)assert(!s_rmutexes[i]);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'mutex.c').write_text(program)
            executable = path / 'mutex'
            subprocess.run(['clang', '-std=c11', '-D_DARWIN_C_SOURCE', '-pthread',
                            '-fsanitize=address,undefined', str(path / 'mutex.c'), '-o', str(executable)],
                           check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
