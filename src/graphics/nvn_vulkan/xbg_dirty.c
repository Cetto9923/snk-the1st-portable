/* Page-generation tracking adapted from nxnative/dm/gfx/nvn/nvn_dirty.c.
 * Copyright (c) 2026 seedds
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
#include "xbg_dirty.h"

#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

enum { PAGE_WRITABLE, PAGE_PROTECTED, PAGE_BUSY, PAGE_RELEASED };
enum { MAX_RANGES = 65536 };

typedef struct {
    uintptr_t memory, begin, end;
    size_t pages;
    _Atomic unsigned char *state;
    _Atomic uint64_t *generation;
    _Atomic int live;
} dirty_range;

/* Published descriptors never move. Reuse retains the same immutable page
 * bounds and atomically advances every page generation before publication. */
static dirty_range *ranges[MAX_RANGES];
static _Atomic unsigned range_count;
static _Atomic unsigned readers;
static _Atomic int enabled, usable;
static _Atomic uint64_t generation = 1;
static uint64_t registrations;
static size_t page_bytes;
static pthread_mutex_t range_mutex = PTHREAD_MUTEX_INITIALIZER;
static _Thread_local unsigned last_range;
_Static_assert(ATOMIC_CHAR_LOCK_FREE == 2 && ATOMIC_LLONG_LOCK_FREE == 2 && ATOMIC_INT_LOCK_FREE == 2,
               "The signal path requires lock-free atomics");

static int enter(void) {
    if (!atomic_load(&enabled)) return 0;
    atomic_fetch_add(&readers, 1);
    if (atomic_load(&enabled)) return 1;
    atomic_fetch_sub(&readers, 1);
    return 0;
}

static void leave(void) { atomic_fetch_sub(&readers, 1); }

static int valid_span(uintptr_t address, size_t bytes) {
    return bytes && address <= UINTPTR_MAX - bytes;
}

static int contains(const dirty_range *range, uintptr_t address, size_t bytes) {
    return atomic_load(&range->live) && address >= range->begin &&
           address <= range->end && bytes <= range->end - address;
}

static dirty_range *find_span(uintptr_t address, size_t bytes) {
    unsigned count = atomic_load_explicit(&range_count, memory_order_acquire);
    if (!valid_span(address, bytes)) return NULL;
    if (last_range < count && contains(ranges[last_range], address, bytes))
        return ranges[last_range];
    for (unsigned i = 0; i < count; ++i) {
        if (contains(ranges[i], address, bytes)) {
            last_range = i;
            return ranges[i];
        }
    }
    return NULL;
}

static uint64_t monotonic_ns(void) {
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    return (uint64_t)time.tv_sec * 1000000000ull + (uint64_t)time.tv_nsec;
}

/* A protection change publishes BUSY before mprotect and its final state after
 * mprotect. A host pre-write racing protection must wait and retry the page. */
static int wait_page(dirty_range *range, size_t page) {
    uint64_t deadline = monotonic_ns() + 2000000000ull;
    unsigned spins = 0;
    while (atomic_load(&range->state[page]) == PAGE_BUSY) {
        if ((++spins & 1023u) == 0) {
            if (monotonic_ns() >= deadline) return 0;
            sched_yield();
        }
    }
    return 1;
}

static void stamp_page(dirty_range *range, size_t page) {
    atomic_store(&range->generation[page], atomic_fetch_add(&generation, 1) + 1);
    /* Invalidate a clock sampled between the increment and generation store. */
    atomic_fetch_add(&generation, 1);
}

static int release_page(dirty_range *range, size_t page) {
    for (;;) {
        unsigned char state = PAGE_PROTECTED;
        if (atomic_compare_exchange_strong(&range->state[page], &state, PAGE_BUSY)) {
            void *memory = (void *)(range->begin + page * page_bytes);
            int result = mprotect(memory, page_bytes, PROT_READ | PROT_WRITE);
            if (result) {
                atomic_store(&usable, 0);
                atomic_store(&range->state[page], PAGE_PROTECTED);
                return 0;
            }
            stamp_page(range, page);
            atomic_store(&range->state[page], PAGE_RELEASED);
            return 1;
        }
        if (state != PAGE_BUSY) return state == PAGE_RELEASED;
        if (!wait_page(range, page)) return 0;
    }
}

