import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class SizedDeleteTests(unittest.TestCase):
    def test_guest_operator_dispatch_and_repeated_reclamation(self):
        source = (ROOT / 'src/runtime/hle/guest_process.c').read_text()
        start = source.index('static int interposed_deallocate(')
        end = source.index('/* Called after nb_call_child', start)
        implementation = source[start:end]
        program = r'''
#include "guest_process.h"
#include "snk_libcxx.h"
#include "native_boundary.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

struct guest_process { nso_module *module; nb_scope boundary; };
static guest_process process;
static guest_process *current_process;
static int calls[4], missing, boundary_failure, live[4];
static unsigned char blocks[4];

uint32_t nso_find_symbol(const nso_module *module, const char *name) {
    assert(module == process.module);
    if (missing) return 0;
    if (!strcmp(name, "free")) return 1;
    if (!strcmp(name, "_ZdlPv")) return 2;
    if (!strcmp(name, "_ZdaPv")) return 3;
    assert(0);
    return 0;
}
uint64_t nso_symbol_value(const nso_module *module, uint32_t index) {
    assert(module == process.module && index >= 1 && index <= 3);
    return index;
}
struct nso_result nso_entry_address(const nso_module *module,
                                    uint64_t offset, uint64_t *out) {
    assert(module == process.module);
    *out = offset;
    return (struct nso_result){.status = NSO_OK};
}
nb_scope *guest_process_current_boundary(void) { return &process.boundary; }
nb_status nb_call_from_host(nb_scope *scope, void (*entry)(void),
                            nb_registers *registers) {
    assert(scope == &process.boundary);
    if (boundary_failure) return NB_BUSY;
    uintptr_t operation = (uintptr_t)entry;
    assert(operation >= 1 && operation <= 3);
    assert(registers->x[0] == (uintptr_t)&blocks[operation]);
    assert(live[operation] == 1);
    live[operation] = 0;
    calls[operation]++;
    return NB_OK;
}
''' + implementation + r'''
int main(void) {
    unsigned arguments = 99, returns = 99;
    uint64_t (*scalar)(void *, uint64_t) = (void *)snk_libcxx_lookup(
        "_ZdlPvm", &arguments, &returns);
    assert(scalar && arguments == 2 && returns == 0);
    uint64_t (*array)(void *, uint64_t) = (void *)snk_libcxx_lookup(
        "_ZdaPvm", &arguments, &returns);
    assert(array && array != scalar && arguments == 2 && returns == 0);
    current_process = &process;
    process.module = (nso_module *)&process;
    scalar(NULL, 48);
    array(NULL, 48);
    for (int i = 0; i < 100000; ++i) {
        live[2] = live[3] = 1;
        scalar(&blocks[2], 48);
        array(&blocks[3], 80);
        assert(!live[2] && !live[3]);
    }
    assert(calls[1] == 0 && calls[2] == 100000 && calls[3] == 100000);
    live[1] = 1;
    assert(guest_process_interposed_free(&blocks[1]) == 1);
    assert(!live[1] && calls[1] == 1);
    live[2] = 1;
    boundary_failure = 1;
    assert(guest_process_interposed_delete(&blocks[2], false) == -1);
    assert(live[2] == 1 && calls[1] == 1);
    boundary_failure = 0;
    missing = 1;
    assert(guest_process_interposed_delete(&blocks[2], false) == -1);
    assert(live[2] == 1 && calls[1] == 1);
    missing = 0;
    assert(guest_process_interposed_delete(&blocks[2], false) == 1);
    current_process = NULL;
    assert(guest_process_interposed_delete(&blocks[2], false) == 0);
    puts("sized_delete_contract reclaimed=200001 errors=0");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'sized_delete.c').write_text(program)
            executable = path / 'sized_delete'
            subprocess.run([
                shutil.which('clang') or 'cc', '-std=c11',
                '-fsanitize=address,undefined', '-pthread',
                '-I', str(ROOT / 'src/runtime/hle'),
                '-I', str(ROOT / 'src/runtime/nso'),
                str(path / 'sized_delete.c'),
                str(ROOT / 'src/runtime/hle/snk_libcxx.c'),
                '-o', str(executable),
            ], check=True, capture_output=True)
            result = subprocess.run([str(executable)], check=True,
                                    capture_output=True, text=True)
            self.assertIn('reclaimed=200001 errors=0', result.stdout)


if __name__ == '__main__':
    unittest.main()
