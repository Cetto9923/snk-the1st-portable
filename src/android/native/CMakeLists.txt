cmake_minimum_required(VERSION 3.22)
project(ffrs_android_diagnostics LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(PROBE_SOURCES probe_core.cpp probe_types.cpp probe_platform.cpp json_writer.cpp probe_vulkan.cpp)
if(ANDROID)
    if(NOT ANDROID_ABI STREQUAL "arm64-v8a")
        message(FATAL_ERROR "The native NSO diagnostic requires arm64-v8a")
    endif()
    list(APPEND PROBE_SOURCES probe_android.cpp)
else()
    list(APPEND PROBE_SOURCES probe_host.cpp)
endif()
add_library(ffrs_probe STATIC ${PROBE_SOURCES})
target_include_directories(ffrs_probe PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
if(ANDROID)
    target_link_libraries(ffrs_probe PUBLIC vulkan android log)
endif()
add_executable(probe_rg477m main.cpp)
target_link_libraries(probe_rg477m PRIVATE ffrs_probe)

if(ANDROID)
    # Read the one runtime implementation in place; never fork the loader here.
    set(FFRS_RUNTIME_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../runtime/nso" CACHE PATH "NSO loader source directory")
    add_library(ffrs_nso STATIC "${FFRS_RUNTIME_DIR}/nso_loader.c")
    target_include_directories(ffrs_nso PUBLIC "${FFRS_RUNTIME_DIR}")
    target_link_libraries(ffrs_nso PUBLIC dl)
    add_library(ffrs_diagnostic_core STATIC nso_diagnostic.cpp)
    target_link_libraries(ffrs_diagnostic_core PUBLIC ffrs_nso ffrs_probe)
    option(FFRS_LINK_NVN_DIAGNOSTICS "Include the NVN dispatch diagnostic surface when available" ON)
    set(FFRS_NVN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../graphics/nvn" CACHE PATH "NVN compatibility source directory")
    if(FFRS_LINK_NVN_DIAGNOSTICS AND EXISTS "${FFRS_NVN_DIR}/src/nvn_dispatch.c")
        add_library(ffrs_nvn_diagnostics STATIC "${FFRS_NVN_DIR}/src/nvn_dispatch.c")
        target_include_directories(ffrs_nvn_diagnostics PUBLIC "${FFRS_NVN_DIR}/include")
        target_link_libraries(ffrs_diagnostic_core PUBLIC ffrs_nvn_diagnostics)
        target_compile_definitions(ffrs_diagnostic_core PRIVATE FFRS_HAS_NVN_DIAGNOSTICS=1)
    endif()
    add_executable(nso_diagnostic diagnostic_main.cpp)
    target_link_libraries(nso_diagnostic PRIVATE ffrs_diagnostic_core)
    add_library(ffrs_diagnostic SHARED diagnostic_jni.cpp display_jni.cpp input_jni.cpp leaf_jni.cpp leaf_validation.cpp)
    target_link_libraries(ffrs_diagnostic PRIVATE ffrs_diagnostic_core)
    # The game window form: the Activity SurfaceView hands its ANativeWindow to
    # the runtime-side holder in src/runtime/hle/native_window.c. No rendering,
    # no input and no nn::vi import binding happen in this library.
    set(FFRS_NATIVE_WINDOW_HLE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../runtime/hle" CACHE PATH "Native window holder source directory")
    # The owned guest runtime, linked into the app process.
    #
    # The window is a process-local platform handle, so the guest has to run in
    # the process that owns the SurfaceView. These are the same sources the
    # standalone CLI is built from (scripts/runtime/build_guest_process_contract.sh):
    # the loader, the typed HLE, the native boundary and the NVN device layer.
    set(FFRS_GUEST_NSO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../runtime/nso" CACHE PATH "NSO runtime source directory")
    set(FFRS_GUEST_HLE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../runtime/hle" CACHE PATH "Typed runtime HLE source directory")
    set(FFRS_GUEST_NVN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../graphics/nvn_device" CACHE PATH "NVN device source directory")
    enable_language(ASM)
    # libopus (decoder only, fixed-point): the title decodes BGM/SE through
    # nn::codec, and an Opus packet decoder is the whole of what it needs from
    # it. The vendored snapshot in third_party/opus was assembled for exactly
    # this configuration: top-level silk files only, no silk/fixed or silk/float
    # subdirectories, so FIXED_POINT is the only configuration it can build.
    set(FFRS_OPUS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../third_party/opus" CACHE PATH "libopus source directory")
    add_library(ffrs_opus STATIC
        "${FFRS_OPUS_DIR}/silk/CNG.c"
        "${FFRS_OPUS_DIR}/silk/LPC_analysis_filter.c"
        "${FFRS_OPUS_DIR}/silk/LPC_fit.c"
        "${FFRS_OPUS_DIR}/silk/LPC_inv_pred_gain.c"
        "${FFRS_OPUS_DIR}/silk/LP_variable_cutoff.c"
        "${FFRS_OPUS_DIR}/silk/NLSF2A.c"
        "${FFRS_OPUS_DIR}/silk/NLSF_decode.c"
        "${FFRS_OPUS_DIR}/silk/NLSF_stabilize.c"
        "${FFRS_OPUS_DIR}/silk/NLSF_unpack.c"
        "${FFRS_OPUS_DIR}/silk/PLC.c"
        "${FFRS_OPUS_DIR}/silk/biquad_alt.c"
        "${FFRS_OPUS_DIR}/silk/bwexpander.c"
        "${FFRS_OPUS_DIR}/silk/bwexpander_32.c"
        "${FFRS_OPUS_DIR}/silk/code_signs.c"
        "${FFRS_OPUS_DIR}/silk/dec_API.c"
        "${FFRS_OPUS_DIR}/silk/decode_core.c"
        "${FFRS_OPUS_DIR}/silk/decode_frame.c"
        "${FFRS_OPUS_DIR}/silk/decode_indices.c"
        "${FFRS_OPUS_DIR}/silk/decode_parameters.c"
        "${FFRS_OPUS_DIR}/silk/decode_pitch.c"
        "${FFRS_OPUS_DIR}/silk/decode_pulses.c"
        "${FFRS_OPUS_DIR}/silk/decoder_set_fs.c"
        "${FFRS_OPUS_DIR}/silk/gain_quant.c"
        "${FFRS_OPUS_DIR}/silk/init_decoder.c"
        "${FFRS_OPUS_DIR}/silk/inner_prod_aligned.c"
        "${FFRS_OPUS_DIR}/silk/interpolate.c"
        "${FFRS_OPUS_DIR}/silk/lin2log.c"
        "${FFRS_OPUS_DIR}/silk/log2lin.c"
        "${FFRS_OPUS_DIR}/silk/pitch_est_tables.c"
        "${FFRS_OPUS_DIR}/silk/resampler.c"
        "${FFRS_OPUS_DIR}/silk/resampler_down2.c"
        "${FFRS_OPUS_DIR}/silk/resampler_down2_3.c"
        "${FFRS_OPUS_DIR}/silk/resampler_private_AR2.c"
        "${FFRS_OPUS_DIR}/silk/resampler_private_IIR_FIR.c"
        "${FFRS_OPUS_DIR}/silk/resampler_private_down_FIR.c"
        "${FFRS_OPUS_DIR}/silk/resampler_private_up2_HQ.c"
        "${FFRS_OPUS_DIR}/silk/resampler_rom.c"
        "${FFRS_OPUS_DIR}/silk/shell_coder.c"
        "${FFRS_OPUS_DIR}/silk/sigm_Q15.c"
        "${FFRS_OPUS_DIR}/silk/sort.c"
        "${FFRS_OPUS_DIR}/silk/stereo_MS_to_LR.c"
        "${FFRS_OPUS_DIR}/silk/stereo_decode_pred.c"
        "${FFRS_OPUS_DIR}/silk/sum_sqr_shift.c"
        "${FFRS_OPUS_DIR}/silk/table_LSF_cos.c"
        "${FFRS_OPUS_DIR}/silk/tables_LTP.c"
        "${FFRS_OPUS_DIR}/silk/tables_NLSF_CB_NB_MB.c"
        "${FFRS_OPUS_DIR}/silk/tables_NLSF_CB_WB.c"
        "${FFRS_OPUS_DIR}/silk/tables_gain.c"
        "${FFRS_OPUS_DIR}/silk/tables_other.c"
        "${FFRS_OPUS_DIR}/silk/tables_pitch_lag.c"
        "${FFRS_OPUS_DIR}/silk/tables_pulses_per_block.c"
        "${FFRS_OPUS_DIR}/celt/bands.c"
        "${FFRS_OPUS_DIR}/celt/celt.c"
        "${FFRS_OPUS_DIR}/celt/celt_decoder.c"
        "${FFRS_OPUS_DIR}/celt/celt_lpc.c"
        "${FFRS_OPUS_DIR}/celt/cwrs.c"
        "${FFRS_OPUS_DIR}/celt/entcode.c"
        "${FFRS_OPUS_DIR}/celt/entdec.c"
        "${FFRS_OPUS_DIR}/celt/entenc.c"
        "${FFRS_OPUS_DIR}/celt/kiss_fft.c"
        "${FFRS_OPUS_DIR}/celt/laplace.c"
        "${FFRS_OPUS_DIR}/celt/mathops.c"
        "${FFRS_OPUS_DIR}/celt/mdct.c"
        "${FFRS_OPUS_DIR}/celt/modes.c"
        "${FFRS_OPUS_DIR}/celt/pitch.c"
        "${FFRS_OPUS_DIR}/celt/quant_bands.c"
        "${FFRS_OPUS_DIR}/celt/rate.c"
        "${FFRS_OPUS_DIR}/celt/vq.c"
        "${FFRS_OPUS_DIR}/src/extensions.c"
        "${FFRS_OPUS_DIR}/src/opus.c"
        "${FFRS_OPUS_DIR}/src/opus_decoder.c"
        "${FFRS_OPUS_DIR}/src/opus_multistream.c"
        "${FFRS_OPUS_DIR}/src/opus_multistream_decoder.c"
        "${FFRS_OPUS_DIR}/src/repacketizer.c"
    )
    target_include_directories(ffrs_opus PRIVATE
        "${FFRS_OPUS_DIR}/include" "${FFRS_OPUS_DIR}/celt"
        "${FFRS_OPUS_DIR}/silk" "${FFRS_OPUS_DIR}/src")
    target_compile_definitions(ffrs_opus PRIVATE FIXED_POINT=1 OPUS_BUILD=1 VAR_ARRAYS=1)
    add_library(ffrs_guest_runtime STATIC
        "${FFRS_GUEST_NSO_DIR}/nso_loader.c"
        "${FFRS_GUEST_NSO_DIR}/nso_boot.c"
        "${FFRS_GUEST_NSO_DIR}/native_boundary.c"
        "${FFRS_GUEST_NSO_DIR}/native_boundary.S"
        "${FFRS_GUEST_HLE_DIR}/guest_context.c"
        "${FFRS_GUEST_HLE_DIR}/guest_process.c"
        "${FFRS_GUEST_HLE_DIR}/nso_host.c"
        "${FFRS_GUEST_HLE_DIR}/hid_bridge.c"
        "${FFRS_GUEST_HLE_DIR}/sdk_component.c"
        "${FFRS_GUEST_HLE_DIR}/movie_buffer.c"
        "${FFRS_GUEST_HLE_DIR}/movie_decoder.cpp"
        "${FFRS_GUEST_HLE_DIR}/multiwait.c"
        "${FFRS_GUEST_HLE_DIR}/snk_hle.c"
        "${FFRS_GUEST_HLE_DIR}/snk_hle_media.c"
        "${FFRS_GUEST_HLE_DIR}/snk_hle_media_table.c"
        "${FFRS_GUEST_HLE_DIR}/snk_libcxx.c"
        "${FFRS_GUEST_HLE_DIR}/audio_bridge.c"
        "${FFRS_GUEST_HLE_DIR}/address_region.c"
        "${FFRS_GUEST_HLE_DIR}/mutex.c"
        "${FFRS_GUEST_HLE_DIR}/exit_registry.c"
        "${FFRS_GUEST_HLE_DIR}/module_tls.c"
        "${FFRS_GUEST_HLE_DIR}/guest_tp.c"
        "${FFRS_GUEST_HLE_DIR}/guest_pages.c"
        "${FFRS_GUEST_HLE_DIR}/guest_os_tls.c"
        "${FFRS_GUEST_HLE_DIR}/native_window.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_device.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_command_buffer.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_command_buffer.generated.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_command_replay.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_queue.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_window.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_memory_pool.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_sampler_pool.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_sampler_builder.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_sampler.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_blend_state.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_render_state.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_program.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_sha256.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_texture_pool.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_texture_builder.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_texture.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_texture_view.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_present.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_buffer.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_bridge.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_engine.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_sync.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_event.c"
        "${FFRS_GUEST_NVN_DIR}/nvn_backend_vulkan.c")
    set_target_properties(ffrs_guest_runtime PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES
        C_EXTENSIONS NO POSITION_INDEPENDENT_CODE ON)
    target_include_directories(ffrs_guest_runtime PUBLIC
        "${FFRS_GUEST_NSO_DIR}" "${FFRS_GUEST_HLE_DIR}" "${FFRS_GUEST_NVN_DIR}")
    # The owned profile is the whole point of this library: without the
    # defines the boot unit would compile to its refusing stub.
    target_compile_definitions(ffrs_guest_runtime PRIVATE NSO_WITH_HOST_HLE=1 NSO_WITH_GUEST_PROFILE=1)
    # The same code generation policy the standalone CLI is built with:
    # -ffixed-x18 keeps the compiler out of the platform register the guest
    # ABI reserves, and -fno-emulated-tls keeps thread locals real.
    target_compile_options(ffrs_guest_runtime PRIVATE -Wall -Wextra -O2 -g
        -fno-omit-frame-pointer -ffixed-x18 -fno-emulated-tls -fvisibility=hidden)
    # The Vulkan engine that replays the guest's NVN commands.
    #
    # It is a separate library because it is written in C++ and because it
    # has its own copy of the NVN headers of this game: the engine was
    # written against them, and the objects it reads are in their layout.
    set(FFRS_NVN_VULKAN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../graphics/nvn_vulkan" CACHE PATH "NVN Vulkan engine source directory")
    add_library(ffrs_nvn_vulkan_engine STATIC
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_command_clone.c"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_depth.c"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_draw_plan.c"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_framebuffer.c"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_quad.c"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_shader_key.c"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_texture.c"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_vertex.c"
        "${FFRS_NVN_VULKAN_DIR}/nvn/nvn_tex.c"
        "${FFRS_NVN_VULKAN_DIR}/tex/nvn_deswizzle.c"
        "${FFRS_NVN_VULKAN_DIR}/xbg_host_bridge.c"
        "${FFRS_NVN_VULKAN_DIR}/nvn_vk_adapter.c"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_blit.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_clear.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_game.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_nvn.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_sampler.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_spirv_ldc.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_spirv_quad.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_spirv_raster.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_spirv_temps.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_spirv_warp.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_stages.cpp"
        "${FFRS_NVN_VULKAN_DIR}/engine/xbg_vulkan.cpp")
    target_include_directories(ffrs_nvn_vulkan_engine PUBLIC
        "${FFRS_NVN_VULKAN_DIR}" "${FFRS_NVN_VULKAN_DIR}/nvn" "${FFRS_NVN_VULKAN_DIR}/tex")
    set_target_properties(ffrs_nvn_vulkan_engine PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON
        POSITION_INDEPENDENT_CODE ON)
    target_compile_options(ffrs_nvn_vulkan_engine PRIVATE -O2 -fno-strict-aliasing -Wall)
    # The engine reads the guest's texture bytes as signed characters, which
    # is not the default on arm64.
    set_source_files_properties("${FFRS_NVN_VULKAN_DIR}/engine/xbg_texture.c"
        PROPERTIES COMPILE_OPTIONS "-fsigned-char")
    # Optional development build: pinned SPIRV-Tools subset is obtained separately.
    # With no source directory, the existing engine and handheld build stay unchanged.
    set(FFRS_SPIRV_TOOLS_SOURCE "" CACHE PATH "Pinned SPIRV-Tools CMake source")
    if(FFRS_SPIRV_TOOLS_SOURCE)
        if(NOT EXISTS "${FFRS_SPIRV_TOOLS_SOURCE}/CMakeLists.txt")
            message(FATAL_ERROR "FFRS_SPIRV_TOOLS_SOURCE is not a complete source directory")
        endif()
        add_subdirectory("${FFRS_SPIRV_TOOLS_SOURCE}" "${CMAKE_CURRENT_BINARY_DIR}/ffrs-spirv-tools")
        target_sources(ffrs_nvn_vulkan_engine PRIVATE "${FFRS_NVN_VULKAN_DIR}/engine/xbg_spirv_inline.cpp")
        target_compile_definitions(ffrs_nvn_vulkan_engine PRIVATE XBG_HAVE_SPIRV_OPT=1)
        target_link_libraries(ffrs_nvn_vulkan_engine PUBLIC dm_spirv_opt)
    endif()
    target_link_libraries(ffrs_nvn_vulkan_engine PUBLIC vulkan)
    target_link_libraries(ffrs_guest_runtime PUBLIC dl m log z vulkan aaudio mediandk ffrs_nvn_vulkan_engine)
    add_library(ffrs_game_window SHARED game_window_jni.cpp game_vulkan_probe.cpp guest_boot_jni.cpp)
    set_target_properties(ffrs_game_window PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)
    target_include_directories(ffrs_game_window PRIVATE "${FFRS_NATIVE_WINDOW_HLE_DIR}" "${FFRS_GUEST_NSO_DIR}")
    target_link_libraries(ffrs_game_window PRIVATE android log vulkan ffrs_guest_runtime ffrs_opus)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    foreach(target probe_rg477m nso_diagnostic ffrs_diagnostic ffrs_game_window)
        target_link_options(${target} PRIVATE "-Wl,-z,max-page-size=16384" "-Wl,--build-id=sha1" "-Wl,--eh-frame-hdr")
        add_custom_command(TARGET ${target} POST_BUILD
            COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/../../../tests/device/verify_eh_frame.py"
                --elf "$<TARGET_FILE:${target}>" --output "$<TARGET_FILE:${target}>.eh.json"
            VERBATIM)
    endforeach()

    # Experimental guest execution belongs to this standalone CLI only. Never
    # link HLE or install its fault handler in the load-only JNI diagnostic.
    option(FFRS_BUILD_RUNTIME_HLE "Cross-build the standalone strict HLE CLI" OFF)
    if(FFRS_BUILD_RUNTIME_HLE)
        set(FFRS_HLE_DIR "${FFRS_RUNTIME_DIR}/../hle" CACHE PATH "Typed runtime HLE source directory")
        add_executable(nso_runtime_hle "${FFRS_RUNTIME_DIR}/nso_call.c"
            "${FFRS_RUNTIME_DIR}/nso_loader.c" "${FFRS_HLE_DIR}/nso_host.c"
            "${FFRS_HLE_DIR}/address_region.c" "${FFRS_HLE_DIR}/mutex.c"
            "${FFRS_HLE_DIR}/exit_registry.c")
        set_target_properties(nso_runtime_hle PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)
        target_include_directories(nso_runtime_hle PRIVATE "${FFRS_RUNTIME_DIR}" "${FFRS_HLE_DIR}")
        target_compile_definitions(nso_runtime_hle PRIVATE NSO_WITH_HOST_HLE=1)
        target_compile_options(nso_runtime_hle PRIVATE -Wall -Wextra -Werror -Wformat=2)
        set(FFRS_HLE_SYSROOT "${CMAKE_SYSROOT}" CACHE PATH "Android compiler sysroot for static C++ ABI archives")
        set(FFRS_HLE_RESOURCE_DIR "" CACHE PATH "Android compiler resource directory")
        if(NOT FFRS_HLE_RESOURCE_DIR)
            execute_process(COMMAND "${CMAKE_C_COMPILER}" -print-resource-dir
                OUTPUT_VARIABLE FFRS_HLE_RESOURCE_DIR OUTPUT_STRIP_TRAILING_WHITESPACE
                COMMAND_ERROR_IS_FATAL ANY)
        endif()
        set(FFRS_HLE_TARGET_LIBS "${FFRS_HLE_SYSROOT}/usr/lib/aarch64-linux-android")
        set(FFRS_HLE_CXX_ARCHIVES "${FFRS_HLE_TARGET_LIBS}/libc++abi.a" "${FFRS_HLE_TARGET_LIBS}/libc++_static.a"
            "${FFRS_HLE_RESOURCE_DIR}/lib/linux/aarch64/libunwind.a"
            "${FFRS_HLE_RESOURCE_DIR}/lib/linux/libclang_rt.builtins-aarch64-android.a")
        foreach(archive IN LISTS FFRS_HLE_CXX_ARCHIVES)
            if(NOT EXISTS "${archive}")
                message(FATAL_ERROR "Missing Android compiler runtime archive: ${archive}")
            endif()
        endforeach()
        target_link_libraries(nso_runtime_hle PRIVATE "-Wl,--start-group" ${FFRS_HLE_CXX_ARCHIVES} "-Wl,--end-group" c m dl)
        target_link_options(nso_runtime_hle PRIVATE "-Wl,--no-undefined" "-Wl,-z,max-page-size=16384"
            "-Wl,--build-id=sha1" "-Wl,--eh-frame-hdr" "-Wl,-z,relro" "-Wl,-z,now" "-Wl,-z,noexecstack"
            "-Wl,-Map,$<TARGET_FILE:nso_runtime_hle>.map")
        find_package(Python3 REQUIRED COMPONENTS Interpreter)
        set(FFRS_READELF "" CACHE FILEPATH "Android LLVM readelf used by the static build gate")
        if(NOT EXISTS "${FFRS_READELF}")
            message(FATAL_ERROR "Set FFRS_READELF to the Android toolchain llvm-readelf")
        endif()
        add_custom_command(TARGET nso_runtime_hle POST_BUILD
            COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/../../../tests/device/verify_runtime_hle_elf.py"
                --elf "$<TARGET_FILE:nso_runtime_hle>" --readelf "${FFRS_READELF}"
                --output "$<TARGET_FILE:nso_runtime_hle>.elf.json"
            COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/../../../scripts/device/build_runtime_hle.sh" --verify-cxx-link
                "${FFRS_READELF}" "$<TARGET_FILE:nso_runtime_hle>" "$<TARGET_FILE:nso_runtime_hle>.map"
            VERBATIM)
    endif()
endif()
install(TARGETS probe_rg477m RUNTIME DESTINATION bin)
