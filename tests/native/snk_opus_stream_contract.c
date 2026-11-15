/* Host regression for the SDK packet ABI and float mixer. No game data needed.
 * clang -std=c11 -D_DARWIN_C_SOURCE -Wno-unused-function -ffunction-sections
 *   tests/native/snk_opus_stream_contract.c /opt/homebrew/lib/libopus.a
 *   -Wl,-dead_strip -lm -lpthread -o snk_opus_stream_contract */
#include "../../src/runtime/hle/snk_hle_media.c"
#include <math.h>

static unsigned failures;
#define CHECK(value) do { if (!(value)) { \
    fprintf(stderr, "FAIL line %d %s\n", __LINE__, #value); ++failures; \
} } while (0)

uint64_t ffrs_audio_lookup(const char *name, unsigned *arguments, unsigned *returns) {
    (void)name; (void)arguments; (void)returns; return 0;
}
const char *ffrs_audio_platform_directory(void) { return NULL; }
uint64_t ffrs_sdk_component_lookup(const char *name, unsigned *arguments, unsigned *returns) {
    (void)name; (void)arguments; (void)returns; return 0;
}
const struct snk_media_entry snk_media_entries[1] = {{0}};
const size_t snk_media_entry_count = 0;

static void write_be32(uint8_t *dst, uint32_t value) {
    dst[0] = (uint8_t)(value >> 24);
    dst[1] = (uint8_t)(value >> 16);
    dst[2] = (uint8_t)(value >> 8);
    dst[3] = (uint8_t)value;
}

static void check_decoder_stream(void) {
    int error = 0, owner = 0;
    OpusEncoder *encoder = opus_encoder_create(48000, 2, OPUS_APPLICATION_AUDIO, &error);
    CHECK(encoder && error == OPUS_OK);
    if (!encoder) return;
    int16_t source[960 * 2];
    uint8_t stream[8 * 4096];
    size_t offsets[9] = {0};
    for (unsigned packet = 0; packet < 8; ++packet) {
        for (unsigned frame = 0; frame < 960; ++frame) {
            double phase = (double)(packet * 960 + frame) * 440.0 * 6.283185307179586 / 48000.0;
            source[frame * 2] = (int16_t)(sin(phase) * 8000.0);
            source[frame * 2 + 1] = (int16_t)(cos(phase) * 4000.0);
        }
        uint8_t *dst = stream + offsets[packet];
        int count = opus_encode(encoder, source, 960, dst + 8, 4088);
        CHECK(count > 0);
        write_be32(dst, (uint32_t)count);
        write_be32(dst + 4, 0);
        offsets[packet + 1] = offsets[packet] + 8u + (size_t)count;
    }
    opus_encoder_destroy(encoder);
    CHECK(snk_opus_initialize(&owner, 48000, 2, NULL, 0, 0) == 0);
    struct { int16_t pcm[960 * 2]; uint32_t guard; } output;
    memset(&output, 0x55, sizeof output);
    size_t consumed = 777;
    int frames = 777;
    CHECK(snk_opus_decode(&owner, &consumed, &frames, output.pcm, sizeof output.pcm - 1,
                          stream, offsets[8]) == 7);
    CHECK(consumed == 0 && frames == 0 && output.pcm[0] == 0x5555);
    CHECK(snk_opus_decode(&owner, &consumed, &frames, output.pcm, sizeof output.pcm,
                          stream, 7) == 6);
    CHECK(consumed == 0 && frames == 0);
    CHECK(snk_opus_decode(&owner, &consumed, &frames, output.pcm, sizeof output.pcm,
                          stream, offsets[1] - 1) == 6);
    CHECK(consumed == 0 && frames == 0);
    unsigned nonzero = 0;
    for (unsigned packet = 0; packet < 8; ++packet) {
        CHECK(snk_opus_decode(&owner, &consumed, &frames, output.pcm, sizeof output.pcm,
                              stream + offsets[packet], offsets[8] - offsets[packet]) == 0);
        CHECK(consumed == offsets[packet + 1] - offsets[packet]);
        CHECK(frames == 960 && output.guard == 0x55555555u);
        for (unsigned i = 0; i < 960 * 2; ++i) nonzero += output.pcm[i] != 0;
    }
    CHECK(nonzero > 960u);
    CHECK(snk_opus_finalize(&owner) == 0);
    CHECK(snk_opus_decode(&owner, &consumed, &frames, output.pcm, sizeof output.pcm,
                          stream, offsets[8]) == 8);
    CHECK(consumed == 0 && frames == 0);
    printf("framed_stream packets=8 nonzero_samples=%u byte_capacity_and_guards=checked\n", nonzero);
}

