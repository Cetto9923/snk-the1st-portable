#include "snk_hle.h"
#include "nso_host.h"

#include <dirent.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <wchar.h>

/* ====================================================================== */
/* nn::os process heap                                                     */
/* ====================================================================== */

static pthread_mutex_t s_heap_lock = PTHREAD_MUTEX_INITIALIZER;
static uint64_t s_heap_budget;

static uint64_t snk_heap_budget(void) {
    pthread_mutex_lock(&s_heap_lock);
    uint64_t budget = s_heap_budget;
    pthread_mutex_unlock(&s_heap_lock);
    return budget;
}

/* nn::os::SetMemoryHeapSize(uint64_t size)
 * The SDK routes this into the process memory manager that owns the
 * application heap. The host keeps the number so the allocator below can
 * refuse a request the console would refuse as well. */
static uint64_t snk_set_memory_heap_size(uint64_t size) {
    pthread_mutex_lock(&s_heap_lock);
    s_heap_budget = size;
    pthread_mutex_unlock(&s_heap_lock);
    fprintf(stderr, "[snk-hle] nn::os::SetMemoryHeapSize: budget=%llu\n",
            (unsigned long long)size);
    return 0;
}

/* nn::os::AllocateMemoryBlock(nn::Result* out, uint64_t size)
 * The console hands the title a reservation inside the application heap
 * address range; pages are committed when the title touches them. A
 * private NORESERVE mapping is the host equivalent, so the large request
 * this title makes costs address space instead of resident memory. */
