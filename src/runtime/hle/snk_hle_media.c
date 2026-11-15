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
#include <errno.h>
#include <math.h>
#include <zlib.h>

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

static unsigned s_audio_evt;
static int snk_audio_event(unsigned limit) {
    unsigned n = __atomic_add_fetch(&s_audio_evt, 1u, __ATOMIC_RELAXED);
    return n <= limit || n % 500u == 0;
}

/* SDK AppendWaveBuffer (0x227460) copies this 0x30-byte public layout.
 * Start/end offsets count interleaved frames, and the end is exclusive. */
struct snk_audio_wave_buffer {
    const int16_t *data;
    uint64_t bytes;
    uint32_t start;
    uint32_t end;
    uint8_t looping;
    uint8_t end_of_stream;
    uint8_t padding[6];
    const void *context;
    uint64_t context_bytes;
};

#define SNK_AUDIO_WAVE_SLOTS 4u
#define SNK_AUDIO_SOURCE_CHANNELS 6u
#define SNK_AUDIO_MIX_BUFFERS 24u
struct snk_audio_wave {
    const void *object;
    struct snk_audio_wave_buffer buffer;
};

struct snk_audio_voice {
    uint64_t magic;
    const void *key;
    uint32_t sample_format;
    uint32_t mix_rate;
    uint32_t mix_src_channels;
    uint32_t play_state;       /* SDK enum: 0 play, 1 stop, 2 pause */
    float mix_volume;
    float mix_pitch;
    float mix_matrix[SNK_AUDIO_SOURCE_CHANNELS][SNK_AUDIO_MIX_BUFFERS];
    int mix_matrix_set;
    unsigned diagnostic_id;
    unsigned diagnostic_appends;
    uint32_t diagnostic_matrix_seen[SNK_AUDIO_SOURCE_CHANNELS];
    uint32_t diagnostic_matrix_nonzero[SNK_AUDIO_SOURCE_CHANNELS];
    unsigned diagnostic_blocks;
    unsigned diagnostic_destinations;
    const void *mix_destination;
    int diagnostic_nonzero;
    double mix_position;      /* source-frame offset within the current wave */
    double mix_samples;       /* consumed source frames, unchanged by append */
    struct snk_audio_wave waves[SNK_AUDIO_WAVE_SLOTS];
    uint64_t wave_read;        /* returned to the title */
    uint64_t wave_play;        /* processed, eligible for GetReleased */
    uint64_t wave_write;       /* accepted by AppendWaveBuffer */
};

#define SNK_AUDIO_VOICE_MAGIC 0x534e4b4155564f58ull
/* Slots stay at fixed addresses while acquired. ReleaseVoiceSlot makes the
 * same entry available for a subsequent voice. */
#define SNK_AUDIO_VOICE_SLOT_COUNT 1024

static struct snk_audio_voice s_audio_voices[SNK_AUDIO_VOICE_SLOT_COUNT];
static unsigned s_audio_voice_serial;

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
    if (!voice_out || channel <= 0 || mixer_index <= 0 ||
        mixer_index > (int)SNK_AUDIO_SOURCE_CHANNELS) return 0;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_out);
    for (size_t i = 0; voice == NULL && i < SNK_AUDIO_VOICE_SLOT_COUNT; i++) {
        if (s_audio_voices[i].magic != SNK_AUDIO_VOICE_MAGIC) {
            memset(&s_audio_voices[i], 0, sizeof(s_audio_voices[i]));
            s_audio_voices[i].magic = SNK_AUDIO_VOICE_MAGIC;
            s_audio_voices[i].key = voice_out;
            s_audio_voices[i].diagnostic_id = ++s_audio_voice_serial;
            s_audio_voices[i].sample_format = (uint32_t)sample_format;
            s_audio_voices[i].mix_rate = (uint32_t)channel;
            s_audio_voices[i].mix_src_channels = mixer_index > 0 ? (uint32_t)mixer_index : 1u;
            s_audio_voices[i].mix_volume = 1.0f;
            s_audio_voices[i].mix_pitch = 1.0f;
            s_audio_voices[i].play_state = 1u;
            voice = &s_audio_voices[i];
            break;
        }
    }
    pthread_mutex_unlock(&s_audio_lock);
    if (!voice) {
        fprintf(stderr, "[snk-media] AcquireVoiceSlot: no free voice slot\n");
        return 0;
    }
    fprintf(stderr, "[audio-voice] acquire id=%u key=%p rate=%d channels=%d format=%d\n",
            voice->diagnostic_id, voice_out, channel, mixer_index, sample_format);
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
/* audren mixer (enabled by default; snk-audio-mix=0 disables it)  */
/* ====================================================================== */
/* The title builds its audio graph through nn::audio::AudioRenderer. The
 * renderer service is what mixes; this port has never had one, so every voice
 * knob was a no-op and no PCM ever reached the output. The mixing is done here
 * from the voice objects this HLE hands out: the title never looks inside them,
 * it only passes the pointer back, so the play head can live in the slot.
 *
 * Enabled for normal installs. An explicit snk-audio-mix=0 marker keeps
 * the diagnostic native-SDK comparison path available. */
#define SNK_MIX_RING 6
static struct {
    int state;                 /* 0 unprobed, 1 on, -1 off */
    int opened;
    void *key;
    uint8_t buffer[64];
    float *pcm;
    uint32_t frames;
    uint32_t capacity_bytes;
    uint32_t rate;
    uint32_t channels;
    uint64_t updates;
    int pending_output;
    int pending_slot;
} s_mix;
/* s_mix_mixed_peak is declared above with the voice handshake state. */
static uint64_t (*s_mix_open)(void *, void *, const void *);
static uint64_t (*s_mix_start)(void *);
static uint64_t (*s_mix_append)(void *, void *);
static void *(*s_mix_released)(void *);

typedef struct { void *next, *data; uint64_t capacity, bytes, offset; } snk_mix_buffer;
static snk_mix_buffer s_mix_buffers[SNK_MIX_RING];
static int s_mix_buffer_used[SNK_MIX_RING];

static int snk_mix_probe(void);
void snk_audio_mixer_update(void);

/* v1.0.7 SDK CopyMemoryPoolData (0x225730) forwards dst/src/bytes to
 * memcpy after checking the pool. Host audio pools use directly mapped PCM. */
static void snk_audio_copy_pool_data(const void *pool, void *dst, const void *src,
                                     size_t bytes) {
    (void)pool;
    if (bytes) memcpy(dst, src, bytes);
}

uint64_t snk_audio_v_append_wave(void *voice_obj, const void *wave_buffer) {
    if (!wave_buffer) return 0;
    struct snk_audio_wave_buffer buffer;
    memcpy(&buffer, wave_buffer, sizeof buffer);
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    if (!voice || voice->wave_write - voice->wave_read == SNK_AUDIO_WAVE_SLOTS) {
        pthread_mutex_unlock(&s_audio_lock);
        return 0;
    }
    uint32_t channels = voice->mix_src_channels;
    if (!buffer.data || !channels || buffer.start >= buffer.end ||
        buffer.end > buffer.bytes / (sizeof(int16_t) * (uint64_t)channels)) {
        pthread_mutex_unlock(&s_audio_lock);
        return 0;
    }
    struct snk_audio_wave *wave = &voice->waves[voice->wave_write % SNK_AUDIO_WAVE_SLOTS];
    *wave = (struct snk_audio_wave){.object = wave_buffer, .buffer = buffer};
    if (voice->wave_play == voice->wave_write) voice->mix_position = buffer.start;
    ++voice->wave_write;
    if (voice->diagnostic_appends++ < 2u) {
        uint64_t scan_frames = buffer.end - buffer.start;
        if (scan_frames > 48000u) scan_frames = 48000u;
        unsigned peak = 0;
        for (uint64_t sample = 0; sample < scan_frames * channels; ++sample) {
            int value = buffer.data[(uint64_t)buffer.start * channels + sample];
            unsigned magnitude = (unsigned)(value < 0 ? -value : value);
            if (magnitude > peak) peak = magnitude;
        }
        fprintf(stderr, "[audio-voice] append id=%u key=%p data=%p start=%u end=%u queued=%llu state=%u source_peak=%u scanned_frames=%llu\n",
                voice->diagnostic_id, voice_obj, (const void *)buffer.data, buffer.start, buffer.end,
                (unsigned long long)(voice->wave_write - voice->wave_play), voice->play_state,
                peak, (unsigned long long)scan_frames);
    }
    pthread_mutex_unlock(&s_audio_lock);
    return 1;
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
    struct timespec deadline;
    clock_gettime(CLOCK_MONOTONIC, &deadline);
    for (;;) {
        snk_audio_mixer_update();
        uint64_t period_ns = s_mix.rate ? (uint64_t)s_mix.frames * 1000000000ull / s_mix.rate : 16000000ull;
        deadline.tv_nsec += (long)period_ns;
        deadline.tv_sec += deadline.tv_nsec / 1000000000l;
        deadline.tv_nsec %= 1000000000l;
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        int64_t wait_ns = (int64_t)(deadline.tv_sec - now.tv_sec) * 1000000000ll +
                          deadline.tv_nsec - now.tv_nsec;
        if (wait_ns > 0) {
            struct timespec wait = {(time_t)(wait_ns / 1000000000ll), (long)(wait_ns % 1000000000ll)};
            while (nanosleep(&wait, &wait) && errno == EINTR) {}
        } else if (wait_ns < -(int64_t)(period_ns * SNK_MIX_RING)) {
            deadline = now;
        }
    }
    return NULL;
}
static int s_mix_thread_started;
static void snk_audio_mixer_start_thread(void) {
    pthread_mutex_lock(&s_audio_lock);
    if (!s_mix_thread_started) {
        pthread_t thread;
        if (pthread_create(&thread, NULL, snk_audio_mixer_thread, NULL))
            fprintf(stderr, "[audio] audren mixer thread could not start\n");
        else {
            s_mix_thread_started = 1;
            pthread_detach(thread);
            fprintf(stderr, "[audio] audren mixer thread started\n");
        }
    }
    pthread_mutex_unlock(&s_audio_lock);
}