static int16_t output[32];
static float mix[32];
static const int16_t *submitted_pcm;
static int voice_key;

static uint64_t capture_append(void *key, void *buffer) {
    (void)key;
    submitted_pcm = ((snk_mix_buffer *)buffer)->data;
    return 1;
}

static void configure_mixer(unsigned frames) {
    memset(s_audio_voices, 0, sizeof s_audio_voices);
    s_mix.state = 1;
    s_mix.opened = 1;
    s_mix.pending_output = 0;
    s_mix.frames = frames;
    s_mix.channels = 2;
    s_mix.rate = 48000;
    s_mix.pcm = mix;
    s_mix_append = capture_append;
    s_mix_released = NULL;
    s_mix_thread_started = 1; /* The contract supplies each update explicitly. */
    memset(s_mix_buffer_used, 1, sizeof s_mix_buffer_used);
    s_mix_buffers[0].data = output;
    CHECK(snk_audio_acquire_voice_slot(NULL, &voice_key, 48000, 2, 2, 0, NULL, 0, NULL) == 1);
}

static void mix_once(void) {
    memset(output, 0x55, sizeof output);
    s_mix_buffer_used[0] = 0;
    snk_audio_mixer_update();
    CHECK(submitted_pcm == output);
}

static void check_float_mixer(void) {
    int16_t source[] = {16384, -8192, 8192, -16384, 0, 4096, -4096, 0};
    struct snk_audio_wave_buffer wave = {.data = source, .bytes = sizeof source, .end = 4};
    configure_mixer(4);
    CHECK(snk_audio_v_append_wave(&voice_key, &wave) == 1);
    mix_once();
    for (unsigned i = 0; i < 8; ++i) CHECK(output[i] == 0);
    CHECK(snk_audio_v_played(&voice_key) == 0 && snk_audio_v_wave_count(&voice_key) == 1);
    snk_audio_v_play_state(&voice_key, 0);
    mix_once();
    CHECK(output[0] >= 16382 && output[0] <= 16384);
    CHECK(output[1] >= -8193 && output[1] <= -8190);
    CHECK(output[4] == 0 && output[7] == 0);
    CHECK(snk_audio_v_played(&voice_key) == 4);
    CHECK(snk_audio_v_released(&voice_key) == &wave);
    CHECK(snk_audio_v_released(&voice_key) == NULL);
    wave.start = 1;
    wave.end = 3;
    CHECK(snk_audio_v_append_wave(&voice_key, &wave) == 1);
    mix_once();
    CHECK(output[0] >= 8190 && output[0] <= 8193);
    CHECK(output[1] >= -16384 && output[1] <= -16382);
    CHECK(output[4] == 0 && output[5] == 0);
    CHECK(snk_audio_v_played(&voice_key) == 6);
    CHECK(snk_audio_v_released(&voice_key) == &wave);
    snk_audio_v_volume(&voice_key, 0.0f);
    CHECK(snk_audio_v_append_wave(&voice_key, &wave) == 1);
    mix_once();
    for (unsigned i = 0; i < 8; ++i) CHECK(output[i] == 0);
    CHECK(snk_audio_v_played(&voice_key) == 8);
    printf("float_mixer stereo_amplitude/start_end/zero_volume/played_clock=checked\n");
}