static int64_t snk_allocate_memory_block(void **out, uint64_t size) {
    if (!out) return -1;
    if (size == 0) size = 4096;
    void *block = mmap(NULL, (size_t)size, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (block == MAP_FAILED) {
        *out = NULL;
        int error = errno ? errno : ENOMEM;
        fprintf(stderr, "[snk-hle] nn::os::AllocateMemoryBlock: size=%llu failed errno=%d\n",
                (unsigned long long)size, error);
        return -error;
    }
    *out = block;
    fprintf(stderr, "[snk-hle] nn::os::AllocateMemoryBlock: size=%llu block=%p\n",
            (unsigned long long)size, block);
    return 0;
}

/* ====================================================================== */
/* nn::mem::StandardAllocator                                               */
/* ====================================================================== */

struct snk_allocator {
    void *object;
    void *base;
    uint64_t capacity;
    uint64_t used;
    bool initialized;
    struct snk_allocator *next;
};

static pthread_mutex_t s_alloc_lock = PTHREAD_MUTEX_INITIALIZER;
static struct snk_allocator *s_allocators;

static struct snk_allocator *allocator_entry(void *object, bool create) {
    pthread_mutex_lock(&s_alloc_lock);
    struct snk_allocator *entry = s_allocators;
    while (entry && entry->object != object) entry = entry->next;
    if (!entry && create) {
        entry = calloc(1, sizeof(*entry));
        if (entry) {
            entry->object = object;
            entry->next = s_allocators;
            s_allocators = entry;
        }
    }
    pthread_mutex_unlock(&s_alloc_lock);
    return entry;
}

/* The SDK20 constructor zeroes this guest object layout before the
 * allocator is bound to a region; mirror it byte for byte. */
static void allocator_zero_object(void *object) {
    if (!object) return;
    unsigned char *bytes = (unsigned char *)object;
    *(uint16_t *)(bytes + 0x00) = 0;
    *(uint64_t *)(bytes + 0x08) = 0;
    *(uint64_t *)(bytes + 0x18) = 0;
    *(uint8_t *)(bytes + 0x20) = 0;
    *(uint64_t *)(bytes + 0x24) = 0;
    *(uint64_t *)(bytes + 0x2c) = 0;
    *(uint32_t *)(bytes + 0x34) = 0;
}

static uint64_t snk_allocator_ctor_default(void *object) {
    allocator_zero_object(object);
    struct snk_allocator *entry = allocator_entry(object, true);
    if (entry) {
        entry->base = NULL;
        entry->capacity = 0;
        entry->used = 0;
        entry->initialized = false;
    }
    fprintf(stderr, "[snk-hle] nn::mem::StandardAllocator::StandardAllocator: object=%p\n", object);
    return 0;
}

static uint64_t snk_allocator_ctor_region(void *object, void *base, uint64_t size) {
    allocator_zero_object(object);
    struct snk_allocator *entry = allocator_entry(object, true);
    if (entry) {
        entry->base = base;
        entry->capacity = size;
        entry->used = 0;
        entry->initialized = false;
    }
    fprintf(stderr, "[snk-hle] nn::mem::StandardAllocator::StandardAllocator: object=%p base=%p size=%llu\n",
            object, base, (unsigned long long)size);
    return 0;
}

/* nn::mem::StandardAllocator::Initialize(void* base, uint64_t size, bool) */
static uint64_t snk_allocator_initialize(void *object, void *base, uint64_t size, bool flag) {
    struct snk_allocator *entry = allocator_entry(object, true);
    if (!entry) {
        fprintf(stderr, "[snk-hle] nn::mem::StandardAllocator::Initialize: out of memory\n");
        return 0;
    }
    if (entry->initialized) {
        fprintf(stderr, "[snk-hle] nn::mem::StandardAllocator::Initialize: already initialized object=%p\n", object);
        return 0;
    }
    /* The SDK rounds the region down to a page boundary before use. */
    uint64_t usable = size & ~(uint64_t)0xfff;
    entry->base = base;
    entry->capacity = usable;
    entry->used = 0;
    entry->initialized = true;
    if (object) *(uint8_t *)object = 1;
    fprintf(stderr, "[snk-hle] nn::mem::StandardAllocator::Initialize: object=%p base=%p size=%llu flag=%d\n",
            object, base, (unsigned long long)usable, flag ? 1 : 0);
    return 0;
}

static uint64_t snk_allocator_finalize(void *object) {
    struct snk_allocator *entry = allocator_entry(object, false);
    if (entry) {
        entry->initialized = false;
        entry->used = 0;
    }
    if (object) *(uint8_t *)object = 0;
    fprintf(stderr, "[snk-hle] nn::mem::StandardAllocator::Finalize: object=%p\n", object);
    return 0;
}

static size_t snk_usable_size(void *block) {
#if defined(__ANDROID__) || defined(__linux__)
    return malloc_usable_size(block);
#else
    (void)block;
    return 0;
#endif
}

static void *snk_allocator_allocate(void *object, uint64_t size, uint64_t alignment) {
    struct snk_allocator *entry = allocator_entry(object, false);
    if (!entry) {
        fprintf(stderr, "[snk-hle] nn::mem::StandardAllocator::Allocate: unknown allocator object=%p\n", object);
        return NULL;
    }
    if (alignment == 0) alignment = 16;
    if ((alignment & (alignment - 1)) != 0) alignment = 16;
    size_t request = (size_t)size;
    if (request == 0) request = 1;
    size_t rounded = (request + (size_t)alignment - 1) / (size_t)alignment * (size_t)alignment;
    pthread_mutex_lock(&s_alloc_lock);
    uint64_t capacity = entry->capacity ? entry->capacity : snk_heap_budget();
    if (capacity && entry->used + rounded > capacity) {
        fprintf(stderr, "[snk-hle] nn::mem::StandardAllocator::Allocate: budget exceeded used=%llu request=%llu capacity=%llu\n",
                (unsigned long long)entry->used, (unsigned long long)rounded,
                (unsigned long long)capacity);
        pthread_mutex_unlock(&s_alloc_lock);
        return NULL;
    }
    void *block = aligned_alloc((size_t)alignment, rounded);
    if (!block) {
        pthread_mutex_unlock(&s_alloc_lock);
        fprintf(stderr, "[snk-hle] nn::mem::StandardAllocator::Allocate: host allocation of %llu bytes failed\n",
                (unsigned long long)rounded);
        return NULL;
    }
    entry->used += rounded;
    pthread_mutex_unlock(&s_alloc_lock);
    return block;
}

static void *snk_allocator_allocate_plain(void *object, uint64_t size) {
    return snk_allocator_allocate(object, size, 16);
}

static uint64_t snk_allocator_free(void *object, void *block) {
    if (!block) return 0;
    size_t size = snk_usable_size(block);
    free(block);
    struct snk_allocator *entry = allocator_entry(object, false);
    if (entry) {
        pthread_mutex_lock(&s_alloc_lock);
        if (entry->used >= size) entry->used -= size; else entry->used = 0;
        pthread_mutex_unlock(&s_alloc_lock);
    }
    return 0;
}

static void *snk_allocator_reallocate(void *object, void *block, uint64_t size) {
    size_t before = block ? snk_usable_size(block) : 0;
    void *next = realloc(block, (size_t)size);
    if (!next) return NULL;
    size_t after = snk_usable_size(next);
    struct snk_allocator *entry = allocator_entry(object, false);
    if (entry) {
        pthread_mutex_lock(&s_alloc_lock);
        if (entry->used >= before) entry->used = entry->used - before + after;
        pthread_mutex_unlock(&s_alloc_lock);
    }
    return next;
}
/* ====================================================================== */
/* nn::os light event, light semaphore and message queue                   */
/* ====================================================================== */

enum snk_sync_kind { SNK_SYNC_EVENT, SNK_SYNC_SEMAPHORE, SNK_SYNC_QUEUE };

struct snk_sync {
    void *object;
    enum snk_sync_kind kind;
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    bool signaled;
    bool initialized;
    uint8_t clear_mode;
    int32_t count;
    int32_t max_count;
    uint64_t *slots;
    uint64_t capacity;
    uint64_t head;
    uint64_t tail;
    uint64_t size;
    struct snk_sync *next;
};

#define SNK_SYNC_BUCKETS 256
static pthread_mutex_t s_sync_lock = PTHREAD_MUTEX_INITIALIZER;
static struct snk_sync *s_sync_buckets[SNK_SYNC_BUCKETS];

static size_t sync_hash(void *object) {
    uintptr_t key = (uintptr_t)object;
    return (size_t)((key >> 4) ^ (key >> 11)) & (SNK_SYNC_BUCKETS - 1);
}

static struct snk_sync *sync_find_locked(void *object) {
    struct snk_sync *entry = s_sync_buckets[sync_hash(object)];
    while (entry && entry->object != object) entry = entry->next;
    return entry;
}

static struct snk_sync *sync_borrow(void *object, enum snk_sync_kind kind, bool create) {
    if (!object) return NULL;
    pthread_mutex_lock(&s_sync_lock);
    struct snk_sync *entry = sync_find_locked(object);
    pthread_mutex_unlock(&s_sync_lock);
    if (entry) return entry;
    if (!create) return NULL;
    entry = calloc(1, sizeof(*entry));
    if (!entry) return NULL;
    pthread_mutex_init(&entry->mutex, NULL);
    pthread_cond_init(&entry->cond, NULL);
    entry->object = object;
    entry->kind = kind;
    entry->initialized = true;
    pthread_mutex_lock(&s_sync_lock);
    size_t bucket = sync_hash(object);
    entry->next = s_sync_buckets[bucket];
    s_sync_buckets[bucket] = entry;
    pthread_mutex_unlock(&s_sync_lock);
    return entry;
}

static void sync_destroy(void *object) {
    pthread_mutex_lock(&s_sync_lock);
    size_t bucket = sync_hash(object);
    struct snk_sync **slot = &s_sync_buckets[bucket];
    while (*slot && (*slot)->object != object) slot = &(*slot)->next;
    struct snk_sync *entry = *slot;
    if (entry) *slot = entry->next;
    pthread_mutex_unlock(&s_sync_lock);
    if (entry) {
        pthread_cond_destroy(&entry->cond);
        pthread_mutex_destroy(&entry->mutex);
        free(entry);
    }
}

/* nn::os::InitializeLightEvent(LightEventType*, bool, EventClearMode) */
static uint64_t snk_initialize_light_event(void *object, bool initially_signaled, int32_t clear_mode) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_EVENT, true);
    if (!entry) {
        fprintf(stderr, "[snk-hle] nn::os::InitializeLightEvent: out of memory\n");
        return 0;
    }
    pthread_mutex_lock(&entry->mutex);
    entry->signaled = initially_signaled;
    entry->clear_mode = (uint8_t)clear_mode;
    entry->initialized = true;
    pthread_mutex_unlock(&entry->mutex);
    fprintf(stderr, "[snk-hle] nn::os::InitializeLightEvent: object=%p signaled=%d mode=%d\n",
            object, initially_signaled ? 1 : 0, clear_mode);
    return 0;
}