uint64_t snk_audio_v_play_state(void *voice_obj, uint32_t play_state) {
    if (play_state > 2u) return 0;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    if (voice) {
        voice->play_state = play_state;
        if (play_state == 1u) {
            voice->mix_samples = 0;
            voice->mix_position = 0;
            voice->wave_play = voice->wave_write;
        }
        if (snk_audio_event(60))
            fprintf(stderr, "[audio] PlayState key=%p state=%u queued=%llu\n", voice_obj, play_state,
                    (unsigned long long)(voice->wave_write - voice->wave_play));
    }
    pthread_mutex_unlock(&s_audio_lock);
    if (voice && play_state == 0u) snk_audio_mixer_start_thread();
    return 0;
}

uint64_t snk_audio_v_flush(void *voice_obj) {
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    if (voice) {
        /* Flushed entries remain owned until GetReleasedWaveBuffer returns
         * them, just like processed entries in the SDK's four-slot queue. */
        voice->wave_play = voice->wave_write;
        voice->mix_position = 0;
    }
    pthread_mutex_unlock(&s_audio_lock);
    return 0;
}

static void snk_audio_release_voice(void *config, void *voice_obj) {
    (void)config;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    if (voice) memset(voice, 0, sizeof *voice);
    pthread_mutex_unlock(&s_audio_lock);
}

uint64_t snk_audio_v_volume(void *voice_obj, float volume) {
    if (!(volume >= 0.0f && volume <= 8.0f)) return 0;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    if (voice) voice->mix_volume = volume;
    pthread_mutex_unlock(&s_audio_lock);
    return 0;
}

/* SDK 0x227170/0x227200 index a separate row for sourceChannel and a
 * separate gain for destination mixBuffer. Off-diagonal zeros do not mute
 * another channel's nonzero routing. The public float lives in v0. */
static void snk_audio_v_mix_volume(void *voice_obj, const void *destination,
                                   float gain, int source_channel, int mix_buffer) {
    if (source_channel < 0 || source_channel >= (int)SNK_AUDIO_SOURCE_CHANNELS ||
        mix_buffer < 0 || mix_buffer >= (int)SNK_AUDIO_MIX_BUFFERS ||
        !(gain >= -8.0f && gain <= 8.0f)) return;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    if (voice && (unsigned)source_channel < voice->mix_src_channels) {
        voice->mix_matrix_set = 1;
        voice->mix_matrix[source_channel][mix_buffer] = gain;
        uint32_t bit = UINT32_C(1) << mix_buffer;
        int first = !(voice->diagnostic_matrix_seen[source_channel] & bit);
        int first_nonzero = gain != 0.0f && !(voice->diagnostic_matrix_nonzero[source_channel] & bit);
        if (first || first_nonzero)
            fprintf(stderr, "[audio-voice] matrix id=%u key=%p destination=%p source=%d buffer=%d gain=%g\n",
                    voice->diagnostic_id, voice_obj, destination, source_channel, mix_buffer, gain);
        voice->diagnostic_matrix_seen[source_channel] |= bit;
        if (gain != 0.0f) voice->diagnostic_matrix_nonzero[source_channel] |= bit;
    }
    pthread_mutex_unlock(&s_audio_lock);
}

static uint64_t snk_audio_v_valid(const void *voice_obj) {
    pthread_mutex_lock(&s_audio_lock);
    int valid = snk_voice_find(voice_obj) != NULL;
    pthread_mutex_unlock(&s_audio_lock);
    return (uint64_t)valid;
}

uint64_t snk_audio_v_pitch(void *voice_obj, float pitch) {
    if (!(pitch > 0.0f && pitch <= 8.0f)) return 0;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    if (voice) voice->mix_pitch = pitch;
    pthread_mutex_unlock(&s_audio_lock);
    return 0;
}

uint64_t snk_audio_v_played(const void *voice_obj) {
    pthread_mutex_lock(&s_audio_lock);
    const struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    uint64_t samples = voice ? (uint64_t)voice->mix_samples : 0;
    pthread_mutex_unlock(&s_audio_lock);
    return samples;
}

/* The graph helpers that only have to say "yes": the pointer they are handed is
 * already the object this module handed out. */
uint64_t snk_audio_set_destination(void *config, void *voice_obj, void *dest) {
    (void)config;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    if (voice) {
        voice->mix_destination = dest;
        if (voice->diagnostic_destinations++ < 4u)
            fprintf(stderr, "[audio-voice] destination id=%u key=%p destination=%p\n",
                    voice->diagnostic_id, voice_obj, dest);
    }
    pthread_mutex_unlock(&s_audio_lock);
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

/* Graph diagnostics use the supplied SDK's public object addresses and ABI.
 * Getters retain acquired metadata. PCM still uses the existing voice mixer. */
#define SNK_GRAPH_TRACE_LIMIT 4096u
#define SNK_GRAPH_TRACE_ROUTES 1024u
#define SNK_GRAPH_TRACE_PARAMETERS 32u
struct snk_audio_splitter_branch {
    const void *destination;
    float matrix[SNK_AUDIO_MIX_BUFFERS][SNK_AUDIO_MIX_BUFFERS];
};
struct snk_graph_trace_node {
    const void *key;
    const char *kind;
    const void *destination;
    unsigned id;
    uint64_t acquired_order;
    int sample_rate;
    int buffers;
    int branches;
    int enabled;
    float volume;
    unsigned volume_logs;
    unsigned destination_logs;
    unsigned enabled_logs;
    unsigned io_logs;
    int io_count;
    int8_t inputs[6], outputs[6];
    float matrix[SNK_AUDIO_MIX_BUFFERS][SNK_AUDIO_MIX_BUFFERS];
    struct snk_audio_splitter_branch *splitter_branches;
    float *mix_pcm;
    size_t mix_capacity;
    struct ffrs_sdk_compressor_parameter compressor_parameter;
    struct ffrs_sdk_compressor_state compressor_state;
    int compressor_initialized;
    unsigned compressor_blocks;
    int compressor_nonzero;
    unsigned compressor_input_peak, compressor_output_peak;
    uint32_t parameters_set;
    double parameters[SNK_GRAPH_TRACE_PARAMETERS];
    unsigned parameter_logs[SNK_GRAPH_TRACE_PARAMETERS];
    uint32_t matrix_seen[SNK_AUDIO_MIX_BUFFERS];
    uint32_t matrix_nonzero[SNK_AUDIO_MIX_BUFFERS];
};
struct snk_graph_trace_route {
    const void *source;
    const void *destination;
    int branch;
    int source_buffer;
    int destination_buffer;
    float gain;
    unsigned logs;
};
static struct snk_graph_trace_node s_graph_trace[SNK_AUDIO_OBJECT_SLOTS];
static struct snk_graph_trace_route s_graph_trace_routes[SNK_GRAPH_TRACE_ROUTES];
static unsigned s_graph_trace_nodes, s_graph_trace_lines;
static unsigned s_graph_trace_route_count, s_graph_trace_snapshots;
static uint64_t s_graph_acquired_order, s_graph_generation;
static unsigned s_graph_device_volume_logs, s_graph_audio_out_volume_logs;
static float s_graph_device_volume, s_graph_audio_out_volume;
static const void *s_graph_audio_out_key;
static char s_graph_device_name[65];

enum snk_graph_parameter {
    SNK_GRAPH_THRESHOLD, SNK_GRAPH_RATIO, SNK_GRAPH_ATTACK_NS, SNK_GRAPH_RELEASE_NS,
    SNK_GRAPH_OUT_GAIN, SNK_GRAPH_PARAMETER_FLAG, SNK_GRAPH_DRY_GAIN,
    SNK_GRAPH_IN_GAIN, SNK_GRAPH_FEEDBACK_GAIN, SNK_GRAPH_DELAY_NS,
    SNK_GRAPH_ROOM_GAIN, SNK_GRAPH_ROOM_HF_GAIN, SNK_GRAPH_HF_REFERENCE,
    SNK_GRAPH_DECAY_NS, SNK_GRAPH_DECAY_HF_RATIO, SNK_GRAPH_REFLECTIONS_GAIN,
    SNK_GRAPH_REFLECTION_NS, SNK_GRAPH_REVERB_GAIN, SNK_GRAPH_REVERB_NS,
    SNK_GRAPH_DIFFUSION, SNK_GRAPH_DENSITY,
    SNK_GRAPH_B0, SNK_GRAPH_B1, SNK_GRAPH_B2, SNK_GRAPH_A1, SNK_GRAPH_A2
};
static const char *const s_graph_parameter_names[] = {
    "threshold", "ratio", "attack_ns", "release_ns", "out_gain", "parameter_flag",
    "dry_gain", "in_gain", "feedback_gain", "delay_ns", "room_gain", "room_hf_gain",
    "hf_reference", "decay_ns", "decay_hf_ratio", "reflections_gain", "reflection_ns",
    "reverb_gain", "reverb_ns", "diffusion", "density", "b0", "b1", "b2", "a1", "a2"
};

/* Caller holds s_audio_lock. */
static struct snk_graph_trace_node *snk_graph_trace_find(const void *key) {
    if (!key) return NULL;
    for (unsigned i = 0; i < s_graph_trace_nodes; ++i)
        if (s_graph_trace[i].key == key) return &s_graph_trace[i];
    return NULL;
}

/* A branch of -1 describes a direct SubMix edge. Buffer indices of -1
 * describe the branch destination, independently of its channel gains. */
static struct snk_graph_trace_route *snk_graph_trace_route(const void *source,
        int branch, int source_buffer, int destination_buffer) {
    if (!source) return NULL;
    for (unsigned i = 0; i < s_graph_trace_route_count; ++i) {
        struct snk_graph_trace_route *route = &s_graph_trace_routes[i];
        if (route->source == source && route->branch == branch &&
            route->source_buffer == source_buffer && route->destination_buffer == destination_buffer)
            return route;
    }
    if (s_graph_trace_route_count == SNK_GRAPH_TRACE_ROUTES) return NULL;
    struct snk_graph_trace_route *route = &s_graph_trace_routes[s_graph_trace_route_count++];
    route->source = source;
    route->branch = branch;
    route->source_buffer = source_buffer;
    route->destination_buffer = destination_buffer;
    return route;
}

/* Matrix setters ignore their destination wrapper in the original SDK.
 * Resolve the current destination from the corresponding destination setter. */
static const void *snk_graph_trace_route_destination(const struct snk_graph_trace_route *route) {
    if (route->branch < 0) {
        const struct snk_graph_trace_node *node = snk_graph_trace_find(route->source);
        return node ? node->destination : NULL;
    }
    for (unsigned i = 0; i < s_graph_trace_route_count; ++i) {
        const struct snk_graph_trace_route *destination = &s_graph_trace_routes[i];
        if (destination->source == route->source && destination->branch == route->branch &&
            destination->source_buffer == -1 && destination->destination_buffer == -1)
            return destination->destination;
    }
    return NULL;
}

static int snk_graph_trace_line(void) {
    if (s_graph_trace_lines >= SNK_GRAPH_TRACE_LIMIT) return 0;
    ++s_graph_trace_lines;
    if (s_graph_trace_lines == SNK_GRAPH_TRACE_LIMIT)
        fprintf(stderr, "[audio-graph] trace limit reached lines=%u\n", s_graph_trace_lines);
    return 1;
}

static void snk_graph_trace_acquired(const char *kind, const void *key, int rate, int buffers) {
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(key);
    if (!node) {
        for (unsigned i = 0; i < s_graph_trace_nodes; ++i)
            if (!s_graph_trace[i].key) { node = &s_graph_trace[i]; break; }
    }
    if (!node && s_graph_trace_nodes < SNK_AUDIO_OBJECT_SLOTS)
        node = &s_graph_trace[s_graph_trace_nodes++];
    if (node) {
        unsigned id = (unsigned)(node - s_graph_trace) + 1u;
        free(node->mix_pcm);
        free(node->splitter_branches);
        memset(node, 0, sizeof *node);
        node->key = key; node->kind = kind; node->id = id; node->buffers = buffers;
        node->sample_rate = rate;
        node->acquired_order = ++s_graph_acquired_order;
        ++s_graph_generation;
        node->volume = 1.0f;
        node->enabled = -1;
        for (unsigned i = 0; i < s_graph_trace_route_count; ++i)
            if (s_graph_trace_routes[i].source == key) {
                s_graph_trace_routes[i].destination = NULL;
                s_graph_trace_routes[i].gain = 0.0f;
                s_graph_trace_routes[i].logs = 0;
            }
        if (snk_graph_trace_line())
            fprintf(stderr, "[audio-graph] acquire kind=%s id=%u key=%p rate=%d buffers=%d\n",
                    kind, id, key, rate, buffers);
    }
    pthread_mutex_unlock(&s_audio_lock);
}

static uint64_t snk_audio_trace_submix_acquire(void *config, void *out, int rate, int buffers) {
    uint64_t result = snk_audio_acquire_object(config, out, NULL, NULL);
    if (result) snk_graph_trace_acquired("submix", out, rate, buffers);
    return result;
}

static uint64_t snk_audio_trace_finalmix_acquire(void *config, void *out, int buffers) {
    uint64_t result = snk_audio_acquire_object(config, out, NULL, NULL);
    if (result) snk_graph_trace_acquired("finalmix", out, 0, buffers);
    return result;
}

/* SDK GetSubMixBufferCount/ GetFinalMixBufferCount read the Acquire count
 * at internal object +8. The public wrapper address remains the lookup key. */
static uint64_t snk_audio_mix_buffer_count(const void *key) {
    pthread_mutex_lock(&s_audio_lock);
    const struct snk_graph_trace_node *node = snk_graph_trace_find(key);
    uint64_t buffers = node ? (uint32_t)node->buffers : 0;
    pthread_mutex_unlock(&s_audio_lock);
    return buffers;
}

static void snk_audio_trace_mix_release(void *config, void *key) {
    (void)config;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(key);
    if (node) {
        if (snk_graph_trace_line())
            fprintf(stderr, "[audio-graph] release kind=%s id=%u key=%p\n", node->kind, node->id, key);
        node->key = NULL;
        node->buffers = 0;
        free(node->mix_pcm);
        node->mix_pcm = NULL;
        node->mix_capacity = 0;
        free(node->splitter_branches);
        node->splitter_branches = NULL;
        ++s_graph_generation;
    }
    pthread_mutex_unlock(&s_audio_lock);
}

static void snk_audio_trace_mix_volume(void *key, float volume) {
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(key);
    if (node) node->volume = volume;
    if ((!node || node->volume_logs++ < 8u) && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] volume kind=%s id=%u key=%p gain=%g\n",
                node ? node->kind : "unknown", node ? node->id : 0, key, volume);
    pthread_mutex_unlock(&s_audio_lock);
}