static void check_pool_copy_and_queue(void) {
    int16_t source[] = {16384, -8192, 8192, -16384, 0, 4096, -4096, 0};
    int16_t copied[8] = {0};
    snk_audio_copy_pool_data(NULL, copied, source, sizeof source);
    CHECK(memcmp(copied, source, sizeof source) == 0);
    struct snk_audio_wave_buffer waves[5];
    configure_mixer(4);
    for (unsigned i = 0; i < 5; ++i) {
        waves[i] = (struct snk_audio_wave_buffer){.data = copied, .bytes = sizeof copied,
                                                .start = i % 4, .end = i % 4 + 1};
        CHECK(snk_audio_v_append_wave(&voice_key, &waves[i]) == (i < 4));
    }
    CHECK(snk_audio_v_wave_count(&voice_key) == 4);
    snk_audio_v_play_state(&voice_key, 0);
    mix_once();
    CHECK(snk_audio_v_wave_count(&voice_key) == 0);
    CHECK(snk_audio_v_played(&voice_key) == 4);
    CHECK(snk_audio_v_append_wave(&voice_key, &waves[4]) == 0);
    CHECK(snk_audio_v_released(&voice_key) == &waves[0]);
    CHECK(snk_audio_v_append_wave(&voice_key, &waves[4]) == 1);
    for (unsigned i = 1; i < 4; ++i) CHECK(snk_audio_v_released(&voice_key) == &waves[i]);
    CHECK(snk_audio_v_released(&voice_key) == NULL);
    mix_once();
    CHECK(snk_audio_v_released(&voice_key) == &waves[4]);
    CHECK(snk_audio_v_released(&voice_key) == NULL);
    CHECK(snk_audio_v_played(&voice_key) == 5);
    int unknown_key = 0;
    CHECK(snk_audio_v_append_wave(&unknown_key, &waves[0]) == 0);
    waves[0].end = 5;
    CHECK(snk_audio_v_append_wave(&voice_key, &waves[0]) == 0);
    snk_audio_release_voice(NULL, &voice_key);
    CHECK(snk_voice_find(&voice_key) == NULL);
    printf("pool_copy_and_queue pcm/four_slots/full_rejection/release_order/invalid_range=checked\n");
}

static void check_pause_and_loop(void) {
    int16_t source[] = {16000, -8000, 8000, -16000, 4000, -4000, -2000, 2000};
    struct snk_audio_wave_buffer wave = {.data = source, .bytes = sizeof source, .end = 4};
    configure_mixer(1);
    CHECK(snk_audio_v_append_wave(&voice_key, &wave) == 1);
    snk_audio_v_play_state(&voice_key, 0);
    mix_once();
    CHECK(snk_audio_v_played(&voice_key) == 1);
    snk_audio_v_play_state(&voice_key, 2);
    mix_once();
    CHECK(output[0] == 0 && output[1] == 0);
    CHECK(snk_audio_v_played(&voice_key) == 1);
    snk_audio_v_play_state(&voice_key, 0);
    mix_once();
    CHECK(output[0] >= 7998 && output[0] <= 8001);
    CHECK(snk_audio_v_played(&voice_key) == 2);
    snk_audio_v_flush(&voice_key);
    CHECK(snk_audio_v_wave_count(&voice_key) == 0);
    CHECK(snk_audio_v_released(&voice_key) == &wave);
    CHECK(snk_audio_v_played(&voice_key) == 2);
    wave.start = 1;
    wave.end = 3;
    wave.looping = 1;
    CHECK(snk_audio_v_append_wave(&voice_key, &wave) == 1);
    s_mix.frames = 4;
    mix_once();
    CHECK(output[0] == output[4] && output[2] == output[6]);
    CHECK(snk_audio_v_wave_count(&voice_key) == 1);
    CHECK(snk_audio_v_released(&voice_key) == NULL);
    CHECK(snk_audio_v_played(&voice_key) == 6);
    snk_audio_v_play_state(&voice_key, 1);
    mix_once();
    CHECK(output[0] == 0 && output[1] == 0);
    CHECK(snk_audio_v_played(&voice_key) == 0);
    CHECK(snk_audio_v_wave_count(&voice_key) == 0);
    CHECK(snk_audio_v_released(&voice_key) == &wave);
    CHECK(snk_audio_v_released(&voice_key) == NULL);
    snk_audio_v_play_state(&voice_key, 0);
    mix_once();
    CHECK(output[0] == 0 && output[1] == 0);
    CHECK(snk_audio_v_played(&voice_key) == 0);
    printf("pause_and_loop pause_resume/loop_range/flush_ownership/stop_without_replay=checked\n");
}

