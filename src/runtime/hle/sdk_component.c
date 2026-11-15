/* Execute the supplied SDK's allowlisted DSP routines natively, with the existing
 * Android x18/SCS boundary. No copied game bytes are stored in source. No
 * decoder, interpreter, JIT, SDK init, or generic export passthrough exists. */
#include "sdk_component.h"
#include "../nso/nso_loader.h"
#include "../nso/native_boundary.h"
#include "../../graphics/nvn_device/nvn_sha256.h"
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

static nso_module *sdk;
static int ready;
static pthread_mutex_t load_lock = PTHREAD_MUTEX_INITIALIZER;
typedef struct { size_t pending, charged; } image_owner;
static image_owner owner;
static struct nso_result result(enum nso_status status, int error) {
    return (struct nso_result){status, error, 0};
}
static struct nso_result reserve(void *context, size_t bytes, void **ticket) {
    image_owner *o = context;
    if (!bytes || bytes > 16u*1024u*1024u || o->pending || o->charged) return result(NSO_LIMIT, ENOMEM);
    o->pending = bytes; *ticket = o; return result(NSO_OK, 0);
}
static struct nso_result commit(void *context, void *ticket) {
    image_owner *o = context;
    if (ticket != o || !o->pending || o->charged) return result(NSO_OWNER_ERROR, EINVAL);
    o->charged = o->pending; o->pending = 0; return result(NSO_OK, 0);
}
static struct nso_result cancel(void *context, void *ticket) {
    image_owner *o = context;
    if (ticket != o || o->charged) return result(NSO_OWNER_ERROR, EINVAL);
    o->pending = 0; return result(NSO_OK, 0);
}
static struct nso_result release(void *context, void *ticket) {
    image_owner *o = context;
    if (ticket != o || !o->charged) return result(NSO_OWNER_ERROR, EINVAL);
    o->charged = 0; return result(NSO_OK, 0);
}
static const struct nso_owner_ops owner_ops = {reserve, commit, cancel, release};

/* Verified SDK images.
 *
 * Each entry pins the SHA-256 of the SDK NSO that was extracted and audited
 * for one title, plus the address and value of the data symbol that proves
 * the loaded image is exactly that audited input. A digest that is not in
 * this table is refused: an unaudited SDK never runs host code. */
struct sdk_verified_image {
    const char *title;
    unsigned char digest[32];
    uint64_t chunk_duration_address;
    int64_t chunk_duration_value;
};

static const struct sdk_verified_image verified_images[] = {
    { "final-fantasy-resonance",
      { 0x9d,0xfd,0x1c,0xc6,0xd3,0x20,0x9d,0x85,0x7d,0xca,0xfb,0x19,0x17,0x36,0x26,0x5a,
        0xc8,0x12,0x40,0x1d,0xdc,0xc7,0xb4,0x9d,0xab,0xf3,0xbc,0x0b,0x11,0x46,0x55,0xa9 },
      0x9a05a8, 5000000 },
    { "sora-no-kiseki-the-1st",
      { 0x32,0xa9,0x6a,0xdc,0x6f,0xf4,0x74,0xf9,0x9f,0x9f,0xa7,0x99,0x58,0x03,0x26,0x7c,
        0xf6,0xad,0x54,0x40,0xc2,0x95,0xf5,0x00,0x9f,0xb4,0x77,0xf8,0xb9,0xfe,0x82,0x7f },
      0x9b0be0, 5000000 },
    /* v1.0.7 update (title 01001E9023920800, 22.5.0, CN/KR): ExeFS sdk.nso,
     * 12,217,984 B, extracted to .local/snk_game_dir/sdk.nso and deployed as
     * /sdcard/SNK/sdk.nso. Audit: ChunkDuration at 0x9d32c8 holds 5000000. */
    { "sora-no-kiseki-the-1st-v1.0.7",
      { 0xf5,0x18,0xe8,0xad,0x45,0x97,0x1a,0xa4,0x68,0x99,0x69,0xc0,0xbe,0xdf,0xa0,0xb2,
        0x8a,0x95,0xe5,0x24,0x53,0x72,0xb6,0x03,0x21,0x4e,0xed,0x78,0xb4,0x01,0x0d,0xaf },
      0x9d32c8, 5000000 },
};

