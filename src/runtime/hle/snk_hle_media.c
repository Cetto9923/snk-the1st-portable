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

#define STBI_ONLY_PNG
#define STB_IMAGE_IMPLEMENTATION
#define STBI_NO_STDIO
#define STBI_NO_SIMD
#include "../../../third_party/stb/stb_image.h"

/* A real Opus packet decoder: the title parses .nxopus itself and hands
 * nn::codec one packet at a time. */
#include "../../../third_party/opus/include/opus.h"

/* libopus exposes the self-delimited framing only internally; this wrapper,
 * added next to it, selects that framing without duplicating decode logic. */
extern int opus_decode_self_delimited(OpusDecoder *st, const unsigned char *data,
                                      int len, short *pcm, int frame_size,
                                      int *packet_offset);

/* Packet framing parser; declared non-static in libopus and used here to learn
 * a packet's length even when the caller's buffer is too small to decode it. */
extern int opus_packet_parse_impl(const unsigned char *data, int len, int self_delimited,
                                  unsigned char *out_toc, const unsigned char *frames[48],
                                  short size[48], int *payload_offset, int *packet_offset,
                                  const unsigned char **padding, int *padding_len);

#include "sdk_component.h"
#include "audio_bridge.h"

/* Defined below with the rest of the audren mixer; the renderer's update entry
 * needs it before its own definition. */
void snk_audio_mixer_update(void);

#include <pthread.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

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
/* One monotonic counter across the whole voice handshake: the console's audio
 * API is a queue protocol, and reading each call site in isolation is what let
 * an earlier round mistake a handle mismatch for silence. */
static unsigned s_mix_mixed_peak;   /* peak of the PCM actually mixed since the last report */

/* ---------------------------------------------------------------- decode tap
 * Measured behaviour of this title: the BGM thread decodes exactly one voice
 * buffer's worth of PCM (480 + 960 frames = 1440 frames = 5760 bytes, matching
 * the wave buffer it appends next), then appends a buffer that is still all
 * zero and immediately flushes it. Nothing ever writes the decoded PCM into the
 * buffer the voice was given, so the voice has nothing to play, the streaming
 * loop never sees played-sample progress, and decoding stops after two packets.
 *
 * The decoded PCM itself is sound (peak 5855 on the second packet), so it is
 * captured here and poured into the voice's own buffer when the title hands one
 * over empty. The voice, its volume, its loop flag and its release handshake
 * stay the title's; only the bytes it failed to place are supplied. */
#define SNK_OPUS_RING_FRAMES 49152u
static int16_t s_opus_ring[SNK_OPUS_RING_FRAMES * 2];
static uint64_t s_opus_ring_written, s_opus_ring_read;
static pthread_mutex_t s_opus_ring_lock = PTHREAD_MUTEX_INITIALIZER;

static void snk_opus_ring_push(const int16_t *pcm, unsigned frames, unsigned channels) {
    if (!pcm || !frames) return;
    pthread_mutex_lock(&s_opus_ring_lock);
    if (frames > SNK_OPUS_RING_FRAMES) {
        pcm += (frames - SNK_OPUS_RING_FRAMES) * channels;
        frames = SNK_OPUS_RING_FRAMES;
    }
    /* A full ring means nobody is consuming; drop the oldest audio rather than
     * the newest, so a late start still hears the current moment. */
    if (s_opus_ring_written - s_opus_ring_read > SNK_OPUS_RING_FRAMES)
        s_opus_ring_read = s_opus_ring_written - SNK_OPUS_RING_FRAMES;
    for (unsigned f = 0; f < frames; ++f) {
        size_t slot = (size_t)((s_opus_ring_written + f) % SNK_OPUS_RING_FRAMES);
        s_opus_ring[slot * 2]     = pcm[f * channels];
        s_opus_ring[slot * 2 + 1] = channels > 1 ? pcm[f * channels + 1] : pcm[f * channels];
    }
    s_opus_ring_written += frames;
    pthread_mutex_unlock(&s_opus_ring_lock);
}

/* Adds the decoded stream straight into the mix block, returns frames used.
 * This is the path that actually carries sound: the title's voice queue is left
 * alone, but nothing it does ever moves the decoded PCM into a playable buffer,
 * so the sample the decoder produced is mixed here at the output rate. */
static unsigned snk_opus_ring_mix_into(float *dst, uint32_t frames, uint32_t channels) {
    if (!dst || !frames) return 0;
    unsigned used = 0, peak = 0;
    pthread_mutex_lock(&s_opus_ring_lock);
    uint64_t avail = s_opus_ring_written - s_opus_ring_read;
    if (avail > frames) avail = frames;
    for (uint64_t f = 0; f < avail; ++f) {
        size_t slot = (size_t)((s_opus_ring_read + f) % SNK_OPUS_RING_FRAMES);
        float l = (float)s_opus_ring[slot * 2] * (1.0f / 32768.0f);
        float r = (float)s_opus_ring[slot * 2 + 1] * (1.0f / 32768.0f);
        unsigned mag = (unsigned)(s_opus_ring[slot * 2] < 0 ? -s_opus_ring[slot * 2] : s_opus_ring[slot * 2]);
        if (mag > peak) peak = mag;
        if (channels == 1u) dst[f] += 0.5f * (l + r);
        else { dst[f * channels] += l; dst[f * channels + 1] += r; }
    }
    s_opus_ring_read += avail;
    used = (unsigned)avail;
    pthread_mutex_unlock(&s_opus_ring_lock);
    if (peak > s_mix_mixed_peak) s_mix_mixed_peak = peak;
    return used;
}

/* Copies up to `frames` stereo frames into a guest buffer, returns how many. */
static unsigned snk_opus_ring_take(int16_t *dst, unsigned frames) {
    if (!dst || !frames) return 0;
    pthread_mutex_lock(&s_opus_ring_lock);
    uint64_t avail = s_opus_ring_written - s_opus_ring_read;
    if (avail > frames) avail = frames;
    for (uint64_t f = 0; f < avail; ++f) {
        size_t slot = (size_t)((s_opus_ring_read + f) % SNK_OPUS_RING_FRAMES);
        dst[f * 2]     = s_opus_ring[slot * 2];
        dst[f * 2 + 1] = s_opus_ring[slot * 2 + 1];
    }
    s_opus_ring_read += avail;
    pthread_mutex_unlock(&s_opus_ring_lock);
    return (unsigned)avail;
}

static unsigned s_audio_evt;
static int snk_audio_event(unsigned limit) {
    unsigned n = __atomic_add_fetch(&s_audio_evt, 1u, __ATOMIC_RELAXED);
    return n <= limit || n % 500u == 0;
}

struct snk_audio_voice {
    uint64_t magic;
    const void *key;           /* the title's own VoiceType address, the real handle */
    uint32_t state;            /* 0 free, 1 acquired */
    uint32_t channel;
    uint32_t sample_format;
    uint32_t reserved;
    uint64_t wave_buffer;
    uint64_t wave_buffer_size;
    /* Mixer state. The title only ever holds the pointer this slot handed back,
     * so everything the audren mixer needs can live here: the wave data it
     * registered plus the play head and the parameters it set. */
    const uint8_t *mix_data;
    uint64_t mix_bytes;
    uint64_t mix_pos;          /* byte offset into mix_data */
    uint32_t mix_rate;         /* source sample rate, 0 = renderer rate */
    int32_t mix_samples;       /* frames played since the wave buffer was added */
    float mix_volume;
    float mix_pitch;
    int32_t mix_playing;
    int32_t mix_loop;
    int32_t mix_loops_done;
    const void *mix_wave_obj;  /* the title's WaveBuffer, handed back when it is done */
    uint32_t mix_src_channels; /* channels in the decoded wave data */
    int32_t mix_wait_data;     /* appended buffer was still silent; hold the play head */
    uint32_t mix_wait_blocks;  /* how many updates it has been waiting */
};