static void check_channel_matrix_and_validity(void) {
    int16_t stereo[] = {16000, -8000, 8000, -16000, 4000, -4000, -2000, 2000};
    struct snk_audio_wave_buffer wave = {.data = stereo, .bytes = sizeof stereo, .end = 4};
    configure_mixer(4);
    CHECK(snk_audio_v_valid(&voice_key) == 1);
    CHECK(snk_audio_v_valid(&wave) == 0);
    snk_audio_v_mix_volume(&voice_key, NULL, 1.0f, 0, 0);
    snk_audio_v_mix_volume(&voice_key, NULL, 1.0f, 1, 1);
    snk_audio_v_mix_volume(&voice_key, NULL, 0.0f, 0, 1);
    snk_audio_v_mix_volume(&voice_key, NULL, 0.0f, 1, 0);
    CHECK(snk_audio_v_append_wave(&voice_key, &wave) == 1);
    snk_audio_v_play_state(&voice_key, 0);
    mix_once();
    CHECK(output[0] >= 15998 && output[0] <= 16001);
    CHECK(output[1] >= -8001 && output[1] <= -7998);
    snk_audio_release_voice(NULL, &voice_key);
    CHECK(snk_audio_v_valid(&voice_key) == 0);

    int16_t mono[] = {16000, 8000, 4000, -2000};
    CHECK(snk_audio_acquire_voice_slot(NULL, &voice_key, 48000, 1, 2, 0, NULL, 0, NULL) == 1);
    CHECK(snk_audio_v_valid(&voice_key) == 1);
    wave = (struct snk_audio_wave_buffer){.data = mono, .bytes = sizeof mono, .end = 4};
    snk_audio_v_mix_volume(&voice_key, NULL, 0.5f, 0, 0);
    snk_audio_v_mix_volume(&voice_key, NULL, 0.5f, 0, 1);
    /* Invalid source-channel writes cannot replace the valid mono routes. */
    snk_audio_v_mix_volume(&voice_key, NULL, 0.0f, 1, 0);
    snk_audio_v_mix_volume(&voice_key, NULL, 0.25f, 0, 23);
    CHECK(snk_voice_find(&voice_key)->mix_matrix[0][23] == 0.25f);
    CHECK(snk_audio_v_append_wave(&voice_key, &wave) == 1);
    snk_audio_v_play_state(&voice_key, 0);
    mix_once();
    CHECK(output[0] >= 7998 && output[0] <= 8001);
    CHECK(output[0] == output[1] && output[2] == output[3]);
    CHECK(snk_audio_v_released(&voice_key) == &wave);
    snk_audio_v_volume(&voice_key, 0.0f);
    CHECK(snk_audio_v_append_wave(&voice_key, &wave) == 1);
    mix_once();
    for (unsigned i = 0; i < 8; ++i) CHECK(output[i] == 0);
    printf("channel_matrix stereo_identity/offdiagonal_zero/mono_to_stereo/24_buffers/validity=checked\n");
}

static void check_end_of_stream(void) {
    int16_t source[] = {16000, -8000, 8000, -16000, 4000, -4000, -2000, 2000};
    struct snk_audio_wave_buffer waves[] = {
        {.data = source, .bytes = sizeof source, .end = 2, .end_of_stream = 1},
        {.data = source, .bytes = sizeof source, .start = 2, .end = 4}
    };
    configure_mixer(4);
    CHECK(snk_audio_v_append_wave(&voice_key, &waves[0]) == 1);
    CHECK(snk_audio_v_append_wave(&voice_key, &waves[1]) == 1);
    snk_audio_v_play_state(&voice_key, 0);
    mix_once();
    CHECK(snk_audio_v_wave_count(&voice_key) == 0);
    CHECK(snk_audio_v_played(&voice_key) == 2);
    CHECK(snk_audio_v_released(&voice_key) == &waves[0]);
    CHECK(snk_audio_v_released(&voice_key) == &waves[1]);
    CHECK(snk_audio_v_append_wave(&voice_key, &waves[0]) == 1);
    mix_once();
    CHECK(snk_audio_v_played(&voice_key) == 0);
    CHECK(snk_audio_v_released(&voice_key) == &waves[0]);
    printf("end_of_stream completed_eos_resets_clock/next_queued_wave_continues=checked\n");
}

static int reject_append;
static uint64_t retry_append(void *key, void *buffer) {
    if (reject_append) { --reject_append; return 0; }
    return capture_append(key, buffer);
}

static void check_output_retry(void) {
    int16_t source[] = {16000, -8000, 8000, -16000};
    struct snk_audio_wave_buffer wave = {.data = source, .bytes = sizeof source, .end = 2};
    configure_mixer(1);
    CHECK(snk_audio_v_append_wave(&voice_key, &wave) == 1);
    snk_audio_v_play_state(&voice_key, 0);
    s_mix_append = retry_append;
    reject_append = 1;
    mix_once();
    int16_t first = output[0];
    CHECK(s_mix.pending_output && snk_audio_v_played(&voice_key) == 1);
    snk_audio_mixer_update();
    CHECK(!s_mix.pending_output && submitted_pcm[0] == first);
    CHECK(snk_audio_v_played(&voice_key) == 1);
    mix_once();
    CHECK(snk_audio_v_played(&voice_key) == 2);
    CHECK(snk_audio_v_released(&voice_key) == &wave);
    printf("output_retry staged_pcm_preserved/no_second_voice_advance=checked\n");
}

