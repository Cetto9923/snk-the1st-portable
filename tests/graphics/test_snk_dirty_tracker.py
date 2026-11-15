import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class DirtyTrackerTests(unittest.TestCase):
    def test_faults_host_reads_shared_pages_retirement_and_protection_races(self):
        source = (ROOT / 'src/runtime/hle/nso_host.c').read_text()
        start = source.index('    // Kernel writes return EFAULT on tracked read-only pages')
        end = source.index('    if (n < 0)', start)
        host_read = source[start:end]
        program = r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include "xbg_dirty.h"
static unsigned fail_protection;
static unsigned allocations,fail_allocation_at;
static void *tracked_calloc(size_t count,size_t size) {
    if(++allocations==fail_allocation_at)return NULL;
    return calloc(count,size);
}
static int tracked_mprotect(void *p,size_t n,int protection) {
    if(fail_protection){--fail_protection;return -1;}
    return mprotect(p,n,protection);
}
extern int xbg_dirty_write_begin(void *,size_t) __attribute__((weak));
#define mprotect tracked_mprotect
#define calloc tracked_calloc
#include "xbg_dirty.c"
#undef mprotect
#undef calloc
extern void xbg_wtrack_prepare(void *,size_t) __attribute__((weak));
unsigned wtrack_prepares;
void xbg_wtrack_prepare(void *p,size_t n){(void)p;(void)n;++wtrack_prepares;}
void end_with_errno(int lease) __attribute__((weak));
void end_with_errno(int lease){xbg_dirty_write_end(lease);errno=EIO;}
#define xbg_dirty_write_end end_with_errno
static ssize_t host_read(int fd,void *buffer,size_t size,int64_t offset) {
''' + host_read + r'''
    return n;
}
#undef xbg_dirty_write_end

