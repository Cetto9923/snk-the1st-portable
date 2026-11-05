/* Host implementations for the nn::audio, nn::codec, nn::image and movie
 * imports of Sora no Kiseki the 1st that the nnSdk module would answer.
 *
 * The register contract is taken from the nnSdk exports themselves: the
 * import gateway is a pass-through thunk, so the host function sees the
 * guest registers live and must leave a defined value in x0.
 *
 * The layouts and the arithmetic below are copied from the disassembly of
 * the nnSdk module (see .local/nca/nso/sdk.bin), not guessed:
 *   nn::audio::InitializeAudioRendererParameter  module offset 0x20e260
 *   nn::audio::IsValidAudioRendererParameter      module offset 0x20e160
 *   nn::audio::GetRequiredBufferSizeForPerformanceFrames  0x214cd0
 *   nn::audio::PerformanceInfo::SetBuffer          module offset 0x214e48
 *   nn::audio::PerformanceInfo::MoveToNextFrame     module offset 0x214f2c
 *   nn::audio::PerformanceInfo::GetTotalProcessingTime   0x214ec8
 *   nn::image::PngDecoder::GetDimension             module offset 0x739bc
 */
#include "snk_hle_media.h"

#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ====================================================================== */
/* nn::audio                                                               */
/* ====================================================================== */

/* The nnSdk AudioRendererParameter is 0x38 bytes. The field names stay
 * offset based because the SDK only proves what each slot holds. */
struct snk_audio_parameter {
    uint32_t slot_00;          /* sample rate: 48000 or 32000 */
    uint32_t slot_04;          /* voice count: 240 or 160 */
    uint32_t slot_08;
    uint32_t slot_0c;
    uint32_t slot_10;
    uint32_t slot_14;
    uint32_t slot_18;
    uint32_t slot_1c;
    uint8_t  slot_20;
    uint8_t  pad_21[3];
    uint32_t slot_24;
    uint32_t slot_28;
    uint32_t slot_2c;
    uint32_t slot_30;
    uint32_t slot_34;          /* device id */
};

#define SNK_AUDIO_DEVICE_ID 0u
#define SNK_AUDIO_SAMPLE_RATE 48000u
#define SNK_AUDIO_VOICE_COUNT 240u

/* The renderer object the guest handle points at. nn::audio::GetAudioRendererState
 * reads the state from handle + 0x14, so the state lives there. */
struct snk_audio_renderer {
    uint64_t magic;
    uint64_t reserved_08;
    uint32_t reserved_10;
    uint32_t state;            /* 0x14: 0 stopped, 1 started */
    uint32_t closed;
    uint32_t reserved_1c;
};

#define SNK_AUDIO_RENDERER_MAGIC 0x534e4b4155444f58ull
#define SNK_AUDIO_RENDERER_COUNT 8

static pthread_mutex_t s_audio_lock = PTHREAD_MUTEX_INITIALIZER;
static struct snk_audio_renderer s_audio_renderers[SNK_AUDIO_RENDERER_COUNT];

uint64_t snk_audio_initialize_renderer_parameter(void *parameter) {
    if (!parameter) return 0;
    struct snk_audio_parameter *p = (struct snk_audio_parameter *)parameter;
    memset(p, 0, sizeof(*p));
    p->slot_00 = SNK_AUDIO_SAMPLE_RATE;
    p->slot_04 = SNK_AUDIO_VOICE_COUNT;
    p->slot_08 = 1;
    p->slot_10 = 1;
    p->slot_14 = 1;
    p->slot_34 = SNK_AUDIO_DEVICE_ID;
    return 0;
}

uint64_t snk_audio_is_valid_renderer_parameter(const void *parameter) {
    const struct snk_audio_parameter *p = (const struct snk_audio_parameter *)parameter;
    if (!p) return 0;
    uint32_t low = p->slot_2c;
    uint32_t high = p->slot_30;
    if (!(low == 1u || (low == 0u && high == 0u))) return 0;
    if (p->slot_34 != SNK_AUDIO_DEVICE_ID) return 0;
    if (p->slot_00 != 48000u && p->slot_00 != 32000u) return 0;
    if (p->slot_04 != 240u && p->slot_04 != 160u) return 0;
    uint32_t expected = (uint32_t)((((p->slot_00 >> 3) * 0x147bu) >> 17) & 0xffffffffu);
    if (p->slot_04 != expected) return 0;
    if (p->slot_08 < 1u) return 0;
    if (p->slot_10 < 1u) return 0;
    if (p->slot_14 < 1u) return 0;
    if (p->slot_18 & 0x80000000u) return 0;
    return 1;
}

