#!/usr/bin/env python3
"""Generate the nn::audio / nn::codec / nn::image / movie HLE import table.

The import gateway marshals guest registers, so every host stub needs the
register count the real nnSdk export uses. The counts are derived from the
Itanium ABI rules and the demangled signature:

  * a member function carries an implicit this pointer in x0;
  * a by-value aggregate of 16 bytes occupies two general registers;
  * float and double arguments travel in the vector registers.

Usage:
  python3 scripts/analysis/gen_hle_media.py \
      --gap .local/analysis/runtime_gap.json \
      --out src/runtime/hle/snk_hle_media_table.c
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

# Symbols whose behaviour is hand written in snk_hle_media.c. The value is
# the C function that implements it.
CUSTOM = {
    "_ZN2nn5audio32InitializeAudioRendererParameterEPNS0_22AudioRendererParameterE":
        "snk_audio_initialize_renderer_parameter",
    "_ZN2nn5audio29IsValidAudioRendererParameterERKNS0_22AudioRendererParameterE":
        "snk_audio_is_valid_renderer_parameter",
    "_ZN2nn5audio30GetAudioRendererWorkBufferSizeERKNS0_22AudioRendererParameterE":
        "snk_audio_renderer_work_buffer_size",
    "_ZN2nn5audio36GetAudioRendererConfigWorkBufferSizeERKNS0_22AudioRendererParameterE":
        "snk_audio_renderer_config_work_buffer_size",
    "_ZN2nn5audio41GetRequiredBufferSizeForPerformanceFramesERKNS0_22AudioRendererParameterE":
        "snk_audio_performance_frames_buffer_size",
    "_ZN2nn5audio17OpenAudioRendererEPNS0_19AudioRendererHandleEPNS_2os11SystemEventERKNS0_22AudioRendererParameterEPvm":
        "snk_audio_open_renderer",
    "_ZN2nn5audio18StartAudioRendererENS0_19AudioRendererHandleE":
        "snk_audio_start_renderer",
    "_ZN2nn5audio21GetAudioRendererStateENS0_19AudioRendererHandleE":
        "snk_audio_renderer_state",
    "_ZN2nn5audio17StopAudioRendererENS0_19AudioRendererHandleE":
        "snk_audio_stop_renderer",
    "_ZN2nn5audio18CloseAudioRendererENS0_19AudioRendererHandleE":
        "snk_audio_close_renderer",
    "_ZN2nn5audio26RequestUpdateAudioRendererENS0_19AudioRendererHandleEPKNS0_19AudioRendererConfigE":
        "snk_audio_request_update_renderer",
    "_ZN2nn5audio16AcquireVoiceSlotEPNS0_19AudioRendererConfigEPNS0_9VoiceTypeEiiNS0_12SampleFormatEiPKvmPKNS3_15BehaviorOptionsE":
        "snk_audio_acquire_voice_slot",
    "_ZN2nn5audio15PerformanceInfoC1Ev": "snk_audio_performance_info_ctor",
    "_ZN2nn5audio15PerformanceInfoD1Ev": "snk_audio_performance_info_dtor",
    "_ZN2nn5audio15PerformanceInfo9SetBufferEPKvm": "snk_audio_performance_info_set_buffer",
    "_ZN2nn5audio15PerformanceInfo15MoveToNextFrameEv": "snk_audio_performance_info_next_frame",
    "_ZNK2nn5audio15PerformanceInfo22GetTotalProcessingTimeEv": "snk_audio_performance_info_total_time",
    "_ZN2nn5codec28GetOpusDecoderWorkBufferSizeEii": "snk_opus_work_buffer_size",
    "_ZN2nn5codec21InitializeOpusDecoderEPNS0_15OpusDecoderTypeEiiPvm": "snk_opus_initialize",
    "_ZN2nn5codec19FinalizeOpusDecoderEPNS0_15OpusDecoderTypeE": "snk_opus_finalize",
    "_ZN2nn5codec24GetOpusDecoderSampleRateEPKNS0_15OpusDecoderTypeE": "snk_opus_sample_rate",
    "_ZN2nn5codec26GetOpusDecoderChannelCountEPKNS0_15OpusDecoderTypeE": "snk_opus_channel_count",
    "_ZN2nn5codec16ResetOpusDecoderEPNS0_15OpusDecoderTypeE": "snk_opus_reset",
    "_ZN2nn5codec36GetHardwareOpusDecoderWorkBufferSizeEiii": "snk_opus_work_buffer_size",
    "_ZN2nn5codec29InitializeHardwareOpusDecoderEPNS0_23HardwareOpusDecoderTypeEiiPvmi":
        "snk_opus_initialize",
    "_ZN2nn5codec27FinalizeHardwareOpusDecoderEPNS0_23HardwareOpusDecoderTypeE": "snk_opus_finalize",
    "_ZN2nn5codec32GetHardwareOpusDecoderSampleRateEPKNS0_23HardwareOpusDecoderTypeE":
        "snk_opus_sample_rate",
    "_ZN2nn5codec34GetHardwareOpusDecoderChannelCountEPKNS0_23HardwareOpusDecoderTypeE":
        "snk_opus_channel_count",
    "_ZN2nn5codec24ResetHardwareOpusDecoderEPNS0_23HardwareOpusDecoderTypeE": "snk_opus_reset",
    "_ZN2nn5codec21DecodeOpusInterleavedEPNS0_15OpusDecoderTypeEPmPiPsmPKvm": "snk_opus_decode",
    "_ZN2nn5codec33DecodeOpusInterleavedWithHardwareEPNS0_23HardwareOpusDecoderTypeEPmPiPsmPKvm":
        "snk_opus_decode",
    "_ZN2nn5image10PngDecoderC1Ev": "snk_png_decoder_ctor",
    "_ZN2nn5image10PngDecoderD1Ev": "snk_png_decoder_dtor",
    "_ZN2nn5image10PngDecoder10InitializeEPFPvmS2_ES2_PFvS2_S2_ES2_": "snk_png_decoder_initialize",
    "_ZN2nn5image10PngDecoder12SetImageDataEPKvm": "snk_png_decoder_set_image_data",
    "_ZN2nn5image10PngDecoder20SetOutputPixelFormatENS0_11PixelFormatE":
        "snk_png_decoder_set_pixel_format",
    "_ZN2nn5image10PngDecoder7AnalyzeEv": "snk_png_decoder_analyze",
    "_ZN2nn5image10PngDecoder6DecodeEPvmm": "snk_png_decoder_decode",
    "_ZNK2nn5image10PngDecoder12GetDimensionEv": "snk_png_decoder_dimension",
    "_ZNK2nn5image10PngDecoder15GetRowStrideMinEv": "snk_png_decoder_row_stride",
    "_ZN2nn5image10PngEncoderC1Ev": "snk_png_encoder_ctor",
    "_ZN2nn5image10PngEncoderD1Ev": "snk_png_encoder_dtor",
    "_ZN2nn5image10PngEncoder10InitializeEPFPvmS2_ES2_PFvS2_S2_ES2_": "snk_png_encoder_initialize",
    "_ZN2nn5image10PngEncoder12SetPixelDataEPKvmNS0_11PixelFormatENS0_9DimensionEm":
        "snk_png_encoder_set_pixel_data",
    "_ZN2nn5image10PngEncoder6EncodeEPmPvm": "snk_png_encoder_encode",
    "_ZNK2nn5image10PngEncoder17GetPngDataSizeMaxEv": "snk_png_encoder_size_max",
    "_ZN5movie9MediaDataC1Ev": "snk_movie_media_data_ctor",
    "_ZN5movie9MediaDataD1Ev": "snk_movie_media_data_dtor",
    "_ZN5movie9MediaData5ClearEv": "snk_movie_media_data_clear",
    "_ZNK5movie9MediaData10FindStringEPKcPS2_": "snk_movie_media_data_find_string",
    "_ZNK5movie9MediaData9FindInt32EPKcPi": "snk_movie_media_data_find_int32",
    "_ZNK5movie9MediaData9FindInt64EPKcPl": "snk_movie_media_data_find_int64",
    "_ZN5movie14StatusToStringENS_6StatusE": "snk_movie_status_to_string",
    "_ZN5movie9ExtractorC1ENS_13ContainerTypeENS_9CacheSizeE": "snk_movie_extractor_ctor",
    "_ZN5movie7DecoderC1ENS_11DecoderTypeENS_19DecoderOutputFormatENS_11DecoderModeEi":
        "snk_movie_decoder_ctor",
    "div": "snk_libc_div",
    "strtof": "snk_libc_strtof",
}

# Types that travel in two general registers when passed by value.
WIDE_AGGREGATES = {"nn::audio::AudioRendererHandle"}

# Symbols whose result registers are not the usual single x0.
RESULT_OVERRIDES = {
    # div returns div_t, the quotient in x0 and the remainder in x1.
    "div": (2, 0, 2, 0),
    # strtof returns a float in s0.
    "strtof": (1, 0, 0, 1),
}

# Implemented next to the movie Buffer object they belong to.
SKIP = {"_ZN5movie6BufferC1Em", "_ZNK5movie6Buffer4DataEv"}


def split_params(text):
    parts, depth, current = [], 0, ""
    for ch in text:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(current.strip())
            current = ""
            continue
        current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def demangle(names):
    out = subprocess.run(["c++filt", "-n"] + names, capture_output=True, text=True).stdout
    return out.splitlines()


def is_member(pretty):
    """A class member carries an implicit this pointer in x0.

    The demangled name of a member is ns::Class::method, the name of a free
    function is ns::function. The component in front of the function name is
    the class for a member and a namespace for a free function, and the class
    of this title always starts with an upper case letter."""
    head = pretty.split("(", 1)[0]
    parts = head.split("::")
    if len(parts) < 3:
        return False
    return parts[-2][:1].isupper()


def classify(pretty):
    head = pretty.split("(", 1)[0]
    gp = 1 if is_member(pretty) else 0
    fp = 0
    params = ""
    if "(" in pretty:
        inner = pretty[pretty.index("(") + 1:]
        depth = 0
        for index, ch in enumerate(inner):
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    params = inner[:index]
                    break
                depth -= 1
    for param in split_params(params):
        base = param.replace("const", "").replace("volatile", "").strip()
        base = re.sub(r"\s+", " ", base)
        if base in ("float", "double"):
            fp += 1
            continue
        gp += 1
        if base in WIDE_AGGREGATES:
            gp += 1
    return gp, fp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gap", type=Path, default=Path(".local/analysis/runtime_gap.json"))
    parser.add_argument("--out", type=Path,
                        default=Path("src/runtime/hle/snk_hle_media_table.c"))
    args = parser.parse_args()

    report = json.loads(args.gap.read_text(encoding="utf-8"))
    # The whole import surface, not only the still open gap: the table has to
    # stay complete after the gap closes. Peer modules keep their imports.
    source = report.get("imports")
    if not source:
        source = report["unresolved"]
    names = []
    for item in source:
        if item.get("provider") == "peer":
            continue
        if item["name"] not in names:
            names.append(item["name"])
    pretty = demangle(names)

    selected = []
    for mangled, nice in zip(names, pretty):
        if mangled in SKIP:
            continue
        if ("2nn5audio" in mangled or "2nn5codec" in mangled
                or "2nn5image" in mangled or "5movie" in mangled) \
           or mangled in ("div", "strtof"):
            selected.append((mangled, nice))

    lines = [
        "/* Generated by scripts/analysis/gen_hle_media.py. Do not edit by hand. */",
        "",
        '#include "snk_hle_media.h"',
        "",
        "#include <stdint.h>",
        "",
        "/* Every entry that only has to answer with a defined value reuses this",
        " * stub. The gateway transports the whole register file, so a stub that",
        " * declares no parameter still sees the guest arguments in x0-x7 and",
        " * simply ignores them. */",
        "uint64_t snk_media_generic(void) {",
        "    return 0;",
        "}",
        "",
        "const struct snk_media_entry snk_media_entries[] = {",
    ]
    for mangled, nice in selected:
        function = CUSTOM.get(mangled, "snk_media_generic")
        gp, fp = classify(nice)
        gp_returns, fp_returns = 1, 0
        if mangled in RESULT_OVERRIDES:
            gp, fp, gp_returns, fp_returns = RESULT_OVERRIDES[mangled]
        # AAPCS64 passes the arguments after the eighth general register on
        # the stack. The generator records how many bytes travel there.
        stack_bytes = 0
        if gp > 8:
            stack_bytes = 8 * (gp - 8)
            gp = 8
        lines.append('    { "%s", %d, %d, %d, %d, %d, (uintptr_t)&%s },'
                     % (mangled, gp, fp, gp_returns, fp_returns, stack_bytes, function))
    lines.append("};")
    lines.append("")
    lines.append("const size_t snk_media_entry_count =")
    lines.append("    sizeof(snk_media_entries) / sizeof(snk_media_entries[0]);")
    lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("wrote %s with %d entries" % (args.out, len(selected)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