static uint64_t snk_finalize_light_event(void *object) {
    sync_destroy(object);
    fprintf(stderr, "[snk-hle] nn::os::FinalizeLightEvent: object=%p\n", object);
    return 0;
}

static uint64_t snk_signal_light_event(void *object) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_EVENT, false);
    if (!entry) {
        fprintf(stderr, "[snk-hle] nn::os::SignalLightEvent: unknown object=%p\n", object);
        return 0;
    }
    pthread_mutex_lock(&entry->mutex);
    entry->signaled = true;
    pthread_cond_broadcast(&entry->cond);
    pthread_mutex_unlock(&entry->mutex);
    return 0;
}

static uint64_t snk_clear_light_event(void *object) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_EVENT, false);
    if (!entry) return 0;
    pthread_mutex_lock(&entry->mutex);
    entry->signaled = false;
    pthread_mutex_unlock(&entry->mutex);
    return 0;
}

static uint64_t snk_wait_light_event(void *object, int64_t nanoseconds, bool timed) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_EVENT, false);
    if (!entry) return false;
    struct timespec deadline;
    if (timed) {
        clock_gettime(CLOCK_MONOTONIC, &deadline);
        if (nanoseconds > 0) {
            deadline.tv_sec += nanoseconds / 1000000000;
            deadline.tv_nsec += nanoseconds % 1000000000;
            if (deadline.tv_nsec >= 1000000000) {
                deadline.tv_nsec -= 1000000000;
                deadline.tv_sec++;
            }
        }
    }
    pthread_mutex_lock(&entry->mutex);
    while (!entry->signaled) {
        int error = timed ? pthread_cond_timedwait(&entry->cond, &entry->mutex, &deadline)
                          : pthread_cond_wait(&entry->cond, &entry->mutex);
        if (error == ETIMEDOUT) break;
    }
    bool signaled = entry->signaled;
    if (signaled && entry->clear_mode == 1) entry->signaled = false;
    pthread_mutex_unlock(&entry->mutex);
    return signaled;
}