static void check_passive_graph_trace(void) {
    void *submix = NULL, *finalmix = NULL, *sink = NULL;
    CHECK(snk_audio_trace_submix_acquire(NULL, &submix, 48000, 2) == 1);
    CHECK(snk_audio_trace_finalmix_acquire(NULL, &finalmix, 2) == 1);
    CHECK(submix && finalmix);
    CHECK(snk_audio_mix_buffer_count(&submix) == 2);
    CHECK(snk_audio_mix_buffer_count(&finalmix) == 2);
    CHECK(snk_audio_mix_buffer_count(&sink) == 0);
    CHECK(snk_audio_mix_buffer_count(NULL) == 0);
    struct snk_graph_trace_node *sub = snk_graph_trace_find(&submix);
    struct snk_graph_trace_node *final = snk_graph_trace_find(&finalmix);
    CHECK(sub && sub->key == &submix && strcmp(sub->kind, "submix") == 0);
    CHECK(final && final->key == &finalmix && strcmp(final->kind, "finalmix") == 0);
    snk_audio_trace_mix_volume(&submix, 2.0f);
    snk_audio_trace_mix_volume(&finalmix, 1.0f);
    snk_audio_trace_mix_destination(NULL, &submix, &finalmix);
    snk_audio_trace_mix_matrix(&submix, &finalmix, 0.5f, 23, 23);
    CHECK(sub->matrix_seen[23] == (UINT32_C(1) << 23));
    CHECK(sub->matrix_nonzero[23] == (UINT32_C(1) << 23));
    int8_t channels[] = {0, 1};
    CHECK(snk_audio_trace_sink(NULL, &sink, &finalmix, channels, 2, "DefaultDevice") == 0);
    CHECK(sink != NULL);
    unsigned gp = 0, fp = 0, gr = 0, fr = 0, stack = 0;
    uint64_t function = snk_hle_media_lookup(
        "_ZN2nn5audio15SetSubMixVolumeEPNS0_10SubMixTypeEf", &gp, &fp, &gr, &fr, &stack);
    CHECK(function == (uintptr_t)snk_audio_trace_mix_volume);
    CHECK(gp == 1 && fp == 1 && gr == 0 && fr == 0 && stack == 0);
    snk_audio_trace_mix_release(NULL, &submix);
    snk_audio_trace_mix_release(NULL, &finalmix);
    CHECK(snk_audio_mix_buffer_count(&submix) == 0);
    CHECK(snk_audio_mix_buffer_count(&finalmix) == 0);
    CHECK(snk_audio_trace_submix_acquire(NULL, &submix, 48000, 6) == 1);
    CHECK(snk_audio_mix_buffer_count(&submix) == 6);
    snk_audio_trace_mix_release(NULL, &submix);
    s_graph_trace_lines = SNK_GRAPH_TRACE_LIMIT - 1;
    CHECK(snk_graph_trace_line() == 1);
    CHECK(snk_graph_trace_line() == 0);
    CHECK(s_graph_trace_lines == SNK_GRAPH_TRACE_LIMIT);
    printf("graph_trace public_object_keys/typed_abi/24x24/count_acquire_release/bounded=checked\n");
}