#define SNK_AUDIO_VOICE_MAGIC 0x534e4b4155564f58ull
/* The host side has no ReleaseVoiceSlot entry, so a slot handed out here stays
 * taken for the lifetime of the process. The pool used to hold 64 entries and
 * the shipping title exhausted it (105 "no free voice slot" failures in one
 * session), after which every further AcquireVoiceSlot failed and the title
 * could not build its voice graph. The size only bounds how many voices may be
 * alive at once; raising it keeps every previously returned pointer valid and
 * changes no other behaviour. */
#define SNK_AUDIO_VOICE_SLOT_COUNT 1024

static struct snk_audio_voice s_audio_voices[SNK_AUDIO_VOICE_SLOT_COUNT];

/* The title owns the VoiceType object: AcquireVoiceSlot is handed its address
 * and every later call passes that same address back. Writing a pointer of our
 * own into the struct is what the first version did, and the title then handed
 * us a completely different address, so nothing matched and every wave buffer
 * was dropped. The state is keyed on the title's address instead. */
static struct snk_audio_voice *snk_voice_find(const void *key) {
    if (!key) return NULL;
    for (size_t i = 0; i < SNK_AUDIO_VOICE_SLOT_COUNT; ++i)
        if (s_audio_voices[i].magic == SNK_AUDIO_VOICE_MAGIC && s_audio_voices[i].key == key)
            return &s_audio_voices[i];
    return NULL;
}

uint64_t snk_audio_acquire_voice_slot(void *config, void *voice_out,
                                       int channel, int mixer_index,
                                       int sample_format, int sample_count,
                                       const void *wave_buffer,
                                       size_t wave_buffer_size,
                                       void *behavior_options) {
    /* Measured on the shipping title: the third and fourth arguments are 48000
     * and 2, the fifth is 2 (PCM_INT16). So the slot's rate comes from the
     * third argument and its channel count from the fourth. */
    (void)config;
    (void)mixer_index;
    (void)sample_count;
    (void)behavior_options;
    struct snk_audio_voice *voice = snk_voice_find(voice_out);
    pthread_mutex_lock(&s_audio_lock);
    for (size_t i = 0; voice == NULL && i < SNK_AUDIO_VOICE_SLOT_COUNT; i++) {
        if (s_audio_voices[i].magic != SNK_AUDIO_VOICE_MAGIC) {
            memset(&s_audio_voices[i], 0, sizeof(s_audio_voices[i]));
            s_audio_voices[i].magic = SNK_AUDIO_VOICE_MAGIC;
            s_audio_voices[i].state = 1u;
            s_audio_voices[i].key = voice_out;
            s_audio_voices[i].channel = (uint32_t)mixer_index;
            s_audio_voices[i].sample_format = (uint32_t)sample_format;
            s_audio_voices[i].mix_rate = (uint32_t)channel;
            s_audio_voices[i].mix_src_channels = mixer_index > 0 ? (uint32_t)mixer_index : 1u;
            s_audio_voices[i].wave_buffer = (uint64_t)(uintptr_t)wave_buffer;
            s_audio_voices[i].wave_buffer_size = (uint64_t)wave_buffer_size;
            s_audio_voices[i].mix_volume = 1.0f;
            s_audio_voices[i].mix_pitch = 1.0f;
            s_audio_voices[i].mix_data = (const uint8_t *)wave_buffer;
            s_audio_voices[i].mix_bytes = (uint64_t)wave_buffer_size;
            voice = &s_audio_voices[i];
            break;
        }
    }
    pthread_mutex_unlock(&s_audio_lock);
    if (!voice) {
        fprintf(stderr, "[snk-media] AcquireVoiceSlot: no free voice slot\n");
        return 0;
    }
    { static unsigned n; if (n < 12) { ++n; fprintf(stderr, "[audio] AcquireVoiceSlot #%u key=%p rate=%d channels=%d format=%d wave=%p bytes=%zu\n",
        n, voice_out, channel, mixer_index, sample_format, wave_buffer, wave_buffer_size); } }
    /* The title's object is left exactly as it was: it is the handle, not a
     * place to store ours. */
    return 1;
}

uint64_t snk_audio_request_update_renderer(void *renderer, void *state_object,
                                                   const void *config) {
    (void)renderer;
    (void)state_object;
    (void)config;
    /* The mixer runs on its own thread at the audio period, so a title that
     * skips RequestUpdate (this one does, its sub mix never opened) still gets
     * PCM. Answering "done" here is what the SDK does after a successful
     * update, and it keeps the caller's pacing unchanged. */
    return 0;
}

/* ====================================================================== */
/* audren mixer (opt-in: marker snk-audio-mix in the app files directory)  */
/* ====================================================================== */
/* The title builds its audio graph through nn::audio::AudioRenderer. The
 * renderer service is what mixes; this port has never had one, so every voice
 * knob was a no-op and no PCM ever reached the output. The mixing is done here
 * from the voice objects this HLE hands out: the title never looks inside them,
 * it only passes the pointer back, so the play head can live in the slot.
 *
 * Default off. With the marker absent the whole path is skipped and behaviour
 * is exactly what it was before (silence). */
#define SNK_MIX_RING 6
static struct {
    int state;                 /* 0 unprobed, 1 on, -1 off */
    int opened;
    void *key;
    uint8_t buffer[64];
    uint8_t *pcm;
    uint32_t frames;
    uint32_t capacity_bytes;
    uint32_t rate;
    uint32_t channels;
    uint64_t updates;
} s_mix;
/* s_mix_mixed_peak is declared above, next to the decode tap. */
static uint64_t (*s_mix_open)(void *, void *, const void *);
static uint64_t (*s_mix_start)(void *);
static uint64_t (*s_mix_append)(void *, void *);
static void *(*s_mix_released)(void *);

typedef struct { void *next, *data; uint64_t capacity, bytes, offset; } snk_mix_buffer;
static snk_mix_buffer s_mix_buffers[SNK_MIX_RING];
static int s_mix_buffer_used[SNK_MIX_RING];

static int snk_mix_probe(void);
void snk_audio_mixer_update(void);

static float snk_voice_volume(const struct snk_audio_voice *v) {
    return v->mix_volume > 0.0f ? v->mix_volume : 1.0f;
}
/* The wave buffer is the title's own object. Its first two words are the data
 * pointer and the byte count in every nnSdk build this port has seen; the dump
 * printed once below records the real bytes so a different layout shows up
 * instead of silently mixing garbage. */
