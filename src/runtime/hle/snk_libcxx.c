#include "snk_libcxx.h"
#include "guest_process.h"
#include "../nso/native_boundary.h"

#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ====================================================================== */
/* std::basic_string                                                     */
/* ====================================================================== */

/* The SDK libc++ string is not the host libc++ layout. The extracted
 * nnSdk code shows the object as:
 *   +0   u64  bit 0 is the long flag, bits 1..63 hold the value
 *              (the size for a short string, the capacity for a long one)
 *   +1        the inline short buffer, at most 22 bytes
 *   +8   u64  size, long strings only
 *   +16  ptr  data pointer, long strings only
 * A short string therefore overlaps its own header with the inline
 * buffer, which is why the size is packed into the flag byte. */
#define SNK_STRING_SHORT_CAPACITY 22

static bool snk_string_is_long(const void *object) {
    return ((const unsigned char *)object)[0] & 1u;
}

static uint64_t snk_string_size(const void *object) {
    if (snk_string_is_long(object)) return *(const uint64_t *)((const char *)object + 8);
    return ((const unsigned char *)object)[0] >> 1;
}

static uint64_t snk_string_capacity(const void *object) {
    if (snk_string_is_long(object)) return *(const uint64_t *)object >> 1;
    return SNK_STRING_SHORT_CAPACITY;
}

static char *snk_string_data(void *object) {
    if (snk_string_is_long(object)) return *(char **)((char *)object + 16);
    return (char *)object + 1;
}

/* Install a long representation with the given capacity. */
static uint64_t snk_string_set_long(void *object, uint64_t capacity, const char *data, uint64_t size) {
    char *buffer = (char *)malloc((size_t)capacity + 1);
    if (!buffer) return 0;
    if (size) memcpy(buffer, data, (size_t)size);
    buffer[size] = 0;
    if (snk_string_is_long(object)) {
        char *previous = *(char **)((char *)object + 16);
        if (previous) free(previous);
    }
    *(uint64_t *)object = (capacity << 1) | 1u;
    *(uint64_t *)((char *)object + 8) = size;
    *(uint64_t *)((char *)object + 16) = (uint64_t)(uintptr_t)buffer;
    return 0;
}

/* Install a short representation. The caller guarantees the size fits. */
static uint64_t snk_string_set_short(void *object, const char *data, uint64_t size) {
    ((unsigned char *)object)[0] = (unsigned char)(size << 1);
    if (size) memcpy((char *)object + 1, data, (size_t)size);
    return 0;
}

/* std::basic_string::operator=(const basic_string&) */
static uint64_t snk_string_assign(void *object, const void *source) {
    if (object == source) return 0;
    uint64_t size = snk_string_size(source);
    const char *data = snk_string_data((void *)source);
    if (!snk_string_is_long(object)) {
        if (size <= SNK_STRING_SHORT_CAPACITY) return snk_string_set_short(object, data, size);
        uint64_t capacity = size * 2;
        return snk_string_set_long(object, capacity, data, size);
    }
    uint64_t capacity = snk_string_capacity(object);
    if (capacity >= size) {
        *(uint64_t *)((char *)object + 8) = size;
        if (size) memmove(snk_string_data(object), data, (size_t)size);
        return 0;
    }
    uint64_t grown = capacity ? capacity * 2 : size * 2;
    if (grown < size) grown = size;
    return snk_string_set_long(object, grown, data, size);
}

/* std::basic_string::replace(size_t pos, size_t n1, const char* s) */
static uint64_t snk_string_replace(void *object, uint64_t pos, uint64_t count, const char *text) {
    uint64_t text_size = text ? strlen(text) : 0;
    uint64_t size = snk_string_size(object);
    if (pos > size) pos = size;
    if (count > size - pos) count = size - pos;
    uint64_t tail = size - pos - count;
    uint64_t result = size - count + text_size;
    char *current = snk_string_data(object);
    char *scratch = (char *)malloc((size_t)result + 1);
    if (!scratch) return 0;
    if (pos) memcpy(scratch, current, (size_t)pos);
    if (text_size) memcpy(scratch + pos, text, (size_t)text_size);
    if (tail) memcpy(scratch + pos + text_size, current + pos + count, (size_t)tail);
    scratch[result] = 0;
    if (!snk_string_is_long(object) && result <= SNK_STRING_SHORT_CAPACITY) {
        uint64_t status = snk_string_set_short(object, scratch, result);
        free(scratch);
        return status;
    }
    uint64_t capacity = snk_string_capacity(object);
    if (capacity < result) capacity = result * 2;
    uint64_t status = snk_string_set_long(object, capacity, scratch, result);
    free(scratch);
    return status;
}