uint64_t snk_audio_renderer_work_buffer_size(const void *parameter) {
    (void)parameter;
    return 0x10000u;
}

uint64_t snk_audio_renderer_config_work_buffer_size(const void *parameter) {
    (void)parameter;
    return 0x1000u;
}

uint64_t snk_audio_performance_frames_buffer_size(const void *parameter) {
    const struct snk_audio_parameter *p = (const struct snk_audio_parameter *)parameter;
    if (!p) return 0;
    uint64_t frames = (uint64_t)p->slot_0c + (uint64_t)p->slot_10 +
                      (uint64_t)p->slot_14 + (uint64_t)p->slot_18 + 1u;
    uint64_t size = frames * 0x18u + 0x990u;
    size *= (uint64_t)p->slot_1c;
    if (size != 0) size += 0x30u;
    size = (size + 0x3fu) & ~(uint64_t)0x3fu;
    return size;
}

uint64_t snk_audio_open_renderer(void **handle_out, void *system_event,
                                        const void *parameter, void *work_buffer,
                                        size_t work_size) {
    (void)system_event;
    (void)parameter;
    (void)work_buffer;
    (void)work_size;
    if (!handle_out) return 0;
    struct snk_audio_renderer *renderer = NULL;
    pthread_mutex_lock(&s_audio_lock);
    for (size_t i = 0; i < SNK_AUDIO_RENDERER_COUNT; i++) {
        if (s_audio_renderers[i].magic != SNK_AUDIO_RENDERER_MAGIC) {
            memset(&s_audio_renderers[i], 0, sizeof(s_audio_renderers[i]));
            s_audio_renderers[i].magic = SNK_AUDIO_RENDERER_MAGIC;
            renderer = &s_audio_renderers[i];
            break;
        }
    }
    pthread_mutex_unlock(&s_audio_lock);
    if (!renderer) {
        fprintf(stderr, "[snk-media] OpenAudioRenderer: no free renderer slot\n");
        return 0;
    }
    /* The guest handle is two pointers; both point at the renderer object so
     * that the state stays at renderer + 0x14 where nnSdk keeps it. */
    handle_out[0] = renderer;
    handle_out[1] = renderer;
    fprintf(stderr, "[snk-media] OpenAudioRenderer: renderer=%p\n", (void *)renderer);
    return 0;
}

uint64_t snk_audio_start_renderer(void *renderer, void *state_object) {
    (void)renderer;
    struct snk_audio_renderer *renderer_state = (struct snk_audio_renderer *)state_object;
    if (!renderer_state) return 0;
    pthread_mutex_lock(&s_audio_lock);
    renderer_state->state = 1u;
    pthread_mutex_unlock(&s_audio_lock);
    return 0;
}

uint64_t snk_audio_renderer_state(void *renderer, void *state_object) {
    (void)renderer;
    struct snk_audio_renderer *renderer_state = (struct snk_audio_renderer *)state_object;
    if (!renderer_state) return 0;
    pthread_mutex_lock(&s_audio_lock);
    uint32_t state = renderer_state->state;
    pthread_mutex_unlock(&s_audio_lock);
    return state;
}

uint64_t snk_audio_stop_renderer(void *renderer, void *state_object) {
    (void)renderer;
    struct snk_audio_renderer *renderer_state = (struct snk_audio_renderer *)state_object;
    if (!renderer_state) return 0;
    pthread_mutex_lock(&s_audio_lock);
    renderer_state->state = 0u;
    pthread_mutex_unlock(&s_audio_lock);
    return 0;
}

uint64_t snk_audio_close_renderer(void *renderer, void *state_object) {
    (void)renderer;
    struct snk_audio_renderer *renderer_state = (struct snk_audio_renderer *)state_object;
    if (!renderer_state) return 0;
    pthread_mutex_lock(&s_audio_lock);
    renderer_state->state = 0u;
    renderer_state->closed = 1u;
    pthread_mutex_unlock(&s_audio_lock);
    return 0;
}