static void snk_voice_take_wave(struct snk_audio_voice *v, const void *wave_buffer) {
    if (!wave_buffer) return;
    const uint8_t *p = (const uint8_t *)wave_buffer;
    static unsigned dumps;
    if (dumps < 4) {
        ++dumps;
        fprintf(stderr, "[audio] wave buffer raw=%p head=", wave_buffer);
        for (unsigned i = 0; i < 48; ++i) fprintf(stderr, "%02x", p[i]);
        fprintf(stderr, "\n");
    }
    /* The layout of the title's WaveBuffer has not been proven by a dump yet, so
     * instead of trusting a fixed offset the data pointer and byte count are
     * searched for among the plausible word pairs and accepted only when the
     * pair is self-consistent: a pointer inside this port's guest heap followed
     * by a byte count that is a multiple of one interleaved frame. The chosen
     * offsets are printed, so the next dump confirms or corrects them. */
    /* Measured guest pointers in this port live in the 0x6d..-0x73.. range
     * (10 hex digits), e.g. 0x6d95c94000 for the wave data itself. The window
     * is that range, not the 48-bit window assumed before, which rejected the
     * real pointer. */
    const uint64_t heap_lo = 0x6000000000ull, heap_hi = 0x7c00000000ull;
    const uint32_t frame_bytes = 2u * (v->mix_src_channels ? v->mix_src_channels : 1u);
    static const unsigned ptr_at[] = {0x00, 0x08, 0x10, 0x18};
    uint64_t data = 0, bytes = 0;
    unsigned chosen = ~0u;
    for (unsigned i = 0; i < sizeof ptr_at / sizeof ptr_at[0]; ++i) {
        uint64_t candidate = 0;
        memcpy(&candidate, p + ptr_at[i], 8);
        if (candidate < heap_lo || candidate >= heap_hi) continue;
        uint64_t size64 = 0;
        uint32_t size32 = 0;
        memcpy(&size64, p + ptr_at[i] + 8, 8);
        memcpy(&size32, p + ptr_at[i] + 4, 4);
        /* a 32-bit count directly after a 32-bit pointer, or a 64-bit count */
        uint64_t size = (size64 > 0 && size64 <= (16ull << 20)) ? size64 : (uint64_t)size32;
        if (!size || size > (16ull << 20) || size % frame_bytes) continue;
        data = candidate; bytes = size; chosen = ptr_at[i];
        break;
    }
    if (chosen == ~0u) {
        fprintf(stderr, "[audio] wave buffer: no plausible pointer/size pair in the first 0x30 bytes\n");
        return;
    }
    /* Peak over the whole buffer, not just its head: a streaming chunk can
     * legitimately begin with a gap, and only a whole-buffer peak tells a
     * silent chunk from a wrong pointer. */
    const int16_t *pcm = (const int16_t *)(uintptr_t)data;
    const uint64_t samples = bytes / 2;
    const uint64_t look = samples < 16384 ? samples : 16384;
    unsigned peak = 0, nonzero = 0;
    for (uint64_t i = 0; i < look; ++i) {
        int v = pcm[i]; unsigned mag = (unsigned)(v < 0 ? -v : v);
        if (mag) ++nonzero;
        if (mag > peak) peak = mag;
    }

    /* The title hands this buffer over empty and then flushes it, so the PCM it
     * decoded for it is poured in here instead (see the decode tap). A buffer
     * that already carries data is left exactly as the title wrote it. */
    unsigned filled = 0;
    if (peak == 0 && bytes >= 4u) {
        unsigned want = (unsigned)(samples / 2u);      /* stereo frames */
        filled = snk_opus_ring_take((int16_t *)(uintptr_t)data, want);
        if (filled) {
            peak = 0;
            for (uint64_t i = 0; i < (uint64_t)filled * 2u; ++i) {
                int v = pcm[i]; unsigned mag = (unsigned)(v < 0 ? -v : v);
                if (mag > peak) peak = mag;
            }
        }
    }

    static unsigned picks;
    ++picks;
    if (picks <= 20 || picks % 50u == 0)
        fprintf(stderr, "[audio] wave buffer #%u accepted ptr@%#x data=%#llx bytes=%llu frames=%llu peak=%u nonzero=%u/%llu filled=%u\n",
                picks, chosen, (unsigned long long)data, (unsigned long long)bytes,
                (unsigned long long)(bytes / frame_bytes), peak, nonzero, (unsigned long long)look, filled);

    v->mix_data = (const uint8_t *)(uintptr_t)data;
    v->mix_bytes = bytes;
    v->mix_pos = 0;
    v->mix_samples = 0;
    v->mix_wave_obj = wave_buffer;
    /* A buffer handed to a voice is meant to play; leaving it parked until the
     * title fills it is what stalled the stream, since the title never does. */
    v->mix_wait_data = 0;
    v->mix_wait_blocks = 0;
    v->mix_playing = 1;
}

uint64_t snk_audio_v_append_wave(void *voice_obj, const void *wave_buffer) {
    struct snk_audio_voice *v = snk_voice_find(voice_obj);
    if (!v || v->magic != SNK_AUDIO_VOICE_MAGIC) {
        if (snk_audio_event(20))
            fprintf(stderr, "[audio] AppendWaveBuffer unknown voice=%p wave=%p\n", voice_obj, wave_buffer);
        return 0;
    }
    snk_voice_take_wave(v, wave_buffer);
    if (snk_audio_event(60))
        fprintf(stderr, "[audio] AppendWaveBuffer key=%p wave=%p data=%p bytes=%llu playing=%d wait=%d\n",
                voice_obj, wave_buffer, (const void *)v->mix_data,
                (unsigned long long)v->mix_bytes, v->mix_playing, v->mix_wait_data);
    return 0;
}

int snk_audio_mixer_enabled(void) { return snk_mix_probe(); }

/* Graph objects (sub mix, final mix, memory pool, splitter, device sink and the
 * effect nodes). The title builds its renderer graph out of these before it
 * touches a single voice, and the generic stub answered "false" for every one
 * of them: the title then printed AcquireSubMix() failed and gave up, which is
 * why no voice was ever created and no PCM ever existed. The objects are opaque
 * to the title (it only keeps the pointer and hands it back), so a zeroed block
 * per slot is all it needs; the mixer does not model the graph yet. */
#define SNK_AUDIO_OBJECT_SLOTS 512
#define SNK_AUDIO_OBJECT_BYTES 64
static uint8_t s_audio_objects[SNK_AUDIO_OBJECT_SLOTS][SNK_AUDIO_OBJECT_BYTES];
static unsigned s_audio_object_next;

static uint64_t snk_audio_acquire_object(void *config, void **out, void *a, void *b) {
    (void)config; (void)a; (void)b;
    if (!out) return 0;
    if (s_audio_object_next >= SNK_AUDIO_OBJECT_SLOTS) {
        fprintf(stderr, "[audio] graph object pool exhausted after %u slots\n", s_audio_object_next);
        return 0;
    }
    void *object = s_audio_objects[s_audio_object_next++];
    memset(object, 0, SNK_AUDIO_OBJECT_BYTES);
    *out = object;
    static unsigned logs;
    if (logs < 24) {
        ++logs;
        fprintf(stderr, "[audio] graph object %u out=%p\n", s_audio_object_next, object);
    }
    return 1;
}

/* The mixer thread: one block per audren update period. Started by the first
 * voice that is actually told to play, so a title that never plays anything
 * pays nothing. */
static void *snk_audio_mixer_thread(void *unused) {
    (void)unused;
    for (;;) {
        snk_audio_mixer_update();
        uint64_t period_ns = s_mix.rate ? (uint64_t)s_mix.frames * 1000000000ull / s_mix.rate : 16000000ull;
        struct timespec ts = {(time_t)(period_ns / 1000000000ull), (long)(period_ns % 1000000000ull)};
        nanosleep(&ts, NULL);
    }
    return NULL;
}
static void snk_audio_mixer_start_thread(void) {
    static int started;
    if (started) return;
    started = 1;
    pthread_t thread;
    if (pthread_create(&thread, NULL, snk_audio_mixer_thread, NULL))
        fprintf(stderr, "[audio] audren mixer thread could not start; staying silent\n");
    else
        fprintf(stderr, "[audio] audren mixer thread started\n");
}

