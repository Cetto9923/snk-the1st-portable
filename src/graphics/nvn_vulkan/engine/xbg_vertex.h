#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Class 0=float32, 1=sint32, 2=uint32. Reject unsupported interfaces. */
int xbg_vertex_input_classes(const uint32_t *words,size_t count,const uint32_t *locations,size_t inputs,uint32_t *classes);
/* Full NVN attribute-state replacement, including clearing the inactive tail. */
int xbg_vertex_attributes_replace(uint32_t state[16],const uint32_t *attributes,int count);
/* Return an unused real binding 0..15, or -1 when none is available. */
int xbg_vertex_zero_binding(const uint32_t attributes[16],const uint32_t *locations,size_t count);
/* CPU-clean NVN indices only. The base vertex is applied to the maximum. */
int xbg_vertex_max_index(const void *indices,size_t bytes,int index_type,
    int32_t base_vertex,uint64_t *out);
/* Preserve the binding origin and every attribute fetched by this draw. */
uint64_t xbg_vertex_prefix_bytes(uint64_t bound_bytes,uint32_t stride,
    uint32_t attribute_end,uint64_t maximum_element);
#ifdef __cplusplus
}
#endif
