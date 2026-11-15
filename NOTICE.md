# Project identity and third-party notices

Sora Native Compatibility Runtime is an independent native-runtime research project. References to game, platform and device names identify compatibility targets; those names, marks, characters, artwork and game materials belong to their respective owners. This project is not an official release and is not endorsed by those owners.

The source publication excludes proprietary games, ROM/NSO input modules, firmware, keys, saves, generated game code and game artwork. Public application releases contain the compatibility runtime and project-owned interface assets. Original game data and game-derived shader bundles are supplied separately by the user. A user must supply their own authorized inputs. No new license for third-party materials is granted by this repository or its private visibility.

Retain existing third-party notices and licenses, including:

- `third_party/opus/LICENSE` (BSD-style), also bundled in APK assets.
- `third_party/lasrecomp/LICENSE` and the headers in its source files.
- `src/graphics/nvn_vulkan/engine/third_party/bcdec/LICENSE`.
- The existing copyright and MIT notice in the NVN headers and other imported files.
- 页写入跟踪 `src/graphics/nvn_vulkan/xbg_dirty.c` 借鉴 nxnative 的 `nvn_dirty.c`，保留 seedds 2026 的完整 MIT 许可声明。
- Optional Android subgroup helper inlining adapts d2r-mobile (MIT, © 2026 jhaizhou), revision `f1e4b081af8ea65d95f0bf490a568cb657c3917e`. Its optional static dependency is SPIRV-Tools (Apache-2.0) and SPIRV-Headers (Khronos MIT-style); their full license texts accompany the pinned source used to build the optional candidate.
- nxnative/Ryujinx and other reference revisions/licenses recorded in `coordination/reports/P-OPT-RG477M-OSS-NOTES.md` and the focused reports. A reference or analysis tool is not automatically part of the distributed runtime.
- Optional AndroidX games-frame-pacing 2.1.3 (Swappy, Google LLC and The Android Open Source Project), Apache-2.0. Its pinned Google Maven AAR is obtained by `scripts/android/prepare_frame_pacing.py`, SHA-256 `a9f83e0cf47d694ed2cea0ae995d5cf7411060d9d4b680610430d03d6b20ea27`. When enabled with `FFRS_ENABLE_FRAME_PACING=1`, the arm64 static library is linked into the existing native library and `third_party/licenses/swappy-Apache-2.0.txt` accompanies the APK. Upstream source is https://android.googlesource.com/platform/frameworks/opt/gamesdk/+/refs/heads/main/games-frame-pacing/ .

No blanket replacement license is assigned to the whole project in this snapshot. Existing per-file and dependency licenses continue to apply.