uint64_t snk_audio_v_play_state(void *voice_obj, uint32_t play_state) {
    struct snk_audio_voice *v = snk_voice_find(voice_obj);
    if (snk_audio_event(60))
        fprintf(stderr, "[audio] PlayState key=%p known=%d state=%u data=%p bytes=%llu\n",
                voice_obj, v != NULL, play_state,
                v ? (const void *)v->mix_data : NULL,
                (unsigned long long)(v ? v->mix_bytes : 0));
    if (!v || v->magic != SNK_AUDIO_VOICE_MAGIC) return 0;
    /* Only "stop" (0) is treated as stopped: the title was seen using both 1
     * and 2 for a voice that is meant to be heard, and playing a paused voice
     * is a smaller error than dropping a playing one. */
    v->mix_playing = play_state != 0u;
    if (play_state == 0u) { v->mix_pos = 0; v->mix_samples = 0; }
    if (play_state != 0u) snk_audio_mixer_start_thread();
    return 0;
}

uint64_t snk_audio_v_flush(void *voice_obj) {
    struct snk_audio_voice *v = snk_voice_find(voice_obj);
    if (snk_audio_event(60))
        fprintf(stderr, "[audio] FlushWaveBuffers key=%p known=%d data=%p bytes=%llu\n",
                voice_obj, v != NULL, v ? (const void *)v->mix_data : NULL,
                (unsigned long long)(v ? v->mix_bytes : 0));
    if (!v || v->magic != SNK_AUDIO_VOICE_MAGIC) return 0;
    /* Keeping an in-flight buffer here was tried and made things worse: the
     * title then spins on InsufficientOpusBuffer instead of giving up, so the
     * drain path is not what it is waiting for. Cleared, as before. */
    v->mix_data = NULL;
    v->mix_bytes = 0;
    v->mix_pos = 0;
    v->mix_samples = 0;
    v->mix_wave_obj = NULL;
    v->mix_wait_data = 0;
    return 0;
}

uint64_t snk_audio_v_volume(void *voice_obj, float volume) {
    struct snk_audio_voice *v = snk_voice_find(voice_obj);
    if (!v || v->magic != SNK_AUDIO_VOICE_MAGIC) return 0;
    if (!(volume >= 0.0f && volume <= 8.0f)) return 0;
    v->mix_volume = volume;
    return 0;
}

uint64_t snk_audio_v_pitch(void *voice_obj, float pitch) {
    struct snk_audio_voice *v = snk_voice_find(voice_obj);
    if (!v || v->magic != SNK_AUDIO_VOICE_MAGIC) return 0;
    if (!(pitch > 0.0f && pitch <= 8.0f)) return 0;
    v->mix_pitch = pitch;
    return 0;
}

uint64_t snk_audio_v_played(const void *voice_obj) {
    const struct snk_audio_voice *v = snk_voice_find(voice_obj);
    if (!v || v->magic != SNK_AUDIO_VOICE_MAGIC) return 0;
    return (uint64_t)(v->mix_samples < 0 ? 0 : v->mix_samples);
}

/* The graph helpers that only have to say "yes": the pointer they are handed is
 * already the object this module handed out. */
uint64_t snk_audio_set_destination(void *config, void *voice, void *dest) {
    static unsigned n;
    if (n < 12) { ++n; fprintf(stderr, "[audio] SetVoiceDestination voice=%p dest=%p\n", voice, dest); }
    (void)config;
    return 1;
}

uint64_t snk_audio_ok(void *a, void *b, void *c) {
    (void)a; (void)b; (void)c;
    return 1;
}

/* The Add<node> family answers with an nn::Result, not a bool: the title prints
 * the value as a code ("failed (result = 0x00000001)") whenever it is not zero,
 * so success here is 0 and the object pointer still has to be stored. */
uint64_t snk_audio_result_ok(void *config, void **out, void *a, void *b) {
    (void)config; (void)a; (void)b;
    if (!out) return 0;
    if (s_audio_object_next >= SNK_AUDIO_OBJECT_SLOTS) return 1;
    void *object = s_audio_objects[s_audio_object_next++];
    memset(object, 0, SNK_AUDIO_OBJECT_BYTES);
    *out = object;
    static unsigned logs;
    if (logs < 24) {
        ++logs;
        fprintf(stderr, "[audio] graph result object %u out=%p\n", s_audio_object_next, object);
    }
    return 0;
}

uint64_t snk_audio_v_wave_count(const void *voice_obj) {
    const struct snk_audio_voice *v = snk_voice_find(voice_obj);
    if (!v || v->magic != SNK_AUDIO_VOICE_MAGIC) return 0;
    return v->mix_data ? 1u : 0u;
}

/* A finished wave buffer goes back to the title so a streaming voice can reuse
 * it. Only a buffer the mixer has played to its end is returned, once. */
void *snk_audio_v_released(void *voice_obj) {
    struct snk_audio_voice *v = snk_voice_find(voice_obj);
    if (!v || v->magic != SNK_AUDIO_VOICE_MAGIC) return NULL;
    if (!v->mix_wave_obj || v->mix_data) return NULL;
    void *wave = (void *)v->mix_wave_obj;
    v->mix_wave_obj = NULL;
    if (snk_audio_event(60))
        fprintf(stderr, "[audio] Released key=%p -> wave=%p\n", voice_obj, wave);
    return wave;
}

static int snk_mix_probe(void) {
    if (s_mix.state) return s_mix.state > 0;
    const char *dir = ffrs_audio_platform_directory();
    char path[PATH_MAX];
    int n = dir ? snprintf(path, sizeof path, "%s/snk-audio-mix", dir) : -1;
    FILE *f = (n > 0 && (size_t)n < sizeof path) ? fopen(path, "rb") : NULL;
    s_mix.state = f ? 1 : -1;
    if (f) fclose(f);
    fprintf(stderr, "[audio] audren mixer=%d (marker snk-audio-mix)%s\n", s_mix.state > 0,
            s_mix.state > 0 ? "" : "; voice calls remain no-ops");
    if (s_mix.state <= 0) return 0;
    unsigned args = 0, rets = 0;
    s_mix_open = (uint64_t (*)(void *, void *, const void *))ffrs_audio_lookup(
        "_ZN2nn5audio19OpenDefaultAudioOutEPNS0_8AudioOutEPNS_2os11SystemEventERKNS0_17AudioOutParameterE", &args, &rets);
    s_mix_start = (uint64_t (*)(void *))ffrs_audio_lookup("_ZN2nn5audio13StartAudioOutEPNS0_8AudioOutE", NULL, NULL);
    s_mix_append = (uint64_t (*)(void *, void *))ffrs_audio_lookup(
        "_ZN2nn5audio20AppendAudioOutBufferEPNS0_8AudioOutEPNS0_14AudioOutBufferE", NULL, NULL);
    s_mix_released = (void *(*)(void *))ffrs_audio_lookup(
        "_ZN2nn5audio25GetReleasedAudioOutBufferEPNS0_8AudioOutE", NULL, NULL);
    if (!s_mix_open || !s_mix_start || !s_mix_append) {
        fprintf(stderr, "[audio] audren mixer: AudioOut bridge entries missing; staying silent\n");
        s_mix.state = -1; return 0;
    }
    return 1;
}

