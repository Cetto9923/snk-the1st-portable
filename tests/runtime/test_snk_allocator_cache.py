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


class AllocatorCacheTests(unittest.TestCase):
    def test_actual_load_cache_boundary_validation_reload_and_threads(self):
        source = (ROOT / 'src/runtime/hle/guest_process.c').read_text()
        enum_start = source.index('enum interposed_allocator {')
        enum_end = source.index('};', enum_start) + 2
        functions = '\n'.join(function(source, name) for name in [
            'static void prepare_interposed_allocators(',
            'struct nso_result guest_process_load(',
            'int guest_process_interposed_aligned_alloc(',
            'static int interposed_deallocate(',
            'int guest_process_interposed_free(',
            'int guest_process_interposed_delete(',
        ])
        program = r'''
#include "guest_process.h"
#include "native_boundary.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
''' + source[enum_start:enum_end] + r'''
struct nso_module {
    uint64_t base;
    unsigned missing, undefined;
    int valid, required, observed;
};
struct guest_process {
    pthread_mutex_t mutex;
    nso_module *module;
    uint64_t interposed_allocator_offsets[INTERPOSED_ALLOCATOR_COUNT];
    int running, quarantined, module_ready;
    nb_scope boundary;
};
static _Thread_local guest_process *current_process;
static nso_module *next_module;
static enum nso_status load_result = NSO_OK;
static int scope_failure, boundary_failure;
static atomic_uint searches, validations, calls;
static const struct nso_owner_ops module_ops;
static struct nso_result status(enum nso_status s, int e, int c) {
    return (struct nso_result){s,e,c};
}
static void guest_process_text_filter(void *text,size_t bytes,void *opaque) {
    (void)text; (void)bytes; (void)opaque;
}
void nso_set_text_filter(nso_text_filter_fn fn,void *opaque) {
    assert((fn == guest_process_text_filter && opaque) || (!fn && !opaque));
}
uint64_t guest_process_resolve(uint32_t index,const char *name) {
    (void)index; (void)name; return 0;
}
struct nso_load_result nso_load_file_owned(const char *path,nso_import_fn resolver,
        const struct nso_owner_ops *ops,void *owner,char *err,size_t len) {
    (void)err; (void)len;
    assert(path && resolver == guest_process_resolve && ops == &module_ops && owner);
    return (struct nso_load_result){status(load_result,0,0),next_module};
}
void nso_require_executor(nso_module *module) { module->required++; }
static int nso_host_exit_scope_begin(nso_module *module) {
    assert(module); return scope_failure;
}
static void nso_host_exit_scope_end(void *module) { assert(module); }
void nso_set_unload_observer(nso_module *module,void (*observer)(void *),void *user) {
    assert(observer == nso_host_exit_scope_end && user == module); module->observed++;
}
struct nso_result nso_release(nso_module **module) {
    *module = NULL; return status(NSO_OK,0,0);
}
uint32_t nso_find_symbol(const nso_module *module,const char *name) {
    static const char *const names[] = {"aligned_alloc","free","_ZdlPv","_ZdaPv"};
    atomic_fetch_add(&searches,1);
    for (unsigned i=0;i<4;i++) if (!strcmp(name,names[i]))
        return module->missing & (1u<<i) ? 0 : i+1;
    assert(0); return 0;
}
uint64_t nso_symbol_value(const nso_module *module,uint32_t index) {
    assert(index>=1 && index<=4);
    return module->undefined & (1u<<(index-1)) ? UINT64_MAX : index*4;
}
struct nso_result nso_entry_address(const nso_module *module,uint64_t offset,uint64_t *out) {
    atomic_fetch_add(&validations,1);
    if (!module->valid || offset<4 || offset>16 || offset%4)
        return status(NSO_INVALID,EINVAL,0);
    *out=module->base+offset; return status(NSO_OK,0,0);
}
nb_status nb_call_from_host(nb_scope *scope,void (*entry)(void),nb_registers *packet) {
    guest_process *p=current_process;
    assert(p && scope==&p->boundary);
    uint64_t offset=(uintptr_t)entry-p->module->base;
    assert(offset>=4 && offset<=16 && offset%4==0);
    if (offset==4) {
        assert(packet->x[0]==64 && packet->x[1]==256);
        if (!boundary_failure) packet->x[0]=0xbeef;
    } else assert(packet->x[0]==0x1234+offset/4-2);
    if (boundary_failure) return NB_BUSY;
    atomic_fetch_add(&calls,1); return NB_OK;
}
''' + functions + r'''
static void load(guest_process *p,nso_module *module) {
    next_module=module;
    assert(guest_process_load(p,"fixture",NULL,0).status==NSO_OK);
    assert(p->module==module && p->module_ready && module->required && module->observed);
}
static void *worker(void *owner) {
    current_process=owner;
    for (unsigned i=0;i<2000;i++) {
        void *out=NULL;
        assert(guest_process_interposed_aligned_alloc(64,256,&out)==1 && out==(void*)0xbeef);
        assert(guest_process_interposed_free((void*)0x1234)==1);
        assert(guest_process_interposed_delete((void*)0x1235,0)==1);
        assert(guest_process_interposed_delete((void*)0x1236,1)==1);
    }
    return NULL;
}
int main(void) {
    guest_process a={.mutex=PTHREAD_MUTEX_INITIALIZER};
    guest_process b={.mutex=PTHREAD_MUTEX_INITIALIZER};
    nso_module first={.base=0x10000,.valid=1}, second={.base=0x20000,.valid=1};
    void *out=(void*)0x5555;
    assert(guest_process_interposed_aligned_alloc(64,256,&out)==0 && out==(void*)0x5555);
    assert(guest_process_interposed_free((void*)0x1234)==0);
    assert(guest_process_load(NULL,"fixture",NULL,0).status==NSO_INVALID);
    load(&a,&first); load(&b,&second);
    assert(atomic_load(&searches)==8);
    assert(guest_process_load(&a,"fixture",NULL,0).status==NSO_INVALID);
    pthread_t threads[8];
    for (unsigned i=0;i<8;i++) assert(!pthread_create(&threads[i],NULL,worker,i%2?&a:&b));
    for (unsigned i=0;i<8;i++) assert(!pthread_join(threads[i],NULL));
    assert(atomic_load(&searches)==8 && atomic_load(&calls)==64000);
    assert(atomic_load(&validations)==64000);
    current_process=&a;
    assert(guest_process_interposed_free(NULL)==1);
    assert(guest_process_interposed_delete(NULL,0)==1);
    assert(atomic_load(&validations)==64000);
    first.valid=0;
    assert(guest_process_interposed_free((void*)0x1234)==-1);
    assert(guest_process_interposed_aligned_alloc(64,256,&out)==-1 && out==(void*)0x5555);
    assert(atomic_load(&calls)==64000);
    first.valid=1; boundary_failure=1;
    assert(guest_process_interposed_delete((void*)0x1236,1)==-1);
    assert(guest_process_interposed_aligned_alloc(64,256,&out)==-1 && out==(void*)0x5555);
    assert(atomic_load(&calls)==64000); boundary_failure=0;
    assert(nso_release(&a.module).status==NSO_OK); a.module_ready=0;
    assert(guest_process_interposed_free((void*)0x1234)==0);
    nso_module replacement={.base=0x30000,.valid=1,.missing=4,.undefined=8};
    load(&a,&replacement);
    assert(atomic_load(&searches)==12);
    assert(guest_process_interposed_delete((void*)0x1235,0)==-1);
    assert(guest_process_interposed_delete((void*)0x1236,1)==-1);
    assert(guest_process_interposed_free((void*)0x1234)==1);
    assert(guest_process_interposed_aligned_alloc(64,256,&out)==1 && out==(void*)0xbeef);
    assert(atomic_load(&calls)==64002 && atomic_load(&searches)==12);
    guest_process failed={.mutex=PTHREAD_MUTEX_INITIALIZER};
    next_module=NULL; load_result=NSO_LOAD_ERROR;
    assert(guest_process_load(&failed,"fixture",NULL,0).status==NSO_LOAD_ERROR);
    assert(!failed.module_ready && atomic_load(&searches)==12);
    next_module=&first; load_result=NSO_OK; scope_failure=1;
    assert(guest_process_load(&failed,"fixture",NULL,0).status==NSO_OWNER_ERROR);
    assert(!failed.module && !failed.module_ready && atomic_load(&searches)==12);
    scope_failure=0; next_module=&first; load_result=NSO_RETAINED;
    assert(guest_process_load(&failed,"fixture",NULL,0).status==NSO_RETAINED);
    assert(failed.quarantined && !failed.module_ready && atomic_load(&searches)==12);
    puts("allocator_cache calls=64002 validation_and_owner_checks=passed");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'cache.c').write_text(program)
            executable = path / 'cache'
            built = subprocess.run([
                'clang', '-std=c11', '-pthread', '-fsanitize=address,undefined',
                '-I', str(ROOT / 'src/runtime/hle'), '-I', str(ROOT / 'src/runtime/nso'),
                str(path / 'cache.c'), '-o', str(executable),
            ], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('validation_and_owner_checks=passed', run.stdout)


if __name__ == '__main__':
    unittest.main()