/* nn::audio::AcquireVoiceSlot
 *
 * The nnSdk export allocates a VoiceType object, writes the pointer into the
 * second argument and answers with a bool (module offset 0x2161b4:
 * "cmp x21,#0; cset w0,ne"). The ninth argument, the
 * VoiceType::BehaviorOptions pointer, arrives on the guest stack at SP+0
 * (module offset 0x216024: "ldr x26,[x29,#0x60]"), so the host entry
 * declares all nine arguments and the import gateway rebuilds that slot. */
struct snk_audio_voice {
    uint64_t magic;
    uint32_t state;            /* 0 free, 1 acquired */
    uint32_t channel;
    uint32_t sample_format;
    uint32_t reserved;
    uint64_t wave_buffer;
    uint64_t wave_buffer_size;
};

#define SNK_AUDIO_VOICE_MAGIC 0x534e4b4155564f58ull
#define SNK_AUDIO_VOICE_SLOT_COUNT 64

static struct snk_audio_voice s_audio_voices[SNK_AUDIO_VOICE_SLOT_COUNT];

uint64_t snk_audio_acquire_voice_slot(void *config, void *voice_out,
                                       int channel, int mixer_index,
                                       int sample_format, int sample_count,
                                       const void *wave_buffer,
                                       size_t wave_buffer_size,
                                       void *behavior_options) {
    (void)config;
    (void)mixer_index;
    (void)sample_count;
    (void)behavior_options;
    struct snk_audio_voice *voice = NULL;
    pthread_mutex_lock(&s_audio_lock);
    for (size_t i = 0; i < SNK_AUDIO_VOICE_SLOT_COUNT; i++) {
        if (s_audio_voices[i].magic != SNK_AUDIO_VOICE_MAGIC) {
            memset(&s_audio_voices[i], 0, sizeof(s_audio_voices[i]));
            s_audio_voices[i].magic = SNK_AUDIO_VOICE_MAGIC;
            s_audio_voices[i].state = 1u;
            s_audio_voices[i].channel = (uint32_t)channel;
            s_audio_voices[i].sample_format = (uint32_t)sample_format;
            s_audio_voices[i].wave_buffer = (uint64_t)(uintptr_t)wave_buffer;
            s_audio_voices[i].wave_buffer_size = (uint64_t)wave_buffer_size;
            voice = &s_audio_voices[i];
            break;
        }
    }
    pthread_mutex_unlock(&s_audio_lock);
    if (!voice) {
        fprintf(stderr, "[snk-media] AcquireVoiceSlot: no free voice slot\n");
        return 0;
    }
    if (voice_out) *(void **)voice_out = voice;
    return 1;
}

uint64_t snk_audio_request_update_renderer(void *renderer, void *state_object,
                                                   const void *config) {
    (void)renderer;
    (void)state_object;
    (void)config;
    return 0;
}

/* nn::audio::PerformanceInfo is 0x28 bytes of guest memory. */
#define SNK_AUDIO_PERFORMANCE_INFO_SIZE 0x28
#define SNK_AUDIO_PERFORMANCE_MAGIC 0x46524550u

uint64_t snk_audio_performance_info_ctor(void *self) {
    if (self) memset(self, 0, SNK_AUDIO_PERFORMANCE_INFO_SIZE);
    return 0;
}

uint64_t snk_audio_performance_info_dtor(void *self) {
    (void)self;
    return 0;
}

uint64_t snk_audio_performance_info_set_buffer(void *self, const void *data,
                                                      size_t size) {
    if (!self) return 0;
    unsigned char *bytes = (unsigned char *)self;
    *(const void **)(bytes + 0x00) = data;
    *(uint64_t *)(bytes + 0x08) = (uint64_t)size;
    *(const void **)(bytes + 0x10) = data;
    if (!data) return 0;
    uint32_t magic = *(const uint32_t *)data;
    if (magic != SNK_AUDIO_PERFORMANCE_MAGIC) return 0;
    uint32_t count = *(const uint32_t *)((const unsigned char *)data + 4);
    uint32_t flag = *(const uint32_t *)((const unsigned char *)data + 8);
    const unsigned char *frames = (const unsigned char *)data + 0x30;
    *(const void **)(bytes + 0x18) = count ? (const void *)frames : NULL;
    const unsigned char *table = frames + (size_t)(int64_t)count * 0x18u;
    *(const void **)(bytes + 0x20) = flag ? (const void *)table : NULL;
    return 1;
}