static int snk_mix_open_output(void) {
    memset(s_mix.buffer, 0, sizeof s_mix.buffer);
    uint64_t parameter = 0;
    if (s_mix_open(s_mix.buffer, NULL, &parameter) != 0) {
        fprintf(stderr, "[audio] audren mixer: AudioOut open refused; staying silent\n");
        return 0;
    }
    s_mix.key = s_mix.buffer;
    s_mix.rate = (uint32_t)((int32_t *)s_mix.buffer)[0];
    s_mix.channels = (uint32_t)((int32_t *)s_mix.buffer)[1];
    if (s_mix.rate < 8000) s_mix.rate = 48000;
    if (!s_mix.channels) s_mix.channels = 2;
    s_mix.frames = s_mix.rate / 60u;               /* audren's 60 Hz update period */
    if (s_mix.channels > 2) s_mix.channels = 2;
    s_mix.capacity_bytes = s_mix.frames * s_mix.channels * 2u;
    for (int i = 0; i < SNK_MIX_RING; ++i) {
        free(s_mix_buffers[i].data);
        s_mix_buffers[i].data = calloc(s_mix.capacity_bytes, 1);
        s_mix_buffers[i].capacity = s_mix.capacity_bytes;
        s_mix_buffers[i].bytes = s_mix.capacity_bytes;
        s_mix_buffers[i].offset = 0;
        s_mix_buffer_used[i] = 0;
    }
    if (!s_mix.pcm) s_mix.pcm = calloc(s_mix.frames * s_mix.channels, sizeof(float));
    s_mix_start(s_mix.key);
    s_mix.opened = 1;
    fprintf(stderr, "[audio] audren mixer opened key=%p rate=%u channels=%u frames_per_update=%u\n",
            s_mix.key, s_mix.rate, s_mix.channels, s_mix.frames);
    return 1;
}

/* One update: mix every playing voice into one block and hand it to the same
 * AAudio transport the AudioOut bridge already owns. */
