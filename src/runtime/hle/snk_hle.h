#ifndef SNK_HLE_H
#define SNK_HLE_H

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

#ifdef __cplusplus
}
#endif

#endif