static bool snk_wait_light_event_plain(void *object) {
    return snk_wait_light_event(object, 0, false);
}

static uint64_t snk_timed_wait_light_event(void *object, int64_t nanoseconds) {
    return snk_wait_light_event(object, nanoseconds, true);
}

/* nn::os::InitializeLightSemaphore(LightSemaphoreType*, int32_t, int32_t) */
static uint64_t snk_initialize_light_semaphore(void *object, int32_t initial, int32_t maximum) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_SEMAPHORE, true);
    if (!entry) {
        fprintf(stderr, "[snk-hle] nn::os::InitializeLightSemaphore: out of memory\n");
        return 0;
    }
    pthread_mutex_lock(&entry->mutex);
    entry->count = initial;
    entry->max_count = maximum;
    entry->initialized = true;
    pthread_mutex_unlock(&entry->mutex);
    fprintf(stderr, "[snk-hle] nn::os::InitializeLightSemaphore: object=%p initial=%d max=%d\n",
            object, initial, maximum);
    return 0;
}

static uint64_t snk_finalize_light_semaphore(void *object) {
    sync_destroy(object);
    fprintf(stderr, "[snk-hle] nn::os::FinalizeLightSemaphore: object=%p\n", object);
    return 0;
}

static uint64_t snk_acquire_light_semaphore(void *object) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_SEMAPHORE, false);
    if (!entry) return false;
    pthread_mutex_lock(&entry->mutex);
    while (entry->count <= 0) pthread_cond_wait(&entry->cond, &entry->mutex);
    entry->count--;
    pthread_mutex_unlock(&entry->mutex);
    return true;
}