static void snk_audio_trace_mix_destination(void *config, void *source, void *destination) {
    (void)config;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *from = snk_graph_trace_find(source);
    struct snk_graph_trace_node *to = snk_graph_trace_find(destination);
    if (from) {
        from->destination = destination;
        ++s_graph_generation;
    }
    if ((!from || from->destination_logs++ < 4u) && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] destination source=%p source_kind=%s source_id=%u destination=%p destination_kind=%s destination_id=%u\n",
                source, from ? from->kind : "unknown", from ? from->id : 0,
                destination, to ? to->kind : "unknown", to ? to->id : 0);
    pthread_mutex_unlock(&s_audio_lock);
}

static void snk_audio_trace_mix_clear(void *config, void *source) {
    snk_audio_trace_mix_destination(config, source, NULL);
}

static void snk_audio_trace_mix_matrix(void *source, void *destination, float gain,
                                      int source_buffer, int destination_buffer) {
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *from = snk_graph_trace_find(source);
    struct snk_graph_trace_route *route = snk_graph_trace_route(source, -1, source_buffer, destination_buffer);
    if (route) { route->destination = destination; route->gain = gain; }
    int log = 1;
    if (from && source_buffer >= 0 && source_buffer < (int)SNK_AUDIO_MIX_BUFFERS &&
        destination_buffer >= 0 && destination_buffer < (int)SNK_AUDIO_MIX_BUFFERS) {
        from->matrix[source_buffer][destination_buffer] = gain;
        uint32_t bit = UINT32_C(1) << destination_buffer;
        log = !(from->matrix_seen[source_buffer] & bit) ||
              (gain != 0.0f && !(from->matrix_nonzero[source_buffer] & bit));
        from->matrix_seen[source_buffer] |= bit;
        if (gain != 0.0f) from->matrix_nonzero[source_buffer] |= bit;
    }
    if (log && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] matrix key=%p kind=%s id=%u destination=%p source=%d buffer=%d gain=%g\n",
                source, from ? from->kind : "unknown", from ? from->id : 0,
                destination, source_buffer, destination_buffer, gain);
    pthread_mutex_unlock(&s_audio_lock);
}

static uint64_t snk_audio_trace_sink(void *config, void *out, void *finalmix,
                                    const int8_t *channels, int count, const char *name) {
    uint64_t result = snk_audio_result_ok(config, out, NULL, NULL);
    if (!result && out) snk_graph_trace_acquired("device-sink", out, 0, count);
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(out);
    if (node) {
        node->destination = finalmix;
        node->io_count = channels && count > 0 ? (count > 6 ? 6 : count) : 0;
        for (int i = 0; i < node->io_count; ++i) {
            node->inputs[i] = channels[i];
            node->outputs[i] = (int8_t)i;
        }
        ++s_graph_generation;
    }
    if (snk_graph_trace_line()) {
        fprintf(stderr, "[audio-graph] device-sink key=%p finalmix=%p count=%d device=%.*s inputs=",
                out, finalmix, count, 64, name ? name : "(null)");
        for (int i = 0; channels && i < count && i < 6; ++i)
            fprintf(stderr, "%s%d", i ? "," : "", channels[i]);
        fprintf(stderr, " result=%llu\n", (unsigned long long)result);
    }
    pthread_mutex_unlock(&s_audio_lock);
    return result;
}

static uint64_t snk_audio_trace_sink_remove(void *config, void *sink, void *finalmix) {
    (void)finalmix;
    snk_audio_trace_mix_release(config, sink);
    return 0;
}

/* Preserve the existing output-volume stub result while capturing the
 * requested scalars. The transport still receives the same PCM bytes. */
static uint64_t snk_audio_trace_audio_out_volume(void *key, float gain) {
    pthread_mutex_lock(&s_audio_lock);
    s_graph_audio_out_key = key;
    s_graph_audio_out_volume = gain;
    if (s_graph_audio_out_volume_logs++ < 32u && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] output-volume api=AudioOut key=%p gain=%g\n", key, gain);
    pthread_mutex_unlock(&s_audio_lock);
    return 0;
}

static uint64_t snk_audio_trace_device_volume(const void *name, float gain) {
    pthread_mutex_lock(&s_audio_lock);
    snprintf(s_graph_device_name, sizeof s_graph_device_name, "%.*s", 64,
             name ? (const char *)name : "(null)");
    s_graph_device_volume = gain;
    if (s_graph_device_volume_logs++ < 32u && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] output-volume api=AudioDevice name=%s gain=%g\n",
                s_graph_device_name, gain);
    pthread_mutex_unlock(&s_audio_lock);
    return 0;
}

/* SDK 0x225b30 passes rate, channel count and destination count to
 * SplitterInfoManager. A branch has its own destination and channel matrix. */
