#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <climits>
#include <vector>
#include "xbg_writeback_policy.h"

// Metadata for shader 9bee7f09d6c655c3 only. Its validated integer module writes
// {template[2], GPU instance count, template[3], 0, 0} at template[0] uint words.
// This does not calculate, replace, or read back the instance count. Callers
// must prove exact shader/bindings, CPU-clean descriptor snapshots, and that
// other storage bindings do not alias the argument destination.
struct XbgIndirectTemplateRow {
    uint64_t address;
    uint32_t index_count,first_index;
};
inline bool xbg_indirect_templates(std::vector<XbgIndirectTemplateRow> &out,
    const std::vector<uint32_t> &words,const uint32_t params[4],
    uint64_t destination,uint64_t destination_bytes,uint32_t gx,uint32_t gy,uint32_t gz){
    out.clear();
    const uint64_t start=params[0],count=params[1];
    if(!destination || destination_bytes<20 || destination_bytes>65536 || (destination&3) ||
       (destination_bytes&3) || destination+destination_bytes<destination || !gx || gy!=1 || gz!=1 ||
       !count || count>256 || count>uint64_t(gx)*64 || words.size()>16384 ||
       start+count>words.size()/5)return false;
    std::vector<XbgIndirectTemplateRow> rows;rows.reserve(size_t(count));
    for(uint64_t j=0;j<count;j++){
        const uint32_t *q=words.data()+(start+j)*5;const uint64_t offset=uint64_t(q[0])*4;
        if(offset>destination_bytes-20 || q[2]>INT32_MAX || q[3]>INT32_MAX)return false;
        rows.push_back({destination+offset,q[2],q[3]});
    }
    std::sort(rows.begin(),rows.end(),[](const XbgIndirectTemplateRow &a,const XbgIndirectTemplateRow &b){return a.address<b.address;});
    for(size_t i=1;i<rows.size();i++)if(rows[i].address<rows[i-1].address+20)return false;
    out.swap(rows);return true;
}

// The audited Falcom instance-cull module only atomically updates word 1 of
// each 20-byte argument row. Capture its four static words from the actual
// CPU-clean descriptor before dispatch. The current consumer publishes zero
// base vertex and base instance, so rows with other values use CPU decoding.
inline bool xbg_snk_instance_templates(std::vector<XbgIndirectTemplateRow> &out,
    const std::vector<uint32_t> &words,uint64_t destination,uint64_t bytes){
    out.clear();
    if(!destination || (destination&3) || bytes<20 || bytes>65536 ||
       (bytes&3) || destination+bytes<destination || words.size()!=bytes/4)return false;
    for(size_t offset=0;offset+5<=words.size();offset+=5){
        const uint32_t *args=words.data()+offset;
        if(args[0]>INT32_MAX || args[2]>INT32_MAX || args[3] || args[4])continue;
        out.push_back({destination+offset*4,args[0],args[2]});
    }
    return !out.empty();
}

// The exact audited cull kernel writes row = metadata[record*80+4] + {0,1}.
// Validate every possible row before excluding descriptor alignment padding
// from its deferred writes. The shader still receives the full descriptor.
inline uint64_t xbg_snk_instance_writeback_bytes(const uint32_t *records,
    size_t record_words,uint32_t active,uint32_t groups,uint64_t bytes){
    if(!records || !active || !groups || bytes<40 || bytes>65536 || (bytes&3) ||
       uint64_t(active)>uint64_t(groups)*1024 || uint64_t(active)*20>record_words)
        return 0;
    const uint64_t rows=bytes/20;
    for(uint32_t i=0;i<active;++i){
        const uint32_t *record=records+size_t(i)*20;
        // Both LOD selectors are disabled unless record flags contain 0x100
        // or 0x200. The exact module then selects row+0 for this record.
        const uint64_t lod=(record[2]&0x300u)?1:0;
        if(uint64_t(record[1])+lod>=rows)return 0;
    }
    return rows*20;
}

// The audited grass module reads base row at byte4 of a 48-byte record and
// selects base or base+1. Its only writes to argument binding41 are atomic
// additions at (row*20+4). Bound every metadata row before preserving the
// other four argument words from their actual CPU-clean pre-dispatch values.
inline bool xbg_snk_grass_argument_rows(const uint32_t *records,
    size_t record_words,uint64_t bytes){
    if(!records || record_words<12 || record_words>262144 ||
       bytes<40 || bytes>65536 || (bytes&3))return false;
    const uint64_t rows=bytes/20;
    for(size_t offset=0;offset+12<=record_words;offset+=12)
        if(uint64_t(records[offset+1])+1>=rows)return false;
    return true;
}

// Binding17 in the audited module only stores byte60 of each 80-byte record.
// The row index at byte4 remains available in the CPU baseline while those
// writes are pending. Unknown writers require the normal synchronization.
template<class Pending>
bool xbg_snk_cull_indices_readable(const Pending &pending,uint64_t address,uint64_t bytes){
    if(!xbg_wb_range_valid(address,bytes))return false;
    for(const auto &write:pending)if(xbg_wb_overlaps(address,bytes,write.addr,write.bytes))
        if(!write.snk_cull_metadata || write.addr!=address ||
           !xbg_wb_contains(write.addr,write.bytes,address,bytes))return false;
    return true;
}

// The audited 42866 kernel copies each enabled particle record's index count
// (224-byte stride, byte 16) into argument word 0 and computes instance count
// in word 1. Argument words 2, 3 and 4 retain their actual pre-dispatch values.
inline bool xbg_snk_particle_templates(std::vector<XbgIndirectTemplateRow> &out,
    const std::vector<uint32_t> &arguments,const std::vector<uint32_t> &records,
    uint32_t active,uint32_t groups,uint64_t address,uint64_t bytes){
    out.clear();
    if(!active || active>bytes/20 || uint64_t(active)>uint64_t(groups)*1024 ||
       uint64_t(active)*56>records.size() || records.size()>262144)return false;
    std::vector<uint32_t> static_arguments=arguments;
    if(static_arguments.size()!=bytes/4)return false;
    for(uint32_t i=0;i<active;i++)if(records[size_t(i)*56]&1u)
        static_arguments[size_t(i)*5]=records[size_t(i)*56+4];
    return xbg_snk_instance_templates(out,static_arguments,address,bytes);
}