static uint64_t snk_release_light_semaphore(void *object) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_SEMAPHORE, false);
    if (!entry) return false;
    pthread_mutex_lock(&entry->mutex);
    if (entry->max_count > 0 && entry->count >= entry->max_count) {
        pthread_mutex_unlock(&entry->mutex);
        return false;
    }
    entry->count++;
    pthread_cond_signal(&entry->cond);
    pthread_mutex_unlock(&entry->mutex);
    return true;
}

/* nn::os::InitializeMessageQueue(MessageQueueType*, void* buffer, uint64_t size) */
static uint64_t snk_initialize_message_queue(void *object, void *buffer, uint64_t size) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_QUEUE, true);
    if (!entry) {
        fprintf(stderr, "[snk-hle] nn::os::InitializeMessageQueue: out of memory\n");
        return 0;
    }
    pthread_mutex_lock(&entry->mutex);
    entry->slots = (uint64_t *)buffer;
    entry->capacity = size / sizeof(uint64_t);
    entry->head = 0;
    entry->tail = 0;
    entry->size = 0;
    entry->initialized = true;
    pthread_mutex_unlock(&entry->mutex);
    fprintf(stderr, "[snk-hle] nn::os::InitializeMessageQueue: object=%p buffer=%p capacity=%llu\n",
            object, buffer, (unsigned long long)entry->capacity);
    return 0;
}

static uint64_t snk_finalize_message_queue(void *object) {
    sync_destroy(object);
    fprintf(stderr, "[snk-hle] nn::os::FinalizeMessageQueue: object=%p\n", object);
    return 0;
}

static uint64_t snk_send_message_queue(void *object, uint64_t message) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_QUEUE, false);
    if (!entry) return false;
    pthread_mutex_lock(&entry->mutex);
    if (entry->capacity == 0 || entry->size >= entry->capacity) {
        pthread_mutex_unlock(&entry->mutex);
        return false;
    }
    entry->slots[entry->tail] = message;
    entry->tail = (entry->tail + 1) % entry->capacity;
    entry->size++;
    pthread_cond_signal(&entry->cond);
    pthread_mutex_unlock(&entry->mutex);
    return true;
}

static uint64_t snk_receive_message_queue(uint64_t *out, void *object) {
    struct snk_sync *entry = sync_borrow(object, SNK_SYNC_QUEUE, false);
    if (!entry || !out) return false;
    pthread_mutex_lock(&entry->mutex);
    while (entry->size == 0) pthread_cond_wait(&entry->cond, &entry->mutex);
    *out = entry->slots[entry->head];
    entry->head = (entry->head + 1) % entry->capacity;
    entry->size--;
    pthread_cond_signal(&entry->cond);
    pthread_mutex_unlock(&entry->mutex);
    return true;
}
/* ====================================================================== */
/* Remaining nn:: entry points the title reaches before the first frame   */
/* ====================================================================== */

/* nn::oe::PopNotificationMessage()
 * The applet message queue does not exist on this host. A title that
 * never received a message gets the console answer "no message". */
static int32_t snk_pop_notification_message(void) {
    return 0;
    return 0;
}

/* nn::init::Start(uint64_t, uint64_t, void(*)(), void(*)(), void(*)())
 * The SDK runs the three title callbacks in this order around its own
 * start up and tear down steps. */
static uint64_t snk_init_start(uint64_t first, uint64_t second,
                          void (*setup1)(void), void (*setup2)(void), void (*setup3)(void)) {
    fprintf(stderr, "[snk-hle] nn::init::Start: first=%llu second=%llu\n",
            (unsigned long long)first, (unsigned long long)second);
    if (setup1) setup1();
    if (setup2) setup2();
    if (setup3) setup3();
    return 0;
}

/* nn::hid::ControllerSupportArg::SetDefault()
 * The SDK20 implementation writes 0x01010040, then 1, then clears the
 * remaining 0x42b bytes of the argument block. */
static uint64_t snk_controller_support_arg_set_default(void *object) {
    if (!object) return 0;
    unsigned char *bytes = (unsigned char *)object;
    uint32_t head = 0x01010040u;
    memcpy(bytes, &head, sizeof(head));
    bytes[4] = 1;
    memset(bytes + 5, 0, 0x42b);
    return 0;
}