static void prepare_range(dirty_range *range, uintptr_t address, size_t bytes) {
    uintptr_t begin = address > range->begin ? address : range->begin;
    uintptr_t end = address + bytes < range->end ? address + bytes : range->end;
    if (begin >= end) return;
    size_t first = (begin - range->begin) / page_bytes;
    size_t last = (end - 1 - range->begin) / page_bytes;
    for (size_t page = first; page <= last; ++page) {
        release_page(range, page);
        /* A neighboring pool may have protected this physical page. Its
         * removal or a host write invalidates every range sharing the page. */
        stamp_page(range, page);
    }
}

void xbg_dirty_enable(int value) {
    pthread_mutex_lock(&range_mutex);
    unsigned count = atomic_load(&range_count);
    for (unsigned i = 0; i < count; ++i)
        if (atomic_load(&ranges[i]->live))
            prepare_range(ranges[i], ranges[i]->begin, ranges[i]->end - ranges[i]->begin);
    atomic_store(&enabled, 0);
    while (atomic_load(&readers)) sched_yield();
    for (unsigned i = 0; i < count; ++i) {
        dirty_range *range = ranges[i];
        free(range->state);
        free(range->generation);
        free(range);
    }
    atomic_store(&range_count, 0);
    page_bytes = (size_t)sysconf(_SC_PAGESIZE);
    registrations = 0;
    atomic_store(&usable, value != 0);
    atomic_store(&enabled, value != 0);
    pthread_mutex_unlock(&range_mutex);
}

void xbg_dirty_add(const void *memory, size_t bytes) {
    uintptr_t address = (uintptr_t)memory;
    if (!memory || !valid_span(address, bytes)) return;
    pthread_mutex_lock(&range_mutex);
    unsigned count = atomic_load(&range_count);
    if (!atomic_load(&enabled) ||
        address + bytes > UINTPTR_MAX - (page_bytes - 1)) {
        pthread_mutex_unlock(&range_mutex);
        return;
    }
    uintptr_t begin = address - address % page_bytes;
    uintptr_t end = (address + bytes + page_bytes - 1) / page_bytes * page_bytes;
    dirty_range *range = NULL;
    for (unsigned i = 0; i < count; ++i) {
        dirty_range *candidate = ranges[i];
        if (!atomic_load(&candidate->live) && candidate->begin == begin && candidate->end == end) {
            range = candidate;
            break;
        }
    }
    int fresh = range == NULL;
    if (fresh && count == MAX_RANGES) { pthread_mutex_unlock(&range_mutex); return; }
    if (fresh) range = calloc(1, sizeof(*range));
    if (fresh && range) {
        range->memory = address;
        range->begin = begin;
        range->end = end;
        range->pages = (range->end - range->begin) / page_bytes;
        range->state = calloc(range->pages, sizeof(*range->state));
        range->generation = calloc(range->pages, sizeof(*range->generation));
    }
    if (!range || !range->state || !range->generation) {
        if (range) { free(range->state); free(range->generation); free(range); }
        pthread_mutex_unlock(&range_mutex);
        return;
    }
    range->memory = address;
    uint64_t stamp = atomic_fetch_add(&generation, 1) + 1;
    for (size_t page = 0; page < range->pages; ++page) {
        if (fresh) {
            atomic_init(&range->state[page], PAGE_WRITABLE);
            atomic_init(&range->generation[page], stamp);
        } else {
            atomic_store(&range->state[page], PAGE_WRITABLE);
            atomic_store(&range->generation[page], stamp);
        }
    }
    if (fresh) atomic_init(&range->live, 1);
    else atomic_store(&range->live, 1);
    if (fresh) {
        ranges[count] = range;
        atomic_store_explicit(&range_count, count + 1, memory_order_release);
    }
    ++registrations;
    pthread_mutex_unlock(&range_mutex);
}

void xbg_dirty_remove(const void *memory) {
    pthread_mutex_lock(&range_mutex);
    unsigned count = atomic_load(&range_count);
    for (unsigned i = 0; i < count; ++i) {
        dirty_range *range = ranges[i];
        if (atomic_load(&range->live) && range->memory == (uintptr_t)memory) {
            /* Every range sharing a boundary page must observe it becoming RW. */
            for (unsigned j = 0; j < count; ++j)
                if (atomic_load(&ranges[j]->live))
                    prepare_range(ranges[j], range->begin, range->end - range->begin);
            atomic_store(&range->live, 0);
            break;
        }
    }
    pthread_mutex_unlock(&range_mutex);
}