/* ====================================================================== */
/* std::recursive_mutex                                                   */
/* ====================================================================== */

/* The SDK recursive mutex wraps an OS mutex handle inside the guest
 * object. This host keeps the lock in its own table instead, so the
 * guest object is never written and its size does not matter. */
struct snk_recursive_mutex {
    void *object;
    pthread_mutex_t native;
    struct snk_recursive_mutex *next;
};

static pthread_mutex_t s_rmutex_lock = PTHREAD_MUTEX_INITIALIZER;
static struct snk_recursive_mutex *s_rmutexes;

static struct snk_recursive_mutex *rmutex_entry(void *object, bool create) {
    pthread_mutex_lock(&s_rmutex_lock);
    struct snk_recursive_mutex *entry = s_rmutexes;
    while (entry && entry->object != object) entry = entry->next;
    if (!entry && create) {
        entry = (struct snk_recursive_mutex *)calloc(1, sizeof(*entry));
        if (entry) {
            pthread_mutexattr_t attributes;
            pthread_mutexattr_init(&attributes);
            pthread_mutexattr_settype(&attributes, PTHREAD_MUTEX_RECURSIVE);
            pthread_mutex_init(&entry->native, &attributes);
            pthread_mutexattr_destroy(&attributes);
            entry->object = object;
            entry->next = s_rmutexes;
            s_rmutexes = entry;
        }
    }
    pthread_mutex_unlock(&s_rmutex_lock);
    return entry;
}

static uint64_t snk_recursive_mutex_ctor(void *object) {
    rmutex_entry(object, true);
    return 0;
}

static uint64_t snk_recursive_mutex_dtor(void *object) {
    pthread_mutex_lock(&s_rmutex_lock);
    struct snk_recursive_mutex **slot = &s_rmutexes;
    while (*slot && (*slot)->object != object) slot = &(*slot)->next;
    struct snk_recursive_mutex *entry = *slot;
    if (entry) *slot = entry->next;
    pthread_mutex_unlock(&s_rmutex_lock);
    if (entry) {
        pthread_mutex_destroy(&entry->native);
        free(entry);
    }
    return 0;
}

static uint64_t snk_recursive_mutex_lock(void *object) {
    struct snk_recursive_mutex *entry = rmutex_entry(object, false);
    if (entry) pthread_mutex_lock(&entry->native);
    return 0;
}

static uint64_t snk_recursive_mutex_unlock(void *object) {
    struct snk_recursive_mutex *entry = rmutex_entry(object, false);
    if (entry) pthread_mutex_unlock(&entry->native);
    return 0;
}

static uint64_t snk_recursive_mutex_try_lock(void *object) {
    struct snk_recursive_mutex *entry = rmutex_entry(object, false);
    if (!entry) return 0;
    return pthread_mutex_trylock(&entry->native) == 0 ? 1u : 0u;
}

/* ====================================================================== */
/* std::__1::__shared_weak_count                                          */
/* ====================================================================== */

/* The SDK control block keeps the weak count at +0x10 and reaches the
 * zero weak callback through the vtable slot at +0x20. A weak count
 * that is already zero calls that callback without a decrement, which
 * is what the extracted nnSdk code does. */