uint64_t snk_audio_performance_info_next_frame(void *self) {
    if (!self) return 0;
    unsigned char *bytes = (unsigned char *)self;
    const unsigned char *frame = *(const unsigned char *const *)(bytes + 0x10);
    if (!frame) return 0;
    uint32_t size = *(const uint32_t *)(frame + 0x0c);
    if (size < 1u) return 0;
    frame += size;
    *(const unsigned char **)(bytes + 0x00) = frame;
    *(const unsigned char **)(bytes + 0x10) = frame;
    uint32_t magic = *(const uint32_t *)frame;
    if (magic != SNK_AUDIO_PERFORMANCE_MAGIC) return 0;
    uint32_t count = *(const uint32_t *)(frame + 4);
    uint32_t flag = *(const uint32_t *)(frame + 8);
    const unsigned char *frames = frame + 0x30;
    *(const void **)(bytes + 0x18) = count ? (const void *)frames : NULL;
    const unsigned char *table = frames + (size_t)(int64_t)count * 0x18u;
    *(const void **)(bytes + 0x20) = flag ? (const void *)table : NULL;
    return 1;
}

uint64_t snk_audio_performance_info_total_time(const void *self) {
    if (!self) return 0;
    const unsigned char *bytes = (const unsigned char *)self;
    const unsigned char *frame = *(const unsigned char *const *)(bytes + 0x10);
    if (!frame) return 0;
    return *(const uint32_t *)(frame + 0x10);
}

/* ====================================================================== */
/* nn::codec (Opus)                                                       */
/* ====================================================================== */

struct snk_opus_state {
    void *owner;
    int sample_rate;
    int channels;
};

static pthread_mutex_t s_opus_lock = PTHREAD_MUTEX_INITIALIZER;
static struct snk_opus_state s_opus_states[8];

static struct snk_opus_state *snk_opus_find(void *owner, bool create) {
    if (!owner) return NULL;
    pthread_mutex_lock(&s_opus_lock);
    struct snk_opus_state *found = NULL;
    for (size_t i = 0; i < sizeof(s_opus_states) / sizeof(s_opus_states[0]); i++) {
        if (s_opus_states[i].owner == owner) {
            found = &s_opus_states[i];
            break;
        }
    }
    if (!found && create) {
        for (size_t i = 0; i < sizeof(s_opus_states) / sizeof(s_opus_states[0]); i++) {
            if (!s_opus_states[i].owner) {
                memset(&s_opus_states[i], 0, sizeof(s_opus_states[i]));
                s_opus_states[i].owner = owner;
                found = &s_opus_states[i];
                break;
            }
        }
    }
    pthread_mutex_unlock(&s_opus_lock);
    return found;
}

uint64_t snk_opus_work_buffer_size(int channels, int sample_rate, int extra) {
    (void)channels;
    (void)sample_rate;
    (void)extra;
    return 0x10000u;
}

uint64_t snk_opus_initialize(void *owner, int sample_rate, int channels,
                                    void *work_buffer, size_t work_size, int extra) {
    (void)work_buffer;
    (void)work_size;
    (void)extra;
    struct snk_opus_state *state = snk_opus_find(owner, true);
    if (!state) return 0;
    pthread_mutex_lock(&s_opus_lock);
    state->sample_rate = sample_rate > 0 ? sample_rate : 48000;
    state->channels = channels > 0 ? channels : 2;
    pthread_mutex_unlock(&s_opus_lock);
    fprintf(stderr, "[snk-media] InitializeOpusDecoder: rate=%d channels=%d\n",
            state->sample_rate, state->channels);
    return 0;
}

uint64_t snk_opus_finalize(void *owner) {
    pthread_mutex_lock(&s_opus_lock);
    for (size_t i = 0; i < sizeof(s_opus_states) / sizeof(s_opus_states[0]); i++) {
        if (s_opus_states[i].owner == owner) {
            memset(&s_opus_states[i], 0, sizeof(s_opus_states[i]));
            break;
        }
    }
    pthread_mutex_unlock(&s_opus_lock);
    return 0;
}

uint64_t snk_opus_sample_rate(const void *owner) {
    struct snk_opus_state *state = snk_opus_find((void *)owner, false);
    if (!state) return 48000u;
    pthread_mutex_lock(&s_opus_lock);
    int sample_rate = state->sample_rate;
    pthread_mutex_unlock(&s_opus_lock);
    return (uint64_t)(uint32_t)sample_rate;
}