static void check_splitter_effect_trace(void) {
    memset(s_graph_trace, 0, sizeof s_graph_trace);
    memset(s_graph_trace_routes, 0, sizeof s_graph_trace_routes);
    s_graph_trace_nodes = s_graph_trace_lines = s_graph_trace_route_count = s_graph_trace_snapshots = 0;
    s_graph_device_volume_logs = s_graph_audio_out_volume_logs = 0;
    void *splitter = NULL, *submix = NULL, *finalmix = NULL;
    CHECK(snk_audio_trace_submix_acquire(NULL, &submix, 48000, 24) == 1);
    CHECK(snk_audio_trace_finalmix_acquire(NULL, &finalmix, 2) == 1);
    CHECK(snk_audio_trace_splitter_acquire(NULL, &splitter, 48000, 2, 3) == 1);
    struct snk_graph_trace_node *split = snk_graph_trace_find(&splitter);
    CHECK(split && split->buffers == 2 && split->branches == 3);
    snk_audio_trace_mix_destination(NULL, &submix, &splitter);
    CHECK(snk_graph_trace_find(&submix)->destination == &splitter);
    snk_audio_trace_splitter_destination(NULL, &splitter, 0, &finalmix);
    snk_audio_trace_splitter_destination(NULL, &splitter, 1, &submix);
    snk_audio_trace_splitter_matrix(&splitter, 0, &finalmix, 0.5f, 0, 0);
    snk_audio_trace_splitter_matrix(&splitter, 1, &submix, 0.75f, 23, 23);
    CHECK(snk_graph_trace_route(&splitter, 0, -1, -1)->destination == &finalmix);
    CHECK(snk_graph_trace_route(&splitter, 1, -1, -1)->destination == &submix);
    CHECK(snk_graph_trace_route(&splitter, 0, 0, 0)->gain == 0.5f);
    CHECK(snk_graph_trace_route(&splitter, 1, 23, 23)->gain == 0.75f);
    CHECK(snk_graph_trace_route_destination(snk_graph_trace_route(&splitter, 1, 23, 23)) == &submix);
    for (unsigned i = 0; i < 20; ++i) {
        snk_audio_trace_splitter_matrix(&splitter, 0, &finalmix, 0.25f, 0, 0);
        snk_audio_trace_mix_volume(&submix, (float)i / 10.0f);
    }
    CHECK(snk_graph_trace_route(&splitter, 0, 0, 0)->gain == 0.25f);
    CHECK(fabsf(snk_graph_trace_find(&submix)->volume - 1.9f) < 0.0001f);
    snk_audio_trace_splitter_clear(NULL, &splitter, 1);
    CHECK(snk_graph_trace_route(&splitter, 1, -1, -1)->destination == NULL);
    CHECK(snk_graph_trace_route_destination(snk_graph_trace_route(&splitter, 1, 23, 23)) == NULL);
    snk_audio_trace_mix_clear(NULL, &submix);
    CHECK(snk_graph_trace_find(&submix)->destination == NULL);

    void *sink = NULL;
    int8_t sink_channels[] = {1, 0};
    CHECK(snk_audio_trace_sink(NULL, &sink, &finalmix, sink_channels, 2, "MainAudioOut") == 0);
    struct snk_graph_trace_node *sink_node = snk_graph_trace_find(&sink);
    CHECK(sink_node && sink_node->destination == &finalmix && sink_node->io_count == 2);
    CHECK(sink_node->inputs[0] == 1 && sink_node->inputs[1] == 0 && sink_node->outputs[1] == 1);
    char device_name[256] = "MainAudioOut";
    CHECK(snk_audio_trace_device_volume(device_name, 0.75f) == 0);
    CHECK(s_graph_device_volume == 0.75f && strcmp(s_graph_device_name, device_name) == 0);
    CHECK(snk_audio_trace_audio_out_volume(&sink, 0.8f) == 0);
    CHECK(s_graph_audio_out_key == &sink && s_graph_audio_out_volume == 0.8f);

    void *compressor = NULL, *delay = NULL, *reverb = NULL, *biquad = NULL;
    CHECK(snk_audio_trace_compressor_add(NULL, &compressor, &submix, 2) == 0);
    CHECK(snk_audio_trace_delay_add(NULL, &delay, NULL, 0, &submix, INT64_C(1000000000), 2) == 0);
    CHECK(snk_audio_trace_reverb_add(NULL, &reverb, NULL, 0, &submix, 2) == 0);
    CHECK(snk_audio_trace_biquad_add(NULL, &biquad, &submix) == 0);
    CHECK(compressor && delay && reverb && biquad);
    CHECK(snk_audio_trace_compressor_enabled(&compressor) == 1);
    snk_audio_trace_effect_enabled(&compressor, false);
    CHECK(snk_audio_trace_compressor_enabled(&compressor) == 0);
    snk_audio_trace_effect_enabled(&compressor, true);
    struct { float threshold, ratio; int64_t attack, release; float gain; uint8_t flag; } parameters = {
        0.2f, 4.0f, INT64_C(1000000), INT64_C(8000000), 2.5f, 1
    };
    snk_audio_trace_compressor_parameters(&compressor, &parameters);
    struct snk_graph_trace_node *comp = snk_graph_trace_find(&compressor);
    CHECK(comp->parameters[SNK_GRAPH_OUT_GAIN] == 2.5);
    CHECK(comp->parameters[SNK_GRAPH_ATTACK_NS] == 1000000.0);
    CHECK(comp->parameters[SNK_GRAPH_PARAMETER_FLAG] == 1.0);
    int8_t inputs[] = {0, 1, 2, 3, 4, 5, 6, 7};
    int8_t outputs[] = {1, 0, 3, 2, 5, 4, 7, 6};
    snk_audio_trace_effect_io(&compressor, inputs, outputs, 8);
    CHECK(comp->io_count == 6 && comp->inputs[5] == 5 && comp->outputs[5] == 4);
    snk_audio_trace_effect_io(&delay, NULL, NULL, 0);
    unsigned char coefficients[12] = {1, 0};
    int16_t q14[] = {16384, 8192, -4096, 2048, -1024};
    memcpy(coefficients + 2, q14, sizeof q14);
    snk_audio_trace_biquad_parameters(&biquad, coefficients);
    struct snk_graph_trace_node *filter = snk_graph_trace_find(&biquad);
    CHECK(filter->enabled == 1 && filter->parameters[SNK_GRAPH_B0] == 1.0);
    CHECK(filter->parameters[SNK_GRAPH_B2] == -0.25 && filter->parameters[SNK_GRAPH_A2] == -0.0625);
    for (unsigned i = 0; i < 20; ++i) snk_audio_trace_out_gain(&compressor, 3.0f);
    CHECK(comp->parameters[SNK_GRAPH_OUT_GAIN] == 3.0);
    uint32_t parameters_before = comp->parameters_set;
    snk_audio_trace_parameter(&compressor, SNK_GRAPH_TRACE_PARAMETERS, 10.0);
    CHECK(comp->parameters_set == parameters_before);
    unsigned route_count = s_graph_trace_route_count;
    s_graph_trace_route_count = SNK_GRAPH_TRACE_ROUTES;
    CHECK(snk_graph_trace_route(&reverb, 9, 22, 22) == NULL);
    s_graph_trace_route_count = route_count;

    int16_t pcm_before[32];
    memcpy(pcm_before, output, sizeof output);
    pthread_mutex_lock(&s_audio_lock);
    for (unsigned i = 0; i < 20; ++i) snk_graph_trace_snapshot();
    pthread_mutex_unlock(&s_audio_lock);
    CHECK(s_graph_trace_snapshots == 16 && memcmp(pcm_before, output, sizeof output) == 0);
    unsigned trace_lines = s_graph_trace_lines;
    snk_graph_trace_snapshot();
    CHECK(s_graph_trace_lines == trace_lines);
    CHECK(snk_audio_trace_sink_remove(NULL, &sink, &finalmix) == 0);
    CHECK(snk_graph_trace_find(&sink) == NULL);
    CHECK(snk_audio_trace_effect_remove(NULL, &compressor, &submix) == 0);
    CHECK(snk_audio_trace_compressor_enabled(&compressor) == 0);
    snk_audio_trace_mix_release(NULL, &splitter);
    CHECK(snk_audio_trace_splitter_acquire(NULL, &splitter, 32000, 1, 1) == 1);
    CHECK(snk_graph_trace_route(&splitter, 0, 0, 0)->gain == 0.0f);
    CHECK(snk_graph_trace_route(&splitter, 0, -1, -1)->destination == NULL);

    static const struct { const char *name; void *function; unsigned gp, fp, gr; } entries[] = {
        {"_ZN2nn5audio15AcquireSplitterEPNS0_19AudioRendererConfigEPNS0_12SplitterTypeEiii", (void *)snk_audio_trace_splitter_acquire, 5, 0, 1},
        {"_ZN2nn5audio20SetSplitterMixVolumeEPNS0_12SplitterTypeEiPNS0_10SubMixTypeEfii", (void *)snk_audio_trace_splitter_matrix, 5, 1, 0},
        {"_ZN2nn5audio20SetCompressorOutGainEPNS0_14CompressorTypeEf", (void *)snk_audio_trace_out_gain, 1, 1, 0},
        {"_ZN2nn5audio19IsCompressorEnabledEPKNS0_14CompressorTypeE", (void *)snk_audio_trace_compressor_enabled, 1, 0, 1},
        {"_ZN2nn5audio8AddDelayEPNS0_19AudioRendererConfigEPNS0_9DelayTypeEPvmPNS0_10SubMixTypeENS_8TimeSpanEi", (void *)snk_audio_trace_delay_add, 7, 0, 1},
        {"_ZN2nn5audio23SetCompressorAttackTimeEPNS0_14CompressorTypeENS_8TimeSpanE", (void *)snk_audio_trace_attack, 2, 0, 0},
        {"_ZN2nn5audio24SetBiquadFilterParameterEPNS0_16BiquadFilterTypeERKNS0_22TBiquadFilterParameterIsEE", (void *)snk_audio_trace_biquad_parameters, 2, 0, 0},
        {"_ZN2nn5audio17SetAudioOutVolumeEPNS0_8AudioOutEf", (void *)snk_audio_trace_audio_out_volume, 1, 1, 1},
        {"_ZN2nn5audio26SetAudioDeviceOutputVolumeEPKNS0_15AudioDeviceNameEf", (void *)snk_audio_trace_device_volume, 1, 1, 1},
        {"_ZN2nn5audio22ClearSubMixDestinationEPNS0_19AudioRendererConfigEPNS0_10SubMixTypeE", (void *)snk_audio_trace_mix_clear, 2, 0, 0}
    };
    for (unsigned i = 0; i < sizeof entries / sizeof entries[0]; ++i) {
        unsigned gp, fp, gr, fr, stack;
        CHECK(snk_hle_media_lookup(entries[i].name, &gp, &fp, &gr, &fr, &stack) == (uintptr_t)entries[i].function);
        CHECK(gp == entries[i].gp && fp == entries[i].fp && gr == entries[i].gr && fr == 0 && stack == 0);
    }
    printf("splitter_effect_trace branches/latest_gain/effect_params/Q14/device_volume/typed_abi/16_snapshots/bounds=checked\n");
}

