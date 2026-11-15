#ifndef FFRS_SDK_COMPONENT_H
#define FFRS_SDK_COMPONENT_H
#include <stdint.h>
#include <stdbool.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Exact supplied SDK only; no SDK startup/CRT or platform-service execution.
 * Only audited DSP routines are exposed through the native boundary. */
int ffrs_sdk_component_load(const char *path);
uint64_t ffrs_sdk_component_lookup(const char *name, unsigned *arguments, unsigned *returns);

/* Supplied v1.0.7 SDK CompressorCommand parameter block at command +0x30.
 * Its int32 PCM buffers retain PCM16 sample units. The DSP state is 64 bytes. */
struct ffrs_sdk_compressor_parameter {
    int8_t inputs[6];
    int8_t outputs[6];
    uint16_t channel_count_max;
    uint16_t channel_count;
    uint32_t sample_rate;
    float threshold_db;
    float ratio;
    int32_t attack_us;
    int32_t release_us;
    float detector_coefficient;
    float attack_coefficient;
    float release_coefficient;
    float output_gain_db;
    uint8_t parameter_state;
    uint8_t makeup_enabled;
    uint8_t reserved_36;
    uint8_t statistics_reset;
};
struct ffrs_sdk_compressor_state {
    float values[16];
};
typedef void (*ffrs_sdk_compressor_configure_fn)(const struct ffrs_sdk_compressor_parameter *,
                                                struct ffrs_sdk_compressor_state *);
typedef void (*ffrs_sdk_compressor_apply_fn)(const struct ffrs_sdk_compressor_parameter *,
        struct ffrs_sdk_compressor_state *, bool, const int32_t *const *, int32_t *const *, int, void *);

#define FFRS_SDK_COMPRESSOR_INITIALIZE "_ZN2nn5audio26InitializeCompressorEffectEPKNS0_19CompressorParameterEPNS0_15CompressorStateE"
#define FFRS_SDK_COMPRESSOR_CONFIGURE "_ZN2nn5audio28SetCompressorEffectParameterEPKNS0_19CompressorParameterEPNS0_15CompressorStateE"
#define FFRS_SDK_COMPRESSOR_APPLY "_ZN2nn5audio21ApplyCompressorEffectEPKNS0_19CompressorParameterEPNS0_15CompressorStateEbPPKiPPiiPNS0_28CompressorStatisticsInternalE"
#ifdef __cplusplus
}
#endif
#endif