/* nn::hid::ShowControllerSupport(const ControllerSupportArg&)
 * The console opens an applet page here. This host has no applet, so the
 * request is recorded and the already prepared argument stays in force. */
static uint64_t snk_show_controller_support(const void *argument) {
    fprintf(stderr, "[snk-hle] nn::hid::ShowControllerSupport: argument=%p (no applet on this host)\n", argument);
    return 0;
}

/* nn::fs::DeleteFile(const char*) */
static int64_t snk_delete_file(const char *path) {
    if (!path) return -1;
    if (remove(path) && errno != ENOENT) {
        fprintf(stderr, "[snk-hle] nn::fs::DeleteFile: path=%s errno=%d\n", path, errno);
        return -errno;
    }
    return 0;
}

static int32_t snk_delete_tree(const char *path) {
    DIR *directory = opendir(path);
    if (!directory) return errno == ENOENT ? 0 : -errno;
    int status = 0;
    struct dirent *item;
    while ((item = readdir(directory)) != NULL) {
        if (!strcmp(item->d_name, ".") || !strcmp(item->d_name, "..")) continue;
        size_t length = strlen(path) + strlen(item->d_name) + 2;
        char *child = malloc(length);
        if (!child) { status = -ENOMEM; break; }
        snprintf(child, length, "%s/%s", path, item->d_name);
        struct stat info;
        if (!lstat(child, &info) && S_ISDIR(info.st_mode)) status = snk_delete_tree(child);
        else status = unlink(child) ? -errno : 0;
        free(child);
        if (status) break;
    }
    closedir(directory);
    if (status) return status;
    return rmdir(path) ? -errno : 0;
}

/* nn::fs::DeleteDirectoryRecursively(const char*) */
static int64_t snk_delete_directory_recursively(const char *path) {
    if (!path) return -1;
    int status = snk_delete_tree(path);
    if (status) {
        fprintf(stderr, "[snk-hle] nn::fs::DeleteDirectoryRecursively: path=%s status=%d\n", path, status);
    }
    return status;
}

/* nn::time::Finalize() */
static uint64_t snk_time_finalize(void) {
    fprintf(stderr, "[snk-hle] nn::time::Finalize\n");
    return 0;
}

/* nn::time::ToCalendarTime(CalendarTime*, CalendarAdditionalInfo*, const PosixTime&) */
static uint64_t snk_time_to_calendar_time(struct nn_calendar_time *out_calendar,
                                         struct nn_calendar_additional_info *out_info,
                                         const int64_t *posix_time) {
    return nso_host_time_to_calendar_time(out_calendar, out_info, posix_time, NULL);
}

/* nn::vi::SetLayerCrop(Layer*, int32_t, int32_t, int32_t, int32_t) */
static int32_t snk_set_layer_crop(void *layer, int32_t x, int32_t y, int32_t width, int32_t height) {
    fprintf(stderr, "[snk-hle] nn::vi::SetLayerCrop: layer=%p crop=%d,%d %dx%d\n",
            layer, x, y, width, height);
    return 0;
    return 0;
}

/* nn::diag::detail::AbortImpl(const nn::Result*) */
static void snk_abort_impl(const int32_t *result) {
    int32_t code = result ? *result : 0;
    fprintf(stderr, "[snk-hle] nn::diag::detail::AbortImpl: result=0x%08x\n", (unsigned)code);
    fflush(stderr);
    abort();
}

/* ====================================================================== */
/* Plain C library entry points the title imports                        */
/* ====================================================================== */

/* operator new(size_t, const std::nothrow_t&) */
static void *snk_operator_new_nothrow(uint64_t size) {
    void *block = malloc((size_t)size);
    if (!block) {
        fprintf(stderr, "[snk-hle] operator new(nothrow): %llu bytes failed\n", (unsigned long long)size);
    }
    return block;
}

/* wmemchr(const wchar_t*, wchar_t, size_t) */
static void *snk_wmemchr(const void *haystack, uint32_t needle, uint64_t count) {
    return wmemchr((const wchar_t *)haystack, (wchar_t)needle, (size_t)count);
}