/* Address of the verified data symbol inside the loaded image. */
static uint64_t active_chunk_duration_address;
static int compressor_dsp_ready;

_Static_assert(sizeof(struct ffrs_sdk_compressor_parameter) == 0x38, "SDK compressor parameter size");
_Static_assert(offsetof(struct ffrs_sdk_compressor_parameter, threshold_db) == 0x14, "SDK compressor threshold offset");
_Static_assert(offsetof(struct ffrs_sdk_compressor_parameter, attack_coefficient) == 0x28, "SDK compressor attack offset");
_Static_assert(offsetof(struct ffrs_sdk_compressor_parameter, output_gain_db) == 0x30, "SDK compressor gain offset");
_Static_assert(sizeof(struct ffrs_sdk_compressor_state) == 0x40, "SDK compressor state size");

static int verify_compressor_dsp(const struct sdk_verified_image *image) {
    if (image->chunk_duration_address != 0x9d32c8) return 0;
    static const struct { const char *name; uint64_t offset; } functions[] = {
        {FFRS_SDK_COMPRESSOR_INITIALIZE, 0x251400},
        {FFRS_SDK_COMPRESSOR_CONFIGURE, 0x251550},
        {FFRS_SDK_COMPRESSOR_APPLY, 0x251690}
    };
    for (size_t i = 0; i < sizeof functions / sizeof functions[0]; ++i) {
        uint32_t symbol = nso_find_symbol(sdk, functions[i].name);
        if (!symbol || nso_symbol_value(sdk, symbol) != functions[i].offset) return 0;
    }
    return 1;
}

static const struct sdk_verified_image *match_verified_image(const unsigned char *digest) {
    for (size_t i = 0; i < sizeof(verified_images) / sizeof(verified_images[0]); i++)
        if (!memcmp(digest, verified_images[i].digest, sizeof(verified_images[i].digest)))
            return &verified_images[i];
    return NULL;
}

int ffrs_sdk_component_load(const char *path) {
    pthread_mutex_lock(&load_lock);
    if (sdk) { pthread_mutex_unlock(&load_lock); return ready ? 0 : -1; }
    FILE *file = path ? fopen(path, "rb") : NULL;
    if (!file) { pthread_mutex_unlock(&load_lock); return -1; }
    unsigned char buffer[65536], digest[32]; size_t bytes;
    nvn_sha256_context hash; nvn_sha256_init(&hash);
    while ((bytes = fread(buffer, 1, sizeof(buffer), file))) nvn_sha256_update(&hash, buffer, bytes);
    int failed = ferror(file); fclose(file); nvn_sha256_final(&hash, digest);
    const struct sdk_verified_image *image = failed ? NULL : match_verified_image(digest);
    if (!image) {
        fprintf(stderr, "[sdk-component] refused: SDK SHA256 differs from every verified input\n");
        pthread_mutex_unlock(&load_lock); return -1;
    }
    active_chunk_duration_address = image->chunk_duration_address;
    char error[256] = {0};
    /* No external import is resolved. Unexpected allocation, startup or
     * foreign module calls stay fatal sentinels, never host fallthrough. */
    struct nso_load_result loaded = nso_load_file_owned(path, NULL, &owner_ops, &owner, error, sizeof(error));
    sdk = loaded.module; /* Retain the owner even if loader cleanup failed. */
    if (loaded.result.status != NSO_OK) {
        fprintf(stderr, "[sdk-component] load failed status=%d error=%s\n", loaded.result.status, error);
        pthread_mutex_unlock(&load_lock); return -1;
    }
    uint32_t symbol = nso_find_symbol(sdk, "_ZN2nn3hid18VibrationConverter13ChunkDurationE");
    if (!symbol || nso_symbol_value(sdk, symbol) != image->chunk_duration_address ||
        *(const int64_t *)(uintptr_t)nso_addr(sdk, image->chunk_duration_address) != image->chunk_duration_value) {
        fprintf(stderr, "[sdk-component] verified data symbol does not match loaded SDK\n");
        pthread_mutex_unlock(&load_lock); return -1;
    }
    fprintf(stderr, "[sdk-component] verified native DSP image title=%s base=%p image_bytes=%zu unresolved=%u; no SDK init\n",
            image->title, (void *)(uintptr_t)nso_base(sdk), owner.charged, nso_unresolved_count(sdk));
    compressor_dsp_ready = verify_compressor_dsp(image);
    __atomic_store_n(&ready, 1, __ATOMIC_RELEASE);
    pthread_mutex_unlock(&load_lock); return 0;
}

