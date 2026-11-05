#ifndef SNK_HLE_MEDIA_H
#define SNK_HLE_MEDIA_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* One host implementation of an nn::audio / nn::codec / nn::image / movie
 * import. The gateway marshals guest registers, so every entry also carries
 * the register counts the real nnSdk export uses: general purpose
 * arguments, floating point arguments and the number of result registers
 * the guest reads back. */
struct snk_media_entry {
    const char *name;
    uint8_t gp_arguments;
    uint8_t fp_arguments;
    uint8_t gp_returns;
    uint8_t fp_returns;
    /* Bytes the guest passes on the stack. AAPCS64 puts every argument
     * after the eighth general register there. */
    uint8_t stack_bytes;
    uintptr_t function;
};

extern const struct snk_media_entry snk_media_entries[];
extern const size_t snk_media_entry_count;

/* The answer for every import that only has to return a defined value. */
uint64_t snk_media_generic(void);

/* The host implementations that need more than a defined return value.
 * Their parameter lists follow the register layout of the nnSdk export
 * they replace. */
uint64_t snk_audio_initialize_renderer_parameter(void *parameter);
uint64_t snk_audio_is_valid_renderer_parameter(const void *parameter);
uint64_t snk_audio_renderer_work_buffer_size(const void *parameter);
uint64_t snk_audio_renderer_config_work_buffer_size(const void *parameter);
uint64_t snk_audio_performance_frames_buffer_size(const void *parameter);
uint64_t snk_audio_open_renderer(void **handle_out, void *system_event,
                                 const void *parameter, void *work_buffer,
                                 size_t work_size);
uint64_t snk_audio_start_renderer(void *renderer, void *state_object);
uint64_t snk_audio_renderer_state(void *renderer, void *state_object);
uint64_t snk_audio_stop_renderer(void *renderer, void *state_object);
uint64_t snk_audio_close_renderer(void *renderer, void *state_object);
uint64_t snk_audio_request_update_renderer(void *renderer, void *state_object,
                                           const void *config);
uint64_t snk_audio_acquire_voice_slot(void *config, void *voice_out,
                                       int channel, int mixer_index,
                                       int sample_format, int sample_count,
                                       const void *wave_buffer,
                                       size_t wave_buffer_size,
                                       void *behavior_options);
uint64_t snk_audio_performance_info_ctor(void *self);
uint64_t snk_audio_performance_info_dtor(void *self);
uint64_t snk_audio_performance_info_set_buffer(void *self, const void *data, size_t size);
uint64_t snk_audio_performance_info_next_frame(void *self);
uint64_t snk_audio_performance_info_total_time(const void *self);

uint64_t snk_opus_work_buffer_size(int channels, int sample_rate, int extra);
uint64_t snk_opus_initialize(void *owner, int sample_rate, int channels,
                             void *work_buffer, size_t work_size, int extra);
uint64_t snk_opus_finalize(void *owner);
uint64_t snk_opus_sample_rate(const void *owner);
uint64_t snk_opus_channel_count(const void *owner);
uint64_t snk_opus_reset(void *owner);
uint64_t snk_opus_decode(void *owner, size_t *consumed, int *frames, short *output,
                          size_t output_samples, const void *input, size_t input_size);

uint64_t snk_png_decoder_ctor(void *self);
uint64_t snk_png_decoder_dtor(void *self);
uint64_t snk_png_decoder_initialize(void *self, void *allocator, void *allocator_context,
                                    void *deallocator, void *deallocator_context);
uint64_t snk_png_decoder_set_image_data(void *self, const void *data, size_t size);
uint64_t snk_png_decoder_set_pixel_format(void *self, int format);
uint64_t snk_png_decoder_analyze(void *self);
uint64_t snk_png_decoder_decode(void *self, void *output, size_t stride, size_t size);
uint64_t snk_png_decoder_dimension(const void *self);
uint64_t snk_png_decoder_row_stride(const void *self);
uint64_t snk_png_encoder_ctor(void *self);
uint64_t snk_png_encoder_dtor(void *self);
uint64_t snk_png_encoder_initialize(void *self, void *allocator, void *allocator_context,
                                    void *deallocator, void *deallocator_context);
uint64_t snk_png_encoder_set_pixel_data(void *self, const void *data, size_t size,
                                         int format, uint64_t dimension, size_t stride);
uint64_t snk_png_encoder_encode(void *self, size_t *size_out, void *output, size_t capacity);
uint64_t snk_png_encoder_size_max(const void *self);

uint64_t snk_movie_media_data_ctor(void *self);
uint64_t snk_movie_media_data_dtor(void *self);
uint64_t snk_movie_media_data_clear(void *self);
uint64_t snk_movie_media_data_find_string(const void *self, const char *key, const char **value);
uint64_t snk_movie_media_data_find_int32(const void *self, const char *key, int *value);
uint64_t snk_movie_media_data_find_int64(const void *self, const char *key, long *value);
uint64_t snk_movie_status_to_string(int status);
uint64_t snk_movie_extractor_ctor(void *self, int container, int cache);
uint64_t snk_movie_decoder_ctor(void *self, int type, int format, int mode, int argument);

/* div returns the quotient in x0 and the remainder in x1. */
struct snk_div_result {
    int quotient;
    int remainder;
};
struct snk_div_result snk_libc_div(int numerator, int denominator);
float snk_libc_strtof(const char *text, char **end);

/* Resolves an import name to its host implementation. Returns 0 when the
 * name is not part of this group. */
uint64_t snk_hle_media_lookup(const char *name, unsigned *gp_arguments,
                               unsigned *fp_arguments, unsigned *gp_returns,
                               unsigned *fp_returns, unsigned *stack_bytes);

#ifdef __cplusplus
}
#endif

#endif