static uint64_t snk_audio_trace_splitter_acquire(void *config, void *out,
                                               int rate, int channels, int branches) {
    uint64_t result = snk_audio_acquire_object(config, out, NULL, NULL);
    if (!result) return result;
    snk_graph_trace_acquired("splitter", out, rate, channels);
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(out);
    if (node) {
        node->branches = branches;
        if (branches > 0 && (size_t)branches <= SIZE_MAX / sizeof *node->splitter_branches)
            node->splitter_branches = calloc((size_t)branches, sizeof *node->splitter_branches);
    }
    if (snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] splitter key=%p rate=%d channels=%d branches=%d\n",
                out, rate, channels, branches);
    pthread_mutex_unlock(&s_audio_lock);
    return result;
}

static void snk_audio_trace_splitter_destination(void *config, void *source,
                                                int branch, void *destination) {
    (void)config;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_route *route = snk_graph_trace_route(source, branch, -1, -1);
    if (route) route->destination = destination;
    struct snk_graph_trace_node *node = snk_graph_trace_find(source);
    if (node && node->splitter_branches && branch >= 0 && branch < node->branches) {
        node->splitter_branches[branch].destination = destination;
        ++s_graph_generation;
    }
    if ((!route || route->logs++ < 8u) && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] splitter-destination key=%p branch=%d destination=%p\n",
                source, branch, destination);
    pthread_mutex_unlock(&s_audio_lock);
}

static void snk_audio_trace_splitter_clear(void *config, void *source, int branch) {
    snk_audio_trace_splitter_destination(config, source, branch, NULL);
}

/* SDK 0x225dc0/0x225e50 uses x0, w1, s0, w3, w4. The destination
 * wrapper in x2 identifies the API overload, while w1 selects the branch. */
static void snk_audio_trace_splitter_matrix(void *source, int branch, void *destination,
                                           float gain, int source_buffer, int destination_buffer) {
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_route *route = snk_graph_trace_route(source, branch, source_buffer, destination_buffer);
    if (route) { route->destination = destination; route->gain = gain; }
    struct snk_graph_trace_node *node = snk_graph_trace_find(source);
    if (node && node->splitter_branches && branch >= 0 && branch < node->branches &&
        source_buffer >= 0 && source_buffer < (int)SNK_AUDIO_MIX_BUFFERS &&
        destination_buffer >= 0 && destination_buffer < (int)SNK_AUDIO_MIX_BUFFERS)
        node->splitter_branches[branch].matrix[source_buffer][destination_buffer] = gain;
    if ((!route || route->logs++ < 4u) && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] splitter-matrix key=%p branch=%d destination=%p source=%d buffer=%d gain=%g\n",
                source, branch, destination, source_buffer, destination_buffer, gain);
    pthread_mutex_unlock(&s_audio_lock);
}

static void snk_graph_trace_effect_added(const char *kind, void *key, void *mix, int channels) {
    snk_graph_trace_acquired(kind, key, 0, channels);
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(key);
    if (node) {
        node->destination = mix;
        /* SDK AddCompressor 0x2214ec, AddBiquadFilter 0x220044,
         * AddDelay 0x222220 and AddI3dl2Reverb 0x222e00 start enabled.
         * IsCompressorEnabled 0x221b50 reads this flag. */
        node->enabled = 1;
        if (!strcmp(kind, "compressor")) node->io_count = channels > 6 ? 6 : (channels > 0 ? channels : 0);
    }
    if (snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] effect key=%p kind=%s mix=%p channels=%d\n", key, kind, mix, channels);
    pthread_mutex_unlock(&s_audio_lock);
}

static uint64_t snk_audio_trace_compressor_add(void *config, void *out, void *mix, int channels) {
    uint64_t result = snk_audio_result_ok(config, out, NULL, NULL);
    if (!result && out) snk_graph_trace_effect_added("compressor", out, mix, channels);
    return result;
}

static uint64_t snk_audio_trace_biquad_add(void *config, void *out, void *mix) {
    uint64_t result = snk_audio_result_ok(config, out, NULL, NULL);
    if (!result && out) snk_graph_trace_effect_added("biquad", out, mix, 0);
    return result;
}

static uint64_t snk_audio_trace_reverb_add(void *config, void *out, void *work,
                                         size_t bytes, void *mix, int channels) {
    (void)work; (void)bytes;
    uint64_t result = snk_audio_result_ok(config, out, NULL, NULL);
    if (!result && out) snk_graph_trace_effect_added("i3dl2-reverb", out, mix, channels);
    return result;
}

static uint64_t snk_audio_trace_delay_add(void *config, void *out, void *work,
        size_t bytes, void *mix, int64_t maximum_delay_ns, int channels) {
    (void)work; (void)bytes; (void)maximum_delay_ns;
    uint64_t result = snk_audio_result_ok(config, out, NULL, NULL);
    if (!result && out) snk_graph_trace_effect_added("delay", out, mix, channels);
    return result;
}

static uint64_t snk_audio_trace_effect_remove(void *config, void *key, void *mix) {
    (void)mix;
    snk_audio_trace_mix_release(config, key);
    return 0;
}

static void snk_audio_trace_effect_enabled(void *key, bool enabled) {
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(key);
    if (node) node->enabled = enabled;
    if ((!node || node->enabled_logs++ < 8u) && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] enabled key=%p kind=%s value=%d\n",
                key, node ? node->kind : "unknown", enabled);
    pthread_mutex_unlock(&s_audio_lock);
}

static uint64_t snk_audio_trace_compressor_enabled(const void *key) {
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(key);
    uint64_t enabled = node && node->enabled == 1;
    pthread_mutex_unlock(&s_audio_lock);
    return enabled;
}

static void snk_audio_trace_effect_io(void *key, const int8_t *inputs, const int8_t *outputs, int count) {
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(key);
    int copied = count > 6 ? 6 : count;
    if (copied < 0 || !inputs || !outputs) copied = 0;
    if (node) {
        node->io_count = copied;
        if (copied) {
            memcpy(node->inputs, inputs, (size_t)copied);
            memcpy(node->outputs, outputs, (size_t)copied);
        }
    }
    if ((!node || node->io_logs++ < 8u) && snk_graph_trace_line()) {
        fprintf(stderr, "[audio-graph] effect-io key=%p kind=%s count=%d routes=", key,
                node ? node->kind : "unknown", count);
        for (int i = 0; i < copied; ++i)
            fprintf(stderr, "%s%d>%d", i ? "," : "", inputs[i], outputs[i]);
        fputc('\n', stderr);
    }
    pthread_mutex_unlock(&s_audio_lock);
}

static void snk_audio_trace_parameter(void *key, unsigned parameter, double value) {
    if (parameter >= sizeof s_graph_parameter_names / sizeof s_graph_parameter_names[0]) return;
    pthread_mutex_lock(&s_audio_lock);
    struct snk_graph_trace_node *node = snk_graph_trace_find(key);
    if (node) {
        node->parameters[parameter] = value;
        node->parameters_set |= UINT32_C(1) << parameter;
    }
    if ((!node || node->parameter_logs[parameter]++ < 4u) && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] parameter key=%p kind=%s name=%s value=%.9g\n",
                key, node ? node->kind : "unknown", s_graph_parameter_names[parameter], value);
    pthread_mutex_unlock(&s_audio_lock);
}

static void snk_audio_trace_threshold(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_THRESHOLD, value);
}
static void snk_audio_trace_ratio(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_RATIO, value);
}
static void snk_audio_trace_attack(void *key, int64_t value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_ATTACK_NS, (double)value);
}
static void snk_audio_trace_release(void *key, int64_t value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_RELEASE_NS, (double)value);
}
static void snk_audio_trace_out_gain(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_OUT_GAIN, value);
}
static void snk_audio_trace_dry_gain(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_DRY_GAIN, value);
}
static void snk_audio_trace_in_gain(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_IN_GAIN, value);
}
static void snk_audio_trace_feedback_gain(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_FEEDBACK_GAIN, value);
}
static void snk_audio_trace_delay_time(void *key, int64_t value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_DELAY_NS, (double)value);
}
static void snk_audio_trace_room_gain(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_ROOM_GAIN, value);
}
static void snk_audio_trace_room_hf_gain(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_ROOM_HF_GAIN, value);
}
static void snk_audio_trace_hf_reference(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_HF_REFERENCE, value);
}
static void snk_audio_trace_decay_time(void *key, int64_t value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_DECAY_NS, (double)value);
}
static void snk_audio_trace_decay_hf_ratio(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_DECAY_HF_RATIO, value);
}
static void snk_audio_trace_reflections_gain(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_REFLECTIONS_GAIN, value);
}
static void snk_audio_trace_reflection_time(void *key, int64_t value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_REFLECTION_NS, (double)value);
}
static void snk_audio_trace_reverb_gain(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_REVERB_GAIN, value);
}
static void snk_audio_trace_reverb_time(void *key, int64_t value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_REVERB_NS, (double)value);
}
static void snk_audio_trace_diffusion(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_DIFFUSION, value);
}
static void snk_audio_trace_density(void *key, float value) {
    snk_audio_trace_parameter(key, SNK_GRAPH_DENSITY, value);
}

/* SDK 0x221c80 reads floats at 0/4/24, TimeSpan at 8/16, and a flag at 28. */
static void snk_audio_trace_compressor_parameters(void *key, const void *parameters) {
    if (!parameters) return;
    const unsigned char *bytes = parameters;
    float threshold, ratio, gain;
    int64_t attack, release;
    memcpy(&threshold, bytes, sizeof threshold);
    memcpy(&ratio, bytes + 4, sizeof ratio);
    memcpy(&attack, bytes + 8, sizeof attack);
    memcpy(&release, bytes + 16, sizeof release);
    memcpy(&gain, bytes + 24, sizeof gain);
    snk_audio_trace_threshold(key, threshold);
    snk_audio_trace_ratio(key, ratio);
    snk_audio_trace_attack(key, attack);
    snk_audio_trace_release(key, release);
    snk_audio_trace_out_gain(key, gain);
    snk_audio_trace_parameter(key, SNK_GRAPH_PARAMETER_FLAG, bytes[28]);
}

