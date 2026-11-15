#include "xbg_vertex.h"
#include <string.h>
int xbg_vertex_max_index(const void *indices,size_t bytes,int index_type,
    int32_t base_vertex,uint64_t *out){
    if(!indices || !out || !bytes || index_type<0 || index_type>2)return -1;
    const size_t element_bytes=(size_t)1<<index_type;
    if(bytes%element_bytes)return -1;
    uint32_t maximum=0;
    const unsigned char *source=indices;
    /* Constant-width loads keep Android's fortified memcpy out of the loop.
     * NVN and the supported ARM64 hosts use little-endian indices. */
    if(index_type==0){
        for(size_t offset=0;offset<bytes;++offset)
            if(source[offset]>maximum)maximum=source[offset];
    }else if(index_type==1){
        for(size_t offset=0;offset<bytes;offset+=2){
            uint16_t index;memcpy(&index,source+offset,2);
            if(index>maximum)maximum=index;
        }
    }else{
        for(size_t offset=0;offset<bytes;offset+=4){
            uint32_t index;memcpy(&index,source+offset,4);
            if(index>maximum)maximum=index;
        }
    }
    const int64_t adjusted=(int64_t)maximum+base_vertex;
    if(adjusted<0)return -1;
    *out=(uint64_t)adjusted;
    return 0;
}
uint64_t xbg_vertex_prefix_bytes(uint64_t bound_bytes,uint32_t stride,
    uint32_t attribute_end,uint64_t maximum_element){
    if(!attribute_end || attribute_end>bound_bytes)return bound_bytes;
    if(stride && maximum_element>(UINT64_MAX-attribute_end)/stride)return bound_bytes;
    const uint64_t needed=maximum_element*stride+attribute_end;
    return needed<bound_bytes?needed:bound_bytes;
}
int xbg_vertex_attributes_replace(uint32_t state[16],const uint32_t *a,int n){
    if(!state || n<0 || n>16 || (n && !a))return -1;
    uint32_t replacement[16]={0};if(n)memcpy(replacement,a,(size_t)n*4);
    memcpy(state,replacement,sizeof(replacement));return 0;
}
int xbg_vertex_zero_binding(const uint32_t a[16],const uint32_t *locations,size_t n){
    if(!a || n>16 || (n && !locations))return -1;
    uint32_t used=0;for(size_t i=0;i<n;i++){
        if(locations[i]>=16)return -1;uint32_t v=a[locations[i]];
        if(v&255){uint32_t stream=v>>27;if(stream>=16)return -1;used|=1u<<stream;}
    }
    for(int i=0;i<16;i++)if(!(used&(1u<<i)))return i;return -1;
}
/* Input bundle locations are authored by the existing SPIR-V converter.
 * Reflect their actual scalar type without changing the on-disk XGS ABI.
 * No speculative format fallback for matrix/array/64-bit/component interfaces.
 */
int xbg_vertex_input_classes(const uint32_t *w,size_t n,const uint32_t *loc,size_t inputs,uint32_t *out){
    if(!w || n<5 || w[0]!=0x07230203 || inputs>16 || (inputs && (!loc || !out)))return -1;
    for(size_t p=5;p<n;){size_t z=w[p]>>16;if(!z || z>n-p)return -2;p+=z;}
    uint32_t result[16]={0};
    for(size_t i=0;i<inputs;i++){
        if(loc[i]>=16)return -3;for(size_t j=0;j<i;j++)if(loc[j]==loc[i])return -3;
        uint32_t variable=0,type=0;
        for(size_t p=5;p<n;p+=w[p]>>16)if((w[p]&65535)==71 && (w[p]>>16)==4 && w[p+2]==30 && w[p+3]==loc[i]){
            /* A matching Output decoration is not a vertex Input. */
            for(size_t q=5;q<n;q+=w[q]>>16)if((w[q]&65535)==59 && (w[q]>>16)>=4 && w[q+2]==w[p+1] && w[q+3]==1){
                if(variable)return -4;variable=w[p+1];type=w[q+1];
            }
        }
        if(!variable)return -5;
        for(size_t p=5;p<n;p+=w[p]>>16)if((w[p]&65535)==71 && (w[p]>>16)>=3 && w[p+1]==variable){
            if(w[p+2]==11)return -6; // BuiltIn cannot also be a user location
            if(w[p+2]==31 && ((w[p]>>16)!=4 || w[p+3]!=0))return -6;
        }
        uint32_t value=0,scalar=0;
        for(size_t p=5;p<n;p+=w[p]>>16)if((w[p]&65535)==32 && (w[p]>>16)==4 && w[p+1]==type && w[p+2]==1)value=w[p+3];
        if(!value)return -7;scalar=value;
        for(size_t p=5;p<n;p+=w[p]>>16)if((w[p]&65535)==23 && (w[p]>>16)==4 && w[p+1]==value){
            if(w[p+3]<2 || w[p+3]>4)return -8;scalar=w[p+2];
        }
        int found=0;
        for(size_t p=5;p<n;p+=w[p]>>16){uint32_t op=w[p]&65535,z=w[p]>>16;
            if(op==22 && z==3 && w[p+1]==scalar && w[p+2]==32){result[i]=0;found++;}
            if(op==21 && z==4 && w[p+1]==scalar && w[p+2]==32 && w[p+3]<=1){result[i]=w[p+3]?1:2;found++;}
        }
        if(found!=1)return -9;
    }
    if(inputs)memcpy(out,result,inputs*4);return 0;
}