static uint64_t snk_shared_weak_count_release_weak(void *object) {
    if (!object) return 0;
    uint64_t *counter = (uint64_t *)((char *)object + 0x10);
    uint64_t value = __atomic_load_n(counter, __ATOMIC_ACQUIRE);
    if (value == 0) {
        void **vtable = *(void ***)object;
        if (vtable) {
            void (*on_zero_weak)(void *) = *(void **)((char *)vtable + 0x20);
            if (on_zero_weak) {
                nb_scope *scope = guest_process_current_boundary();
                if (scope) {
                    nb_registers reg = {0};
                    reg.x[0] = (uint64_t)(uintptr_t)object;
                    nb_call_from_host(scope, (void (*)(void))(uintptr_t)on_zero_weak, &reg);
                } else {
                    on_zero_weak(object);
                }
            }
        }
        return 0;
    }
    __atomic_fetch_sub(counter, 1, __ATOMIC_ACQ_REL);
    return 0;
}

/* The SDK destructor of this control block is an empty function. */
static uint64_t snk_shared_weak_count_dtor(void *object) {
    (void)object;
    return 0;
}

/* ====================================================================== */
/* std::__1::__next_prime                                                */
/* ====================================================================== */

static uint64_t snk_next_prime(uint64_t value) {
    if (value <= 2) return 2;
    uint64_t candidate = value;
    if ((candidate & 1) == 0) candidate++;
    for (;;) {
        bool prime = true;
        for (uint64_t divisor = 3; divisor * divisor <= candidate; divisor += 2) {
            if (candidate % divisor == 0) { prime = false; break; }
        }
        if (prime) return candidate;
        candidate += 2;
        if (candidate < value) return value;
    }
}

static uint64_t snk_sized_delete(void *ptr, uint64_t size) {
    (void)size;
    if (ptr) {
        if (guest_process_interposed_free(ptr) != 1) {
            fprintf(stderr, "[snk-libcxx] _ZdlPvm: guest_process_interposed_free failed for %p\n", ptr);
        }
    }
    return 0;
}

/* ====================================================================== */
/* The import table                                                    */
/* ====================================================================== */

struct snk_libcxx_entry {
    const char *name;
    uintptr_t function;
    unsigned arguments;
    unsigned returns;
};

static const struct snk_libcxx_entry s_entries[] = {
    { "_ZNSt3__115recursive_mutexC1Ev", (uintptr_t)&snk_recursive_mutex_ctor, 1, 1 },
    { "_ZNSt3__115recursive_mutexD1Ev", (uintptr_t)&snk_recursive_mutex_dtor, 1, 1 },
    { "_ZNSt3__115recursive_mutex4lockEv", (uintptr_t)&snk_recursive_mutex_lock, 1, 1 },
    { "_ZNSt3__115recursive_mutex6unlockEv", (uintptr_t)&snk_recursive_mutex_unlock, 1, 1 },
    { "_ZNSt3__115recursive_mutex8try_lockEv", (uintptr_t)&snk_recursive_mutex_try_lock, 1, 1 },
    { "_ZNSt3__119__shared_weak_count14__release_weakEv", (uintptr_t)&snk_shared_weak_count_release_weak, 1, 1 },
    { "_ZNSt3__119__shared_weak_countD2Ev", (uintptr_t)&snk_shared_weak_count_dtor, 1, 1 },
    { "_ZNSt3__112basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEEaSERKS5_", (uintptr_t)&snk_string_assign, 2, 1 },
    { "_ZNSt3__112basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEE7replaceEmmPKc", (uintptr_t)&snk_string_replace, 4, 1 },
    { "_ZNSt3__112__next_primeEm", (uintptr_t)&snk_next_prime, 1, 1 },
    { "_ZdlPvm", (uintptr_t)&snk_sized_delete, 2, 0 },
    { "_ZdaPvm", (uintptr_t)&snk_sized_delete, 2, 0 },
};

uint64_t snk_libcxx_lookup(const char *name, unsigned *arguments, unsigned *returns) {
    if (!name) return 0;
    for (size_t i = 0; i < sizeof(s_entries) / sizeof(*s_entries); i++) {
        if (strcmp(name, s_entries[i].name)) continue;
        if (arguments) *arguments = s_entries[i].arguments;
        if (returns) *returns = s_entries[i].returns;
        return (uint64_t)s_entries[i].function;
    }
    return 0;
}
