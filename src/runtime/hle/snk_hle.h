#ifndef SNK_HLE_H
#define SNK_HLE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Host implementations for the nn:: API that Sora no Kiseki the 1st calls
 * before its first frame is on screen.
 *
 * The lookup table below is the single source of truth for two decisions:
 * which host function answers an import name, and the argument and
 * return counts the native boundary needs for that call. Both the
 * import resolver and the call ABI read it, so a symbol can never be
 * bound with a signature that disagrees with its implementation. */
uint64_t snk_hle_lookup(const char *name, unsigned *arguments, unsigned *returns);

/* Tells the optional heap trace (marker hle-heap-trace) where the guest
 * address region the title reserves lives, so the trace can label the blocks
 * that pass through this allocator. A no-op when the trace is off. */
void snk_hle_heap_trace_arena(uintptr_t base, size_t bytes);

/* Read-only allocator snapshot for the fault handler. Prints only when the
 * heap trace marker is on; otherwise it is a single cached branch. */
void snk_hle_dump_allocators(void);

#ifdef __cplusplus
}
#endif

#endif