int xbg_dirty_write_begin(void *memory, size_t bytes) {
    if (!valid_span((uintptr_t)memory, bytes) || !atomic_load(&enabled)) return 0;
    pthread_mutex_lock(&range_mutex);
    if (!atomic_load(&enabled)) { pthread_mutex_unlock(&range_mutex); return 0; }
    unsigned count = atomic_load_explicit(&range_count, memory_order_acquire);
    for (unsigned i = 0; i < count; ++i)
        if (atomic_load(&ranges[i]->live)) prepare_range(ranges[i], (uintptr_t)memory, bytes);
    return 1;
}

void xbg_dirty_write_end(int lease) {
    if (lease) pthread_mutex_unlock(&range_mutex);
}

int xbg_dirty_fault(void *address, int is_write) {
    if (!is_write || !enter()) return 0;
    int handled = 0;
    uintptr_t value = (uintptr_t)address;
    unsigned count = atomic_load_explicit(&range_count, memory_order_acquire);
    for (unsigned i = 0; i < count; ++i) {
        dirty_range *range = ranges[i];
        if (atomic_load(&range->live) && value >= range->begin && value < range->end) {
            size_t page = (value - range->begin) / page_bytes;
            handled |= release_page(range, page);
        }
    }
    if (handled) for (unsigned i = 0; i < count; ++i) {
        dirty_range *range = ranges[i];
        if (atomic_load(&range->live) && value >= range->begin && value < range->end)
            stamp_page(range, (value - range->begin) / page_bytes);
    }
    leave();
    return handled;
}

int nvn_dirty_tracked(const void *address, size_t bytes) {
    if (!enter()) return 0;
    int tracked = atomic_load(&usable) && find_span((uintptr_t)address, bytes) != NULL;
    leave();
    return tracked;
}

uint64_t nvn_dirty_now(void) { return atomic_load(&generation); }

void nvn_dirty_protect(const void *address, size_t bytes) {
    pthread_mutex_lock(&range_mutex);
    dirty_range *range = atomic_load(&enabled) && atomic_load(&usable)
        ? find_span((uintptr_t)address, bytes) : NULL;
    if (range) {
        size_t first = ((uintptr_t)address - range->begin) / page_bytes;
        size_t last = ((uintptr_t)address + bytes - 1 - range->begin) / page_bytes;
        for (size_t page = first; page <= last; ++page) {
            unsigned char state = atomic_load(&range->state[page]);
            if (state == PAGE_PROTECTED) continue;
            if (state == PAGE_BUSY) {
                if (!wait_page(range, page)) { atomic_store(&usable, 0); break; }
                --page;
                continue;
            }
            if (atomic_compare_exchange_strong(&range->state[page], &state, PAGE_BUSY)) {
                int result = mprotect((void *)(range->begin + page * page_bytes), page_bytes, PROT_READ);
                atomic_store(&range->state[page], result ? state : PAGE_PROTECTED);
                if (result) atomic_store(&usable, 0);
            } else --page;
        }
    }
    pthread_mutex_unlock(&range_mutex);
}

int nvn_dirty_since(const void *address, size_t bytes, uint64_t stamp) {
    if (!bytes) return 0;
    if (!enter()) return 1;
    dirty_range *range = atomic_load(&usable) ? find_span((uintptr_t)address, bytes) : NULL;
    int dirty = range == NULL;
    if (range) {
        size_t first = ((uintptr_t)address - range->begin) / page_bytes;
        size_t last = ((uintptr_t)address + bytes - 1 - range->begin) / page_bytes;
        for (size_t page = first; page <= last; ++page)
            if (atomic_load(&range->generation[page]) > stamp) { dirty = 1; break; }
    }
    leave();
    return dirty;
}

void nvn_dirty_slot_stats(int *live, int *used, uint64_t *adds) {
    pthread_mutex_lock(&range_mutex);
    *used = (int)atomic_load(&range_count);
    *live = 0;
    for (int i = 0; i < *used; ++i) *live += atomic_load(&ranges[i]->live) != 0;
    *adds = registrations;
    pthread_mutex_unlock(&range_mutex);
}
