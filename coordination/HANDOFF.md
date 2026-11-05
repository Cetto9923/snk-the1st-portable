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

## 2026-11-05 · T07 运行时导入补齐 + asset_config.json 定位（MiniMax Code）

### 已做到（提交 `4bd1fdc`，分支 `work/snk-the1st-honor-gtpro`）

- **DT_INIT 阻塞已解除**：`nn::audio::AcquireVoiceSlot` 有 9 个整数参数，AAPCS64 把第 9 个
  放在调用者栈上，原来的 register-only 导入契约因此拒绝绑定（`nb_import_bind` 返回
  `NB_UNSUPPORTED`），`nso_retarget_imports` 以 status 5 失败。
  - 证据（nnSdk 反汇编，非猜测）：导出 thunk 在 `sdk.bin` 0x2161e4 处 `ldr x8,[sp]`，
    内部实现在 0x216024 处 `ldr x26,[x29,#0x60]`（`[x29+0x60]` 即入栈帧 SP+0）。
  - 改法：`native_boundary` 新增签名版本 5 `NB_SIG_GP8_STACK1` 与 `nb_import_stack1_gateway`，
    在调用宿主前把 guest 的栈参数槽重建到出参区；宿主侧第 9 参由 clang 按 `[sp]` 读取
    （已用 9 参探针函数反汇编确认 `ldr x0,[sp]`）。
- **导入缺口归零**：`main imports=395 hle=395 unresolved=0`，`rtld 1/1`。
  新增 49 个手写宿主实现（nn::audio / nn::codec / nn::image / movie）与 190 条生成表；
  `AcquireVoiceSlot` 按 nnSdk 语义分配 VoiceType、经第 2 参（出参）写回并返回 bool。
- **真机已跑到资源加载**：HONOR ROD2-W69（`A42BBB5109000333`）上 guest 越过 DT_INIT，
  建线程、初始化 NVN、拿窗口纹理，并成功打开读取
  `app0:/asset/asset_config.json`（6962 字节）。
  APK：`sha256 03ef9aa5158bc3707f80e9c317148d196ba2f91690fd816d7a96215bd1ad40a4`
  （`.local/android-apk/snk-the1st-game-window-debug.apk`，不入库）。

### RomFS 物理布局（本轮实测结论，交给 T07 worker 继续）

- 该游戏不是标准 RomFS。四个元数据区 + 数据区都在同一个 NSP 段里，虚拟偏移：
  dir_hash 0x378238780/0x13c、dir_meta 0x3782388bc/0x928、file_hash 0x3782391e4/0x46a0c、
  file_meta 0x37827fbf0/0x390a7c，数据从虚拟 0 开始（文件 0 在 0x200）。
- `file_meta` 尾部 fm+0x387b58 起是 **24 字节定长记录表**（1526 槽）：
  `[u32 hash_off][u32 0][u32 data_off][u32 0][u32 type][u32 size]`；
  type=3 且 size 合理 = 文件（172 条），type=0 = 目录（size=0xFFFFFFFF）。
- 名字表在 `file_hash` 尾部 fh+0x448a0 起，是**前缀压缩**存储，尚未完全解码。
- **asset_config.json 的真实格式已还原**（引擎的二进制 JSON，main.bin 反汇编）：
  - 引擎读文件后要求首 4 字节 == `"JSON"`（0x4E4F534A），否则打印
    `JSONの書式に異常が見られます(%s)`（字符串 0x5163a0；检查点 0x3fb2cc）。
  - header：`u32 version=0`、`u32 段偏移`、`u32 ?`、`u32 ?`（实测 0x000FFFFF）。
  - 字符串池每项 = `[u32 CRC32][NUL 结尾 key]`，CRC 用引擎自带表 0x52d1fc（初值
    0xFFFFFFFF、不做最终异或），已验证 23 处精确匹配。
  - 哈希表段：`1 字节类型（低 4 位必须 == 4）` + 计数 + `u32` 桶数组（元素是文件内偏移），
    每桶指向 `[1 字节类型][u32 CRC][字符串]`；查询函数在 main.bin 0x3fb4f0。
- **当前卡点**：虚拟偏移 0x201 处的 `"JSON"` 魔数所在文件按记录表只有 6962 字节，
  而它偏移 8 的 u32 = `0x0100041E`（≈16.7MB），引擎在 0x3fb538 越界崩溃。
  ⇒ **那个 6962 字节的文件不是引擎要的 asset_config.json**，或它被分块存储而我们只拿到
  第一块（C 字段很可能不是载荷起点：dev_font.otf 的 `OTTO` 在 C+2，JSON 魔数在 C+1）。

### 下一步（精确命令）

1. 拿到真正的 asset_config.json（全量扫 14.8GB 数据区找 `"JSON"`，或解出块表）。
   判据：首 4 字节 = `"JSON"` 且偏移 8 的 u32 < 文件长度。
2. 补齐剩下的宿主缺口：`nn::image::PngDecoder::Decode` 目前返回失败，
   `nn::codec::DecodeOpusInterleaved` 是返回 0 帧的桩；出画面前必须先真解码。
3. `scripts/analysis/runtime_gap.py` 需要把所有 HLE 源都喂进去（`src/runtime/hle/*.c`），
   否则会虚报未解析。

### 未完成 / 风险

- 尚未出现真机画面证据（还卡在 asset_config.json）。
- RomFS 名字表仍是前缀压缩，未完全解码，路径级 RomFS 供给还没做。
- PNG / Opus 解码仍是桩。