/* SDK 0x220420 converts the five signed Q14 coefficients at +2..+10. */
static void snk_audio_trace_biquad_parameters(void *key, const void *parameters) {
    if (!parameters) return;
    const unsigned char *bytes = parameters;
    snk_audio_trace_effect_enabled(key, (bytes[0] & 1u) != 0);
    for (unsigned i = 0; i < 5; ++i) {
        int16_t coefficient;
        memcpy(&coefficient, bytes + 2 + i * 2, sizeof coefficient);
        snk_audio_trace_parameter(key, SNK_GRAPH_B0 + i, coefficient / 16384.0);
    }
}

/* Caller holds s_audio_lock. Current values keep updating after their initial
 * per-coordinate logs stop. At most sixteen snapshots are emitted. */
static void snk_graph_trace_snapshot(void) {
    if (s_graph_trace_snapshots >= 16u || s_graph_trace_lines >= SNK_GRAPH_TRACE_LIMIT) return;
    ++s_graph_trace_snapshots;
    if (snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] snapshot number=%u update=%llu\n",
                s_graph_trace_snapshots, (unsigned long long)s_mix.updates);
    if (s_graph_device_volume_logs && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] current-output-volume api=AudioDevice name=%s gain=%g\n",
                s_graph_device_name, s_graph_device_volume);
    if (s_graph_audio_out_volume_logs && snk_graph_trace_line())
        fprintf(stderr, "[audio-graph] current-output-volume api=AudioOut key=%p gain=%g\n",
                s_graph_audio_out_key, s_graph_audio_out_volume);
    for (unsigned i = 0; i < s_graph_trace_nodes; ++i) {
        const struct snk_graph_trace_node *node = &s_graph_trace[i];
        if (!node->key || !snk_graph_trace_line()) continue;
        fprintf(stderr, "[audio-graph] current key=%p kind=%s buffers=%d branches=%d destination=%p volume=%g enabled=%d parameters=",
                node->key, node->kind, node->buffers, node->branches, node->destination, node->volume, node->enabled);
        for (unsigned p = 0; p < sizeof s_graph_parameter_names / sizeof s_graph_parameter_names[0]; ++p)
            if (node->parameters_set & (UINT32_C(1) << p))
                fprintf(stderr, "%s=%.9g,", s_graph_parameter_names[p], node->parameters[p]);
        fprintf(stderr, " io=");
        for (int c = 0; c < node->io_count; ++c)
            fprintf(stderr, "%d>%d,", node->inputs[c], node->outputs[c]);
        fputc('\n', stderr);
    }
    for (unsigned i = 0; i < s_graph_trace_route_count; ++i) {
        const struct snk_graph_trace_route *route = &s_graph_trace_routes[i];
        const void *destination = snk_graph_trace_route_destination(route);
        if (!snk_graph_trace_find(route->source) ||
            (route->source_buffer >= 0 && !destination) ||
            (route->source_buffer >= 0 && route->gain == 0.0f) || !snk_graph_trace_line()) continue;
        fprintf(stderr, "[audio-graph] current-route key=%p branch=%d destination=%p source=%d buffer=%d gain=%g\n",
                route->source, route->branch, destination,
                route->source_buffer, route->destination_buffer, route->gain);
    }
    for (unsigned i = 0; i < SNK_AUDIO_VOICE_SLOT_COUNT; ++i) {
        const struct snk_audio_voice *voice = &s_audio_voices[i];
        if (voice->magic != SNK_AUDIO_VOICE_MAGIC || voice->play_state != 0u ||
            voice->wave_play == voice->wave_write || !snk_graph_trace_line()) continue;
        fprintf(stderr, "[audio-graph] current-voice id=%u key=%p destination=%p channels=%u volume=%g routes=",
                voice->diagnostic_id, voice->key, voice->mix_destination,
                voice->mix_src_channels, voice->mix_volume);
        for (unsigned source = 0; source < voice->mix_src_channels; ++source)
            for (unsigned buffer = 0; buffer < SNK_AUDIO_MIX_BUFFERS; ++buffer)
                if (voice->mix_matrix[source][buffer] != 0.0f)
                    fprintf(stderr, "%u>%u:%g,", source, buffer, voice->mix_matrix[source][buffer]);
        fputc('\n', stderr);
    }
}

uint64_t snk_audio_v_wave_count(const void *voice_obj) {
    pthread_mutex_lock(&s_audio_lock);
    const struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    uint64_t pending = voice ? voice->wave_write - voice->wave_play : 0;
    pthread_mutex_unlock(&s_audio_lock);
    return pending;
}

void *snk_audio_v_released(void *voice_obj) {
    pthread_mutex_lock(&s_audio_lock);
    struct snk_audio_voice *voice = snk_voice_find(voice_obj);
    void *object = NULL;
    if (voice && voice->wave_read < voice->wave_play) {
        struct snk_audio_wave *wave = &voice->waves[voice->wave_read % SNK_AUDIO_WAVE_SLOTS];
        object = (void *)wave->object;
        memset(wave, 0, sizeof *wave);
        ++voice->wave_read;
    }
    pthread_mutex_unlock(&s_audio_lock);
    return object;
}