static void invoke(uint64_t offset, nb_registers *packet) {
    uint64_t address = 0;
    nb_scope scope = {0};
    if (!sdk || nso_entry_address(sdk, offset, &address).status != NSO_OK ||
        nb_scope_init(&scope) != NB_OK) abort();
    nb_status status = nb_call(&scope, (void (*)(void))(uintptr_t)address, packet);
    if (status != NB_OK) {
        fprintf(stderr, "[sdk-component] native boundary failed offset=%#llx status=%d\n", (unsigned long long)offset, status);
        abort();
    }
    if (nb_scope_close(&scope) != NB_OK) abort();
}
static void converter_ctor(void *self, int rate) {
    nb_registers packet = {.x={(uintptr_t)self, (uint32_t)rate}};
    invoke(0x517e00, &packet);
    fprintf(stderr, "[sdk-component] original VibrationConverter constructed rate=%d\n", rate);
}
static void converter_process(void *self, void *out, const int16_t *pcm, int count) {
    nb_registers packet = {.x={(uintptr_t)self, (uintptr_t)out, (uintptr_t)pcm, (uint32_t)count}};
    invoke(0x518030, &packet);
}
static void converter_dtor(void *self) {
    nb_registers packet = {.x={(uintptr_t)self}};
    invoke(0x518008, &packet);
}
/* Same verified SDK: these four DSP-only functions use caller-owned state
 * and work memory. Their internal memset/FIR calls stay within this image. */
static uint64_t resampler_size(int channels) {
    nb_registers p={.x={(uint32_t)channels}}; invoke(0x2634e0,&p); return p.x[0];
}
static int resampler_count(const void *state,int frames) {
    nb_registers p={.x={(uintptr_t)state,(uint32_t)frames}};invoke(0x2634f0,&p);return (int)p.x[0];
}
static uint32_t resampler_init(void *state,void *work,uint64_t bytes,int input_rate,int output_rate,int channels) {
    nb_registers p={.x={(uintptr_t)state,(uintptr_t)work,bytes,(uint32_t)input_rate,(uint32_t)output_rate,(uint32_t)channels}};
    invoke(0x263530,&p);return (uint32_t)p.x[0];
}
static uint32_t resampler_process(void *state,int *count,int16_t *output,uint64_t capacity,const int16_t *input,int frames) {
    nb_registers p={.x={(uintptr_t)state,(uintptr_t)count,(uintptr_t)output,capacity,(uintptr_t)input,(uint32_t)frames}};
    invoke(0x263690,&p);return (uint32_t)p.x[0];
}

/* Audited v1.0.7 DSP functions. Configure/initialize are leaf routines. Apply's
 * sole call is the SDK's own memcpy on its disabled-copy path. None enters
 * the renderer service, TLS helpers, allocator or SDK startup. */
static void compressor_initialize(const struct ffrs_sdk_compressor_parameter *parameter,
                                   struct ffrs_sdk_compressor_state *state) {
    nb_registers packet = {.x = {(uintptr_t)parameter, (uintptr_t)state}};
    invoke(0x251400, &packet);
}

static void compressor_configure(const struct ffrs_sdk_compressor_parameter *parameter,
                                 struct ffrs_sdk_compressor_state *state) {
    nb_registers packet = {.x = {(uintptr_t)parameter, (uintptr_t)state}};
    invoke(0x251550, &packet);
}

