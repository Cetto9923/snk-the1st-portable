import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class CompletedWritebackTests(unittest.TestCase):
    def test_completed_results_preserve_order_and_slot_boundaries(self):
        source = (ROOT / 'src/graphics/nvn_vulkan/engine/xbg_game.cpp').read_text()
        start = source.index('void apply_writeback(PendingWriteback &write)')
        end = source.index('void write_report(', start)
        implementation = source[start:end]
        start = source.index('void resolve_pending(){')
        end = source.index('// 先完成待写回', start)
        implementation += source[start:end]
        program = r'''
#include "xbg_writeback_policy.h"
#include <array>
#include <cassert>
#include <cstring>
#include <map>
#include <cstdio>

static bool fenced, disabled, resolving_pending, honor_pipeline_diagnostics;
static uint64_t writeback_bytes, wb_completed_skipped, wb_completed_bytes;
static uint64_t wb_skipped, wb_skipped_bytes;
struct Buffer {
    const void *mapped;
    void invalidate() { assert(fenced && resolving_pending); }
};
struct PendingWriteback {
    uint64_t addr, bytes, modified_bytes;
    const void *slot;
    Buffer buffer;
};
struct PendingReport {};
static std::vector<PendingWriteback> pending_writebacks;
static std::vector<PendingReport> pending_reports;
static std::map<int, int> epochs;
static int counter_epoch;
static struct {int sync_query, sync_writeback;} perf;
static struct {uint64_t load() { return 0; }} presents;
static struct {decltype(presents) presents;} stats;
static void xbg_logf(const char *, ...) {}
static bool ab_off(const char *name) {
    assert(!strcmp(name, "wbcomplete"));
    return disabled;
}
template<class Callback>
static void for_images_overlapping(uint64_t, uint64_t, Callback) {}
struct Image {};
static void invalidate_cpu_range(uint64_t, uint64_t) {}
static bool writeback_superseded(size_t) { return false; }
static void gpu_sync(int &) { assert(resolving_pending); fenced = true; }
static void write_report(const PendingReport &) { assert(fenced); }
static void apply_ready_events() { assert(pending_writebacks.empty()); }
''' + implementation + r'''
static uint32_t seed = 17;
static uint32_t next() { seed = seed * 1664525u + 1013904223u; return seed; }
int main() {
    std::array<unsigned char, 256> guest, expected;
    std::array<std::array<unsigned char, 256>, 32> outputs;
    int slots[2];
    for (int iteration = 0; iteration < 2000; ++iteration) {
        guest.fill(0x23);
        expected = guest;
        pending_writebacks.clear();
        disabled = iteration % 3 == 0;
        bool all = iteration % 2 == 0;
        size_t count = 4 + next() % 28;
        for (size_t i = 0; i < count; ++i) {
            size_t offset = next() % 128;
            size_t bytes = 1 + next() % 128;
            size_t modified = next() % 7 == 0 ? 1 + next() % bytes : 0;
            const void *slot = &slots[next() % 2];
            outputs[i].fill(static_cast<unsigned char>(next()));
            pending_writebacks.push_back({uint64_t(guest.data() + offset),
                bytes, modified, slot, {outputs[i].data()}});
            if (all || slot == &slots[0])
                memcpy(expected.data() + offset, outputs[i].data(),
                       modified ? modified : bytes);
        }
        resolving_pending = false;
        fenced = false;
        if (all) {
            resolve_pending();
            assert(pending_writebacks.empty() && fenced);
        } else {
            // The slot caller already observed this fence. The other slot's
            // writes remain pending and cannot suppress this slot's copies.
            fenced = true;
            resolve_slot_writebacks(&slots[0]);
            for (const auto &write : pending_writebacks)
                assert(write.slot == &slots[1]);
        }
        assert(!resolving_pending && guest == expected);
    }
    pending_writebacks.clear();
    assert(!xbg_wb_completed_superseded(pending_writebacks, 0, false));
    assert(wb_completed_skipped > 0 && wb_completed_bytes > 0);
    printf("completed_writeback_contract cases=2000 skipped=%llu errors=0\n",
           static_cast<unsigned long long>(wb_completed_skipped));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'writeback.cpp').write_text(program)
            executable = path / 'writeback'
            subprocess.run([
                shutil.which('clang++') or 'c++', '-std=c++17',
                '-fsanitize=address,undefined',
                '-I', str(ROOT / 'src/graphics/nvn_vulkan/engine'),
                str(path / 'writeback.cpp'), '-o', str(executable),
            ], check=True, capture_output=True)
            result = subprocess.run([str(executable)], check=True,
                                    capture_output=True, text=True)
            self.assertIn('cases=2000', result.stdout)
            self.assertIn('errors=0', result.stdout)


if __name__ == '__main__':
    unittest.main()
