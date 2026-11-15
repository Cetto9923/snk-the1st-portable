#ifndef XBG_DIRTY_H
#define XBG_DIRTY_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Pool lifetime and host writes are synchronous, including with async rendering. */
void xbg_dirty_enable(int enabled);
void xbg_dirty_add(const void *memory, size_t bytes);
void xbg_dirty_remove(const void *memory);
int xbg_dirty_write_begin(void *memory, size_t bytes);
void xbg_dirty_write_end(int lease);
int xbg_dirty_fault(void *address, int is_write);

int nvn_dirty_tracked(const void *address, size_t bytes);
uint64_t nvn_dirty_now(void);
void nvn_dirty_protect(const void *address, size_t bytes);
int nvn_dirty_since(const void *address, size_t bytes, uint64_t stamp);
void nvn_dirty_slot_stats(int *live, int *used, uint64_t *adds);

#ifdef __cplusplus
}
#endif
#endif