static int snk_mix_probe(void) {
    if (s_mix.state) return s_mix.state > 0;
    const char *dir = ffrs_audio_platform_directory();
    char path[PATH_MAX];
    int n = dir ? snprintf(path, sizeof path, "%s/snk-audio-mix", dir) : -1;
    FILE *f = (n > 0 && (size_t)n < sizeof path) ? fopen(path, "rb") : NULL;
    s_mix.state = f && fgetc(f) == '0' ? -1 : 1;
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
    if (s_mix.pending_output) {
        int pending = s_mix.pending_slot;
        if (s_mix_append(s_mix.key, &s_mix_buffers[pending])) {
            s_mix_buffer_used[pending] = 1;
            s_mix.pending_output = 0;
            ++s_mix.updates;
        }
        return;
    }
    int slot = -1;
    for (int i = 0; i < SNK_MIX_RING; ++i) if (!s_mix_buffer_used[i]) { slot = i; break; }
    if (slot < 0 && s_mix_released) {
        void *back = s_mix_released(s_mix.key);
        if (back) for (int i = 0; i < SNK_MIX_RING; ++i)
            if (&s_mix_buffers[i] == back) { s_mix_buffer_used[i] = 0; slot = i; break; }
    }
    if (slot < 0) return;
    memset(s_mix.pcm, 0, (size_t)frames * channels * sizeof(float));
    unsigned audible = 0;
    pthread_mutex_lock(&s_audio_lock);
    for (size_t i = 0; i < SNK_AUDIO_VOICE_SLOT_COUNT; ++i) {
        struct snk_audio_voice *voice = &s_audio_voices[i];
        if (voice->magic != SNK_AUDIO_VOICE_MAGIC || voice->play_state != 0u ||
            voice->wave_play == voice->wave_write) continue;
        if (voice->sample_format != 2u) {
            static unsigned format_logs;
            if (format_logs++ < 4)
                fprintf(stderr, "[audio] unsupported voice format=%u\n", voice->sample_format);
            continue;
        }
        uint32_t source_channels = voice->mix_src_channels;
        double step = (double)voice->mix_pitch * voice->mix_rate / s_mix.rate;
        unsigned voice_source_peak = 0, voice_mixed_peak = 0, voice_frames = 0;
        for (uint32_t frame = 0; frame < frames && voice->wave_play < voice->wave_write; ++frame) {
            struct snk_audio_wave *wave = &voice->waves[voice->wave_play % SNK_AUDIO_WAVE_SLOTS];
            uint64_t index = (uint64_t)voice->mix_position;
            ++voice_frames;
            for (uint32_t channel = 0; channel < channels; ++channel) {
                float sample = 0.0f;
                for (uint32_t source_channel = 0; source_channel < source_channels; ++source_channel) {
                    int16_t raw = wave->buffer.data[index * source_channels + source_channel];
                    unsigned magnitude = (unsigned)(raw < 0 ? -raw : raw);
                    if (magnitude > voice_source_peak) voice_source_peak = magnitude;
                    float gain = voice->mix_matrix_set ? voice->mix_matrix[source_channel][channel] :
                                 (source_channels == 1u || source_channel == channel ? 1.0f : 0.0f);
                    sample += raw * (1.0f / 32768.0f) * gain;
                }
                sample *= voice->mix_volume;
                unsigned magnitude = (unsigned)((sample < 0.0f ? -sample : sample) * 32768.0f);
                if (magnitude > voice_mixed_peak) voice_mixed_peak = magnitude;
                s_mix.pcm[frame * channels + channel] += sample;
            }
            double advance = step;
            while (advance > 0.0 && voice->wave_play < voice->wave_write) {
                wave = &voice->waves[voice->wave_play % SNK_AUDIO_WAVE_SLOTS];
                double remaining = wave->buffer.end - voice->mix_position;
                double consumed = advance < remaining ? advance : remaining;
                voice->mix_position += consumed;
                voice->mix_samples += consumed;
                advance -= consumed;
                if (voice->mix_position >= wave->buffer.end) {
                    if (wave->buffer.looping) voice->mix_position = wave->buffer.start;
                    else {
                        if (wave->buffer.end_of_stream) voice->mix_samples = 0;
                        ++voice->wave_play;
                        if (voice->wave_play < voice->wave_write)
                            voice->mix_position = voice->waves[voice->wave_play % SNK_AUDIO_WAVE_SLOTS].buffer.start;
                    }
                }
            }
        }
        if (voice_mixed_peak > s_mix_mixed_peak) s_mix_mixed_peak = voice_mixed_peak;
        if (voice->diagnostic_blocks++ < 2u || (voice_source_peak && !voice->diagnostic_nonzero)) {
            fprintf(stderr, "[audio-voice] mix id=%u key=%p rate=%u channels=%u format=%u frames=%u source_peak=%u post_gain_peak=%u volume=%g matrix=%d pending=%llu\n",
                    voice->diagnostic_id, voice->key, voice->mix_rate, source_channels,
                    voice->sample_format, voice_frames, voice_source_peak, voice_mixed_peak,
                    voice->mix_volume, voice->mix_matrix_set,
                    (unsigned long long)(voice->wave_write - voice->wave_play));
            if (voice_source_peak) voice->diagnostic_nonzero = 1;
        }
        ++audible;
    }
    pthread_mutex_unlock(&s_audio_lock);

    int16_t *out = (int16_t *)s_mix_buffers[slot].data;
    for (size_t i = 0; i < (size_t)frames * channels; ++i) {
        float s = s_mix.pcm[i];
        if (s > 1.0f) s = 1.0f; else if (s < -1.0f) s = -1.0f;
        out[i] = (int16_t)(s * 32767.0f);
    }
    if (!s_mix_append(s_mix.key, &s_mix_buffers[slot])) {
        s_mix.pending_slot = slot;
        s_mix.pending_output = 1;
        return;
    }
    s_mix_buffer_used[slot] = 1;
    ++s_mix.updates;
    if (s_mix.updates % 300u == 1u) {
        unsigned with_data = 0, playing = 0;
        pthread_mutex_lock(&s_audio_lock);
        for (size_t i = 0; i < SNK_AUDIO_VOICE_SLOT_COUNT; ++i) {
            struct snk_audio_voice *v = &s_audio_voices[i];
            if (v->magic != SNK_AUDIO_VOICE_MAGIC) continue;
            if (v->wave_play < v->wave_write) ++with_data;
            if (v->play_state == 0u) ++playing;
        }
        if (s_mix.updates % 600u == 1u) snk_graph_trace_snapshot();
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

/* The supplied v1.0.7 SDK's DecodeOpusInterleavedImpl (0x2bc680) accepts
 * an eight-byte big-endian packet header followed by one ordinary Opus packet.
 * The first word is the payload size. Capacity is PCM bytes, consumed includes
 * the header, and decoded frames are per channel (0x2bc718-0x2bc788). */
uint64_t snk_opus_decode(void *owner, size_t *consumed, int *frames, short *output,
                         size_t output_capacity, const void *input, size_t input_size) {
    enum { INVALID_DATA = 4, INTERNAL_ERROR = 5, INSUFFICIENT_INPUT = 6,
           INSUFFICIENT_OUTPUT = 7, INVALID_STATE = 8, INVALID_PACKET = 9 };
    if (consumed) *consumed = 0;
    if (frames) *frames = 0;
    if (!input || input_size < 8u) return INSUFFICIENT_INPUT;
    const uint8_t *bytes = input;
    uint32_t packet_size = ((uint32_t)bytes[0] << 24) | ((uint32_t)bytes[1] << 16) |
                           ((uint32_t)bytes[2] << 8) | bytes[3];
    if ((size_t)packet_size > input_size - 8u) return INSUFFICIENT_INPUT;
    if (!packet_size || packet_size > INT_MAX) return INVALID_DATA;

    pthread_mutex_lock(&s_opus_lock);
    struct snk_opus_state *state = snk_opus_slot(owner, false);
    if (!state || !state->decoder) {
        pthread_mutex_unlock(&s_opus_lock);
        return INVALID_STATE;
    }
    const int channels = state->channels;
    int packet_frames = opus_packet_get_nb_samples(bytes + 8u, (opus_int32)packet_size,
                                                   state->sample_rate);
    if (packet_frames <= 0 || packet_frames > 5760) {
        pthread_mutex_unlock(&s_opus_lock);
        return INVALID_DATA;
    }
    size_t required_bytes = (size_t)packet_frames * (size_t)channels * sizeof(short);
    if (!output || output_capacity < required_bytes) {
        pthread_mutex_unlock(&s_opus_lock);
        return INSUFFICIENT_OUTPUT;
    }
    int decoded = opus_decode(state->decoder, bytes + 8u, (opus_int32)packet_size,
                               state->pcm, packet_frames, 0);
    if (decoded < 0) {
        pthread_mutex_unlock(&s_opus_lock);
        return decoded == OPUS_INTERNAL_ERROR ? INVALID_PACKET :
               decoded == OPUS_UNIMPLEMENTED ? INTERNAL_ERROR : INVALID_DATA;
    }
    size_t sample_count = (size_t)decoded * (size_t)channels;
    memcpy(output, state->pcm, sample_count * sizeof(short));
    unsigned peak = 0;
    for (size_t i = 0; i < sample_count; ++i) {
        int sample = state->pcm[i];
        unsigned magnitude = (unsigned)(sample < 0 ? -sample : sample);
        if (magnitude > peak) peak = magnitude;
    }
    pthread_mutex_unlock(&s_opus_lock);
    if (consumed) *consumed = 8u + (size_t)packet_size;
    if (frames) *frames = decoded;
    if (snk_audio_event(40))
        fprintf(stderr, "[opus] framed packet payload=%u consumed=%zu decoded=%d peak=%u capacity_bytes=%zu ch=%d\n",
                packet_size, 8u + (size_t)packet_size, decoded, peak, output_capacity, channels);
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
    int format;
    size_t stride;
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
    snk_png_find(self, true);
    fprintf(stderr, "[snk-media] PngDecoder::SetOutputPixelFormat: %d\n", format);
    return 0;
}

/* SDK 1.0.7 Analyze returns zero on success. Decode uses x2 for the
 * output capacity and x3 for row stride (sdk offsets 0x80b90/0x80e70). */
uint64_t snk_png_decoder_analyze(void *self) {
    struct snk_png_state *state = snk_png_find(self, true);
    if (!state || !state->data || state->size < 24u) return 1;
    static const unsigned char signature[8] = {0x89, 'P', 'N', 'G', 0x0d, 0x0a, 0x1a, 0x0a};
    const unsigned char *data = (const unsigned char *)state->data;
    if (memcmp(data, signature, sizeof(signature))) return 1;
    if (memcmp(data + 12, "IHDR", 4)) return 1;
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
    return 0;
}

uint64_t snk_png_decoder_decode(void *self, void *output, size_t size, size_t stride) {
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
    return snk_png_decoder_ctor(self);
}

uint64_t snk_png_encoder_dtor(void *self) {
    return snk_png_decoder_dtor(self);
}

uint64_t snk_png_encoder_initialize(void *self, void *allocator, void *allocator_context,
                                           void *deallocator, void *deallocator_context) {
    return snk_png_decoder_initialize(self, allocator, allocator_context,
                                     deallocator, deallocator_context);
}

uint64_t snk_png_encoder_set_pixel_data(void *self, const void *data, size_t size,
                                                int format, uint64_t dimension, size_t stride) {
    struct snk_png_state *state = snk_png_find(self, true);
    if (!state) return 0;
    pthread_mutex_lock(&s_png_lock);
    state->data = data;
    state->size = size;
    state->format = format;
    state->width = (uint32_t)dimension;
    state->height = (uint32_t)(dimension >> 32);
    state->stride = stride;
    pthread_mutex_unlock(&s_png_lock);
    return 0;
}

/* PixelFormat tables from SDK 1.0.7 GetBitDepth/GetChannelCount at
 * 0x81730/0x81760 and GetPngColorType at 0x80790. Formats 1..4 require
 * palette information, which SetPixelData does not supply. */
static bool snk_png_encoder_layout(const struct snk_png_state *state,
                                   size_t *row_bytes, size_t *stride, size_t *raw_size) {
    static const unsigned bits[] = {1, 2, 4, 8, 16, 8, 16, 8, 16, 8, 16};
    static const unsigned channels[] = {1, 1, 1, 1, 1, 3, 3, 2, 2, 4, 4};
    if (!state->data || !state->width || !state->height ||
        state->width > INT_MAX || state->height > INT_MAX ||
        state->format < 5 || state->format > 15) return false;
    unsigned index = (unsigned)state->format - 5u;
    uint64_t row_bits = (uint64_t)state->width * bits[index] * channels[index];
    *row_bytes = (size_t)((row_bits + 7u) / 8u);
    *stride = state->stride ? state->stride : *row_bytes;
    if (*stride < *row_bytes ||
        (size_t)(state->height - 1u) > (SIZE_MAX - *row_bytes) / *stride ||
        state->size < (size_t)(state->height - 1u) * *stride + *row_bytes ||
        *row_bytes >= UINT_MAX || state->height > UINT_MAX / (*row_bytes + 1u)) return false;
    *raw_size = (*row_bytes + 1u) * state->height;
    return true;
}

static void snk_png_write_u32(unsigned char *output, uint32_t value) {
    output[0] = (unsigned char)(value >> 24);
    output[1] = (unsigned char)(value >> 16);
    output[2] = (unsigned char)(value >> 8);
    output[3] = (unsigned char)value;
}

static size_t snk_png_write_chunk(unsigned char *output, const char *type,
                                   const unsigned char *data, uint32_t size) {
    snk_png_write_u32(output, size);
    memcpy(output + 4u, type, 4u);
    if (size) memcpy(output + 8u, data, size);
    uLong crc = crc32(0, (const Bytef *)type, 4u);
    if (size) crc = crc32(crc, data, size);
    snk_png_write_u32(output + 8u + size, (uint32_t)crc);
    return (size_t)size + 12u;
}

uint64_t snk_png_encoder_encode(void *self, size_t *size_out, void *output,
                                       size_t capacity) {
    if (size_out) *size_out = 0u;
    if (!size_out || !output) return 1;
    struct snk_png_state *state = snk_png_find(self, false);
    if (!state) return 1;
    pthread_mutex_lock(&s_png_lock);
    struct snk_png_state input = *state;
    pthread_mutex_unlock(&s_png_lock);
    size_t row_bytes, stride, raw_size;
    if (!snk_png_encoder_layout(&input, &row_bytes, &stride, &raw_size)) return 1;
    uLong bound = compressBound((uLong)raw_size);
    if (bound > UINT_MAX || bound > SIZE_MAX - 57u) return 1;
    unsigned char *raw = malloc(raw_size);
    unsigned char *compressed = malloc((size_t)bound);
    if (!raw || !compressed) {
        free(raw);
        free(compressed);
        return 2;
    }
    for (uint32_t y = 0; y < input.height; ++y) {
        unsigned char *row = raw + (size_t)y * (row_bytes + 1u);
        const unsigned char *source = (const unsigned char *)input.data + (size_t)y * stride;
        row[0] = 0; /* PNG filter None. */
        memcpy(row + 1u, source, row_bytes);
        /* The SDK requests PNG_TRANSFORM_SWAP_ENDIAN for 16-bit samples. */
        if (input.format == 9 || input.format == 11 || input.format == 13 || input.format == 15) {
            for (size_t x = 0; x < row_bytes; x += 2u) {
                row[x + 1u] = source[x + 1u];
                row[x + 2u] = source[x];
            }
        }
    }
    uLongf compressed_size = bound;
    int result = compress2(compressed, &compressed_size, raw, (uLong)raw_size, Z_DEFAULT_COMPRESSION);
    free(raw);
    if (result != Z_OK || capacity < (size_t)compressed_size + 57u) {
        free(compressed);
        return result == Z_MEM_ERROR ? 2 : 1;
    }
    static const unsigned char signature[] = {0x89, 'P', 'N', 'G', 13, 10, 26, 10};
    static const unsigned char depths[] = {1, 2, 4, 8, 16, 8, 16, 8, 16, 8, 16};
    static const unsigned char colors[] = {0, 0, 0, 0, 0, 2, 2, 4, 4, 6, 6};
    unsigned char header[13] = {0};
    snk_png_write_u32(header, input.width);
    snk_png_write_u32(header + 4u, input.height);
    header[8] = depths[input.format - 5];
    header[9] = colors[input.format - 5];
    unsigned char *destination = output;
    memcpy(destination, signature, sizeof(signature));
    size_t written = sizeof(signature);
    written += snk_png_write_chunk(destination + written, "IHDR", header, sizeof(header));
    written += snk_png_write_chunk(destination + written, "IDAT", compressed, (uint32_t)compressed_size);
    written += snk_png_write_chunk(destination + written, "IEND", NULL, 0);
    free(compressed);
    *size_out = written;
    fprintf(stderr, "[snk-media] PngEncoder::Encode: %ux%u format=%d bytes=%zu\n",
            input.width, input.height, input.format, written);
    return 0;
}

uint64_t snk_png_encoder_size_max(const void *self) {
    struct snk_png_state *state = snk_png_find((void *)self, false);
    if (!state) return 0;
    pthread_mutex_lock(&s_png_lock);
    struct snk_png_state input = *state;
    pthread_mutex_unlock(&s_png_lock);
    size_t row_bytes, stride, raw_size;
    if (!snk_png_encoder_layout(&input, &row_bytes, &stride, &raw_size)) return 0;
    uLong bound = compressBound((uLong)raw_size);
    return bound <= UINT_MAX && bound <= SIZE_MAX - 57u ? (uint64_t)bound + 57u : 0;
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
        /* The host-side mixer needs the voice calls to reach it. When it
         * is enabled the native SDK audio path is not used, because the
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
     * answer with the generic stub. With the mixer enabled these
     * names resolve here instead, so the mixer sees the wave buffers, the play
     * state and the block updates. */
    if (snk_audio_mixer_enabled()) {
        static const struct { const char *name; void *fn; unsigned gp, fp, gr; } voice[] = {
            {"_ZN2nn5audio18CopyMemoryPoolDataEPKNS0_14MemoryPoolTypeEPvPKvm", (void *)snk_audio_copy_pool_data, 4, 0, 0},
            /* Renderer graph. Every one of these answered false before, and the
             * title stops building its graph at the first false, so the voice
             * calls below were never reached at all. */
            {"_ZN2nn5audio17AcquireMemoryPoolEPNS0_19AudioRendererConfigEPNS0_14MemoryPoolTypeEPvm", (void *)snk_audio_acquire_object, 4, 0, 1},
            {"_ZN2nn5audio13AcquireSubMixEPNS0_19AudioRendererConfigEPNS0_10SubMixTypeEii", (void *)snk_audio_trace_submix_acquire, 4, 0, 1},
            {"_ZN2nn5audio15AcquireFinalMixEPNS0_19AudioRendererConfigEPNS0_12FinalMixTypeEi", (void *)snk_audio_trace_finalmix_acquire, 3, 0, 1},
            {"_ZN2nn5audio15AcquireSplitterEPNS0_19AudioRendererConfigEPNS0_12SplitterTypeEiii", (void *)snk_audio_trace_splitter_acquire, 5, 0, 1},
            {"_ZN2nn5audio15ReleaseSplitterEPNS0_19AudioRendererConfigEPNS0_12SplitterTypeE", (void *)snk_audio_trace_mix_release, 2, 0, 0},
            {"_ZN2nn5audio22SetSplitterDestinationEPNS0_19AudioRendererConfigEPNS0_12SplitterTypeEiPNS0_10SubMixTypeE", (void *)snk_audio_trace_splitter_destination, 4, 0, 0},
            {"_ZN2nn5audio22SetSplitterDestinationEPNS0_19AudioRendererConfigEPNS0_12SplitterTypeEiPNS0_12FinalMixTypeE", (void *)snk_audio_trace_splitter_destination, 4, 0, 0},
            {"_ZN2nn5audio24ClearSplitterDestinationEPNS0_19AudioRendererConfigEPNS0_12SplitterTypeEi", (void *)snk_audio_trace_splitter_clear, 3, 0, 0},
            {"_ZN2nn5audio20SetSplitterMixVolumeEPNS0_12SplitterTypeEiPNS0_10SubMixTypeEfii", (void *)snk_audio_trace_splitter_matrix, 5, 1, 0},
            {"_ZN2nn5audio20SetSplitterMixVolumeEPNS0_12SplitterTypeEiPNS0_12FinalMixTypeEfii", (void *)snk_audio_trace_splitter_matrix, 5, 1, 0},
            {"_ZN2nn5audio13AddDeviceSinkEPNS0_19AudioRendererConfigEPNS0_14DeviceSinkTypeEPNS0_12FinalMixTypeEPKaiPKc", (void *)snk_audio_trace_sink, 6, 0, 1},
            {"_ZN2nn5audio16RemoveDeviceSinkEPNS0_19AudioRendererConfigEPNS0_14DeviceSinkTypeEPNS0_12FinalMixTypeE", (void *)snk_audio_trace_sink_remove, 3, 0, 1},
            {"_ZN2nn5audio17SetAudioOutVolumeEPNS0_8AudioOutEf", (void *)snk_audio_trace_audio_out_volume, 1, 1, 1},
            {"_ZN2nn5audio26SetAudioDeviceOutputVolumeEPKNS0_15AudioDeviceNameEf", (void *)snk_audio_trace_device_volume, 1, 1, 1},
            {"_ZN2nn5audio20GetSubMixBufferCountEPKNS0_10SubMixTypeE", (void *)snk_audio_mix_buffer_count, 1, 0, 1},
            {"_ZN2nn5audio22GetFinalMixBufferCountEPKNS0_12FinalMixTypeE", (void *)snk_audio_mix_buffer_count, 1, 0, 1},
            {"_ZN2nn5audio13ReleaseSubMixEPNS0_19AudioRendererConfigEPNS0_10SubMixTypeE", (void *)snk_audio_trace_mix_release, 2, 0, 0},
            {"_ZN2nn5audio15ReleaseFinalMixEPNS0_19AudioRendererConfigEPNS0_12FinalMixTypeE", (void *)snk_audio_trace_mix_release, 2, 0, 0},
            {"_ZN2nn5audio15SetSubMixVolumeEPNS0_10SubMixTypeEf", (void *)snk_audio_trace_mix_volume, 1, 1, 0},
            {"_ZN2nn5audio17SetFinalMixVolumeEPNS0_12FinalMixTypeEf", (void *)snk_audio_trace_mix_volume, 1, 1, 0},
            {"_ZN2nn5audio18SetSubMixMixVolumeEPNS0_10SubMixTypeES2_fii", (void *)snk_audio_trace_mix_matrix, 4, 1, 0},
            {"_ZN2nn5audio18SetSubMixMixVolumeEPNS0_10SubMixTypeEPNS0_12FinalMixTypeEfii", (void *)snk_audio_trace_mix_matrix, 4, 1, 0},
            {"_ZN2nn5audio20SetSubMixDestinationEPNS0_19AudioRendererConfigEPNS0_10SubMixTypeES4_", (void *)snk_audio_trace_mix_destination, 3, 0, 0},
            {"_ZN2nn5audio20SetSubMixDestinationEPNS0_19AudioRendererConfigEPNS0_10SubMixTypeEPNS0_12FinalMixTypeE", (void *)snk_audio_trace_mix_destination, 3, 0, 0},
            {"_ZN2nn5audio20SetSubMixDestinationEPNS0_19AudioRendererConfigEPNS0_10SubMixTypeEPNS0_12SplitterTypeE", (void *)snk_audio_trace_mix_destination, 3, 0, 0},
            {"_ZN2nn5audio22ClearSubMixDestinationEPNS0_19AudioRendererConfigEPNS0_10SubMixTypeE", (void *)snk_audio_trace_mix_clear, 2, 0, 0},
            {"_ZN2nn5audio8AddDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPvmPNS0_10SubMixTypeENS_8TimeSpanEi", (void *)snk_audio_trace_delay_add, 7, 0, 1},
            {"_ZN2nn5audio15AddBiquadFilterEPNS0_19AudioRendererConfigEPNS0_16BiquadFilterTypeEPNS0_10SubMixTypeE", (void *)snk_audio_trace_biquad_add, 3, 0, 1},
            {"_ZN2nn5audio15AddBiquadFilterEPNS0_19AudioRendererConfigEPNS0_16BiquadFilterTypeEPNS0_12FinalMixTypeE", (void *)snk_audio_trace_biquad_add, 3, 0, 1},
            {"_ZN2nn5audio13AddCompressorEPNS0_19AudioRendererConfigEPNS0_14CompressorTypeEPNS0_10SubMixTypeEi", (void *)snk_audio_trace_compressor_add, 4, 0, 1},
            {"_ZN2nn5audio13AddCompressorEPNS0_19AudioRendererConfigEPNS0_14CompressorTypeEPNS0_12FinalMixTypeEi", (void *)snk_audio_trace_compressor_add, 4, 0, 1},
            {"_ZN2nn5audio14AddI3dl2ReverbEPNS0_19AudioRendererConfigEPNS0_15I3dl2ReverbTypeEPvmPNS0_10SubMixTypeEi", (void *)snk_audio_trace_reverb_add, 6, 0, 1},
            {"_ZN2nn5audio21SetI3dl2ReverbEnabledEPNS0_15I3dl2ReverbTypeEb", (void *)snk_audio_trace_effect_enabled, 2, 0, 0},
            {"_ZN2nn5audio15SetDelayEnabledEPNS0_9DelayTypeEb", (void *)snk_audio_trace_effect_enabled, 2, 0, 0},
            {"_ZN2nn5audio22SetBiquadFilterEnabledEPNS0_16BiquadFilterTypeEb", (void *)snk_audio_trace_effect_enabled, 2, 0, 0},
            {"_ZN2nn5audio20SetCompressorEnabledEPNS0_14CompressorTypeEb", (void *)snk_audio_trace_effect_enabled, 2, 0, 0},
            {"_ZN2nn5audio19IsCompressorEnabledEPKNS0_14CompressorTypeE", (void *)snk_audio_trace_compressor_enabled, 1, 0, 1},
            {"_ZN2nn5audio22SetCompressorThresholdEPNS0_14CompressorTypeEf", (void *)snk_audio_trace_threshold, 1, 1, 0},
            {"_ZN2nn5audio18SetCompressorRatioEPNS0_14CompressorTypeEf", (void *)snk_audio_trace_ratio, 1, 1, 0},
            {"_ZN2nn5audio23SetCompressorAttackTimeEPNS0_14CompressorTypeENS_8TimeSpanE", (void *)snk_audio_trace_attack, 2, 0, 0},
            {"_ZN2nn5audio24SetCompressorReleaseTimeEPNS0_14CompressorTypeENS_8TimeSpanE", (void *)snk_audio_trace_release, 2, 0, 0},
            {"_ZN2nn5audio20SetCompressorOutGainEPNS0_14CompressorTypeEf", (void *)snk_audio_trace_out_gain, 1, 1, 0},
            {"_ZN2nn5audio23SetCompressorParametersEPNS0_14CompressorTypeEPKNS0_22CompressorParameterSetE", (void *)snk_audio_trace_compressor_parameters, 2, 0, 0},
            {"_ZN2nn5audio15SetDelayDryGainEPNS0_9DelayTypeEf", (void *)snk_audio_trace_dry_gain, 1, 1, 0},
            {"_ZN2nn5audio14SetDelayInGainEPNS0_9DelayTypeEf", (void *)snk_audio_trace_in_gain, 1, 1, 0},
            {"_ZN2nn5audio20SetDelayFeedbackGainEPNS0_9DelayTypeEf", (void *)snk_audio_trace_feedback_gain, 1, 1, 0},
            {"_ZN2nn5audio12SetDelayTimeEPNS0_9DelayTypeENS_8TimeSpanE", (void *)snk_audio_trace_delay_time, 2, 0, 0},
            {"_ZN2nn5audio21SetI3dl2ReverbDryGainEPNS0_15I3dl2ReverbTypeEf", (void *)snk_audio_trace_dry_gain, 1, 1, 0},
            {"_ZN2nn5audio22SetI3dl2ReverbRoomGainEPNS0_15I3dl2ReverbTypeEf", (void *)snk_audio_trace_room_gain, 1, 1, 0},
            {"_ZN2nn5audio24SetI3dl2ReverbRoomHfGainEPNS0_15I3dl2ReverbTypeEf", (void *)snk_audio_trace_room_hf_gain, 1, 1, 0},
            {"_ZN2nn5audio25SetI3dl2ReverbHfReferenceEPNS0_15I3dl2ReverbTypeEf", (void *)snk_audio_trace_hf_reference, 1, 1, 0},
            {"_ZN2nn5audio33SetI3dl2ReverbLateReverbDecayTimeEPNS0_15I3dl2ReverbTypeENS_8TimeSpanE", (void *)snk_audio_trace_decay_time, 2, 0, 0},
            {"_ZN2nn5audio36SetI3dl2ReverbLateReverbHfDecayRatioEPNS0_15I3dl2ReverbTypeEf", (void *)snk_audio_trace_decay_hf_ratio, 1, 1, 0},
            {"_ZN2nn5audio29SetI3dl2ReverbReflectionsGainEPNS0_15I3dl2ReverbTypeEf", (void *)snk_audio_trace_reflections_gain, 1, 1, 0},
            {"_ZN2nn5audio33SetI3dl2ReverbReflectionDelayTimeEPNS0_15I3dl2ReverbTypeENS_8TimeSpanE", (void *)snk_audio_trace_reflection_time, 2, 0, 0},
            {"_ZN2nn5audio24SetI3dl2ReverbReverbGainEPNS0_15I3dl2ReverbTypeEf", (void *)snk_audio_trace_reverb_gain, 1, 1, 0},
            {"_ZN2nn5audio33SetI3dl2ReverbLateReverbDelayTimeEPNS0_15I3dl2ReverbTypeENS_8TimeSpanE", (void *)snk_audio_trace_reverb_time, 2, 0, 0},
            {"_ZN2nn5audio33SetI3dl2ReverbLateReverbDiffusionEPNS0_15I3dl2ReverbTypeEf", (void *)snk_audio_trace_diffusion, 1, 1, 0},
            {"_ZN2nn5audio31SetI3dl2ReverbLateReverbDensityEPNS0_15I3dl2ReverbTypeEf", (void *)snk_audio_trace_density, 1, 1, 0},
            {"_ZN2nn5audio24SetCompressorInputOutputEPNS0_14CompressorTypeEPKaS4_i", (void *)snk_audio_trace_effect_io, 4, 0, 0},
            {"_ZN2nn5audio19SetDelayInputOutputEPNS0_9DelayTypeEPKaS4_i", (void *)snk_audio_trace_effect_io, 4, 0, 0},
            {"_ZN2nn5audio25SetI3dl2ReverbInputOutputEPNS0_15I3dl2ReverbTypeEPKaS4_i", (void *)snk_audio_trace_effect_io, 4, 0, 0},
            {"_ZN2nn5audio26SetBiquadFilterInputOutputEPNS0_16BiquadFilterTypeEPKaS4_i", (void *)snk_audio_trace_effect_io, 4, 0, 0},
            {"_ZN2nn5audio24SetBiquadFilterParameterEPNS0_16BiquadFilterTypeERKNS0_22TBiquadFilterParameterIsEE", (void *)snk_audio_trace_biquad_parameters, 2, 0, 0},
            {"_ZN2nn5audio17RemoveI3dl2ReverbEPNS0_19AudioRendererConfigEPNS0_15I3dl2ReverbTypeEPNS0_10SubMixTypeE", (void *)snk_audio_trace_effect_remove, 3, 0, 1},
            {"_ZN2nn5audio17RemoveI3dl2ReverbEPNS0_19AudioRendererConfigEPNS0_15I3dl2ReverbTypeEPNS0_12FinalMixTypeE", (void *)snk_audio_trace_effect_remove, 3, 0, 1},
            {"_ZN2nn5audio11RemoveDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPNS0_10SubMixTypeE", (void *)snk_audio_trace_effect_remove, 3, 0, 1},
            {"_ZN2nn5audio11RemoveDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPNS0_12FinalMixTypeE", (void *)snk_audio_trace_effect_remove, 3, 0, 1},
            {"_ZN2nn5audio18RemoveBiquadFilterEPNS0_19AudioRendererConfigEPNS0_16BiquadFilterTypeEPNS0_10SubMixTypeE", (void *)snk_audio_trace_effect_remove, 3, 0, 1},
            {"_ZN2nn5audio18RemoveBiquadFilterEPNS0_19AudioRendererConfigEPNS0_16BiquadFilterTypeEPNS0_12FinalMixTypeE", (void *)snk_audio_trace_effect_remove, 3, 0, 1},
            {"_ZN2nn5audio16RemoveCompressorEPNS0_19AudioRendererConfigEPNS0_14CompressorTypeEPNS0_10SubMixTypeE", (void *)snk_audio_trace_effect_remove, 3, 0, 1},
            {"_ZN2nn5audio16RemoveCompressorEPNS0_19AudioRendererConfigEPNS0_14CompressorTypeEPNS0_12FinalMixTypeE", (void *)snk_audio_trace_effect_remove, 3, 0, 1},
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
            {"_ZN2nn5audio16ReleaseVoiceSlotEPNS0_19AudioRendererConfigEPNS0_9VoiceTypeE", (void *)snk_audio_release_voice, 2, 0, 0},
            {"_ZN2nn5audio13SetVoicePitchEPNS0_9VoiceTypeEf", (void *)snk_audio_v_pitch, 1, 1, 1},
            {"_ZN2nn5audio17SetVoiceMixVolumeEPNS0_9VoiceTypeEPNS0_10SubMixTypeEfii", (void *)snk_audio_v_mix_volume, 4, 1, 0},
            {"_ZN2nn5audio17SetVoiceMixVolumeEPNS0_9VoiceTypeEPNS0_12FinalMixTypeEfii", (void *)snk_audio_v_mix_volume, 4, 1, 0},
            {"_ZN2nn5audio14SetVoiceVolumeEPNS0_9VoiceTypeEf", (void *)snk_audio_v_volume, 1, 1, 0},
            {"_ZN2nn5audio12IsVoiceValidEPKNS0_9VoiceTypeE", (void *)snk_audio_v_valid, 1, 0, 1},
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