void snk_audio_mixer_update(void) {
    if (!snk_mix_probe()) return;
    if (!s_mix.opened && !snk_mix_open_output()) return;
    if (!s_mix.pcm) return;
    const uint32_t frames = s_mix.frames, channels = s_mix.channels;
    memset(s_mix.pcm, 0, (size_t)frames * channels * sizeof(float));
    unsigned audible = 0;
    pthread_mutex_lock(&s_audio_lock);
    for (size_t i = 0; i < SNK_AUDIO_VOICE_SLOT_COUNT; ++i) {
        struct snk_audio_voice *v = &s_audio_voices[i];
        if (v->magic != SNK_AUDIO_VOICE_MAGIC || !v->mix_data) {
            if (v->magic == SNK_AUDIO_VOICE_MAGIC && v->mix_bytes) {
                static unsigned why_logs;
                if (why_logs++ < 4)
                    fprintf(stderr, "[mix] voice has bytes=%llu but mix_data is null\n",
                            (unsigned long long)v->mix_bytes);
            }
            continue;
        }
        if (v->mix_wait_data) {
            const int16_t *pcm = (const int16_t *)v->mix_data;
            uint64_t look = v->mix_bytes / 2 < 512 ? v->mix_bytes / 2 : 512;
            unsigned peak = 0;
            for (uint64_t i = 0; i < look; ++i) { int x = pcm[i]; unsigned m = (unsigned)(x < 0 ? -x : x); if (m > peak) peak = m; }
            ++v->mix_wait_blocks;
            if (peak) {
                v->mix_wait_data = 0; v->mix_playing = 1;
                fprintf(stderr, "[audio] voice data appeared after %u updates peak=%u\n", v->mix_wait_blocks, peak);
            } else if (v->mix_wait_blocks == 600) {
                fprintf(stderr, "[audio] voice still silent after 10 s at data=%p bytes=%llu; source never filled it\n",
                        (const void *)v->mix_data, (unsigned long long)v->mix_bytes);
            }
            if (v->mix_wait_data) continue;
        }
        if (!v->mix_playing && !v->mix_data) continue;
        /* The played-sample clock advances at the output rate even when the
         * voice has no buffer in hand. The title's streaming thread waits on
         * this counter before decoding the next packet, so a clock that only
         * moves while data is present stops the stream dead -- measured: two
         * packets decoded, then nothing for the rest of the session. */
        if (v->mix_playing) v->mix_samples += frames;
        if (!v->mix_data) continue;
        /* Only PCM16 is mixed. Anything else is reported once instead of being
         * played as noise: the format enum is the title's, not a guess. */
        if (v->sample_format != 2u) {
            static unsigned fmt_logs;
            if (fmt_logs++ < 4)
                fprintf(stderr, "[audio] voice format=%u not mixed (PCM16 only in this build)\n", v->sample_format);
            continue;
        }
        const int16_t *src = (const int16_t *)v->mix_data;
        const uint32_t src_ch = v->mix_src_channels ? v->mix_src_channels : 1u;
        const uint64_t src_frames = v->mix_bytes / (2ull * src_ch);
        if (!src_frames) {
            static unsigned why_logs3;
            if (why_logs3++ < 4)
                fprintf(stderr, "[mix] voice src_frames=0 bytes=%llu src_ch=%u fmt=%u\n",
                        (unsigned long long)v->mix_bytes, src_ch, v->sample_format);
            continue;
        }
        float volume = snk_voice_volume(v);
        double step = v->mix_pitch > 0.01f ? (double)v->mix_pitch : 1.0;
        if (v->mix_rate && v->mix_rate != s_mix.rate) step *= (double)v->mix_rate / (double)s_mix.rate;
        double at = (double)v->mix_pos;
        int drained = 0;
        for (uint32_t f = 0; f < frames; ++f) {
            uint64_t index = (uint64_t)at;
            if (index >= src_frames) {
                if (v->mix_loop) { at = 0.0; index = 0; v->mix_loops_done++; }
                else { drained = 1; break; }
            }
            if (src_ch == 1u) {
                float sample = (float)src[index] * (1.0f / 32768.0f) * volume;
                unsigned mag = (unsigned)(src[index] < 0 ? -src[index] : src[index]);
                if (mag > s_mix_mixed_peak) s_mix_mixed_peak = mag;
                for (uint32_t c = 0; c < channels; ++c) s_mix.pcm[f * channels + c] += sample;
            } else {
                for (uint32_t c = 0; c < channels && c < src_ch; ++c) {
                    int16_t raw = src[index * src_ch + c];
                    unsigned mag = (unsigned)(raw < 0 ? -raw : raw);
                    if (mag > s_mix_mixed_peak) s_mix_mixed_peak = mag;
                    s_mix.pcm[f * channels + c] += (float)raw * (1.0f / 32768.0f) * volume;
                }
            }
            at += step;
        }
        if (drained) {
            /* Hand the buffer back the moment it is used up: the streaming loop
             * will not decode again until GetReleasedWaveBuffer collects it. */
            v->mix_data = NULL;
            v->mix_bytes = 0;
            v->mix_pos = 0;
        } else {
            v->mix_pos = (uint64_t)at;
        }
        ++audible;
    }
    pthread_mutex_unlock(&s_audio_lock);

    /* The decoded stream goes in whether or not any voice is audible: it is the
     * only source of real samples in this build (see snk_opus_ring_mix_into). */
    {
        static unsigned tap_logs;
        unsigned used = snk_opus_ring_mix_into(s_mix.pcm, frames, channels);
        if (used && tap_logs < 6) { ++tap_logs;
            fprintf(stderr, "[mix] decode tap fed %u/%u frames, peak=%u\n",
                    used, frames, s_mix_mixed_peak); }
        if (!used && s_mix.updates % 300u == 1u) {
            static unsigned starve;
            if (starve++ < 6) fprintf(stderr, "[mix] decode tap starved (ring empty)\n");
        }
    }

    int slot = -1;
    for (int i = 0; i < SNK_MIX_RING; ++i) if (!s_mix_buffer_used[i]) { slot = i; break; }
    if (slot < 0 && s_mix_released) {
        void *back = s_mix_released(s_mix.key);
        if (back) for (int i = 0; i < SNK_MIX_RING; ++i) if (&s_mix_buffers[i] == back) { s_mix_buffer_used[i] = 0; slot = i; break; }
    }
    if (slot < 0) return;                            /* the transport is still reading them */
    int16_t *out = (int16_t *)s_mix_buffers[slot].data;
    for (size_t i = 0; i < (size_t)frames * channels; ++i) {
        float s = s_mix.pcm[i];
        if (s > 1.0f) s = 1.0f; else if (s < -1.0f) s = -1.0f;
        out[i] = (int16_t)(s * 32767.0f);
    }
    s_mix_buffer_used[slot] = 1;
    s_mix_append(s_mix.key, &s_mix_buffers[slot]);
    ++s_mix.updates;
    if (s_mix.updates % 300u == 1u) {
        unsigned with_data = 0, playing = 0;
        pthread_mutex_lock(&s_audio_lock);
        for (size_t i = 0; i < SNK_AUDIO_VOICE_SLOT_COUNT; ++i) {
            struct snk_audio_voice *v = &s_audio_voices[i];
            if (v->magic != SNK_AUDIO_VOICE_MAGIC) continue;
            if (v->mix_bytes) ++with_data;
            if (v->mix_playing) ++playing;
        }
        pthread_mutex_unlock(&s_audio_lock);
        fprintf(stderr, "[audio] audren mixer updates=%llu mixed=%u with_data=%u playing=%u mixed_peak=%u\n",
                (unsigned long long)s_mix.updates, audible, with_data, playing, s_mix_mixed_peak);
        s_mix_mixed_peak = 0;
    }
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

/* The title decodes BGM and SE itself. It parses the .nxopus container and
 * hands nn::codec one Opus packet at a time, so a packet decoder is the whole
 * of what this service has to provide -- the container never reaches here.
 * third_party/opus is that decoder; the previous version of this file returned
 * a buffer of zeros, which is why the mixer ran with perfect timing and no
 * sound. */

struct snk_opus_state {
    void *owner;
    int sample_rate;
    int channels;
    OpusDecoder *decoder;
    /* One 120 ms packet at 48 kHz is the Opus maximum; the decode goes here
     * first so the caller's buffer can never be written past its capacity. */
    short pcm[5760 * 2];
};

static pthread_mutex_t s_opus_lock = PTHREAD_MUTEX_INITIALIZER;
static struct snk_opus_state s_opus_states[16];

static struct snk_opus_state *snk_opus_slot(void *owner, bool create) {
    /* Caller holds s_opus_lock. */
    if (!owner) return NULL;
    struct snk_opus_state *free_slot = NULL;
    for (size_t i = 0; i < sizeof(s_opus_states) / sizeof(s_opus_states[0]); i++) {
        if (s_opus_states[i].owner == owner) return &s_opus_states[i];
        if (!free_slot && !s_opus_states[i].owner) free_slot = &s_opus_states[i];
    }
    if (!create || !free_slot) return NULL;
    memset(free_slot, 0, sizeof(*free_slot));
    free_slot->owner = owner;
    return free_slot;
}

uint64_t snk_opus_work_buffer_size(int channels, int sample_rate, int extra) {
    (void)sample_rate;
    (void)extra;
    /* libopus keeps its own state, so this buffer is never touched. A real
     * size is still reported, because the title sizes its allocation from it. */
    int size = opus_decoder_get_size(channels == 1 ? 1 : 2);
    return (uint64_t)(size > 0x10000 ? size : 0x10000);
}

uint64_t snk_opus_initialize(void *owner, int sample_rate, int channels,
                                    void *work_buffer, size_t work_size, int extra) {
    (void)work_buffer;
    (void)work_size;
    (void)extra;
    if (!owner) return 0;
    int rate = sample_rate > 0 ? sample_rate : 48000;
    int ch = (channels == 1 || channels == 2) ? channels : 2;
    int err = OPUS_OK;
    OpusDecoder *decoder = opus_decoder_create(rate, ch, &err);

    pthread_mutex_lock(&s_opus_lock);
    struct snk_opus_state *state = snk_opus_slot(owner, true);
    if (state) {
        if (state->decoder) opus_decoder_destroy(state->decoder);
        state->decoder = (err == OPUS_OK) ? decoder : NULL;
        state->sample_rate = rate;
        state->channels = ch;
    }
    pthread_mutex_unlock(&s_opus_lock);

    fprintf(stderr, "[opus] InitializeOpusDecoder owner=%p rate=%d channels=%d -> %s%s%s\n",
            owner, rate, ch, err == OPUS_OK ? "ok" : "FAILED",
            err == OPUS_OK ? "" : ": ", err == OPUS_OK ? "" : opus_strerror(err));
    if (err != OPUS_OK && decoder) opus_decoder_destroy(decoder);
    return 0;
}

uint64_t snk_opus_finalize(void *owner) {
    pthread_mutex_lock(&s_opus_lock);
    struct snk_opus_state *state = snk_opus_slot(owner, false);
    if (state) {
        if (state->decoder) opus_decoder_destroy(state->decoder);
        memset(state, 0, sizeof(*state));
    }
    pthread_mutex_unlock(&s_opus_lock);
    return 0;
}

uint64_t snk_opus_sample_rate(const void *owner) {
    pthread_mutex_lock(&s_opus_lock);
    struct snk_opus_state *state = snk_opus_slot((void *)owner, false);
    int rate = state && state->sample_rate > 0 ? state->sample_rate : 48000;
    pthread_mutex_unlock(&s_opus_lock);
    return (uint64_t)(uint32_t)rate;
}

uint64_t snk_opus_channel_count(const void *owner) {
    pthread_mutex_lock(&s_opus_lock);
    struct snk_opus_state *state = snk_opus_slot((void *)owner, false);
    int ch = state && state->channels > 0 ? state->channels : 2;
    pthread_mutex_unlock(&s_opus_lock);
    return (uint64_t)(uint32_t)ch;
}

uint64_t snk_opus_reset(void *owner) {
    pthread_mutex_lock(&s_opus_lock);
    struct snk_opus_state *state = snk_opus_slot(owner, false);
    if (state && state->decoder) opus_decoder_ctl(state->decoder, OPUS_RESET_STATE);
    pthread_mutex_unlock(&s_opus_lock);
    return 0;
}

uint64_t snk_opus_decode(void *owner, size_t *consumed, int *frames, short *output,
                                 size_t output_samples, const void *input, size_t input_size) {
    if (consumed) *consumed = input_size;
    if (frames) *frames = 0;
    if (!owner) return 0;

    static unsigned calls;
    ++calls;

    if (calls <= 3) {
        const uint8_t *raw = (const uint8_t *)input;
        fprintf(stderr, "[opus] call #%u owner=%p consumed_ptr=%p frames_ptr=%p out=%p cap=%zu in=%p in_size=%zu head=",
                calls, owner, (void *)consumed, (void *)frames, (void *)output, output_samples,
                input, input_size);
        if (raw) for (unsigned i = 0; i < 32; ++i) fprintf(stderr, "%02x", raw[i]);
        fprintf(stderr, "\n");
    }

    pthread_mutex_lock(&s_opus_lock);
    struct snk_opus_state *state = snk_opus_slot(owner, false);
    if (!state || !state->decoder) {
        pthread_mutex_unlock(&s_opus_lock);
        if (calls <= 4)
            fprintf(stderr, "[opus] decode #%u owner=%p has no decoder; dropped %zu bytes\n",
                    calls, owner, input_size);
        return 0;
    }

    const int channels = state->channels == 1 ? 1 : 2;
    /* nn::codec hands over a stream chunk, not one packet: measured 11899 bytes
     * against a 1920x1080 BGM file whose largest legal Opus packet is 1276.
     * The framing is therefore self-delimited, which is also the only reading
     * of the API that gives pOutConsumed a meaning -- the decoder reports how
     * much of the chunk the first packet used up.
     *
     * The capacity is read as a frame count divided by the channel count, the
     * stricter of the two possible readings (frames vs interleaved shorts), so
     * a caller that meant shorts can never be overrun. Decoding happens into
     * our own buffer first and is copied out afterwards for the same reason. */
    uint64_t capacity = output_samples / (uint64_t)channels;
    if (capacity == 0 || capacity > 5760u) capacity = 5760u;

    opus_int32 used = 0;
    int decoded = opus_decode_self_delimited(state->decoder, (const unsigned char *)input,
                                             (opus_int32)input_size, state->pcm,
                                             (int)capacity, &used);
    if (decoded < 0) {
        /* Reporting a failure here makes the title retry the same packet in a
         * tight loop (measured: ~700 retries/s, 85k lines) instead of moving on,
         * so the packet is consumed and dropped instead. The self-delimited
         * framing still yields its length, so the stream keeps advancing even
         * when the caller's remaining capacity is too small for this packet. */
        unsigned char toc = 0;
        opus_int16 sizes[48];
        opus_int32 packet_offset = 0;
        int parsed = opus_packet_parse_impl((const unsigned char *)input, (opus_int32)input_size, 1,
                                            &toc, NULL, sizes, NULL, &packet_offset, NULL, NULL);
        pthread_mutex_unlock(&s_opus_lock);
        if (snk_audio_event(40))
            fprintf(stderr, "[opus] decode #%u in=%zu dropped (%s), consumed=%d\n",
                    calls, input_size, opus_strerror(decoded),
                    parsed == OPUS_OK && packet_offset > 0 ? (int)packet_offset : (int)input_size);
        if (consumed) *consumed = (parsed == OPUS_OK && packet_offset > 0) ? (size_t)packet_offset : input_size;
        return 0;
    }

    uint64_t shorts = (uint64_t)decoded * (uint64_t)channels;
    if (output && output_samples && shorts > output_samples)
        shorts = output_samples - (output_samples % (uint64_t)channels);
    if (output && shorts) memcpy(output, state->pcm, (size_t)shorts * sizeof(short));
    unsigned peak = 0;
    for (uint64_t i = 0; i < shorts; ++i) {
        int v = state->pcm[i];
        unsigned mag = (unsigned)(v < 0 ? -v : v);
        if (mag > peak) peak = mag;
    }
    pthread_mutex_unlock(&s_opus_lock);

    snk_opus_ring_push(state->pcm, (unsigned)(decoded > 0 ? decoded : 0), (unsigned)channels);
    if (consumed) *consumed = used > 0 ? (size_t)used : input_size;
    if (frames) *frames = decoded;
    if (snk_audio_event(40))
        fprintf(stderr, "[opus] decode #%u in=%zu consumed=%d decoded=%d peak=%u cap=%zu ch=%d\n",
                calls, input_size, (int)used, decoded, peak, output_samples, channels);
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
    pthread_mutex_lock(&s_png_lock);
    for (size_t i = 0; i < sizeof(s_png_states) / sizeof(s_png_states[0]); i++) {
        if (s_png_states[i].owner == self) {
            memset(&s_png_states[i], 0, sizeof(s_png_states[i]));
            break;
        }
    }
    pthread_mutex_unlock(&s_png_lock);
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
    state->width = 0;
    state->height = 0;
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
    uint32_t width = ((uint32_t)data[16] << 24) | ((uint32_t)data[17] << 16) |
                     ((uint32_t)data[18] << 8) | (uint32_t)data[19];
    uint32_t height = ((uint32_t)data[20] << 24) | ((uint32_t)data[21] << 16) |
                      ((uint32_t)data[22] << 8) | (uint32_t)data[23];
    pthread_mutex_lock(&s_png_lock);
    state->width = width;
    state->height = height;
    state->analyzed = 1;
    pthread_mutex_unlock(&s_png_lock);
    fprintf(stderr, "[snk-media] PngDecoder::Analyze: %ux%u\n", width, height);
    return 1;
}

uint64_t snk_png_decoder_decode(void *self, void *output, size_t stride, size_t size) {
    struct snk_png_state *state = snk_png_find(self, false);
    if (!state || !state->data || state->size == 0 || !output) return 2; /* nn::Result error */

    pthread_mutex_lock(&s_png_lock);
    const void *src_data = state->data;
    size_t src_size = state->size;
    uint32_t expected_w = state->width;
    uint32_t expected_h = state->height;
    pthread_mutex_unlock(&s_png_lock);

    if (src_size > INT_MAX) return 2;
    int w = 0, h = 0, channels = 0;
    unsigned char *decoded = stbi_load_from_memory((const stbi_uc *)src_data, (int)src_size,
                                                   &w, &h, &channels, 4);
    if (!decoded) {
        fprintf(stderr, "[snk-media] PngDecoder::Decode: stbi_load_from_memory failed\n");
        return 2;
    }

    if (expected_w == 0 || expected_h == 0) {
        expected_w = (uint32_t)w;
        expected_h = (uint32_t)h;
    }

    if (w <= 0 || h <= 0 || (uint32_t)w != expected_w || (uint32_t)h != expected_h ||
        (size_t)w > SIZE_MAX / 4u) {
        stbi_image_free(decoded);
        return 2;
    }
    size_t row_bytes = (size_t)w * 4u;
    size_t dst_stride = stride ? stride : row_bytes;
    if (dst_stride < row_bytes || (size_t)(h - 1) > (SIZE_MAX - row_bytes) / dst_stride ||
        size < (size_t)(h - 1) * dst_stride + row_bytes) {
        stbi_image_free(decoded);
        return 2;
    }

    unsigned char *dst = (unsigned char *)output;
    for (int y = 0; y < h; y++) {
        memcpy(dst + (size_t)y * dst_stride, decoded + (size_t)y * ((size_t)w * 4u), row_bytes);
    }

    stbi_image_free(decoded);
    fprintf(stderr, "[snk-media] PngDecoder::Decode: %dx%d decoded successfully\n", w, h);
    return 0; /* nn::ResultSuccess */
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
    /* SNK_NATIVE_AUDIO=1: let sdk.nso's own nn::audio AudioRenderer run.  The
     * table above only has host stubs, and those stubs leave the SDK's
     * AudioRendererConfig/memory pool uninitialised, so AcquireSubMix always
     * fails.  Returning "not found" makes the import resolver use the native
     * sdk export instead. */
    static int native_audio = -1;
    if (native_audio < 0) {
        const char *value = getenv("SNK_NATIVE_AUDIO");
        native_audio = value && value[0] == '1';
        /* The host-side mixer needs the voice calls to reach it. When its
         * marker is present the native SDK audio path is not used, because the
         * SDK client keeps its own voice objects and this port has no audren
         * service for it to talk to (its AcquireSubMix never succeeds). */
        if (native_audio && snk_audio_mixer_enabled()) native_audio = 0;
        fprintf(stderr, "[snk-media] native nn::audio=%d (SNK_NATIVE_AUDIO%s)\n", native_audio,
                native_audio ? "" : ", host mixer takes the voice calls");
    }
    if (native_audio && !strncmp(name, "_ZN2nn5audio", 12)) {
        /* sdk.nso does not export these pure helpers (its own imports need
         * them), so keep the host implementations.  Every renderer object
         * operation runs natively. */
        static const char *keep[] = {
            "_ZN2nn5audio15PerformanceInfo",
            "_ZN2nn5audio32InitializeAudioRendererParameter",
            "_ZN2nn5audio29IsValidAudioRendererParameter",
            "_ZN2nn5audio30GetAudioRendererWorkBufferSize",
            "_ZN2nn5audio36GetAudioRendererConfigWorkBufferSize",
            "_ZN2nn5audio41GetRequiredBufferSizeForPerformanceFrames",
        };
        bool keep_hle = false;
        for (size_t k = 0; k < sizeof(keep) / sizeof(keep[0]); k++)
            if (!strncmp(name, keep[k], strlen(keep[k]))) { keep_hle = true; break; }
        /* Only hand the symbol to the native image when the image really
         * exports it. ffrs_sdk_component_lookup exposes the eight DSP and
         * vibration symbols it validated, not the whole sdk.nso export table,
         * so e.g. OpenAudioRenderer would stay unresolved and the import slot
         * would keep its trap. Fall back to the host stub in that case. */
        if (!keep_hle && ffrs_sdk_component_lookup(name, NULL, NULL)) return 0;
    }
    /* audren mixer overrides, ahead of the generated table.
     *
     * The generated table is not edited by hand, and its voice entries all
     * answer with the generic stub. When the opt-in marker is present these
     * names resolve here instead, so the mixer sees the wave buffers, the play
     * state and the block updates. Without the marker nothing changes. */
    if (snk_audio_mixer_enabled()) {
        static const struct { const char *name; void *fn; unsigned gp, fp, gr; } voice[] = {
            /* Renderer graph. Every one of these answered false before, and the
             * title stops building its graph at the first false, so the voice
             * calls below were never reached at all. */
            {"_ZN2nn5audio17AcquireMemoryPoolEPNS0_19AudioRendererConfigEPNS0_14MemoryPoolTypeEPvm", (void *)snk_audio_acquire_object, 4, 0, 1},
            {"_ZN2nn5audio13AcquireSubMixEPNS0_19AudioRendererConfigEPNS0_10SubMixTypeEii", (void *)snk_audio_acquire_object, 4, 0, 1},
            {"_ZN2nn5audio15AcquireFinalMixEPNS0_19AudioRendererConfigEPNS0_12FinalMixTypeEi", (void *)snk_audio_acquire_object, 3, 0, 1},
            {"_ZN2nn5audio15AcquireSplitterEPNS0_19AudioRendererConfigEPNS0_12SplitterTypeEiii", (void *)snk_audio_acquire_object, 5, 0, 1},
            {"_ZN2nn5audio13AddDeviceSinkEPNS0_19AudioRendererConfigEPNS0_14DeviceSinkTypeEPNS0_12FinalMixTypeEPKaiPKc", (void *)snk_audio_result_ok, 6, 0, 1},
            {"_ZN2nn5audio8AddDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPvmPNS0_10SubMixTypeENS_8TimeSpanEi", (void *)snk_audio_result_ok, 7, 0, 1},
            {"_ZN2nn5audio15AddBiquadFilterEPNS0_19AudioRendererConfigEPNS0_16BiquadFilterTypeEPNS0_10SubMixTypeE", (void *)snk_audio_result_ok, 3, 0, 1},
            {"_ZN2nn5audio15AddBiquadFilterEPNS0_19AudioRendererConfigEPNS0_16BiquadFilterTypeEPNS0_12FinalMixTypeE", (void *)snk_audio_result_ok, 3, 0, 1},
            {"_ZN2nn5audio13AddCompressorEPNS0_19AudioRendererConfigEPNS0_14CompressorTypeEPNS0_10SubMixTypeEi", (void *)snk_audio_result_ok, 4, 0, 1},
            {"_ZN2nn5audio13AddCompressorEPNS0_19AudioRendererConfigEPNS0_14CompressorTypeEPNS0_12FinalMixTypeEi", (void *)snk_audio_result_ok, 4, 0, 1},
            {"_ZN2nn5audio14AddI3dl2ReverbEPNS0_19AudioRendererConfigEPNS0_15I3dl2ReverbTypeEPvmPNS0_10SubMixTypeEi", (void *)snk_audio_result_ok, 6, 0, 1},
            {"_ZN2nn5audio10AddCaptureEPNS0_19AudioRendererConfigEPNS0_11CaptureTypeEPNS0_10SubMixTypeEPvm", (void *)snk_audio_result_ok, 5, 0, 1},
            {"_ZN2nn5audio10AddCaptureEPNS0_19AudioRendererConfigEPNS0_11CaptureTypeEPNS0_12FinalMixTypeEPvm", (void *)snk_audio_result_ok, 5, 0, 1},
            {"_ZN2nn5audio19SetVoiceDestinationEPNS0_19AudioRendererConfigEPNS0_9VoiceTypeEPNS0_10SubMixTypeE", (void *)snk_audio_set_destination, 3, 0, 1},
            {"_ZN2nn5audio19SetVoiceDestinationEPNS0_19AudioRendererConfigEPNS0_9VoiceTypeEPNS0_12FinalMixTypeE", (void *)snk_audio_set_destination, 3, 0, 1},
            {"_ZN2nn5audio19SetVoiceDestinationEPNS0_19AudioRendererConfigEPNS0_9VoiceTypeEPNS0_12SplitterTypeE", (void *)snk_audio_set_destination, 3, 0, 1},
            {"_ZN2nn5audio23RequestAttachMemoryPoolEPNS0_14MemoryPoolTypeE", (void *)snk_audio_ok, 1, 0, 1},
            {"_ZN2nn5audio23RequestDetachMemoryPoolEPNS0_14MemoryPoolTypeE", (void *)snk_audio_ok, 1, 0, 1},
            {"_ZN2nn5audio16AppendWaveBufferEPNS0_9VoiceTypeEPKNS0_10WaveBufferE", (void *)snk_audio_v_append_wave, 2, 0, 1},
            {"_ZN2nn5audio17SetVoicePlayStateEPNS0_9VoiceTypeENS1_9PlayStateE", (void *)snk_audio_v_play_state, 2, 0, 1},
            {"_ZN2nn5audio16FlushWaveBuffersEPNS0_9VoiceTypeE", (void *)snk_audio_v_flush, 1, 0, 1},
            {"_ZN2nn5audio13SetVoicePitchEPNS0_9VoiceTypeEf", (void *)snk_audio_v_pitch, 1, 1, 1},
            {"_ZN2nn5audio17SetVoiceMixVolumeEPNS0_9VoiceTypeEPNS0_10SubMixTypeEfii", (void *)snk_audio_v_volume, 4, 1, 1},
            {"_ZN2nn5audio17SetVoiceMixVolumeEPNS0_9VoiceTypeEPNS0_12FinalMixTypeEfii", (void *)snk_audio_v_volume, 4, 1, 1},
            {"_ZN2nn5audio25GetVoicePlayedSampleCountEPKNS0_9VoiceTypeE", (void *)snk_audio_v_played, 1, 0, 1},
            {"_ZN2nn5audio18GetWaveBufferCountEPKNS0_9VoiceTypeE", (void *)snk_audio_v_wave_count, 1, 0, 1},
            {"_ZN2nn5audio21GetReleasedWaveBufferEPNS0_9VoiceTypeE", (void *)snk_audio_v_released, 1, 0, 1},
        };
        for (size_t i = 0; i < sizeof voice / sizeof voice[0]; ++i) {
            if (strcmp(name, voice[i].name)) continue;
            if (gp_arguments) *gp_arguments = voice[i].gp;
            if (fp_arguments) *fp_arguments = voice[i].fp;
            if (gp_returns) *gp_returns = voice[i].gr;
            if (fp_returns) *fp_returns = 0;
            if (stack_bytes) *stack_bytes = 0;
            return (uintptr_t)voice[i].fn;
        }
    }
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