/* Optional offline input is a supplied foxn file. Its packet bytes stay local. */
static void check_game_stream(const char *path) {
    FILE *file = fopen(path, "rb");
    CHECK(file != NULL);
    if (!file) return;
    fseek(file, 0, SEEK_END);
    long size = ftell(file);
    rewind(file);
    uint8_t *data = malloc((size_t)size);
    CHECK(size >= 64 && data && fread(data, 1, (size_t)size, file) == (size_t)size);
    fclose(file);
    if (size < 64 || !data) { free(data); return; }
    CHECK(memcmp(data, "foxn", 4) == 0);
    uint32_t rate = (uint32_t)data[8] | ((uint32_t)data[9] << 8) |
                    ((uint32_t)data[10] << 16) | ((uint32_t)data[11] << 24);
    uint32_t start = (uint32_t)data[24] | ((uint32_t)data[25] << 8) |
                     ((uint32_t)data[26] << 16) | ((uint32_t)data[27] << 24);
    int channels = data[5], owner = 0;
    CHECK(snk_opus_initialize(&owner, (int)rate, channels, NULL, 0, 0) == 0);
    size_t offset = start;
    unsigned packets = 0;
    uint64_t total_frames = 0, nonzero = 0;
    int16_t output[5760 * 2];
    while (offset < (size_t)size) {
        size_t consumed = 0;
        int frames = 0;
        uint64_t result = snk_opus_decode(&owner, &consumed, &frames, output, sizeof output,
                                          data + offset, (size_t)size - offset);
        CHECK(result == 0 && consumed > 8 && frames > 0);
        if (result || !consumed) break;
        offset += consumed;
        total_frames += (unsigned)frames;
        for (int i = 0; i < frames * channels; ++i) nonzero += output[i] != 0;
        ++packets;
    }
    CHECK(offset == (size_t)size && packets > 100 && nonzero > 0);
    snk_opus_finalize(&owner);
    printf("supplied_stream packets=%u frames=%llu nonzero_samples=%llu bytes=%zu/%ld\n",
           packets, (unsigned long long)total_frames, (unsigned long long)nonzero, offset, size);
    free(data);
}

int main(int argc, char **argv) {
    check_decoder_stream();
    check_float_mixer();
    check_pool_copy_and_queue();
    check_pause_and_loop();
    check_output_retry();
    check_end_of_stream();
    check_channel_matrix_and_validity();
    check_passive_graph_trace();
    check_splitter_effect_trace();
    if (argc > 1) check_game_stream(argv[1]);
    printf("snk_opus_stream_contract failures=%u\n", failures);
    return failures != 0;
}
