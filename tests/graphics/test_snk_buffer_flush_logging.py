import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def function(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class BufferFlushLoggingTests(unittest.TestCase):
    def test_actual_noop_calls_stats_logging_lookup_limit_and_concurrency(self):
        source = (ROOT / 'src/graphics/nvn_device/nvn_buffer.c').read_text()
        bodies = '\n'.join(function(source, name) for name in [
            'void nvnBufferFlushMappedRange(', 'void nvnBufferInvalidateMappedRange(',
        ])
        program = r'''
#include <assert.h>
#include <inttypes.h>
#include <pthread.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdatomic.h>
#include <string.h>
typedef struct {int initialized;} nvn_buffer_state;
static nvn_buffer_state ready={1},uninitialized={0};
static pthread_mutex_t s_buffer_lock=PTHREAD_MUTEX_INITIALIZER;
static struct {uint64_t calls,flushes,invalidates;} s_stats;
static unsigned lookups;static int allow_lookup=1;static atomic_uint returns;
static nvn_buffer_state *buffer_find(void *buffer,int create){
    assert(!create && allow_lookup);++lookups;
    if(buffer==(void*)1)return &ready;
    if(buffer==(void*)2)return &uninitialized;
    return NULL;
}
#define NVN_VOID_RETURN() do {atomic_fetch_add(&returns,1);return;} while(0)
''' + bodies + r'''
static void *worker(void *unused){
    (void)unused;
    for(unsigned i=0;i<2000;++i){
        nvnBufferFlushMappedRange((void*)1,-1,SIZE_MAX);
        nvnBufferInvalidateMappedRange((void*)1,0,0);
    }
    return NULL;
}
int main(int argc,char **argv){
    assert(argc==2);uint64_t before=0;
    if(!strcmp(argv[1],"sequential")){
        for(uintptr_t i=0;i<8;++i){
            nvnBufferFlushMappedRange((void*)(i%4),(ptrdiff_t)i,(size_t)i);
            nvnBufferInvalidateMappedRange((void*)(i%2),0,0);
        }
        assert(lookups==16 && s_stats.calls==16);
        allow_lookup=0;
        for(unsigned i=0;i<64;++i){
            nvnBufferFlushMappedRange(NULL,-1,SIZE_MAX);
            nvnBufferInvalidateMappedRange(NULL,0,0);
        }
        before=72;
    }else assert(!strcmp(argv[1],"parallel"));
    pthread_t threads[8];
    for(unsigned i=0;i<8;++i)assert(!pthread_create(&threads[i],NULL,worker,NULL));
    for(unsigned i=0;i<8;++i)assert(!pthread_join(threads[i],NULL));
    uint64_t each=before+8*2000;
    assert(lookups==16 && s_stats.flushes==each && s_stats.invalidates==each);
    assert(s_stats.calls==2*each && atomic_load(&returns)==2*each);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'flush.c').write_text(program)
            executable = path / 'flush'
            built = subprocess.run(['clang', '-std=c11', '-pthread', '-fsanitize=address,undefined',
                                    str(path / 'flush.c'), '-o', str(executable)],
                                   capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            for mode in ['sequential', 'parallel']:
                with self.subTest(mode=mode):
                    run = subprocess.run([str(executable), mode], capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(run.stderr.count('nvnBufferFlushMappedRange:'), 8)
                    self.assertEqual(run.stderr.count('nvnBufferInvalidateMappedRange:'), 8)
                    self.assertEqual(run.stderr.count('initialized=1;'), 6 if mode == 'sequential' else 16)


if __name__ == '__main__':
    unittest.main()