static void compressor_apply(const struct ffrs_sdk_compressor_parameter *parameter,
        struct ffrs_sdk_compressor_state *state, bool enabled,
        const int32_t *const *inputs, int32_t *const *outputs, int frames, void *statistics) {
    nb_registers packet = {.x = {(uintptr_t)parameter, (uintptr_t)state, (uint32_t)enabled,
        (uintptr_t)inputs, (uintptr_t)outputs, (uint32_t)frames, (uintptr_t)statistics}};
    invoke(0x251690, &packet);
}
uint64_t ffrs_sdk_component_lookup(const char *name, unsigned *arguments, unsigned *returns) {
    if (!__atomic_load_n(&ready, __ATOMIC_ACQUIRE) || !name) return 0;
    uint64_t address = 0; unsigned args = 0,rets=0;
    if (!strcmp(name, "_ZN2nn3hid18VibrationConverter13ChunkDurationE")) address = nso_addr(sdk, active_chunk_duration_address);
    else if (!strcmp(name, "_ZN2nn3hid18VibrationConverterC1Ei")) { address=(uintptr_t)converter_ctor; args=2; }
    else if (!strcmp(name, "_ZN2nn3hid18VibrationConverterD1Ev")) { address=(uintptr_t)converter_dtor; args=1; }
    else if (!strcmp(name, "_ZN2nn3hid18VibrationConverter12ProcessChunkEPNS0_14VibrationValueEPKsi")) {
        address=(uintptr_t)converter_process; args=4;
    }
    else if(!strcmp(name,"_ZN2nn5audio33GetRequiredBufferSizeForResamplerEi")){address=(uintptr_t)resampler_size;args=1;rets=1;}
    else if(!strcmp(name,"_ZN2nn5audio29GetResamplerOutputSampleCountEPKNS0_13ResamplerTypeEi")){address=(uintptr_t)resampler_count;args=2;rets=1;}
    else if(!strcmp(name,"_ZN2nn5audio19InitializeResamplerEPNS0_13ResamplerTypeEPvmiii")){address=(uintptr_t)resampler_init;args=6;rets=1;}
    else if(!strcmp(name,"_ZN2nn5audio22ProcessResamplerBufferEPNS0_13ResamplerTypeEPiPsmPKsi")){address=(uintptr_t)resampler_process;args=6;rets=1;}
    else if (compressor_dsp_ready && !strcmp(name, FFRS_SDK_COMPRESSOR_INITIALIZE)) {
        address = (uintptr_t)compressor_initialize; args = 2;
    }
    else if (compressor_dsp_ready && !strcmp(name, FFRS_SDK_COMPRESSOR_CONFIGURE)) {
        address = (uintptr_t)compressor_configure; args = 2;
    }
    else if (compressor_dsp_ready && !strcmp(name, FFRS_SDK_COMPRESSOR_APPLY)) {
        address = (uintptr_t)compressor_apply; args = 7;
    }
    else if(!strncmp(name,"_ZN2nn5audio",12)){
        /* 通用兜底：把 sdk.nso 自己导出的 nn::audio 符号解析到真实实现。
         *
         * 实测结果（2026-11-13）：打开后 260 个符号全部命中，AcquireSubMix
         * 失败次数从 31 降到 0，AudioRenderer 的配置终于能搭起来。但游戏随后
         * 新建的音频线程会在 sdk.nso 内访问空指针 +0x1f8 崩溃——说明配置层通了、
         * 底层的音频系统线程还缺配套实现（输出桥 AudioOut 仍走 HLE，不匹配）。
         *
         * 因此默认关闭：只有显式设置 FFRS_AUDIO_NATIVE_ALL=1 才启用，避免为了
         * 一个尚未打通的子系统把可玩的游戏弄崩。关掉时返回值与改动前完全一致。 */
        static int native_all = -1;
        if (native_all < 0) {
            const char *v = getenv("FFRS_AUDIO_NATIVE_ALL");
            native_all = v && v[0] == '1';
        }
        if (native_all) {
            uint32_t sym = nso_find_symbol(sdk, name);
            uint64_t value = sym ? nso_symbol_value(sdk, sym) : 0;
            if (value) address = nso_addr(sdk, value);
            if (arguments) fprintf(stderr, "[sdk-component] audio %s -> %s%#llx\n",
                                   name, address ? "sdk.nso " : "not-exported ", (unsigned long long)value);
        }
    }
    if (address) { if (arguments) *arguments=args; if (returns) *returns=rets; }
    return address;
}
