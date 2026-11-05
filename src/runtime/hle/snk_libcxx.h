#ifndef SNK_LIBCXX_H
#define SNK_LIBCXX_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Host implementations for the SDK libc++ internals that Sora no Kiseki
 * the 1st imports from nnSdk.
 *
 * The Horizon SDK ships its own libc++, so the object layouts here are
 * the ones the SDK compiled code uses and not the ones of the host
 * toolchain. Every layout below was read out of the extracted nnSdk
 * module, not assumed. */
uint64_t snk_libcxx_lookup(const char *name, unsigned *arguments, unsigned *returns);

#ifdef __cplusplus
}
#endif

#endif