uint64_t snk_opus_channel_count(const void *owner) {
    struct snk_opus_state *state = snk_opus_find((void *)owner, false);
    if (!state) return 2u;
    pthread_mutex_lock(&s_opus_lock);
    int channels = state->channels;
    pthread_mutex_unlock(&s_opus_lock);
    return (uint64_t)(uint32_t)channels;
}

uint64_t snk_opus_reset(void *owner) {
    (void)owner;
    return 0;
}

uint64_t snk_opus_decode(void *owner, size_t *consumed, int *frames, short *output,
                                 size_t output_samples, const void *input, size_t input_size) {
    (void)owner;
    (void)output;
    (void)output_samples;
    if (consumed) *consumed = input ? input_size : 0u;
    if (frames) *frames = 0;
    return 0;
}

/* ====================================================================== */
/* nn::image (PNG)                                                         */
/* ====================================================================== */

struct snk_png_state {
    void *owner;
    const void *data;
    size_t size;
    uint32_t width;
    uint32_t height;
    int analyzed;
};

static pthread_mutex_t s_png_lock = PTHREAD_MUTEX_INITIALIZER;
static struct snk_png_state s_png_states[8];

static struct snk_png_state *snk_png_find(void *owner, bool create) {
    if (!owner) return NULL;
    pthread_mutex_lock(&s_png_lock);
    struct snk_png_state *found = NULL;
    for (size_t i = 0; i < sizeof(s_png_states) / sizeof(s_png_states[0]); i++) {
        if (s_png_states[i].owner == owner) {
            found = &s_png_states[i];
            break;
        }
    }
    if (!found && create) {
        for (size_t i = 0; i < sizeof(s_png_states) / sizeof(s_png_states[0]); i++) {
            if (!s_png_states[i].owner) {
                memset(&s_png_states[i], 0, sizeof(s_png_states[i]));
                s_png_states[i].owner = owner;
                found = &s_png_states[i];
                break;
            }
        }
    }
    pthread_mutex_unlock(&s_png_lock);
    return found;
}

uint64_t snk_png_decoder_ctor(void *self) {
    snk_png_find(self, true);
    return 0;
}

uint64_t snk_png_decoder_dtor(void *self) {
    snk_png_find(self, false);
    return 0;
}

uint64_t snk_png_decoder_initialize(void *self, void *allocator, void *allocator_context,
                                           void *deallocator, void *deallocator_context) {
    (void)allocator;
    (void)allocator_context;
    (void)deallocator;
    (void)deallocator_context;
    snk_png_find(self, true);
    return 0;
}

uint64_t snk_png_decoder_set_image_data(void *self, const void *data, size_t size) {
    struct snk_png_state *state = snk_png_find(self, true);
    if (!state) return 0;
    pthread_mutex_lock(&s_png_lock);
    state->data = data;
    state->size = size;
    state->analyzed = 0;
    pthread_mutex_unlock(&s_png_lock);
    return 0;
}

uint64_t snk_png_decoder_set_pixel_format(void *self, int format) {
    (void)format;
    snk_png_find(self, true);
    return 0;
}

uint64_t snk_png_decoder_analyze(void *self) {
    struct snk_png_state *state = snk_png_find(self, true);
    if (!state || !state->data || state->size < 24u) return 0;
    static const unsigned char signature[8] = {0x89, 'P', 'N', 'G', 0x0d, 0x0a, 0x1a, 0x0a};
    const unsigned char *data = (const unsigned char *)state->data;
    if (memcmp(data, signature, sizeof(signature))) return 0;
    if (memcmp(data + 12, "IHDR", 4)) return 0;
    uint32_t width = 0, height = 0;
    memcpy(&width, data + 16, 4);
    memcpy(&height, data + 20, 4);
    pthread_mutex_lock(&s_png_lock);
    state->width = width;
    state->height = height;
    state->analyzed = 1;
    pthread_mutex_unlock(&s_png_lock);
    fprintf(stderr, "[snk-media] PngDecoder::Analyze: %ux%u\n", width, height);
    return 1;
}

uint64_t snk_png_decoder_decode(void *self, void *output, size_t stride, size_t size) {
    (void)output;
    (void)stride;
    (void)size;
    (void)self;
    /* A full PNG decoder is not in place yet: the title treats a failed
     * decode as a missing texture instead of crashing. */
    return 0;
}

uint64_t snk_png_decoder_dimension(const void *self) {
    struct snk_png_state *state = snk_png_find((void *)self, false);
    if (!state) return 0;
    pthread_mutex_lock(&s_png_lock);
    uint64_t dimension = ((uint64_t)state->height << 32) | (uint64_t)state->width;
    pthread_mutex_unlock(&s_png_lock);
    return dimension;
}