static _Atomic unsigned faults;
static void fault_handler(int signal,siginfo_t *info,void *context) {
    (void)signal;(void)context;
    if(!xbg_dirty_fault(info->si_addr,1))_exit(101);
    atomic_fetch_add(&faults,1);
}
static unsigned char *memory;
static size_t page;
static _Atomic int started,finished;
static void *protect_once(void *unused) {
    (void)unused;atomic_store(&started,1);
    nvn_dirty_protect(memory,page);atomic_store(&finished,1);return NULL;
}
static void *protect_repeatedly(void *unused) {
    (void)unused;
    for(unsigned i=0;i<2000;++i)nvn_dirty_protect(memory,page*2);
    return NULL;
}
static void *write_second_page(void *unused) {
    (void)unused;volatile unsigned char *target=memory+page;
    for(unsigned i=0;i<2000;++i)*target=(unsigned char)i;
    return NULL;
}
int main(void) {
    struct sigaction action={0};action.sa_sigaction=fault_handler;
    action.sa_flags=SA_SIGINFO;sigemptyset(&action.sa_mask);
    assert(!sigaction(SIGSEGV,&action,NULL));
    assert(!sigaction(SIGBUS,&action,NULL));
    page=(size_t)sysconf(_SC_PAGESIZE);
    memory=mmap(NULL,page*6,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(memory!=MAP_FAILED);
    xbg_dirty_add(memory,page*3);assert(!nvn_dirty_tracked(memory,1));
    assert(nvn_dirty_since(memory,1,UINT64_MAX));
    xbg_dirty_enable(1);xbg_dirty_add(memory,page*3);
    uint64_t stamp=nvn_dirty_now();
    assert(nvn_dirty_tracked(memory,page*3));
    assert(!nvn_dirty_tracked(memory+page*3,1));
    assert(!nvn_dirty_tracked((void*)(UINTPTR_MAX-1),3));
    for(unsigned failure=1;failure<=3;++failure) {
        fail_allocation_at=allocations+failure;
        xbg_dirty_add(memory+page*4,page);
        assert(!nvn_dirty_tracked(memory+page*4,1));
        fail_allocation_at=0;
    }
    assert(!xbg_dirty_fault(memory,0));
    assert(!xbg_dirty_fault(memory+page*4,1));
    assert(!xbg_dirty_fault(memory,1));
    nvn_dirty_protect(memory+7,1);assert(!nvn_dirty_since(memory+7,1,stamp));
    memory[7]=43;assert(faults==1 && nvn_dirty_since(memory+7,1,stamp));
    assert(!nvn_dirty_since(memory+page,1,stamp));
    stamp=nvn_dirty_now();nvn_dirty_protect(memory,page);
    assert(!nvn_dirty_since(memory,page,stamp));

    FILE *file=tmpfile();assert(file);
    unsigned char input[128];memset(input,79,sizeof input);
    assert(fwrite(input,1,sizeof input,file)==sizeof input);fflush(file);
    int lease=xbg_dirty_write_begin(memory,sizeof input);assert(lease);
    assert(pread(fileno(file),memory,sizeof input,0)==sizeof input);
    xbg_dirty_write_end(lease);
    assert(!memcmp(memory,input,sizeof input));assert(nvn_dirty_since(memory,1,stamp));
    nvn_dirty_protect(memory,page);
    assert(host_read(fileno(file),memory,sizeof input,0)==sizeof input);
    assert(wtrack_prepares==1 && !memcmp(memory,input,sizeof input));
    assert(host_read(-1,memory,sizeof input,0)==-1 && errno==EBADF);
    lease=xbg_dirty_write_begin(memory,1);assert(lease);xbg_dirty_write_end(lease);

    // A kernel write keeps the protection mutex until pread has finished.
    nvn_dirty_protect(memory,page);lease=xbg_dirty_write_begin(memory,page);
    pthread_t worker;assert(!pthread_create(&worker,NULL,protect_once,NULL));
    while(!atomic_load(&started))sched_yield();
    usleep(10000);assert(!atomic_load(&finished));
    assert(pread(fileno(file),memory,sizeof input,0)==sizeof input);
    xbg_dirty_write_end(lease);assert(!pthread_join(worker,NULL));
    assert(atomic_load(&finished));memory[9]=12;

    assert(!pthread_create(&worker,NULL,protect_repeatedly,NULL));
    pthread_t writer;assert(!pthread_create(&writer,NULL,write_second_page,NULL));
    for(unsigned i=0;i<2000;++i) {
        lease=xbg_dirty_write_begin(memory,sizeof input);
        assert(pread(fileno(file),memory,sizeof input,0)==sizeof input);
        xbg_dirty_write_end(lease);
        nvn_dirty_protect(memory,1);
        memory[0]=(unsigned char)i;
    }
    assert(!pthread_join(worker,NULL));
    assert(!pthread_join(writer,NULL));assert(memory[page]==(unsigned char)1999);

    xbg_dirty_remove(memory);uint64_t old_stamp=nvn_dirty_now();
    assert(!nvn_dirty_tracked(memory,1));memory[0]=17;
    xbg_dirty_add(memory,page*3);assert(nvn_dirty_since(memory,1,old_stamp));
    int live,used;uint64_t adds;nvn_dirty_slot_stats(&live,&used,&adds);
    int reused_slots=used;
    for(unsigned i=0;i<2000;++i) {
        xbg_dirty_remove(memory);old_stamp=nvn_dirty_now();
        xbg_dirty_add(memory,page*3);assert(nvn_dirty_since(memory,1,old_stamp));
    }
    nvn_dirty_slot_stats(&live,&used,&adds);assert(used==reused_slots && live==1);
    xbg_dirty_remove(memory);

    // Two 4KB guest pools may share a larger host page.
    unsigned char *left=memory+16,*right=memory+page-32;
    xbg_dirty_add(left,page-16);xbg_dirty_add(right,64);
    stamp=nvn_dirty_now();
    nvn_dirty_protect(left,1);nvn_dirty_protect(right,1);
    memory[page-16]=91;
    assert(nvn_dirty_since(left,1,stamp) && nvn_dirty_since(right,1,stamp));
    stamp=nvn_dirty_now();nvn_dirty_protect(right,1);
    xbg_dirty_remove(left);
    assert(nvn_dirty_since(right,1,stamp));
    memory[page-16]=92;
    xbg_dirty_remove(right);assert(!nvn_dirty_tracked(memory,1));

    xbg_dirty_add(memory,page);stamp=nvn_dirty_now();
    fail_protection=1;nvn_dirty_protect(memory,page);
    assert(!nvn_dirty_tracked(memory,1) && nvn_dirty_since(memory,1,stamp));
    memory[0]=13;xbg_dirty_enable(0);
    xbg_dirty_enable(1);xbg_dirty_add(memory,page);
    nvn_dirty_protect(memory,page);fail_protection=1;
    assert(!xbg_dirty_fault(memory,1));
    assert(nvn_dirty_since(memory,1,nvn_dirty_now()));
    assert(xbg_dirty_fault(memory,1));memory[0]=14;
    nvn_dirty_protect(memory,page);
    xbg_dirty_enable(0);unsigned before=atomic_load(&faults);
    memset(memory,0,page*6);assert(faults==before);
    assert(!nvn_dirty_tracked(memory,1) && !nvn_dirty_since(memory,0,0));
    nvn_dirty_slot_stats(&live,&used,&adds);
    assert(!live && !used && !adds);
    assert(atomic_load(&faults)>=2000);
    fprintf(stderr,"dirty_tracker real_faults=%u protection_races=2000 host_reads=2000 shared_page_retirement=passed\n",atomic_load(&faults));
    fclose(file);assert(!munmap(memory,page*6));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'dirty.c').write_text(program)
            executable = path / 'dirty'
            subprocess.run(['clang', '-std=c11', '-D_DARWIN_C_SOURCE', '-D_GNU_SOURCE',
                            '-Wall', '-Wextra', '-Werror', '-pthread',
                            '-fsanitize=address,undefined', '-I',
                            str(ROOT / 'src/graphics/nvn_vulkan'), str(path / 'dirty.c'),
                            '-o', str(executable)], check=True, capture_output=True)
            result = subprocess.run([str(executable)], check=True, capture_output=True, timeout=30)
            print(result.stderr.decode(), end='')


if __name__ == '__main__':
    unittest.main()
