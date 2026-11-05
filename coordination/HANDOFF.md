# 交接记录 — 空之轨迹 the 1st → 荣耀平板 GT Pro

## 2026-11-05 · T00 基线与复用差距（MiniMax Code）

- **已做到**：确认目标游戏为《空之轨迹 the 1st》（TID 01001E9023920000）；自建 NSP/NSO 解包链路并解出 title key（titlekek_11）；提取 ExeFS 四个模块并解压为未压缩 NSO；建立跨模块导入图，量出与 FFRS 荣耀基线的复用差距；建立新工程工作树并继承基线运行时。
- **证据**：`docs/analysis/2026-11-05-baseline-and-reuse.md`；产物在 `.local/nca/`（不入库）。
- **关键结论**：游戏模块 main 的 395 个导入全部可解析（135 HLE + 260 nnSdk）；新增工作在 SDK 层与 nn::os 缺口；`xbg_*` 引擎胶水与 Falcom 引擎无关，需重写。
- **下一步（精确命令）**：
  1. 改包名：`src/android/app/gamewindow/AndroidManifest.xml` 与 `src/android/app/java/org/ffrs/diagnostic/` 迁到本游戏包名，避免与基线同设备冲突。
  2. 把 `.local/nca/nso/main.bin` 等四个模块与 romfs 数据按基线同构目录放进设备，调用继承的 `guest_boot` 拉起 guest，先看退出码与首个未解析符号。
  3. 按 `coordination/state.json` 的 T02 清单补 nn::os 缺口（先用 `scripts/analysis/module_graph.py` 的未解析名单）。
- **未完成/风险**：RomFS 物理元数据映射未解（T07）；升级档未合并；APK 包名未改；真机一次都没跑过。

## 环境事实（2026-11-05 复核）

- 荣耀平板已连接：`adb -s A42BBB5109000333`，`/data` 剩余 175G（放 3.9GB 游戏数据无压力）。
- 本机有 arm64 Android AVD `pvz2`，可在 Mac 上跑 HLE CLI 做宿主侧验证（FFRS 基线用的就是这条回环）。
- 继承的构建脚本入口：`scripts/android/build_game_window_apk.sh`（出包到 `.local/android-apk`）、`scripts/android/install_honor_game_window_apk.sh`（装机）、`scripts/device/build_runtime_hle.sh`（HLE CLI 静态构建）。

## T01 的两条可选路径

1. **AVD 回环（快）**：用 `scripts/device/build_runtime_hle.sh` 产出 arm64 HLE CLI，放到 `pvz2` AVD 上跑 FC 的 `sora_deploy`，先拿第一个未解析符号与退出码。
2. **真机（最终验收）**：改包名 → `build_game_window_apk.sh` → `install_honor_game_window_apk.sh` → `adb shell am start` → 读 `/sdcard/Android/data/<新包名>/files/guest_boot.log`。

两条路都要先做同一件事：把 `.local/nca/nso/main.bin`、`rtld.bin`、`sdk.bin`、`subsdk0.bin` 与 romfs 数据按基线同构目录布置到设备（基线结构见 `ff-resonance-honor-gtpro/.local/release-pack-20261028/`）。