uint64_t snk_png_decoder_row_stride(const void *self) {
    struct snk_png_state *state = snk_png_find((void *)self, false);
    if (!state) return 0;
    pthread_mutex_lock(&s_png_lock);
    uint64_t stride = (uint64_t)state->width * 4u;
    pthread_mutex_unlock(&s_png_lock);
    return stride;
}

uint64_t snk_png_encoder_ctor(void *self) {
    (void)self;
    return 0;
}

uint64_t snk_png_encoder_dtor(void *self) {
    (void)self;
    return 0;
}

uint64_t snk_png_encoder_initialize(void *self, void *allocator, void *allocator_context,
                                           void *deallocator, void *deallocator_context) {
    (void)self;
    (void)allocator;
    (void)allocator_context;
    (void)deallocator;
    (void)deallocator_context;
    return 0;
}

uint64_t snk_png_encoder_set_pixel_data(void *self, const void *data, size_t size,
                                                int format, uint64_t dimension, size_t stride) {
    (void)self;
    (void)data;
    (void)size;
    (void)format;
    (void)dimension;
    (void)stride;
    return 0;
}

uint64_t snk_png_encoder_encode(void *self, size_t *size_out, void *output,
                                       size_t capacity) {
    (void)self;
    (void)output;
    (void)capacity;
    if (size_out) *size_out = 0u;
    return 0;
}

uint64_t snk_png_encoder_size_max(const void *self) {
    (void)self;
    return 0x10000u;
}

/* ====================================================================== */
/* movie                                                                   */
/* ====================================================================== */

uint64_t snk_movie_media_data_ctor(void *self) {
    (void)self;
    return 0;
}

uint64_t snk_movie_media_data_dtor(void *self) {
    (void)self;
    return 0;
}

uint64_t snk_movie_media_data_clear(void *self) {
    (void)self;
    return 0;
}

uint64_t snk_movie_media_data_find_string(const void *self, const char *key,
                                                  const char **value) {
    (void)self;
    (void)key;
    if (value) *value = NULL;
    return 0;
}

uint64_t snk_movie_media_data_find_int32(const void *self, const char *key, int *value) {
    (void)self;
    (void)key;
    if (value) *value = 0;
    return 0;
}

uint64_t snk_movie_media_data_find_int64(const void *self, const char *key, long *value) {
    (void)self;
    (void)key;
    if (value) *value = 0;
    return 0;
}

uint64_t snk_movie_status_to_string(int status) {
    (void)status;
    static const char *const unknown = "Unknown";
    return (uint64_t)(uintptr_t)unknown;
}

uint64_t snk_movie_extractor_ctor(void *self, int container, int cache) {
    (void)self;
    (void)container;
    (void)cache;
    return 0;
}

uint64_t snk_movie_decoder_ctor(void *self, int type, int format, int mode, int argument) {
    (void)self;
    (void)type;
    (void)format;
    (void)mode;
    (void)argument;
    return 0;
}

/* ====================================================================== */
/* libc                                                                    */
/* ====================================================================== */

struct snk_div_result snk_libc_div(int numerator, int denominator) {
    struct snk_div_result result;
    result.quotient = numerator / denominator;
    result.remainder = numerator % denominator;
    return result;
}

float snk_libc_strtof(const char *text, char **end) {
    return strtof(text, end);
}

/* ====================================================================== */
/* The lookup                                                              */
/* ====================================================================== */

uint64_t snk_hle_media_lookup(const char *name, unsigned *gp_arguments,
                               unsigned *fp_arguments, unsigned *gp_returns,
                               unsigned *fp_returns, unsigned *stack_bytes) {
    if (!name) return 0;
    for (size_t i = 0; i < snk_media_entry_count; i++) {
        if (strcmp(name, snk_media_entries[i].name)) continue;
        if (gp_arguments) *gp_arguments = snk_media_entries[i].gp_arguments;
        if (fp_arguments) *fp_arguments = snk_media_entries[i].fp_arguments;
        if (gp_returns) *gp_returns = snk_media_entries[i].gp_returns;
        if (fp_returns) *fp_returns = snk_media_entries[i].fp_returns;
        if (stack_bytes) *stack_bytes = snk_media_entries[i].stack_bytes;
        return snk_media_entries[i].function;
    }
    return 0;
}