static uint64_t snk_sched_yield(void) {
    sched_yield();
    return 0;
}

static FILE *snk_fopen(const char *path, const char *mode) {
    FILE *file = fopen(path, mode);
    fprintf(stderr, "[snk-hle] fopen: path=%s mode=%s handle=%p\n", path, mode, (void *)file);
    return file;
}

static int64_t snk_fclose(FILE *file) {
    return fclose(file);
}

static char *snk_stpcpy(char *destination, const char *source) {
    return stpcpy(destination, source);
}

static char *snk_strtok(char *text, const char *delimiters) {
    return strtok(text, delimiters);
}

static int32_t *snk_errno_location(void) {
    return &errno;
}

/* ====================================================================== */
/* The import table                                                    */
/* ====================================================================== */

struct snk_entry {
    const char *name;
    uintptr_t function;
    unsigned arguments;
    unsigned returns;
};

static const struct snk_entry s_entries[] = {
    { "_ZN2nn2os17SetMemoryHeapSizeEm", (uintptr_t)&snk_set_memory_heap_size, 1, 1 },
    { "_ZN2nn2os19AllocateMemoryBlockEPmm", (uintptr_t)&snk_allocate_memory_block, 2, 1 },
    { "_ZN2nn3mem17StandardAllocatorC1Ev", (uintptr_t)&snk_allocator_ctor_default, 1, 1 },
    { "_ZN2nn3mem17StandardAllocatorC1EPvm", (uintptr_t)&snk_allocator_ctor_region, 3, 1 },
    { "_ZN2nn3mem17StandardAllocator10InitializeEPvmb", (uintptr_t)&snk_allocator_initialize, 4, 1 },
    { "_ZN2nn3mem17StandardAllocator8FinalizeEv", (uintptr_t)&snk_allocator_finalize, 1, 1 },
    { "_ZN2nn3mem17StandardAllocator8AllocateEmm", (uintptr_t)&snk_allocator_allocate, 3, 1 },
    { "_ZN2nn3mem17StandardAllocator8AllocateEm", (uintptr_t)&snk_allocator_allocate_plain, 2, 1 },
    { "_ZN2nn3mem17StandardAllocator4FreeEPv", (uintptr_t)&snk_allocator_free, 2, 1 },
    { "_ZN2nn3mem17StandardAllocator10ReallocateEPvm", (uintptr_t)&snk_allocator_reallocate, 3, 1 },
    { "_ZN2nn4diag6detail9AbortImplEPKNS_6ResultE", (uintptr_t)&snk_abort_impl, 1, 1 },
    { "_ZN2nn2os20InitializeLightEventEPNS0_14LightEventTypeEbNS0_14EventClearModeE", (uintptr_t)&snk_initialize_light_event, 3, 1 },
    { "_ZN2nn2os18FinalizeLightEventEPNS0_14LightEventTypeE", (uintptr_t)&snk_finalize_light_event, 1, 1 },
    { "_ZN2nn2os16SignalLightEventEPNS0_14LightEventTypeE", (uintptr_t)&snk_signal_light_event, 1, 1 },
    { "_ZN2nn2os15ClearLightEventEPNS0_14LightEventTypeE", (uintptr_t)&snk_clear_light_event, 1, 1 },
    { "_ZN2nn2os14WaitLightEventEPNS0_14LightEventTypeE", (uintptr_t)&snk_wait_light_event_plain, 1, 1 },
    { "_ZN2nn2os19TimedWaitLightEventEPNS0_14LightEventTypeENS_8TimeSpanE", (uintptr_t)&snk_timed_wait_light_event, 2, 1 },
    { "_ZN2nn2os24InitializeLightSemaphoreEPNS0_18LightSemaphoreTypeEii", (uintptr_t)&snk_initialize_light_semaphore, 3, 1 },
    { "_ZN2nn2os22FinalizeLightSemaphoreEPNS0_18LightSemaphoreTypeE", (uintptr_t)&snk_finalize_light_semaphore, 1, 1 },
    { "_ZN2nn2os21AcquireLightSemaphoreEPNS0_18LightSemaphoreTypeE", (uintptr_t)&snk_acquire_light_semaphore, 1, 1 },
    { "_ZN2nn2os21ReleaseLightSemaphoreEPNS0_18LightSemaphoreTypeE", (uintptr_t)&snk_release_light_semaphore, 1, 1 },
    { "_ZN2nn2os22InitializeMessageQueueEPNS0_16MessageQueueTypeEPmm", (uintptr_t)&snk_initialize_message_queue, 3, 1 },
    { "_ZN2nn2os20FinalizeMessageQueueEPNS0_16MessageQueueTypeE", (uintptr_t)&snk_finalize_message_queue, 1, 1 },
    { "_ZN2nn2os16SendMessageQueueEPNS0_16MessageQueueTypeEm", (uintptr_t)&snk_send_message_queue, 2, 1 },
    { "_ZN2nn2os19ReceiveMessageQueueEPmPNS0_16MessageQueueTypeE", (uintptr_t)&snk_receive_message_queue, 2, 1 },
    { "_ZN2nn2oe22PopNotificationMessageEv", (uintptr_t)&snk_pop_notification_message, 0, 1 },
    { "_ZN2nn4init5StartEmmPFvvES2_S2_", (uintptr_t)&snk_init_start, 5, 1 },
    { "_ZN2nn3hid20ControllerSupportArg10SetDefaultEv", (uintptr_t)&snk_controller_support_arg_set_default, 1, 1 },
    { "_ZN2nn3hid21ShowControllerSupportERKNS0_20ControllerSupportArgE", (uintptr_t)&snk_show_controller_support, 1, 1 },
    { "_ZN2nn2fs10DeleteFileEPKc", (uintptr_t)&snk_delete_file, 1, 1 },
    { "_ZN2nn2fs26DeleteDirectoryRecursivelyEPKc", (uintptr_t)&snk_delete_directory_recursively, 1, 1 },
    { "_ZN2nn4time8FinalizeEv", (uintptr_t)&snk_time_finalize, 0, 1 },
    { "_ZN2nn4time14ToCalendarTimeEPNS0_12CalendarTimeEPNS0_22CalendarAdditionalInfoERKNS0_9PosixTimeE", (uintptr_t)&snk_time_to_calendar_time, 3, 1 },
    { "_ZN2nn2vi12SetLayerCropEPNS0_5LayerEiiii", (uintptr_t)&snk_set_layer_crop, 5, 1 },
    { "_ZnwmRKSt9nothrow_t", (uintptr_t)&snk_operator_new_nothrow, 1, 1 },
    { "wmemchr", (uintptr_t)&snk_wmemchr, 3, 1 },
    { "sched_yield", (uintptr_t)&snk_sched_yield, 0, 1 },
    { "fopen", (uintptr_t)&snk_fopen, 2, 1 },
    { "fclose", (uintptr_t)&snk_fclose, 1, 1 },
    { "stpcpy", (uintptr_t)&snk_stpcpy, 2, 1 },
    { "strtok", (uintptr_t)&snk_strtok, 2, 1 },
    { "__errno_location", (uintptr_t)&snk_errno_location, 0, 1 },
};

/* nvnPrivate0 (main NSO import index 290) is a data import. The guest
 * reads the pointer from its own GOT slot and then reads one 32 bit flag
 * from that object. The console NVN module owns that block; this host has
 * no NVN module, so it hands over the block with the flag cleared, which is
 * the state a retail title sees outside of a capture session. */
static uint32_t s_nvn_private_object[64];

uint64_t snk_hle_lookup(const char *name, unsigned *arguments, unsigned *returns) {
    if (!name) return 0;
    if (!strcmp(name, "nvnPrivate0")) {
        if (arguments) *arguments = 0;
        if (returns) *returns = 0;
        return (uint64_t)(uintptr_t)s_nvn_private_object;
    }
    for (size_t i = 0; i < sizeof(s_entries) / sizeof(*s_entries); i++) {
        if (strcmp(name, s_entries[i].name)) continue;
        if (arguments) *arguments = s_entries[i].arguments;
        if (returns) *returns = s_entries[i].returns;
        return (uint64_t)s_entries[i].function;
    }
    return 0;
}
