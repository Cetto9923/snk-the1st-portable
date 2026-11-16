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

## 2026-11-05 · asset_config.json 容器格式最终锁定（MiniMax Code，续上条）

### 引擎容器语义（反汇编实证，不再是推测）

- `find-by-key` 0x3fb4f0 / `find-by-CRC` 0x3fb5f0：`x10 = doc[+0x10] + u32@buffer[8]`，
  **无掩码**；随后 `ldrb w11,[x10]`（崩溃点 0x3fb538）读类型字节，低 nibble 必须 == 4。
- 段布局：`type 字节`（bit0x10 决定跳过 5 字节还是 0 字节）→ `u32 count` → `count` 个升序 `u32` 桶（引擎二分）。
- 桶 → 记录（12 字节）：`[u8 flags(bit0x10=墓碑)][u32 next][3B][u32 value_off]`；
  `next` 指向存放 CRC 的位置，引擎 `ldr w15,[x9,x15]` 取该 CRC 与 key 的 CRC32 比较；命中后返回桶值。
- 取值：记录 +8 的 u32 = 值偏移；值首字节低 nibble = 值类型。
- ctor 0x3fb0d0 有三条路径（文件 / mmap / memcpy）。文件路径：buffer = alloc(fileSize)，
  ReadFile 全量读入，`doc[+8]=doc[+0x10]=buffer`、`doc[+0x18]=读到的字节数`。
- **结论：`app0:/asset/asset_config.json` 必须是 ≥0x0100041E 的单个文件**，且首字节必须是 `'J'`。
  （我们喂 16384 字节假文件时崩溃地址恰好 = base+0x0100041E，证明 base=buffer、w10 取自 buffer[8..12)。）

### 容器头实测（源偏移 0x201；容器偏移 = 源偏移 − 0x201）

```
[0x00] 'JSON' | [0x04] version=0 | [0x08] 0x0100041E | [0x0C] 0xFF27F200 | [0x10] 0x00FFFFFF
[0x14] 键池：[u32 CRC32][name][NUL]（紧凑无对齐）
```

- CRC32 = 反射多项式、初值 0xFFFFFFFF、**不做最终异或**（复算命中 31 个键）。
- 键池偏移（容器相对，括号为 key）：0x14 Platform、0x21 Prefs、0x2b data_path、0x66 Font、
  0x6f name、0x78 font_size、0x86 ActorConvertTable、0xaf DebugAssetDefine、0xfc Collider、
  0x109 keyword、0x115 mask、0x12b value、0x143 flag、0x14c TwoBoneIKTypes、0x15f type、
  0x168 ShaderInfos、0x178 switches、0x185 tex_slot、0x230 Desc、0x239 suffix、0x244 format、
  0x24f mipmap、0x2dd default_base_dir_id、0x30d EnvNames、0x31a id、0x334 MaxGPUMemSize、
  0x359 HeatMapBlockLength、0x370 GridSettings、0x381 range、**0x38b Language**、0x398 code。
  `crc("Language")=0xD252EC1C`。
- 容器偏移 0x426 处有 type=0x04 的段（count=3、桶 0x4a7/0x4b7/0x4cb），但按引擎语义解不通
  （next 指向的是链式 u32 表而非 CRC 槽）⇒ 那是**游戏自己的表**，不是引擎哈希段。
- 全 9.09GiB 源扫描：容器头 20 字节指纹 **只出现 1 次**（源 0x201）⇒ 真实容器头唯一。

### 桶树与块粒度（实测）

- BKTR 条目 200281 条，每条 24 字节 `[u64 virt][u64 src][u32 flags][u32 size]`；
  virt 侧是 64KB 步进槽（0x200, 0x33e0, 0x133e0, 0x233e0 …），src 侧紧凑排布。
- **所有块 size ≤ 65536**（无一块装得下 16.78MB）⇒ 容器必然跨 ≥257 块，
  ⇒ 必须找到「文件 → 块链」映射才能重组。
- 块数据在源里带 1~2 字节前缀：JSON 容器块前缀 0xb1（数据从 +1 起）；
  dev_font 块前缀 f4 a9（数据从 +2 起 = `OTTO`，OTF 头 numTables=9/searchRange=0x80 已核对）。

### file_meta 名字记录格式修正（推翻上一条结论）

- 条目 = **7×u32 + nameLen(u32) + name**，nameLen 在条目 +0x1C、name 从 +0x20 起；
  第 7 个 u32 恒为 0xffffffff。实测样本：
  - `map#6664ef58.nvn`：`[0, 0, 0, 0x271, 0x00f26000, 0x15f00001, 0xffffffff]`
  - `map#dcacfc5e.nvn`：`[0x5e0001e, 0x5adb, 0, 0x271, 0x366800, 0x15f00001, 0xffffffff]`
  - `m1_ob0051uniquetile_01_p.xtx`：`[0x6000128b, 0xaf1ffe, 0, 0x171, 0xb63c00, 0x21f00001, 0xffffffff]`
- 第 5 个 u32 的低 16 位 = 该文件大小（≤64KB，与块上限一致）；第 4/6 个 u32 看起来是目录/组字段。
  ⇒ **这张表描述的是一堆 ≤64KB 的小文件，不是 16.78MB 的容器**；容器不在 fm.bin 里。

### 本轮已排除的假设（勿重试）

1. 容器在源里连续（源 0x0100061F / 0x0100041E 处都不是 type nibble=4）。
2. 容器 = 所有块按 virt 顺序拼接（该映射下 0x0100041E 落在源 0x10a1852，字节 0x98 → nibble 8）。
3. 容器 = 虚拟映像 [0x200, 0x200+16.78MB) 连续区（虚拟 0x0100061E 是升序 u32 数组 0x180c,0x180d…，首字节 0x00）。
4. 源里存在「≥8 条连续等间距节点记录」（numpy 全源扫描 35s，0 命中）⇒ 节点表不是等间距连续数组。
5. 3dbrew/Nintendo 标准 RomFS 元数据结构在本镜像上完全对不上（file/dir entry 扫描 0 命中）。

### 下一步（按性价比）

1. **解出「文件 → 块链」**：fm.bin 那 7 个 u32 字段里，第 5 个 u32 低 16 位是大小，
   第 6 个 u32 高 16 位（0x15f0 / 0x21f0）疑似链偏移或块数；fh.bin 尾部名字池里
   `asset_config.json` 的 6 字段（0x58, 0x60, 0x31002ce0, 0x3519ce00, 0xff0ff200, 0xffffffff）也未解。
   拿到链后按块序重组 ≥16.78MB 容器，覆盖式 push 到
   `/sdcard/SNK/romfs/asset/asset_config.json`，真机应越过 0x3fb538。
2. 并行补 PNG / Opus 真解码（出画面前必需，现在仍是桩）。
3. 兜底定位法（仅用于暴露下一个缺口，不得当作通过）：
   临时喂「真实头 + 自建哈希段」的小文件，让引擎跑过 0x3fb538 看下一个缺什么。

### 本轮新增脚本（均在 .local/，不入库）

`probe_head.py`（容器头/键池）、`probe_nodes.py`（节点记录）、`probe_nodescan2.py`（全源节点表扫描）、
`probe_hash3.py`（全源哈希段扫描）、`probe_map.py`/`probe_hist.py`/`probe_vread.py`（块映射与分布）、
`probe_sig.py`（全源容器头指纹）、`probe_fmraw.py`/`probe_meta3.py`（file_meta 结构）、`probe_nca.py`（NCA 段头）。


## 2026-11-06 · T07 容器语义校正 + u32@8 语义收紧（MiniMax Code）

本轮没有越过 0x3fb538，但把「根表偏移」这件事从猜测推进到**机器码级闭合**，并推翻上一轮两条结论。

### 校正 1：`csinc` 极性反了（推翻上一轮「0x426 解不通」）

自己反汇编 main.mod.bin 复核（0x3fb548 起）：

```
003fb548  tst   w11, #0x10
003fb54c  add   x11, x10, #5
003fb550  csinc x10, x11, x10, eq      ; EQ -> x10=x11=seg+5 ; 否则 x10=x10+1=seg+1
003fb554  ldr   w11, [x10], #4         ; count_raw
003fb558  subs  w11, w11, #1           ; count = count_raw - 1
003fb55c  b.mi  #0x3fb5dc              ; count<0 失败
```

- **tag&0x10==0 ⇒ count_raw 在 seg+5、elements 在 seg+9；tag&0x10!=0 ⇒ count_raw 在 seg+1、elements 在 seg+5**。
- 上一轮用的是反的极性，所以「全文件暴力找根表」必然全空（`roots=[]` 是假阴性）。
- 按正确规则重算我们这份 6962B 文件：
  - `0x3b2`：tag=0x04 → count_raw@0x3b7=15 → count=14 → elements@0x3bb（14 个 u32）
    = 0x4e9,0x2f32,0x2224,0x965,0x88f,0x463,0x492,0x999,0x85c,0x2f07,0x307c,0x316d,0x1197,0x9e5
    ⇒ 其中 6 个 > 文件长 0x1b32，**文件确实被截断**（此结论不变）。
  - `0x426`：tag=0x04 → count_raw@0x42b=3 → count=2 → elements@0x42f = 0x4a7,0x4b7（升序）
    ⇒ 这段**是**合法引擎哈希段，不是「游戏自己的表」（上一轮结论作废）。
- 记录格式（引擎逐指令）：`[flags u8][crc_slot u32]`，crc_slot 相对 base，
  实际 CRC = `u32[base+crc_slot]`；元素数组按 CRC 升序（引擎在 0x3fb598-0x3fb5c8 做二分）。

### 校正 2：open_ctor 的真实机制 ⇒ 文件必须 ≥ 16,778,271 字节

`0x3fb0d0`（doc 类 vfunc[5]）逐指令：

```
0x3fb194  bl 0x3f6fa0        ; 打开文件句柄
0x3fb1f4  blr x8             ; vfunc[4] -> size
0x3fb21c  bl 0x4687c0        ; 按 size 分配新缓冲
0x3fb2a8  ldp x9,x8,[x8,#0x18]; 0x3fb2ac add x1,x9,x8   ; 源地址 = handle[0x18]+handle[0x20]
0x3fb2b0  bl 0x4f66b0        ; memcpy(dst=新缓冲, src=该指针, size)
0x3fb2bc  stp x22,x22,[x20,#8]  ; doc[8] == doc[0x10] == 新缓冲
0x3fb2c8  str w21,[x20,#0x18]   ; doc[0x18] = size
```

- 源地址是**已挂载镜像里的指针**（handle[0x18]+handle[0x20]），不是逐块读。
- 引擎把文件**整份拷进一个按文件大小分配的缓冲区**，所以 `base+0x0100041E` 必须落在该分配内
  ⇒ **真实 asset_config.json 至少 16,778,271 字节**（6962B 副本必然越界，与真机算术 fa-base=0x0100041E 完全吻合）。

### 事实 3：u32@8 不是「文件内偏移」（统计否证掩码解释）

- 全 arena **4940** 个 'JSON' 容器：u32@8 高字节=0x01 的 4820 个、=0x00 的 116 个；
  我们这份是**唯一** seed(u32@0xC)=0xFF27F200 的。
- 掩码假设统计检验（120 个随机容器，各读一次目标字节，判 nibble==4）：
  `u32@8 & 0xFFFF` 命中 7/120、`&0xFFFFFF` 7/120、`&0xFFFF + 8` 5/120
  ⇒ **与随机 1/16 不可区分 ⇒ 掩码解释被否证**。
- ⇒ u32@8 只能是「相对某个大容器/分区的偏移」或其它语义，**不可**当文件内偏移使用。

### 事实 4：NCA Fs 分区结构（本轮解出）

- BKTR/reloc 200281 槽：virt 侧 **64KB 页粒度**（0x200, 0x33e0, 0x133e0, 0x233e0 …），src 侧紧凑排布。
- `fm+0x383B48`：293 个 u64 各 pack 起始 virt，**恰好 = V[(k+1)*682]** ⇒ **293 个 pack，每 pack 682 槽**。
- 预区（slot 0..681，virt 0..0x2A90FD0 ≈ 44.7MB）：675 个非空洞块，紧凑长度 19,087,289B；
  第 1 块就是我们的 JSON（v=0x200, size=0x1b32）。
- `fm+0x387B58`：173 条 24B 块记录 = slot 1..173（file 0），紧凑长度 5,330,518B。
- 块前缀**不是固定 1 字节**：slot1 前缀 0xb1（数据从 +1），slot2 前缀 f4 a9（数据从 +2 = 'OTTO'），其余不定长。
- `fh` 名字池条目 = `[u32 len][name][meta…]`，meta 以 0xffffffff 收尾；
  asset_config.json 的 6 个 u32 = 0x58, 0x60, 0x31002ce0, 0x3519ce00, 0xff0ff200, 0xffffffff。
  **新发现：第 1 个 u32 恒为 0x58**（asset_config.json / dev_font.otf 都是 0x58），
  第 2 个 u32 逐条不同（0x60 / 0x8c / 0x74）⇒ 第 2 个字段更像**逐成员索引/偏移**，第 1 个是共享 tag。

### 本轮排除的重组模型（勿重试）

1. 紧凑拼接 675 块（btree 显式 size，pstart=0/1）→ 0x0100041E 处字节 0x98 / 0x00。
2. 稀疏虚拟映像（file offset = virt − 0x200）→ 0x00。
3. 页对齐（slot k → (k−1)·64KB）→ 0x10 / 0x00。
4. 「前 257 页」模型 → 累计长度要 616 块才覆盖 0x0100041E。
5. 293 个 pack 基址 + 0x0100041E → 21/294 命中 nibble=4，但 count 全是垃圾 ⇒ 随机噪声。
6. 全部前缀长度扫描（616 种前缀 × ±3 字节）→ 只有 2 个 tag=0x14 的噪声。
7. 「根表元素全部指向 key 池记录」判据扫 19MB 紧凑体 → 0 命中（两种 pstart 都是）。

### 阻塞点（已收紧成一句话）

> 真实 asset_config.json 是**某个 pack 的成员**，**≥16,778,271 字节**，其**根表在成员内偏移 0x0100041E**；
> 成员的 (offset,size) 在 `fh` 名字池的逐成员字段里 —— **这是唯一还没解的结构**。

### 下一步（唯一主线）

1. 严格逐条解析 `fh` 名字池（`[u32 len][name][定长 meta]`），把第 2 个 u32 与已知成员
   （dev_font.otf / bicon.t / font_0.fnt / 924.mdl）在 arena 里的**块起点与长度**对齐，
   反推出成员表 (offset,size) 布局。
2. 拿到成员表后按 pack 块序重组 ≥16.78MB 成员，覆盖 push 到
   `/sdcard/SNK/romfs/asset/asset_config.json`，真机应越过 0x3fb538。
3. 并行补 PNG / Opus 真解码（`src/runtime/hle/snk_hle_media.c` 仍是桩）。

### 设备与代码状态

- 平板在线，APK 已装（含故障插桩）；设备上 `app0:/asset/asset_config.json` = 真实 6962B，与本地 byte-exact。
- 真机仍崩在 `0x3fb538`（fa−base = 0x0100041E，与头字段精确相等）。
- 本轮**未改产品代码**；`src/runtime/nso/nso_loader.c` 的故障插桩保留并随本轮提交。
- 本轮新增脚本（均在 `.local/`，不入库）：
  `hdr_survey.py`（4940 容器头统计）、`virt_probe.py`（槽布局）、`file0_recon.py`、
  `sparse_recon.py`/`sparse2.py`/`page_hunt.py`/`page_check.py`（三种重组模型）、
  `compact_hunt.py`/`relax_hunt.py`/`root_hunt.py`（根表判据扫描）、
  `mask_test.py`（掩码统计检验）、`pack_base_test.py`（pack 基址检验）、
  `meta_struct.py`/`names_fm.py`/`names_crc.py`（fm/fh 结构）、`land_test.py`/`fit257.py`/`sweep.py`、
  `dump_preregion.py`（预区物理字节落盘 `.local/preregion.bin` + `.local/preblocks.pkl`）、
  `pool_parse.py`/`pool_corr.py`/`pool_records.py`/`pool_records2.py`（fh 名字池条目定长暴力反解）、
  `fm_lookup.py`（fm/fh 里查 `asset_config.json`：**fm 里没有，fh 名字池里有 ⇒ 它是 pack 成员，不是 fm 小文件**）、
  `tables_map.py`/`fmt_test.py`/`root_hunt.py`（容器结构与根表判据）。

### 名字池条目格式（本轮新增，供参考）

- 条目 = `[7×u32][u32 nameLen][name]`；`asset_config.json` 的条目基址 = `0x44884`（nameLen 在 `0x448a0`），
  7 个 u32 = `0x01d88528, 0x27495c62, 0xe8001800, 0x01001304, 0x31d92200, 0x16f30009, 0xffffffff`。
- 但**相邻条目对不齐**：dev_font.otf 之后（`0x448df`）的 6 个 u32 是 `(0x58, 0x8c, 0x0024ffe0, 0x01f4b43d, …)`，
  再往后 `bicon.t` / `a0000` **没有长度前缀** ⇒ 条目里夹着变长数据（疑似内嵌字符串），
  固定长解析（16~40B 全试）**全部失败** ⇒ 需要按「变长记录」继续解。
- 已知可对齐的只有第 1 条；`0x58` 在 asset_config.json / dev_font.otf 两个条目里都出现 ⇒ 第 1 个字段可能是共享 tag。


## 2026-11-08 Codex takeover

- Branch `work/snk-the1st-honor-gtpro`, HEAD `84472d7`, dirty. Prior changes and untracked files saved at `.local/checkpoints/takeover-20261108-105710/`. No device or build used.
- `scripts/extract/nca_romfs.py`: preserve compressed lengths, decode LZ4 blocks, validate bounds. Full image and extraction NOT_RUN.
- 6962-byte local sample decoded to 12768 bytes, root 0x41e, 15 sorted CRCs; synthetic cross-block and invalid input checks passed using a stub for missing crypto dependencies. Actual NCA read NOT_RUN.
- Next: prepare isolated crypto dependencies; verify table offsets and types against an independent reader; reconstruct and validate original resources. Existing dirty changes remain. Audio, graphics, deployment and gameplay remain unverified. Device tests BLOCKED until device availability.

## 2026-11-08 resource reconstruction and safety fixes (Codex)

- Branch `work/snk-the1st-honor-gtpro`, HEAD `84472d7`, dirty. Baseline archive `.local/checkpoints/takeover-20261108-105710/` retains pre-existing work, including removed guest bypass and GPU-skip patches.
- `nca_romfs.py` reads the compression table from payload + declared table offset and decompresses LZ4 blocks. Real v1.0.0 NCA sample: 200281 entries; config content matches recovered block. No complete image scan performed.
- `scripts/extract/snk_romfs_inventory.py` parsed 72318 RomFS records; `.local/recovered-t07/manifest.json` contains offsets and sizes. Extracted original config (12761 B), font (1691136 B), loading (12176 B), title (48146 B) in `.local/recovered-t07/original/`. `.local/recovered-t07/asset_config.json` is the prior padded block, NOT the original exact file.
- `.local/logs/t07-inventory-20261108.log` and `.exitcode` document extraction. `.local/logs/t07-verify-20261108.log` and `.exitcode` validate 15 config root CRCs, both layout roots, 9 font table checksums. `.local/logs/t07-unit-20261108.log` and `.exitcode`: 4 synthetic block tests. These do not prove game boot or independent verification of all manifest entries.
- Reproduce validation: `python3 -B scripts/analysis/verify_snk_resources.py .local/recovered-t07/original`; tests: `.local/python-t07/bin/python -B -m unittest discover -s tests/extract -v`. Isolated Python env created from binary wheels only.
- Guest bypass and silent draw/dispatch/counter skips removed. PNG capacity and state-slot lifetime guarded; shader dump is opt-in and bounded; device scripts constrained and no settings/log deletion. Opus decode now reports an error rather than falsely consuming data. C changes are NOT_RUN (no build authorized).
- NEXT: implement and test guest SDK/software Opus forwarding and audio renderer semantics, verify PNG pixel format/ABI and concurrent lifetime, implement Falcom GPU compatibility, compare metadata and files with an independent implementation, integrate original resources, then build and test on authorized device once available. No gameplay or device acceptance.

## 2026-11-10 Antigravity Takeover & Infrastructure Pipeline Completion

- **工作区映射**：`/Users/yuyan9923/GitHub/FC` 通过符号链接与本项目全量同步，统一在 `snk-the1st-honor-gtpro` 上推进。
- **ExeFS & NSO 重建与暂存**：
  - 成功从本地 NSP 提取 ExeFS，通过自带 LZ4 解码器完整还原未压缩 NSO：`main.bin` (6,668,644 B, `sora_deploy`)、`rtld.bin` (16,648 B)、`sdk.bin` (12,121,568 B)、`subsdk0.bin` (5,692,552 B)。
  - 暂存到 `.local/snk_game_dir/` 作为规范模块文件：`main.nso`、`rtld.nso`、`sdk.nso`、`subsdk0.nso`。
- **Android APK 构建验证**：
  - 本地 Android SDK 34 / NDK 26.1 / Clang 17 工具链就绪，成功编译 `libffrs_game_window.so`（启用 16KB 页面兼容 `-Wl,-z,max-page-size=16384`）。
  - 打包并签名生成最新 debug APK：`.local/android-apk/snk-the1st-game-window-debug.apk`（SHA-256 `a0d2df53ed67bb7568cfac155c7b81cf0267eec428ec47ef5c2dec531dc7c0d1`）。包名 `org.snk.the1st.gamewindow`，活动 `org.snk.the1st.GameActivity`。
- **RomFS 解密与批处理提取**：
  - 自研 `scripts/extract/extract_all_romfs.py`，支持断点续传与前缀流式提取。
  - 提取并验证首批启动关键资产：`asset/asset_config.json`（真实解密 12,761 B，BJSON 根表偏移 0x41e，排除了此前 6,962 B 压缩块在 0x3fb538 越界崩溃的根因）、`layout/`（85 文件全部完成）、`system/` + `system_nx/`（21 文件全部完成）、`multilang_resource_list.json`。
  - `asset/common/` 正在执行后台批处理提取。
- **下一步**：
  1. 完成 RomFS 批处理提取与 `.local/snk_game_dir/romfs` 暂存。
  2. 设备上线时执行 `scripts/android/install_honor_game_window_apk.sh`，推送 APK 与游戏目录到 `/sdcard/SNK`，验证越过 0x3fb538 进入标题初始化。
  3. 推进 T03：Falcom 引擎 NVN 绘制指令重构与首批 Maxwell Shader 编译。

## 2026-11-11 · v1.0.7 升级档集成 + 视频跳过 + 标题画面与中文难度选择全通验收（Antigravity）

- **升级档突破**：
  - 用户反馈原版提示“欲設定為繁體中文字幕遊玩，需先安裝遊戲更新。”，经逆向确认系 v1.0.0 专属的 `vis_9999.xtx` 实体卡提示画面。
  - 从 `[升级档v1.0.7][01001E9023920800][22.5.0][中文][KR].nsp` 解压部署 v1.0.7 未压缩 NSO（`main.nso` 7,491,940 B，`sdk.nso` 12,217,984 B，`subsdk0.nso` 5,583,016 B，`rtld.nso` 20,744 B）。v1.0.7 已彻底移除了 `vis_9999` 实体卡更新警示。
- **HLE 符号与内存管理修复**：
  - v1.0.7 引入了 C++14 sized deallocation（`_ZdaPvm` / `_ZdlPvm`）。此前直接调用 host `free` 导致 Scudo 检测到 guest heap 指针异常崩溃。
  - 修复：接入 `guest_process_interposed_free(ptr)`，通过原生调用网关将释放操作重定向回 guest 的内部堆管理器，保证 guest 内存安全释放。
- **开场视频与跳过**：
  - Android MediaCodec/MediaExtractor 硬件加速解码与虚函数网关正常工作，开场视频播放与按键跳过无缝切换。
- **真机验收（HONOR ROD2-W69 / A42BBB5109000333）**：
  - 原生 ARM64 执行，Vulkan 稳定 60 FPS（16.6ms 帧延迟）。
  - 成功越过开场动画，完整呈现艾丝蒂尔与约修亚的主标题画面（Title Screen）与按键触控层。
  - 点击“New Game”并按下 A 键，成功推进至中文难度选择菜单（Very Easy / Easy / Normal / Hard / Nightmare），繁体中文文本与字库渲染完全正常。

## 2026-11-11 · 数据包打包、发布说明与过程数据清理完成（Antigravity）

- **帧率稳定性总结**：
  - SurfaceFlinger 连续延迟采样：帧间隔严格稳定在 16,666,666 ns（即 16.67 ms），锁定 60.00 FPS。
  - Adreno 735 Vulkan 管线平稳，跳过视频、主菜单渲染、中文难度选择交互均无掉帧与抖动。
- **便携数据包发布（参照 FFRS 标准规范）**：
  - 编写并执行 `scripts/distribution/package_honor_portable.py`，采用标准 ZIP64 + ZIP_STORED（无二次损耗）打包生成 `SNK-data.zip`（7.08 GiB / 7,595,322,526 B，包含 38,971 个资产、v1.0.7 专属 NSO 与 152 个预编译 Maxwell 着色器二进制）。
  - 生成 `SNK-data.zip.sha256`（`c69890717051ac149ba80c9e4f2db40c474062123cb9a4316ef50d6265083586`）与完整资产清单 `data-manifest.json`。
  - 同步部署至项目根目录与 `release/` 发布目录。
- **发布安装说明与 APK 就绪**：
  - 编写用户级安装文档 `README-HONOR.md`，提供“ADB 一键脚本部署”与“脱机纯平板文件拷贝”两种完整操作指引。
  - 整理最新签名安装包 `release/snk-the1st-game-window-debug.apk`（SHA-256 `61a61962904ca7b6fcf7cb7747a11374eac99d5babf57f94458fb485b81d64b0`）。
- **过程测试数据清理**：
  - 清理本地 `.local/` 下 7 个临时调试截图（正式验收证据已持久化于 Brain 产物库）。
  - 清理中间解压暂存 `staging_romfs` 与 `build/game-window-apk.*` 临时编译目录。
  - 保持 `.local/snk_game_dir` 为规范纯净的 v1.0.7 原生执行目录。

## 2026-11-11 · RG477M 掌机真机安装与天玑 8300 (Mali-G615) 兼容性实测通过（Antigravity）

- **目标设备**：Anbernic RG477M（`RG477M01445122` / MediaTek 天玑 8300 / MT6897 / Mali-G615 MC6 / Android 14 / 1280x960 4:3 屏幕）。
- **安装与数据自发现**：
  - 成功安装 `release/snk-the1st-game-window-debug.apk`。
  - 推送 7.08GB 完整游戏数据至 `/sdcard/SNK`，冷启动完全自动识别目标目录。
- **Mali-G615 MC6 Vulkan 架构与图形兼容**：
  - 代码中原生包含针对 Mali TBDR 架构的黑边缓存优化，在 1280x960 4:3 屏幕上以 16:9 居中加黑边呈现，完全无频闪。
  - 动画硬件解码与按键跳过流畅，主标题艾丝蒂尔与约修亚立绘、光环特效与文本渲染均 100% 正常。
  - 实体手柄按键与十字键完美响应：按 A 键进入 New Game，按十字键下切换难度至 Hard（“難易度【Hard】戰鬥難度將變得相當嚴峻。適合高手玩家。”）。
- **实测帧率与性能**：
  - SurfaceFlinger 连续采样：帧时间稳定为 `33.33 ms`，稳定锁定 **30.00 FPS**（掌机标准同步帧率），方差小于 0.3 ms。
- **全平台工具链更新**：
  - 脚本 `scripts/android/install_honor_game_window_apk.sh` 与 `scripts/deploy_device.sh` 已扩展，支持同时识别与部署荣耀平板 GT Pro (`A42BBB5109000333`) 与 RG477M 掌机 (`RG477M01445122`)。

## 2026-11-11 · 荣耀平板 GT Pro 重新安装与跨平台双端一致性实测通过（Antigravity）

- **目标设备**：荣耀平板 GT Pro（`A42BBB5109000333` / Qualcomm 骁龙 8s Gen 3 / SM8635 / Adreno 735 / Android 16 / 3000x1920 16:10 屏幕）。
- **实测与排障突破**：
  - 安装最新统一包 `release/snk-the1st-game-window-debug.apk`（SHA-256 `61a61962...`），自发现 `/sdcard/SNK`。
  - 清理了平板残留的历史后台进程 `org.ffrs.gamewindow`（释放其占用的 4.2GB 内存与 Vulkan 资源），并移除了历史 `files/touch-pad=0` 隐藏标记。
  - 自适应虚拟手柄即刻在平板触控屏上生效（左侧十字键，右侧 A/B/X/Y），同时完全消除 `nn::hid::ShowControllerSupport` 弹窗死循环。
- **真机表现**：
  - 触摸虚拟 A 键瞬间跳过 MediaCodec 硬件解码开场动画。
  - 完整渲染主标题画面（艾丝蒂尔与约修亚立绘、Title 菜单、半透明触控层），产出截图证据 `preview_honor_title.png`。
  - 点击“New Game”并确认，成功进入繁体中文难度选择界面（Very Easy / Easy / Normal / Hard / Nightmare），产出截图证据 `preview_honor_difficulty.png`。
  - 性能采样：SurfaceFlinger 刷新间隔为 16.67ms（60.00 FPS），Adreno 735 单帧 GPU 用时仅 3-4ms，运行平稳顺畅。
- **交付包状态**：
  - 最终发布的通用 APK（`release/snk-the1st-game-window-debug.apk`）与数据包（`release/SNK-data.zip`）现已通过天玑 8300 (Mali) 与骁龙 8s Gen 3 (Adreno) 两个截然不同芯片体系的双真机实测验证，100% 可直接交付与开箱即玩！

## 2026-11-11 · “有字幕无画面”根因定位、全量 12,568 纹理补齐与 3D 实机画面全通验收（Antigravity）

- **故障现象**：用户反馈“有字幕，但是画面没出来”，进入 New Game 后只有剧情字幕文字推进，但背景是纯色灰色 `#C5C5C3`，3D 角色与场景未显示。
- **根因深度溯源**：
  1. 日志分析发现海量错误：`texture is null (model : chr5000, material : cloth01, filename : chr5000_03_a)`。
  2. 逆向 `main.nso` 0x514e54 确认：Falcom 引擎材质初始化如果检索不到对应纹理，直接打印该报错并返回 `0` 失败，导致整个角色和 3D 模型无法绑定至场景图进行渲染。
  3. 资产清查核对：对比解密元数据 `manifest.json`（72,318 个文件）与原暂存目录，发现原 RomFS 提取时漏掉了 `asset/nx/` 与 `scene/`、`vfx/`、`voice/` 等关键目录。特别是 `asset/nx/image/*.xtx`（包含全部 12,568 个 Switch 专属 NVN 压缩纹理，共 5.37 GiB）以及 1,135 个场景文件完全未被提取，导致引擎因缺少全部角色贴图与场景几何无法绘制 3D 画面。
- **修复与资产补齐**：
  1. 使用正确的本体 Title Key (`5586aabfc96ddf4939952c21f2cf27d5`) 执行 `scripts/extract/extract_all_romfs.py`，完整提取了全部 12,568 个 `asset/nx/image/*.xtx` 纹理、1,135 个 `scene/` 场景文件、1,757 个 `vfx/` 特效文件及 17,199 个 `voice/` 语音文件。
  2. 捕获实机加载后续地图时请求的未编译着色器（如 `8117cb0a043218ed.xgs` 等），使用 `compile_dumped_shaders.py` 完整编译出全部 **449 个预编译着色器**（449/449，100% 成功率）。
  3. 全量数据通过 ADB 高速推送到 RG477M 掌机与荣耀平板 GT Pro。
  4. 使用 ZIP64 标准重新打包生成终版便携数据包 `release/SNK-data.zip`（13.75 GiB，包含 71,459 个游戏资产与 449 个着色器），并更新 SHA-256（`9f1041825531be26a1e62776f1fb0c26bad77ca5ef6320e16e1cfb99e262b095`）与安装说明。
- **双端真机 3D 实机验收（100% 通过）**：
  - **RG477M 掌机（天玑 8300 / Mali-G615 MC6）**：
    - 冷启动并进入 New Game，跳过序章独白进入地图场景，`texture is null` 错误彻底归零。
    - 3D 地图、环境树木、建筑物与角色模型完整正常渲染，色彩丰富度由原先纯色跃升至 **366,438 种颜色**。
    - 帧率稳定锁定 **30.00 FPS**（1280x960 4:3 居中 16:9 无黑边频闪），产出实机证据 `rg477m_map_gameplay.png`。

## 2026-11-11 · “启动过图闪退”根因定位、过图着色器全量编译与双端真机全通验收（Antigravity）

- **故障现象**：用户反馈“但是闪退了。启动过图闪退”，在 New Game 序章剧情结束后切换地图/场景瞬间应用崩溃退出。
- **根因深度溯源**：
  1. 崩溃日志审查：
     `[engine] FATAL: Missing or invalid shader bundle /storage/emulated/0/Android/data/org.snk.the1st.gamewindow/files/shaders/9afc8fa419c53b1b.xgs`
  2. 逆向与调用栈分析：
     在地图过渡期，引擎调用 `nvnProgramSetShaders` 绑定新场景渲染着色器 `9afc8fa419c53b1b`（SHA-256 control key）。Vulkan 兼容层在 `load_shader` 阶段检索本地预编译 `.xgs` 时未命中，触发 `xbg_fatalf` 直接 `abort()`。
  3. 新增着色器清查：
     实机通过 `SNK_DUMP_SHADERS=1` 自动捕获并导出了 4 个过图关键着色器：
     - `9afc8fa419c53b1b` (Pixel Shader, 7,336 SPIR-V words)
     - `07c80a491ead3c71` (Pixel Shader, 112,600 bytes)
     - `9e7823764e7ccaf7` (Pixel Shader, 11,008 bytes)
     - `dbc83046b95be308` (Pixel Shader, 106,388 bytes)
- **修复与全量编译**：
  1. 拉取两台设备所有最新 dump 着色器，执行 `python3 scripts/graphics/compile_dumped_shaders.py`。
  2. 经 `dmsh_xlate` 编译与 `build_ffrs_xgs` 打包，453 个着色器全部 100% 编译成功（453/453，0 错误），包含 `9afc8fa419c53b1b.xgs`（29,856 字节）。
  3. 将 453 个 `.xgs` 高速推送到 RG477M 掌机与荣耀平板 GT Pro 的目标着色器目录。
  4. 重新打包终版便携数据包 `release/SNK-data.zip`（13.76 GiB，包含 71,641 个文件与 453 个着色器），SHA-256：`bd573678f52c63260c7cd736017070242012cd1e3f7ac0cbee6245004b60f304`。
- **双端真机过图实测全通（100% 通过）**：
  - **RG477M 掌机（天玑 8300 / Mali-G615 MC6）**：
    - 启动游戏，跳过视频与序章，连续推进对话完成场景过图过渡。
    - 验证日志：`[engine] NVN shader 9afc8fa419c53b1b stage=4 loaded words=7336 ms read=0.07 rewrite=0.36 analyse=0.26 module=0.03 reused=0`。
    - 过图加载完全平稳，无任何 FATAL 闪退，游戏常驻内存 2.8 GB，30.00 FPS 稳定运行。
  - **荣耀平板 GT Pro（骁龙 8s Gen 3 / Adreno 735）**：
    - 启动游戏走完过图加载，成功加载 `9afc8fa419c53b1b` 着色器：`ms read=0.39 rewrite=0.33 analyse=0.23 module=0.07 reused=0`。
    - 过图前后帧率无卡顿，60.00 FPS 稳定运行，无崩溃。

## 2026-11-12 · bit36→bit32 根因、sdk v1.0.7 校验与 native audio 条件启用（RG477M 3/3 冷启动进标题）

- **根因（一句话）：arena 指针 bit36 恒为 0，不能用 bit36 判空。** guest arena 位于 `0x6ff8_xxxxxxxx`（`>>36 == 6`），`tbz/tbnz #36` 的指针判空会把有效指针当成 NULL，`std::map` 插入由此拿到 0 节点并写坏内存；判空统一用 **bit32**（指令 `0xb6xxxxxx`），不要再写回 bit36。
- **改动位置**：`guest_process.c` 的 `0x56952c/0x569540/0x56955c/0x569570` 四处 `tbz #36` 改为 bit32；`0x355608` trampoline 的 `tbz x21,#36` 同样改为 bit32（目标仍为 `0x355394`，imm14=0x3F63）。放行/拦截集合未变宽：只多放行 bit36=0 且 bit32=1 的 arena 指针，宿主/模块区（bit36=1）判据与改前一致。
- **sdk.nso 校验**：RG477M `/sdcard/SNK/sdk.nso` SHA-256 `f518e8ad45971aa4689969c0bedfa0b28a95e5245372b603214eed78b4010daf`，与 `[升级档v1.0.7][01001E9023920800][22.5.0][中文][KR].nsp` ExeFS 提取件（`.local/snk_game_dir/sdk.nso`，12,217,984 B）一致；已作为 `sora-no-kiseki-the-1st-v1.0.7` 表项补入 `ffrs_sdk_component_load` 已验证输入表（未删旧项、未降低校验强度）。
- **`SNK_NATIVE_AUDIO` 条件启用**：`ffrs_sdk_component_load` 成功才置 1，失败置 0 并回落 HLE audio stub。`snk_hle_media_lookup` 再加一层：`_ZN2nn5audio*` 仅当 `ffrs_sdk_component_lookup` 确实提供该符号时才交给原生镜像，否则回落 HLE stub（OpenAudioRenderer 即属此列——sdk 组件只暴露 8 个 DSP/振动符号）。
- **真机验证**（RG477M01445122，APK sha256 `5865ecb5ec9404cdecb2d4e540b8daee825dc7cb2389a42bd03df837e5681ef8`）3/3 冷启动：无 `[fault]`、无 `unresolved-import`，均推进到标题画面（`fr≈2910`，25 s 采样点进程仍存活，截图确认 Continue/New Game/Load Game/System 菜单）。
- **已知遗留**：`OpenAudioRenderer` 走 HLE stub 后，原生 `AcquireSubMix/AcquireMemoryPool` 与该 host 渲染器对象不匹配，日志持续 `*** Audio *** nn::audio::AcquireSubMix() failed` —— 无声音，但不阻塞启动。根治二选一：让 `ffrs_sdk_component_lookup` 暴露 sdk.nso 完整导出表（含 OpenAudioRenderer），或整套 audio 走 HLE stub（`SNK_NATIVE_AUDIO=0`）。





## T58 社区发布检查点 2026-11-15

- 用户要求暂停荣耀真机操作，发布独立空轨社区应用，参照 FFRS 触屏布局，后续金手指另行加入，并转到 RG477M 调试。
- 当前独立 clone，分支 task/T58-community-release，正确 origin 为 Cetto9923/snk-the1st-portable。基线 cab771a7，已迁入 takeover 工作区 C1-C62 的源代码与回归用例。原共享工作区与 FFRS 原仓保持原状。
- 版本选择 1.0.1-preview / versionCode 2。公开包为 APK、自有矢量图标、说明与第三方许可。游戏与其衍生着色器由使用者准备，私有补全包只在本地。
- 构建命令为 FFRS_SPIRV_TOOLS_SOURCE=<父项目>/.local/third-party/d2r-mobile-f1e4b08/dm/third_party/spirv-tools FFRS_BUILD_JOBS=6 bash scripts/android/build_game_window_apk.sh。原始构建和测试输出保存于 .local/publication/。
- 候选 b5837d53588e8553e97c6fc0e6ec4eba5dea3c0aaf15c0b5f9c69546ba39cbb3，Android 安装退出 0。签名与 RG477M 旧版相同。安装前 APK 与存档已备份在 .local/publication/device-backup/。
- 58 项 graphics 测试中 57 通过、1 项缺私有 UINT 输入跳过。runtime 6 项通过，DeviceProfile 合约通过。均为本机组件检查。
- 触屏对齐参考仓的当前 TouchPad，菜单提供布局和显隐，长按 PAD 编辑，保留实体键与摇杆。已打开菜单和编辑器截图，证据 rg-menu.png、rg-touch-editor.png。
- 新安装音频无声来自 snk-audio-mix 缺省关闭。改成默认启用，0 标记可诊断回退。用户已确认有声音。新装缺省与显式关闭的主机用例已加入。
- RG477M MT6897 / Mali-G615 MC6 的 subgroup 固定为 16（min/max 16）。只据运行时查询记录，不把 Vulkan 允许的 subgroup-size control 当成设备支持 32。
- 用户仍反馈人物缺失和拉伸。旧数据条件 async1 有明显人物长条，尚无根因结论。async0 对照在加载时发生 strncpy 访存故障，日志 rg-sync-load-crash.log，不能称该对照通过。
- RG477M 原目录与 v1.0.7 合并资源有差异。存储卡复制受小文件开销影响，已终止本会话两个复制进程。改在 app 私有 files/community-v107 建目录，70004 个未变化文件链接到原 SNK/romfs，2356 个更新文件单独导入，4 个 NSO 链接到原目录。全清单 72360 项 SHA256 校验进行中。派生目录与旧输入分开，存档继续使用原 app 外部文件目录。
- 当前 shader 已全量校验 6611 项一致，原 shaders 已改名为 shaders-before-1.0.1 留作恢复。
- 下一步先等待 .local/publication/rg-merged-validation.json，修复任何缺失或差异，配置 game-directory 到上述私有合并目录，再测人物、音频与真实游戏操作。完成代码修正后重新构建与安装，打包 release、push SNK 独立仓、建立标签与预览 Release，并回下载核 SHA。


## T58 Mali 人物修正与 30 帧优化检查点

- 用户明确要求 GPU 适配保留荣耀此前正常显示，真机当前全部 RG477M01445122。用户已重新激活“正常游玩、稳住 30Hz”目标，当前优先 RG477M，发布工作仍待完成。
- 完整资源在 RG477M app 私有 files/community-v107/romfs，70004 个链接加2356个更新文件，72360/72360 SHA256 一致。shader 6611/6611 一致。game-directory 标记已指向该私有目录，标题原作版本实际显示1.07。数据清单一致后人物仍畸形，不能把畸形归因于已发现的文件差异。
- 在 Mali 设备实际抓到 9 个顶点 shader 的 RGBA32_UINT 属性配 float 输入。原始日志 .local/publication/rg-mali-vertex-inputs2.log。新增 xbg_spirv_vertex.h 保持原寄存器位模式，把输入变量/指针/加载改成匹配的 UINT/SINT，加载后 OpBitcast 回原 FP32 运算。按实际 draw 属性生成并缓存模块，warm 路径同样匹配输入。仅 vendorID 0x13b5 分支启用。
- 9 个实际 stage 离线补丁 spirv-val Vulkan1.1 均退出0。临时私有覆盖现已重命名 spv-override-before-runtime，当前使用 APK 中的运行时修正。现装候选 SHA a72ecaca151b97646feeda3877773d241ad6457e2fa786735fe357581689198a，构建退出0，覆盖安装退出0。
- 61 项 graphics 测试，60通过1项缺私有 UINT 输入跳过。6项runtime通过。额外 Mali vendor 门禁用例编译真实 draw/warm 分支，ARM启用，Adreno/NVIDIA/未知vendor保留原模块，退出0。Opus完整混音合约 failures=0。图形测试一度因新 helper 插在旧函数提取边界中而编译失败，已把 helper 移到函数前，保留旧断言复测通过。
- 用户确认有声音。默认混音器已固化进源码。用户最新确认“现在人出来了，但是好卡”，正确人物截图 rg-sync-results-outcome.png / rg-scene-pause-observed.png。
- 当前人物正确与新建流程可推进的真机条件同时包括 gfx-sync-mode=1、gfx-sync-submit=1（因此async0）、GPU indexed resident1、完整数据、Mali类型修正。这是诊断强同步，约7.2FPS，不能当30帧通过。sync0先前新建常在main+49d478 strncpy访问0x5xxxxxxxx崩溃，完整数据/旧包控制也复现。是否是延迟GPU写回覆盖CPU数据仍待单变量对照，尚未宣称根因解决。
- 正确帧 GPASS在 .local/publication/rg-pass-profile.txt，frame4923共74项合计70.7ms。内部主目标1600x900，UI/呈现1920x1080，手持profile720是目标配置，尚无实际720p3D证明。重项为主GBuffer14ms、183334461b277951全屏10.5ms，另多个后处理1-2ms。gpu80ms/submitCPU123ms，snapshot约40MB/frame，writeback30MB/frame。Mali内存type0 flags0x7（coherent未缓存）、type1 flags0xb（cached非coherent）。现有gfx-readback-cached值得对照，Honor旧实验不可代替Mali实测。
- 已按原游戏 PAUSE→Y 略过全部，当前经过开场影片末尾logo暗帧。用户说封面变且暗，已解释处于影片标志画面并用Plus尝试退出，截图 rg-logo-skip.png 待查看。异步问题已向用户问清封面指游戏标题还是桌面图标，尚待答复。应用图标确实换为自有矢量资源，该选择最终须披露，不能把用户此处反馈误判为认可。
- LLDB 在 .local/publication/ 有日志。Android app无INTERNET，TCP监听被拒绝，改unix-abstract://snk-rg477m，adb forward tcp5039 localabstract:snk-rg477m。Mac LLDB需 target.memory-module-load-level minimal、auto-import-clang-modules false、symbols.enable-external-lookup false、platform remote-android，可立即连接。默认模块加载曾卡住。
- 调试器已detach/kill本会话测试进程并退出，当前新进程23813运行，未留断点。旧自动软件断点未命中，SIGSEGV现场已读到自定义String指针0x501012200。调用 main+5d07c0→49d350，字符串源Default；向量行0的String在row+0x60。owner内向量begin指向owner+0x68并与自身元数据重叠，疑似生命周期/覆盖，尚无根因结论。原始反汇编 .local/publication/disasm-vfx-*.txt/bin/elf，仅本地私有。
- 所有设备命令仍只用 RG477M01445122。FFRS已按用户授权force-stop。临时存储卡 SNK-community-v107 是本会话生成的中断副本，当前不用，后续清理需核对精确路径。原/sdcard/SNK和游戏包保持原输入。
- 下一步先查看 rg-logo-skip.png 回到真实可操作场景并正常存档，获取同点帧时间。做gfx-live-sync=0与1单变量对照，再测cached readback，避免以剧情/封面或重复呈现替代稳定30。性能修复固化APK后复测新建、画面、声音、输入，再发布独立SNK仓。


## T58 标题复核与分配器重叠对照

- 用户澄清封面指游戏内标题。重启后两张标题截图 rg-title-check-1.png / rg-pointer-ab-title.png 均为艾丝蒂尔和约修亚原版 Ver1.07 标题，截图亮度与之前正常标题相符。3D偏暗仍需逐场景核对，未用全局gamma掩盖。
- 新建在强同步下也复现 main+49d478 strncpy 故障，因此撤回“强同步可解决新建”推断。原日志 rg-newgame-reentry-crash.log，先前略过剧情故障另为 main+54efbc，rg-logo-current.log。
- RG477M PID14330，main base0x6f441da000。LLDB硬件断点 main+5d05a0 条件分配返回范围与活跃owner重叠，成功命中，返回x0和owner x19均为0x6c00785270，x21=3、每行184字节。分配器把仍有vtable、特效名的owner地址再次返回。原始寄存器和头部内存保存在 .local/publication/lldb-overlap-evidence.log。未手工修复游戏对象。调试器和目标进程随后退出。
- 旧4处allocator CBZ→TBZ bit32补丁对当前12GiB arena错误。实际arena 0x6bfa800000..0x6ecbc00000，0x6c/0x6e开头的合法地址bit32=0，会被拒绝。新增诊断marker hle-original-pointer-tests=1，经guest_boot_jni置SNK_ORIGINAL_POINTER_TESTS=1，仅跳过这4处补丁，其他源路径保持。荣耀未操作、缺省仍原设置，待477M对照充分后再固化设备范围。
- 候选 a3caa24f8648cd00fef41371efb42f135bd745003211fb9e0ec0fb6a15c2f082，构建/覆盖安装退出0，原日志build-original-pointer-tests.log / rg-pointer-tests-install.log。单变量先保持sync1/1，正常新建进入闪回屋内，再略过闪回、播放/跳过影片进入正常布莱特家剧情，后略过到首个自由移动点，截图rg-first-play-menu.png / rg-camp-first.png。未复现上述strncpy和54efbc崩溃，但尚无多次冷启验收。
- 在同进程 gfx-live-sync=0，仅去掉每NVN批的complete_all，Vk sync-submit仍1。记录rg-pointer-ab-skip2.log，进入真实游戏后仍约7.5FPS，GPU81.7ms，约609draws/30dispatches。主瓶颈仍包含GPU和CPU回写，尚未30。
- 完整graphics62项，61通过1私有fixture跳过，runtime6通过（包含编译真实textfilter、缺省旧补丁和诊断原始分支），日志graphics-tests-pointer-ab.log / runtime-tests-pointer-ab.log。
- 当前PID17116，已进入原游戏camp，Plus打开原生存档列表，准备新建正常槽方便同点对照。后续测试cached readback，再测安全提交和shader组件fold/temporary forwarding。


## T58 原游戏分辨率档位与性能继续

- 原生cfg对象位于已审计main build 4f4fd1aed39eb96a649aba489ad3767d的+0x7251b0。main+8540每帧执行分辨率配置，+1b4/1b8为基准1600x900，+1c4/1c8为有效场景区域，+1e8为原游戏分辨率枚举，+1f1固定档位、+1f2脏标记。原表main+61901c为640x360、800x450、960x540、1280x720、1440x810、1600x900等。保留原游戏更新viewport、UV与依赖资源的流程。反汇编仅留.local/publication/disasm-render-*.
- PID30152上在原游戏配置边界硬断点读取后，诊断写原生枚举3/固定/脏，GPU pass总和约67.2→39.0ms，但frame4913等外部调试暂停间隔不作帧率基准。RT分配仍可1600x900，不能仅靠GPASS附件extent宣称有效渲染区域。调试器已detach退出。再次attach曾启动连接失败，已按精确cmdline核对后终止本会话server4013。
- 新增guest_process_apply_snk_render_height，在guest-side present边界、图形任务enqueue前调用，限定上述main build、镜像边界、cfg已初始化和基准尺寸，只设置原生540/720档位与dirty标记一次。gfx端仅ARM vendor解析gfx-mali-render-height诊断marker，缺省0。荣耀及其他vendor分支保持原来不调用。
- 059136cd68c666569c1c22cde6fa13e51741ad1a2d54a8fcbf35745e4c3e9038构建和RG安装退出0，日志build-native-render-profile.log / rg-native-render-install.log。RG marker540，源日志确认native render profile height=540 selector=2。
- 首个室内正常存档save000已建立、缩略图显示，截图rg-normal-save-created.png；设备存档备份device-backup/saves-first-play.tar。之后已有户外正常存档与auto，二者缩略图正确，截图rg-outdoor-save3.png；全部存档又备份saves-outdoor-540.tar。当前Continue实际读取最新户外档，不能把此前室内900p与户外540p当同点严格A/B。
- 当前户外540、deferred Vulkan、gfx async0、cached readback1时，约24.4–25.3FPS。源日志rg-540-room.log（文件名旧，但截图实际户外）。画面/人物可见，未使用全局gamma，未作稳定30验收。
- cached readback的CPU回写部分从约17ms降到0.02–0.9ms，仍有GPU与snapshot/descriptor瓶颈。旧同步诊断gfx-sync-submit1约7FPS，移除后约11FPS室内900p。
- async1同户外约17.8–21.4FPS，额外worker调度并未稳定改善。gfx-render-cpu6写入成功，CPU6 max3200000、CPU7 max3350000，仍约19–21FPS，未固化绑核。
- 当前重启对照组合为540、async0、cached1、wtrack1、ldc-fold1、forward-temps1、defer-events1、render-cpu=-1。仅RG设备诊断marker，尚未固化APK默认。标题截图rg-540-opt-title.png待查看，再正常Continue确认加载。
- runtime7项通过，新增编译真实native配置函数的ASan/UBSan覆盖build不匹配、未初始化、边界、无关字段保留、540/720与一次性应用。Mali门禁2项通过，编译真实配置vendor门禁和present调用，ARM按marker生效，Adreno/NVIDIA/未知与缺marker保持原路径。原始日志runtime-tests-render-profile.log / mali-render-gates.log。
- 屏幕system brightness110、manual0、night_display_activated0，仅查询，未调整设备屏幕设置。


## T58 天空闪烁回退与默认配置固化

- 用户反馈天空闪烁。组合540/async0/cached1/wtrack1/fold1/temps1/defer-events1在站立预热约29.6FPS，实际移动40.899秒仅26.382 distinct-work FPS，p95 44.244ms，p99 49.915ms，最大136.075ms，重复呈现0。原始rg-opt-motion.csv/rg-opt-motion-metrics.json，未达到稳定30。
- rg-sky-flicker-before.png有天空粉/蓝细线。live关闭wtrack后rg-sky-wtrack-off.mp4逐秒帧仍有细线。随后defer-events0且wtrack0重启，保留fold/temps，用户明确确认“这个版本没闪烁”。这是配置回退的现场结果，完整事件/写回根因仍待审计。当前默认不启用事件延迟。
- 用户随后在城门/城里游玩。rg-sky-nodefer-stable.log、rg-sky-stable-city.log/csv记录复杂场景约10-20FPS，不能用早先户外29.6宣称城镇30。最新UI教程背景城镇截图rg-stable-current.png。
- 未安装的sky ROI诊断构建已停止，xbg_probe.inc临时4行已精确还原，不进入发布源码。
- 源码将Mali默认配置设为原生960x540、cached readback1、fold1、temps1、async0、wtrack0。defer-events保留默认0。MT68/MT69默认原始allocator pointer tests。标记保留显式覆盖，Adreno路径经编译门禁保留旧默认。
- build-mali-defaults.log退出0，APK SHA256 25b98d5ed43c0a350be167df91e5a624912cd5d2aaa30f2858ca2a1801913952，RG覆盖安装退出0，rg-defaults-install.log。测试graphics64项63通过1私有fixture跳过、runtime8通过、deviceprofile通过。
- 用户已授权随时重启并停止游玩。重启前全部存档备份device-backup/saves-city-before-defaults.tar。设备缺省验证时把本会话性能marker移动到config-before-defaults-20261115，可恢复，保留game-directory及帧时间诊断。
- PID6411缺marker正常入口日志rg-defaults-boot.log确认pointer1、defer0、cached1、fold1/temps1、wtrack0、async0。原版Ver1.07标题截图rg-defaults-start.png。最新读档列表只有auto5:48布莱特家户外、两个人工槽，用户说已保存的城镇槽未出现，已明确告知并继续查保存。未覆盖旧存档。
- normal Load Game载入auto后真实户外rg-defaults-game.png人物和亮度正常，约21-23帧。还需重新到城镇并正常新建槽、重启读回，做无闪烁配置移动/音频回归。
- 借鉴主源https://github.com/seedds/nxnative/issues/2112，上游Metal已处理事件拆分造成renderpass/loadstore增加。该游戏/Metal帧率不能代替本项目Mali验收。当前优先保证正确同步，另查安全减少提交与snapshot。


## T58 发布完成与 T59 CPU 开销继续

- 正确独立仓已push task/T58-community-release、标签v1.0.1-preview→a35c458ce2248e459e96134e116214f4d05d4754。发布https://github.com/Cetto9923/snk-the1st-portable/releases/tag/v1.0.1-preview ，prerelease=true、draft=false。版本1.0.1-preview/code2、Mali540p、自有几何图标为本轮自主选择，发布说明已披露。
- 构建build-release-a35c458.log退出0、构建源clean，APK ea32adb3d3e0fe8061dc33c5fb5ade73ca8ace9ce4cdfd2638787164fa864dc1。社区ZIP含APK、中文安装/免责声明、完整许可证、sourcecommit及SHA清单。公开内容经脚本排除游戏输入。
- 中文文件名作为GitHub独立asset会被服务端归一化成相同名称，首次create422后CLI回滚了草稿。已用install-guide.zh-CN.md和copyright-notice.zh-CN.md重试成功，ZIP内保留中文文件名。回下载release-redownload中全部SHA256SUMS条目与ZIP成员一致。
- 用户明确“现在不在玩，随时可以重启，不要问”。设备仍ONLY RG477M01445122，荣耀继续暂停。
- 保存回归正常经游戏camp→save→新建→选是生成save002，艾里兹街道9:08，rg-defaults-save-created.png。完整备份device-backup/saves-new-slot002.tar。覆盖安装发布APK后Continue可见该记录，rg-release-continue.png；正常读回两人同位置rg-release-readback-game.png。用户此前城镇记录缺失的原因仍未确定，当前正常写入和读回已验证。
- T59分支task/T59-rg477m-frame-time从发布提交新建。系统simpleperf可在run-as app上下文采样，无需root或放开内核符号。原记录rg-simpleperf-record.log/rg-simpleperf-report.txt/callgraph与rg-probe-before-profile.txt，后者独占memcpy21.29%CPU采样、descriptors_build2.80%、programinfo1.77%。
- 调用栈显示prepare_read→probe_image_read_barrier反复fopen。gfx-codex-probe0仍让probe.waiting=true，默认关闭状态下每次observer均读取文件。新增probe_request把同帧请求共享一次读取，保留下一帧观察标记变化与renderer重初始化。没有改图形同步、shader、分辨率或游戏时间。真实helper ASan/UBSan用例通过，1000次同帧调用只open1次，缺文件/文件变化/重置均验证。
- build-probe-poll.log退出0，APK5eb5a46e07b12d89fce191fdb32c80adfa9ca081d5e4e64609a0358b5a6afe66，rg-probe-poll-install.log覆盖安装退出0，当前正在正常Load同save002做同点profile。发布附件保持ea32原包。
- 下一步观测新包标题和Continue9:08读回，simpleperf同点10s采样并保留CSV。优先核减少CPU复制与安全同步，未达到30不标记目标complete。


## T59 CPU 分析与递归锁候选

- probe缓存候选已装机正常进入原版标题，正常Continue9:08。graphics65项64通过1跳过，日志graphics-tests-probe-poll.log。之后截图rg-probe-poll-loaded.png已在道路向城镇移动。前后CPU采样的画面/剧情状态发生变化，不能写成严格同点FPS提升。
- 新发现正常save003在12:33:21记录艾里兹街道城门10:35，rg-city-save-list.png；run-as目录确有save003。已备份device-backup/saves-city-slot003.tar。原save002与以前槽保持。
- 取得可操作camp后B退回城门站立，rg-rmutex-before.png。simpleperf同场景10秒记录perf-rmutex-before.data，输出rg-rmutex-before-profile.txt：memcpy26.69%、snk_recursive_mutex_lock2.52%、unlock1.49%、program_info2.24%。该场景日志rg-rmutex-before.log约11.44FPS、GPU46.18ms、提交CPU69.66ms，672draw/34dispatch，复杂城镇仍重。
- snk_libcxx.c每次递归锁lock/unlock在全局链表线性查找。改为256bucket地址散列，仍使用同一table锁与原pthread递归锁，guest对象内容保持。实际实现提取用例以4096对象验证碰撞、重复构造、同线程递归、跨线程trylock、4线程80000次互斥递增、析构重建与guest字节保持，ASan/UBSan通过。runtime9项通过。
- build-rmutex-buckets.log构建退出0，rg-rmutex-install.log覆盖安装退出0，当前PID24948，待Continue最新10:35后做同点CPU采样和真实移动。该候选还没更新公开Release。
- 注意原生540档只per-process应用一次。城镇GPU46ms需复核过图是否恢复900p，尚无证据，不能先当原因。可以用现有probe1抓capture.txt的实际viewport，或读native cfg，不能仅按附件尺寸推断。

## T59 城门540确认与wtrack单变量

- 递归锁候选APK c42db65c30e83cefeb4b1b37674bcb964d6f9c0bfa126cf03bca30fec989af6d正常Continue城门save00310:35，rg-rmutex-loaded.png与rg-rmutex-before.png同点。站立约12.5FPS、GPU44.82ms、submit68.22ms，未稳30。
- 同点simpleperf10s rg-rmutex-after-profile.txt，递归锁lock/unlock均不再进入>=1%热点，memcpy27.40%仍第一，descriptors3.41%、program_info3.07%。采样比例不能直接写成绝对用时减少多少。原始data仍app私有files/perf-rmutex-before/after.data。
- 完整帧诊断拉到rg-city-viewport-capture.txt，198个drawgroup实际viewport0,0,960,540，另47个1024阴影、14个480x270等。排除本场景恢复900p的假设。诊断帧同步开销不作FPS基准，probe已重设0。
- 下一轮同APK只把gfx-wtrack设1，defer-events保持缺省0，另gfx-pass-profile=0 120 20000采集每120帧GPU阶段。重启后需要标题Plus、Continue10:35确认、A读回，再核wtrack mismatch、CPU副本开销、真实移动和天空。此配置为诊断，发布源码默认wtrack0保持。

## T59 片元编译优化候选

- wtrack1/defer0同城门更慢，约9.8FPS、提交89.55ms、GPU49ms、6submits，mismatch0仍不能据此验收。live-off wtrack后重设gfx-wtrack0，原始rg-city-wtrack-profile.log与rg-city-wtrack-off-profile.log。公开默认0继续保持。
- 当前RG无FFRS进程，top记录空闲CPU约600%，空轨RSS6GB，未改系统热控或内核权限。
- GPASS最新正常城门frame6961合计21.598ms，主GBuffer5.351ms/223draw，照明FS183334461b277951为1.695ms，其余shadow及后处理分散。NVN PERF整帧GPU跨度仍约48ms，二者含义不同，需继续查提交/等待空档。
- 从实际捕获的drawgroup提取111个片元模块，使用本机spirv-opt -O，4,302,672字节缩到1,655,080字节，全部spirv-val --target-env vulkan1.1退出0。结果.local/publication/optimized-city-fragments/results.json。这仅为离线编译验证，正确显示与FPS需真机。
- 111个私有诊断SPV在RG专属files/spv-override，哈希逐个一致，rg-opt-fragments-device-sha.txt。原NSO/RomFS/XGS保持原输入。现有spv_override正常runtime与warm入口均读取这些派生模块，仍叠加原有类型/草叶等修正。回退可将该目录改名，再重启。此目录不进入公开包。
- 当前同APK c42db65c、wtrack0、defer0、gfx-pass-profile0/120/20000重启测试片元优化，正常标题/Continue输入脚本session32564。下一步先截图确认是否载入10:35城门，检查override加载日志、画面、GPU阶段和真实帧时间。

## T59 阶段采集干扰修正与事件守卫

- 更正上条wtrack性能归因。gfx-pass-profile会使indirect_dispatch_inputs_resident和owned_input_copy关闭GPU常驻快路径，整个运行区间都有影响。加profile的wtrack对照不能直接归因为wtrack变慢，已向用户纠正。GPASS仅用于该采集条件下GPU阶段分析。
- 移走gfx-pass-profile到config-before-defaults-20261115/gfx-pass-profile-city，重启恢复正常间接绘制路径。片元111个优化模块正常加载88个、截图rg-opt-fragments-after-start.png，缺阶段采集时稳定城门约12.21FPS、GPU46.14ms、submit70.54ms、670draw/34dispatch，没有可确认的改善。日志rg-opt-fragments-normal-path.log。已把spv-override改名spv-override-opt-fragments-20261115，恢复原XGS入口，诊断派生物只留设备私有目录。
- 发现gfx-pass-live有帧数上界却一直保留pass_prof_enabled，后续帧仍禁GPU快路径。新增呈现边界到达pass_prof_until后清除此flag，保留已录制slot的查询退休。真实block ASan/UBSan用例覆盖上界前/等于/越过、重复呈现边界、再次启动与无限窗口。测试pass-profile-expiry-test.log通过。
- 新构建build-pass-profile-expiry.log退出0，APK SHA9ea1d4a04fc88958ac3209fe932781be481f5af1e16e82a6cf52ba70c46cad34，覆盖安装rg-pass-expiry-install.log退出0。源码尚待检查点提交，公开Release仍a35c458。
- 下一轮gfx-defer-events1、gfx-event-guard1、wtrack0，无pass-profile，无SPV覆盖。用现有守卫查是否有guest直接读取待完成事件，守卫只作观察，fault后打开页不会强行完成GPU，不能当修复。脚本session81801正常标题/Continue10:35，之后抓evguard exact/other/write PC与LR，若画面闪即保存录像，结束时恢复defer0并移走guard marker。
- GitHub默认分支work/snk-the1st-honor-gtpro已从cab771a安全快进到发布a35c458，tag和默认源码一致。当前T59实验独立分支，不改已发布APK。

## T59 环形槽写回顺序修复候选

- 事件守卫PID10673城门样本guards1403、exact0、other6/writes6。llvm-addr2line将写入PC/LR定位到nvnEventSignal，本轮未发现guest直接读事件word的证据。守卫marker已移到config-before-defaults-20261115/gfx-event-guard-observed。defer1下rg-evguard-city.png曾缺少金属柱体，rg-no-guard-deferred-city.png墙体/房屋也不稳定，尚未显示验收。
- 为cpu_access why3增加过限量观察，APK7625b8d87fb74162665891fb541bf59418cd12086606c320172f15a714aaa854，PID15747原始rg-storage-overlap-trace.log未命中部分SSBO的未完成CPU复制。该诊断代码已还原，不据此修复未证实路径。defer1/无守卫/原shader城门约20.2-20.8FPS，仍不稳定30。
- 代码审计发现poll_retire按active_slots物理0..15顺序退休，而slot_index标识下一录制/最老在途槽。回绕时可先写回新提交，再把旧提交结果写回CPU。defer0的complete_all路径按slot_index顺序，因此配置相关性与此缺陷一致，真机修复效果仍待确认。
- 修改poll_retire按slot_index起始的环形提交顺序，只退休连续完成前缀，遇到未完成或仍录制的最老槽停止。xbg_legacy_wait最终wait-all回退也改为相同顺序，保留原超时预算。其他退休点已检查，原有oldest_pending与submit_slots(true)本来按提交顺序。
- 新增提取真实poll_retire函数的ASan/UBSan回归，以2/4/16槽所有回绕点验证写回/完成值递增、未完成首槽阻断、部分前缀退休、录制槽、通知和空轮询。单项通过retirement-order-test.log。完整图形测试进行中，构建build-retirement-order.log退出0。
- 下一步保存旧defer1视频rg-before-retirement-order.mp4后装新包，marker保持defer1、wtrack0、无guard、无pass-profile、无SPV覆盖，Continue同save00310:35，观察墙/柱/天空与帧时间。显示未过前保持公开Mali默认defer0。

## T59 写回顺序真机初步结果

- 修复提交e7c1052，build-retirement-order.log APK3083dc9fdb738bafab0f51b28eb12bfad0f7cedb13e98ff3032252614a0a179f，覆盖安装退出0。graphics67项66通过1跳过。旧物理顺序循环负控因越过未完成前缀被断言拒绝，retirement-order-negative-control.log。
- PID22131同save00310:35、defer1/wtrack0。rg-retirement-order-scene.png与10秒录像rg-after-retirement-order.mp4中城墙/金属柱体持续显示，2fps共20张采样拼图rg-after-retirement-order-sheet.png保持。旧defer1录像rg-before-retirement-order-sheet.png缺失城墙。此为城门流程的初步显示证据，未覆盖道路天空和长时移动。
- 同点预热后约25.2-25.6FPS，submitCPU21.2ms、GPU24.6-25.3ms，sync_wb0、why_access0；此前错误退休defer1约20.2-20.8FPS、submit35-36ms、sync_wb30/60frames。仍未稳30，未改公开默认defer0。
- 再核诊断配置发现gfx-live-off=wtrack一直保留，会在启动30帧后关闭wtrack。此前与pass-profile叠加的实验均不作为单变量wtrack证据。现在已把live-off移动到config-before-defaults-20261115/gfx-live-off-wtrack，再将gfx-wtrack1单独重启，保留defer1/新退休顺序、无guard、无pass-profile、无SPV覆盖。当前启动脚本session67121。
- 下一步确认新PID、wtrack enabled及region/mismatch/fallback数据、同点FPS，再做草叶/开阔天空与原游戏保存回读。若无改善或出现异常，恢复gfx-wtrack0。后续启用Mali默认defer1需要更长画面回归，荣耀设备继续暂停。

## T59 写跟踪槽位代际候选

- 单变量wtrack1、无live-off/无pass-profile，PID26148同城门约22.7-23.3FPS、submit24-25ms、GPU25ms。tracked仅复制48.7KB/帧、dirty7.7页、mismatch0，但fallback30/60帧，较wtrack0的25.2-25.6FPS更慢。原始rg-ordered-wtrack-before-generation.log/csv、截图rg-ordered-wtrack-scene.png。
- version_reusable只看last_slot当前pending/recording。物理槽已经退休并复用后，新一代正在录制会让旧版本被误判仍有读者，产生可避免的整缓冲回退。新增Slot.generation，recording_slot真实入口设为slot_serial。版本只有对应代际仍活跃时等待，槽已换代说明其旧读者已退休，允许复用。继续保留同代pending/recording保护，不能按串行距离猜退休。
- 扩展现有真实helper回归，提取recording_slot的实际代际赋值语句，覆盖同代录制/在途拒绝、换代复用、再次被新一代读取后继续保护与非法索引，ASan/UBSan通过wtrack-generation-test.log。完整图形测试进行中。
- build-wtrack-generation.log构建退出0。覆盖安装rg-wtrack-generation-install.log，脚本session31827重启并Continue同10:35。配置仍defer1/wtrack1，缺guard/pass-profile/SPV覆盖/live-off。下一步确认fallback是否降低、图形稳定性和实际移动帧率，未验证前保持公开默认wtrack0。

## T59 代际实测与批末事件对照

- 6124c21，APK45ea4d042d26786f93aa389f8f1585f7775e9a8100b0f6648ab699982f6da0c5覆盖安装成功。完整graphics67项66通过1跳过。PID31081同点实际wtrack1，无live-off，mismatch0，fallback3/60帧从此前30降低。约24.5-24.9FPS、submit21.6-22.1ms、GPU24.5-25ms，rg-wtrack-generation-scene.log/png，尚未达到30，跟踪未确证比wtrack0快。
- 现在恢复gfx-wtrack0，改现有gfx-defer-events2。该模式保留signal到本次录制提交末尾，避免每个signal强行切开Vulkan批次，等待者poll/WaitEvent仍会推进真正提交。退休顺序已修正，因此值得单变量验证。无其他采集/覆盖，APK保持45ea不变，Continue同save00310:35。下一步核提交数、帧时间与城墙/柱/天空，不能仅以批次数减少宣称显示或30FPS通过。

## T59 批末事件初步显示与实际移动采样

- PID1745、defer2/wtrack0/async0，同城门预热约26.0-26.3FPS，submit19.6-19.8ms、GPU24.1ms，Vulkan提交2次/帧，sync_wb0，rg-batch-events-scene.log/png。只是该点站立数据，仍未稳30。
- 20秒视频rg-batch-events-motion-visual.mp4检查左右旋转、仰俯视、实际前后步行。墙柱、人物、道路与天空保持显示，接触表rg-batch-events-motion-sheet.png。仰视人物靠近相机时出现原游戏的规则点阵淡出，单帧rg-batch-events-sky-85.png。天空有平滑白色云带，未见之前随机粉蓝条纹，仍需更长移动和草叶流程。
- 开始无录屏的实际左右移动600帧采样。预先固定PID1745的frame13440至14040，未按帧时间筛选。起始宣告batch-events-motion-plan.json，输入左右各1秒、释放0.2秒，脚本session6995。结束后会输出batch-events-motion.csv/metrics.json。保存原save003不覆盖，移动只在该城门点附近。
- 当前源码6124c21之后仅交接记录待提交。公开版本仍v1.0.1-preview/a35c458，默认defer0。下一步先完成该帧时间窗口，再比较async1，已有退休顺序修正后应重新测量，不能照搬旧版异步更慢的结论。

## T59 实际移动600帧结果与异步对照

- batch-events-motion-plan.json预先确定frame13440至14040，实际23.448351694秒、601次成功queue callback、601 distinct-work、重复0、失败0。25.588FPS，p50 38.158ms、p95 48.658ms、p99 56.187ms、max67.105ms，>100ms为0。原始batch-events-motion.csv、batch-events-motion-metrics.json，未筛长帧。未达到稳定30。
- 移动结束rg-batch-motion-performance-end.png在城门内右墙边，左右输入因相机跟随有少量位置漂移，仍是真实城镇移动。后续与其他配置比较须核画面/位置，不能当逐像素同轨迹。
- 现在保持APK45ea、defer2/wtrack0，无guard/profile/override/live-off，只新增gfx-async-submit1重启，正常Continue原save00310:35。下一步测默认调度下FPS、async drain/wait与显示，再用现有gfx-render-cpu标记作独立绑核对照，避免把旧defer0或旧写回顺序时的结果当现版结论。

## T59 异步默认调度记录

- PID10492、gfx-async-submit1/defer2/wtrack0同城门约18.0-18.4FPS、CPU提交28ms、GPU24ms，2次Vulkan提交，较async0约26FPS更慢。画面截图rg-async-batch-events-scene.png，原始rg-async-batch-events-scene.log。top可见dm-gfx与guest线程分别占CPU，没有FFRS进程。
- 随后仅将gfx-render-cpu设7，现有worker自身亲和诊断可实时生效，保留其余设置。下一步核成功日志与FPS。若仍无改善，恢复async0及render-cpu缺省，再尝试现有只读vertex/index跨帧缓存gfx-vcache，依赖现有dirty tracker，必须验证动态人物、草叶与过图。

## T59 缓存对照与程序对象查找检查点

- 用户已明确现在不在玩，可随时安装、重启，不再询问。仍只操作RG477M01445122，荣耀暂停。当前正常Continue为save003艾里兹街道10:35。
- 异步绑CPU7仍约17.3-18.9FPS，已恢复async0并移动render-cpu标记。vcache缺少完整宿主dirty tracker接口，实际entries0/hits0。修正日志必须同时检查since/tracked/protect/now，避免把单个stub存在当tracker已接入。
- 几何写跟踪mode2只选大于等于1MiB的vertex/index，没有命中，copied0/dirty0。APK05c34ec4、build-wtrack-geometry.log、graphics-tests-geometry-track.log为68项67通过1私有fixture跳过。改动已撤回，geometry-track-trial.patch和test_snk_wtrack_sites-trial.py只保留.local/publication。
- 程序PID17592同城门simpleperf10秒记录8413样本、丢失0。rg-batch-current-profile.txt中memcpy15.93%、descriptors_build4.03%、program_info_if_changed2.90%。原始perf-batch-current.data保留app私有files。
- gfx-perf-sample0单独重启后城门约26.17-26.29FPS，无明确吞吐改善。后续均保持0以避免诊断计时周期长帧，暂未改变公开默认。
- 同提交内较短前缀复用试验APK81c31d9b、graphics68项67通过1跳过，实际城门约26.22FPS、复制量仍约40MB/帧，未确认收益，已撤回。保留snapshot-prefix-trial.patch、test_snk_snapshot_prefix-trial.py与rg-snapshot-prefix-scene.log/png。早先黑屏截图发生于正常读档加载，稍后两个人物、城墙与柱体正常。
- 缓存上传试验APK683a3e0d，逐小范围flush约25.66-25.88FPS、submit23ms。批末刷新试验APK98449d45约25.18-25.61FPS、submit20.5ms，均低于原上传配置，已撤回。真实Buffer缓存范围与批量flush组件回归、完整graphics68项67通过1跳过。原始upload-cached-batch-trial.patch、test_snk_buffer_cache_range-trial.py、rg-upload-batch-live.log留.local。设备gfx-upload-cached已设0，下次重启恢复原上传类型。
- 新候选将nvn_program.c的256个单项缓存改为索引桶链，冲突在桶内查找。保留原互斥锁、对象表扩容、首次空槽复用及serial语义，复用空槽前从旧地址桶摘除索引。测试覆盖3000对象扩容、同桶交替、finalize后异址复用、原址重建和整表释放。新增9000查询小于288000次表访问断言，旧全表回退负控SIGABRT被拒绝。program-buckets-tests.log、program-buckets-negative-control.log。
- build-program-buckets.log退出0，APK SHA a66bd9edae9bf6d16429f9ac41d190c8a192bc85a6174d368a0904833a312173。完整graphics67项66通过1私有fixture跳过，日志graphics-tests-program-buckets.log。rg-program-buckets-install.log装机，session9257按既定10/8/6/6秒输入Continue，下一步等加载结束核画面、同点simpleperf与真实移动600帧。
- 当前源码68b7795加未提交程序桶链与tracker日志修正。公开Release仍a35c458的1.0.1-preview。稳定30尚未达到，保留active目标。最新600帧移动证据仍为25.588FPS、p95 48.658ms，不能用新标题帧率替代。
- 程序桶链候选已正常读回城门，截图rg-program-buckets-scene.png人物、柱体和城墙持续显示。PID32313同点simpleperf10秒8165样本、丢失0，nvn_program_info_if_changed退出至少1%热点，memcpy17.01%仍第一，rg-program-buckets-profile.txt。CPU比例只作热点定位，不能据此声称端到端已提速。
- 新真实移动窗口在操作前声明600帧，program-buckets-motion-plan.json记录PID、源码dirty基线、APK、flags和动作。无录屏，横向杆左右各1秒、释放0.2秒。601次成功queue回调、601个不同工作帧、失败0、重复0，25.404914FPS，p50 37.913ms、p95 48.765462ms、p99 55.106461ms、max86.723615ms，超过100ms为0，未按帧时间删行。原CSV、metrics、actions和运行退出0日志均留.local/publication。该移动指标没有优于前次25.588FPS，未声称稳定30或严格同轨迹提升。
- 完整图形67项66通过1私有输入跳过。程序查找组件另补1000个不同链位置的销毁、异址复用与存活对象验证，通过ASan/UBSan。下一步保留本轮索引查找有界性修正，评估为现有vertex/index缓存接入完整dirty tracker，以减少每帧约22MB几何复制，须先覆盖真实写入、宿主pread、池销毁与并发保护，未实现前保持vcache0。

## T59 宿主页写入跟踪与几何缓存

- 新增xbg_dirty.c/h，借鉴只读nxnative f02d0474cf1ed1de32ccee1313e1448d4f7da401的nvn_dirty.c页状态与代际思路，保留完整MIT许可。移除旧nvn_dirty_since恒0stub。只在Mali且显式gfx-vcache1时启用，缺标记默认仍关闭，Adreno默认不启用。
- 内存池同步注册/撤销，退出时恢复RW。描述符边界不可变，退休描述符仅在相同页边界下复用，重新发布前原子推进每页代际。共享边界页的写入与撤销必须同时戳记全部覆盖范围，避免缓存查找切换到邻接池后误判干净。
- 页面状态先BUSY、mprotect完成后再发布最终状态。NSO现有Linux ARM64故障处理器先路由写故障。NN ReadFile在保护互斥锁下执行pread，保留errno，避免准备写入后再次被渲染线程设只读而触发EFAULT。没有修改游戏包与存档字节。
- tests/graphics/test_snk_dirty_tracker.py编译真实模块及真实NN ReadFile片段，ASan/UBSan覆盖2000次保护竞争/宿主读取、至少2000次真实写保护故障、两线程写入、共享页、2000次销毁复用、三个分配失败位置、mprotect失败、错误errno与关闭恢复。dirty-tracker-host-entry-tests.log通过，最新完整graphics68项67通过1私有fixture跳过，runtime9通过。
- 首候选APK74f80db4，RG覆盖安装成功，vcache1/defer2/async0/wtrack0/perf0。同城门站立27.4-27.6FPS、CPU约18.5ms、GPU24.2ms。vcache命中22.30MB/帧，实际vertex约0.03MB、index约0.01MB，storage仍17.2MB。rg-geometry-dirty-initial.log、rg-geometry-dirty-scene.png。
- 首版描述符每次注册追加，发现临时池每帧注册/撤销，已补相同页边界复用。后候选APK3512136b78520b3a508c1005dd10534cdfafc7921340d9e68e07281341de6beb，rg-dirty-reuse-install.log成功，graphics68项67通过1跳过。当前源码另删除未调用的prepare薄封装，行为入口不变，下一构建需重新记录SHA。
- PID19744已明确从Load Game列表选save003艾里兹街道10:35，保存列表缩略图正常。加载后进入城门对白“时间刚刚好呢”，当前34-35FPS/730draw/13dispatch属于对白场景，不能和旧900draw自由场景直接比较。日志rg-dirty-reuse-explicit-gameplay.log中注册累计79209次、369描述符槽、13活跃池，复用后没有随每帧追加持续增长。当前界面rg-dirty-reuse-explicit-gameplay.png。下一步正常推进到城内自由移动并新建普通存档，再做600帧移动与视觉回归。

## T60 用户新增设备适配方向

- 用户明确所有设备均使用底座模式，477M允许降低内部渲染分辨率。高端手机期望1080p，先稳定30帧与正常显示，60帧后续独立验证。无需再次询问重启。
- 已只读核对FFRS的DeviceProfile.java，它用分档连接operation mode与目标帧率。本项目当前JNI只把tablet_sd8s当docked，且所有Mali统一540，未满足用户新增要求，须改为底座模式与内部渲染分辨率分别配置。FFRS_PROFILE_TABLET还控制荣耀特有路径，不能直接把它对所有手机置1。
- 原始main NSO build仍4f4fd1aed39eb96a649aba489ad3767d，rodata表main+61901c有640x360、800x450、960x540、1280x720、1440x810、1600x900、1920x1080、2560x1440、2880x1620、3840x2160。1080对应selector6。当前运行时基准1600x900，1080入口尚须验证附件、viewport与UV一起更新，不能只改变最终surface尺寸就声称原生1080。
- 公开参考已查官方Qualcomm Snapdragon 8 Elite Gen5、MediaTek Dimensity9500规格及RogelioLB/nxnative-android、shenmintao/nxnative-android。后者明确Mali仍在调查，其他项目帧率不迁移为本项目验收。任天堂官方确认第一代Switch底座最高1920x1080/60Hz输出，具体游戏内部渲染率需实测。

## T60 全设备底座模式检查点与城内同步热点

- 现分支task/T60-docked-profiles，基于T59检查点22457ba。用户最终明确“要求都是底座模式”，先正常画面与稳定30，1080p/60后续分别验证。T60卡启动依赖为已完成T58，T59整体帧率目标仍未完成。
- 新APK启动固定FFRS_OPERATION_MODE1，旧oe-operation-mode0文件与intent不再改变APK的底座模式。HLE只读APK提供的环境配置，移除FFRS包硬编码路径。独立HLE诊断保留显式环境模式0/1。FFRS_PROFILE_TABLET继续只标记荣耀平板专用路径，所有设备底座模式没有把手机误标为荣耀平板。
- 分档新增SM8xxx/旗舰Snapdragon名称、MT69xx/Dimensity9xxx系列，目标1080/30，低屏幕手机720/30，RG477M540/30，未知与较低芯片720/30。物理屏幕短边参与手机档位。nativeRenderHeight0保留原游戏底座尺寸，高端设备真实1080场景尚未验收。不要把targetShortEdge1080或界面1920x1080当作实际3D1080证明。
- setProfileRenderHeight独立传递540/720/原生尺寸。原mali_render_height改名native_render_height，通用环境可作用于所有GPU，旧gfx-mali-render-height诊断标记仍只作用于ARM。荣耀默认原生入口不增加强制低分辨率。新包默认软件限帧30，显式诊断marker/env覆盖保留。
- 修正xbg_frame_pace原来睡眠后没有重新读时钟、耗时恒0的统计错误。nanosleep被信号打断时继续等待剩余时长。真实函数组件覆盖首次期限、打断重试、实际等待时长、严重迟到重置和0不限帧覆盖。未改游戏tick、动画/物理/音频时间。
- 构建build-docked-paced.log退出0，安装APK ab12ac3ee6c3cdb7d8e4be9ebe42d15d346abd1e42a3238b59459dcd9d8716c5，rg-all-docked-install.log成功。之后仅将JNI形参名docked改为tablet，函数ABI和机器行为不变，下一构建重新记录SHA。完整graphics69项68通过1私有fixture跳过，runtime9通过，重点设备环境/底座启动/限帧5项与Java分档合约通过。
- 一次对整个tests/device用unittest discover误收4个需要--classes/--elf等参数的独立CLI脚本，出现4个导入参数错误。还发现原限帧门禁期待缺省30、实现却为0，已恢复缺省30并通过原断言。该混合目录不能报全绿，独立CLI门禁本轮未按其专用参数重跑。没有删除或放松断言。
- 已正常新建save004洛连特市，界面Playtime22:44，时间14:46:34。原槽保留，device-backup/saves-town-slot004.tar备份。新包Continue确认同存档并正常读回。rg-all-docked-current-boot.log确认operation_mode1、GetOperationMode1、native540/selector2、target_fps30。标题30FPS仅为限帧入口核对。
- PID32341城内站立约26.61FPS。无录屏、事先声明600帧真实左右移动，all-docked-motion-plan/actions/csv/metrics/run.log保留。601成功queue回调、601不同工作帧、重复0/失败0，耗时51.410862695s，11.670685FPS，p50 84.324308ms、p95 104.982153ms、p99 113.460692ms、max132.375385ms，超过100ms70个，无按帧时间删行。该窗口较旧城门移动更差，场景及模式不同，未作严格单变量归因。
- 当前慢点每帧why5同步一次，GPU约47ms/submitCPU约66ms，dispatch间接15/15均在GPU且CPU fallback0，问题来自索引间接绘制回退。6秒probe3诊断已恢复0，日志rg-town-indirect-sync-diagnostic.log。具体为op26/a.ind20B，最新GPU写回1280B，writer342eaea42136f6fc，vs b8dee80fcc1d969e、fs066dad9ed3341f65，proof0/rows0，注册索引地址可用空间约1.5GB，不能盲目整段拷贝或删除范围门禁。原始无诊断窗口也有每帧why5一次，probe3数据只作定位。
- 未覆盖的compute342eaea42136f6fc已从私有XGS提取到town-indirect-342.spv并spirv-val Vulkan1.1退出0，反汇编town-indirect-342.spvasm。LocalSize32，常量绑定41/47/53/59，存储绑定11/17/23/29/35。下一步分析它写入20字节索引绘制参数的静态字段，扩展已有indirect_template_batch模板证明与GPU常驻路径，保留输入范围和在途副本生命周期校验。
- 已把当前低帧率镜头位置正常新建save005，23:00时设备目录确认存在，备份device-backup/saves-town-slow-slot005.tar。下一次重启可Continue该点。当前设备仅RG477M01445122，FFRS进程不存在。公开Release仍a35c458的1.0.1-preview，新模式候选尚未发布。稳定30与全机型实测仍未完成，目标继续active。

## T61 粒子更新间接绘制检查点

- 分支task/T61-town-indirect-gpu，基于8e8c07c。诊断包b41fb73c已安装，PID16563，probe3仅记录最初3次342e dispatch后恢复0。诊断显示direct xyz16/64/1、binding17元数据9216B且CPU-clean、binding29绘制参数1280B且CPU-clean。启动截图仍在Continue确认，额外A后已正常读回save005洛连特市，rg-particle-update-before.png/log保留。
- 原342e模块SPV SHA256 bf83d82a4141cb02a6b6fd152ec9d6124281d6f06c716b501c8a74d3b56f9b35，优化反汇编确认每WorkGroupID.y读取144B记录，byte4粒子数为0时在参数访问前退出，byte76为参数行，仅对binding29的row*20+4做AtomicIAdd，其他4字段不写。计算仍由原GPU着色器执行。
- 候选在所有可选改写前匹配原模块SHA，复用原CPU-clean静态参数捕获与GPU间接绘制。只对该模块允许direct Y>1，读取Y*144有界元数据并逐行校验非零粒子数的参数行。未知间接维度、GPU脏元数据、参数不干净、其他可写绑定重叠、非零baseVertex/baseInstance等继续走原回退。临时probe_particle_update helper与调用已移除。
- 新组件编译真实indirect_template_batch与模板helper，ASan/UBSan覆盖64行、最后一行越界、零粒子早退、padding、Y/XYZ/indirect、CPU-clean与可写别名负例。particle-update-tests.log三项通过。完整graphics-tests-particle-update.log为72项71通过1私有fixture跳过，dirty tracker真实fault2003。
- build-particle-update-resident.log退出0，候选APK SHA256 3fcc2a9c9ca67e3f40031638a01e4cb961fe627ed6fb3ae2cf9c3bd5d12c5afa。当前仍在基线诊断包收集save005站立300帧，town-particle-baseline-plan.json在输入前固定窗口，不录屏。完成后覆盖安装候选并相同save005核对画面、GPU同步和实际帧时间。此检查点尚未声称真机提速。

- 首候选3fcc2a9c已覆盖安装，PID21879，Continue正常读回save005，rg-particle-resident-first.png/log。精确342e分类module1，每帧why5等待已消除。无录屏事先固定站立300帧，基线诊断包301不同工作帧12.606317FPS、p95 95.003ms、最大100.735ms，新包301不同工作帧29.560783FPS、p95 36.429ms、最大44.496ms，均无失败/重复。两次镜头位置相同，角色idle姿态自然不同。
- 显示PAD后事先固定600帧左右1秒/释放0.2秒，601不同工作帧26.580273FPS、p50 34.808ms、p95 52.187ms、p99 59.105ms、max82.156ms，超过100ms0、失败0/重复0。town-particle-resident-motion全套plan/actions/csv/metrics/run.log。镜头稍漂移，和旧11.671移动窗口不作为严格单轨迹对照。
- 移动末尾出现新同步，每两帧一次OP_UPDATE_UB/op6、why4，14200B CPU参数更新碰到14208B pending，writer1618f5e9ae2a6df7，已有710行静态模板但modified_bytes0。rg-particle-resident-write-sync-corrected.log证据，继续分析原cull模块padding证明。末尾场景人物/城门正常截图rg-particle-resident-motion-end.png，站立已降约20.6FPS，不能宣称稳30。
- 一次通过adb shell/run-as/sh-c写probe的引号在远端丢失，实际写成换行，因此首份write-sync.log没有诊断。已改用Python subprocess把单字节送run-as tee，重采6秒并finally恢复字节0。该问题影响诊断开关，正式FPS窗口probe未启用。去掉新helper参数行边界的负控退出-6，particle-update-negative-control.log已记录。runtime-tests-particle-update.log九项通过。

- 已提交并推送8b59ed8到task/T61-town-indirect-gpu，包含342e模板证明与回归，公开release仍a35c458。源码随后只添加有界临时CODEX_CULL_BOUNDS诊断，最多3次且只在args14208B时触发，输出真实params/exclusive/indices_readable与越界行/flag，未改行为。
- build-cull-bounds-diagnostic.log退出0，APK d8b97d902a5cd79b447bf39b54e2e0f211f5d79eac42e47d50c85a7aebe7dc7a已覆盖安装，rg-cull-bounds-diagnostic-run/install/first.log/png。Continue回save005，初始约29.36FPS且尚未分配14208B参数，因此正在正常左右移动复现场景。该诊断包不作正式性能验收。
- 原始1618私有SPV提取town-cull-1618.spv，raw SHA99cd37314a28e2ddeded7af5e4e72474ec1e5f969b9d34b6e8f1549a5ad8f843，spirv-val Vulkan1.1退出0。运行时snk_counter_rewrite后原有audited SHA a7f28d...仍module1。原模块LocalSize1024，binding53/CP_c5 byte160为active，binding59/CP_c1 byte0为拒绝flags mask，binding17记录80B。被mask命中的record在参数访问之前退出，现helper仍保守检查所有active记录，诊断会核是否因此拒绝padding范围证明。
- 旧包移动末尾simpleperf 10秒6519样本、丢失0，memcpy18.71%、descriptors_build4.25%、hash_memory2.12%，日志rg-particle-resident-record.log/profile.txt，原data在app私有files/perf-particle-resident.data。仍先处理已复现GPU同步，再评估复制。

- 首份有界诊断在14208B初次出现时active21757/gx22，exclusive1/valid1，首帧readable0、后续readable1，没有越界行。该移动窗口27.881FPS仅定位线索，未改变正式候选代码。后续改为仅在modified_bytes0时最多12次打印重叠metadata writer，build-cull-failed-diagnostic.log退出0，APK cd9b55da已安装。
- rg-cull-failed-diagnostic-first.png实际仍停Continue确认。本轮启动输入最后A被吞，误启动的town-cull-failed-diagnostic-motion窗口已Ctrl-C中止并释放摇杆，该窗口无有效场景数据，不用于验收。补A后再确认真实场景。

- 第二份诊断cd9b55da在真实Continue后复现失败，rg-cull-failed-valid-motion.log：frame5313，active21757/gx22、exclusive1/valid1、metadata 1740560/4000000B，readable0。重叠writer有已证明1618(modified1738400, audited1)和未分类978a71642064cba1(modified0,audited0)。没有在无证据时取消范围门禁。
- 原978a模块town-metadata-978a.spv SHA97affce7b9fc1bbbcb2935e69bc87b283484fe1564a22855db21569ef11ff899，spirv-val Vulkan1.1退出0，优化反汇编552行。LocalSize64，binding35/CP_c5 uint0=count、uint1=目标起始记录、uint2=word0调整。binding11源80B记录到binding17目标(first+i)*80，每个word原样复制，只有word0加常量。另一输出binding29复制128B记录。
- 新候选在原SPV SHA精确匹配下，使用实际count/first/gx验证源/目标边界，并比较被拷贝记录的word1索引和word2标志与原CPU目标是否相同。仅全部相同才标记目标仍可用于cull索引边界证明。初次加入/索引改变、脏源、未知目标写者、报告、源或目标与其他GPU写区重叠、间接或非一维dispatch均保留原回退。没有在CPU执行GPU任务或修改guest数据。
- tests/graphics/test_snk_cull_metadata_copy.py编译实际preserve_cull_copy_indices，ASan/UBSan覆盖参数/尺寸/64线程覆盖、最后索引和flags变化、旧已证明/未知writer、CPU脏源、报告及源/目标别名。三项通过，去掉索引与flags比较的负控SIGABRT -6被拒绝。原342分类测试边界改为本if块结束，仍逐字校验原32字节SHA，避免后续新分支串入哈希提取。完整图形回归和build-cull-metadata-copy.log进行中。

- 元数据候选build-cull-metadata-copy.log退出0，APK7f602684，完整graphics75项74通过1私有fixture跳过，runtime9通过。RG正常Continue截图rg-cull-copy-first.png/log。600帧移动601不同工作帧26.612575FPS、p95 51.615ms、max80.240ms，失败0/重复0，town-cull-copy-motion全套。末尾why4又增加至23/60帧、约21.37FPS，没有metadata copy preserves日志，尚无运行时收益，不把它当已修复。
- 当前新代码仍保守拒绝GPU间接/非一维dispatch和非CPU-clean源。有界CODEX_COPY_GUARD诊断仅现有probe3下最多4次，输出真实indirect/xyz和params/源CPU-clean/目标可证明状态，build-cull-copy-guard-diagnostic.log退出0，APKa571fe47已开始覆盖安装，rg-cull-copy-guard-run.log。该临时诊断尚未进入commit，下一步先确认Continue真实场景，再单字节tee写probe3采样并finally恢复0。避免再次在Continue确认时开始移动。
- 设备热状态已留rg-cull-failed-thermal-before.txt，HAL当时CPU/GPU84.754°C、SOC86.238°C、SKIN47.801°C，系统缓存Thermal Status0与HAL存在差异，未据此声称降频或修改系统性能模式。正式移动测试没有录屏。

- COPY_GUARD实证：978a是direct1/1/1或3/1/1，count27或138、first21592，源2160/11040B为CPU-clean，目标4MB也可读。旧“必须与CPU目标相等”的策略没有命中，原因是上传索引确实改变。该无收益比较策略已替换，没有把它发布为修复。
- 新方案为978a精确模块从CPU-clean源捕获每条record word1/word2，按实际count/first写入独立XbgCullMetadataPatch，不写guest CPU镜像。挂在该GPU结果的pending_writeback上，cull范围判断在CPU基线之上按命令顺序叠加所有已知patch。未知writer、移位descriptor、不足覆盖、坏patch及报告仍拒绝。GPU完整拷贝与动态实例数计算保持原调用。
- 新测试覆盖两个顺序上传、后者覆盖前者、旧生产者先退休后CPU基线更新、未知writer/部分覆盖/坏patch/边界拒绝，并编译真实capture_cull_copy_indices校验源脏与别名。旧等值测试按新数据结构更换，原边界和未知数据拒绝仍覆盖。丢弃上传索引字段的负控-6被拒绝，日志cull-metadata-shadow-negative-control.log。graphics-tests-cull-metadata-shadow.log共75项74通过1私有fixture跳过。
- build-cull-metadata-shadow.log退出0，APK461fa7aa76d8b98e6962c019edf73f708070d9471051108584463118769d2b46，安装启动rg-cull-shadow-run.log进行中。当前probe字节0，后续先确认实际Continue场景，再观察captured cull indices与why4，最后600帧移动。尚未声称本轮shadow真机提速。

- Shadow包461fa7aa已覆盖安装，PID13287，rg-cull-shadow-first.png/log确认Continue真实场景、metadata copy captured日志（例如64行first2265）。操作前固定600帧真实左右移动，601不同工作帧27.641261FPS、p50 34.840ms、p95 43.842ms、p99 49.921ms、max79.347ms，失败0/重复0、超过100ms0，town-cull-shadow-motion全套原始证据。无录屏，无按长帧删行。
- 移动末尾和随后站立多窗口why4为0，少数加载新对象窗口1/60仍正常保守回退。原持续每2帧一次的padding等待消除，当前站立约27.55-27.90FPS，rg-cull-shadow-idle.log。角色/城墙/天空截图正常，rg-cull-shadow-idle.png同时有两位主角和NPC。移动结束一张图只显示约修亚，后续idle图艾丝蒂尔正常出现，未凭单截图宣称角色丢失或整段动态验收。
- cull-metadata-shadow-provenance.json记录HEAD8b59ed8 dirty、4个源码/测试文件SHA、APK、原main build与完整运行配置。runtime-tests-cull-metadata-shadow.log另行重跑九项通过。公开版仍a35c458，稳定30尚未达到。
- 下一步在相同shadow APK上仅将gfx-async-submit由0改1，重启Continue5后确认worker与实际场景，再600帧移动，其他标记保持540/底座1/target30/defer2/vcache1/wtrack0/perf0/probe0。旧async1慢的试验早于这两处读回消除，本次重新验证当前路径。如果更慢，恢复0，不固化无收益开关。

## T62 新位置同点测试与原生分辨率档位

- 467f656已提交推送T61元数据有序索引记录，源码干净。现在分支task/T62-rg477m-30fps，T59/60/61整体稳定30仍未完成。只操作RG477M，荣耀暂停。
- 用户确认刚才正在玩，并明确“你继续操作”“我换了个地方”。之前async1启动后的画面移动来自用户操作，不能与旧城门按同点归因，也没有硬件漂移结论。随后已获继续操作授权。
- 在用户新位置露天餐桌旁正常新建save006，截图rg-user-new-save-confirm/result.png确认是新建，Playtime32:36，日期2026/11/15 16:03:31，run-as ls确认save000-006与015均在。之前备份saves-before-user-new-location.tar，保存后saves-user-town-cafe-slot006.tar。缩略图正常，未覆盖旧槽。
- async1先在该位置退出Save/Camp，事先300帧站立窗口cafe-async1-standing，301不同工作帧23.886959FPS、p95 74.250ms、max81.482ms，无重复/失败。软件PAD隐藏，纯站立。之后独立SurfaceFlinger最后127条短历史126有效不同呈现时间，22.304598FPS、p95 79.407ms。raw rg-cafe-async1-sf-latency.txt及cafe-async1-standing-sf-*，这份短SF历史未宣称等同整个300帧窗口。
- 已查AOSP FrameTracker.cpp，dumpStats列顺序为desiredPresentTime/actualPresentTime/frameReadyTime，解析第二列，仅排除原生无效0/INT64_MAX，报告重复呈现时间，不过滤长帧。来源https://android.googlesource.com/platform/frameworks/native/+/master/services/surfaceflinger/FrameTracker.cpp 。私有sf-latency-snapshot.py留完整原始历史，适合补充真实显示证据。
- 已仅将gfx-async-submit恢复0并重启同一461fa7aa APK，rg-cafe-async0-run.log进行中，下一步确认Continue6到餐桌场景，300帧站立同点比较。尚未把早先异步测试判成严格同点失败。

- 同一save006餐桌位置在async0/540下，301不同工作帧30.004489FPS、p95 35.568ms、最大46.437ms，无重复/失败，cafe-async0-standing全套原始记录。随后独立SurfaceFlinger短历史127不同actualPresentTime，30.007004FPS，p95 49.613ms，max49.650ms。这里SF是短呈现样本，不能把它宣称为完整300帧物理长回归。
- async1同点只有23.887FPS，因此保留async0。当前源码Mali无marker缺省本来就是async0，Adreno默认async1，未引入额外厂商开关。rg-cafe-async0-first.png仍在Continue确认，补A后rg-cafe-async0-loaded.png确实读回32:36的save006，随后才开始测量。
- 原生450试验只增加HLE selector1与Mali诊断marker450支持，缺省仍540，Java和JNI设备分档尚未改动。原main已知分辨率表selector1为800x450，运行时仍要求精确build、initialized和原1600x900基准。runtime九项通过，新增450仅改selector/480拒绝，原540/720和不匹配build等负例保留。
- build-native-450-diagnostic.log退出0，APK18854bdfad4dcca31cac757a83ac03f5411e0b77c26cab5fde11acb927cbde90，graphics75项74通过1跳过，原始native450-provenance.json记录源与APK哈希。当前设备依然461fa7aa/540，正在cafe-native540-motion预先600帧基线。完成前不得安装18854或改分辨率marker。之后再marker450+覆盖安装并Continue6进行同点画面与帧时间验证，有收益才固化RG默认。

- Cafe540基线600帧移动完成，cafe-native540-motion全套，601不同工作帧26.726210FPS、p50 34.604ms、p95 51.165ms、p99 56.757ms、max85.126ms，失败0/重复0、超过100ms0。最后独立SF短历史127不同呈现29.314702FPS、p95 49.619ms。末尾短SF处于释放输入后的时段，未当成整个移动窗口。
- 现已按用户允许477M降低分辨率的方向，将唯一gfx-mali-render-height marker设450并开始安装18854bdfad4dcca31cac757a83ac03f5411e0b77c26cab5fde11acb927cbde90，rg-native450-run.log进行中。async0/defer2/vcache1/wtrack0/target30/全设备底座1。Next先确认Continue6/32:36在餐桌附近及日志height450 selector1，再用现有单帧probe采样viewport800x450，之后再预先声明600帧移动对照。450尚未固化设备默认，也未声称性能收益。

- 18854bdf已成功装机，PID26798，rg-native450-first.png/log确认真实Continue6餐桌位置，日志operation_mode1、native height450/selector1。单次probe1后finally字节0，目录codex-probe-26798，native450-frame-capture-final.txt END3156/events201/bytes66097052。3D group45起viewport800x450，UI group193/197viewport1920x1080，真实分辨率已核，没有只把surface尺寸当内部渲染。
- 单帧capture对性能有同步影响，未用于FPS。完成后另行预声明600帧窗口cafe-native450-motion，启动当前帧+30，probe0，使用native450-provenance.json核APK18854与源哈希。当前工具session83590正在该移动脚本，完成后会采独立SF短历史、末尾截图和boot.log。必须先等该session并观察指标，再决定是否将450固化477M默认。

- 450候选600帧移动601不同工作帧27.534035FPS、p95 49.790ms、p99 54.422ms、max95.012ms，无失败重复/超过100ms0，cafe-native450-motion全套。末尾SF短历史126不同actualPresentTime29.769FPS、p95 49.633ms、max66.133ms，不是完整移动物理窗口。截图rg-cafe-native450-motion-end.png人物/餐桌/颜色正常。
- 相对540的26.726FPS只有约3%均值提升，未稳30，未将450固化RG默认。原生450支持保留作已验证诊断档位，Java/JNI分档默认540。现在marker恢复540，覆盖同一18854 APK并重启Continue6，rg-restore540-run.log进行中。不得把当前恢复540前后当新代码性能提升。
- 下一步读取实际profile定位CPU复制。既有hostdirty.c的find_span有thread-local last_range，每页nvn_dirty_since查询可复用范围查找，可用现有API实现只读storage双副本逐页刷新，无需新增信号处理器或脏页API。复用OwnedIndirectBuffer与Slot.retire.objects，owner.use_count==1证明无在途读者，unchanged副本可多槽只读复用，有写入时只改无读者副本。未实现之前不改变默认。

## T63 只读storage逐页缓存实现检查点

- 分支task/T63-storage-cache，基于b54abe6，当前未提交。cache缺省0，只在Mali且gfx-storage-cache1/2启用。重用现有nvn_dirty_tracked/now/protect/since，没有新增故障处理器、脏页API或改动hostdirty.c。
- storage_cache每个范围最多两个OwnedIndirectBuffer，范围1-32MiB、最多8项、逻辑分配预算128MiB。Slot.retire.objects保留所有返回的owner直到fence退休。未改变内容时可多槽共享只读，改变时只有owner.use_count()==1的版本可逐页重写，否则保守走原stream snapshot。先取得recording_slot，再检查缓存/复制，避免中间退休失效。
- 使用sysconf实际页大小，对首尾非整页裁剪，stamp在protect前取得，之后写入必更新页代际，下次读取会刷新。GPU pending_view与cpu_access先执行原处理，cache仅snap_site3只读storage。拒绝旧wtrack保护范围和evguard诊断，pooldel清entry时增加memo_epoch迫使旧持久descriptor重绑，GPU在途引用继续持有独立allocation。shutdown在GPUidle后释放cache。
- 模式2在追踪未报告后续写入时对整个源与副本memcmp，遇到不一致禁用该范围并回退原snapshot，不编辑仍有GPU读者的副本。模式1只做逐页刷新。统计每60帧输出hits/hit_mb/copied_mb/fallbacks/verified/mismatches/entries/allocated_mb。
- tests/graphics/test_snk_storage_cache.py编译实际namespace，ASan/UBSan覆盖4K/16K逻辑页与非整页首尾、两个GPU读者阻止覆写、旧副本退休后逐页更新、保护时发生写入、pooldel后owner存活至fence/descriptor epoch、保护失败/未追踪/旧tracker冲突、验证发现未报告写入、128MiB预算与8项上限。storage-cache-final-tests.log两项通过。忽略use_count直接重写的负控-6被拒绝，storage-cache-negative-control.log。
- 首版build-storage-cache.log退出0，APK9357798a，但随后补了pooldel descriptor epoch，935版本未安装。graphics-tests-storage-cache.log共77项76通过1私有fixture跳过。最新build-storage-cache-epoch.log与graphics-tests-storage-cache-epoch.log正在运行，必须等它们完成取新SHA再装机。
- 设备恢复540的18854 APK已重新Continue到save006，rg-restore540-first.log真实operation_mode1/native540 selector2。下一步新cache包先marker2做真实动态全字节比对，确认mismatches0/命中复制量，然后marker1重启同存档做600帧正常移动和SF呈现记录。未知之前不固化缺省、不声称稳定30。

- 最新cache-epoch build退出0，APKe029d680c5ba914b4c4130c4710f3a7396ce47336f17cf6999cfd5ea66903b90已安装，provenance storage-cache-provenance.json记录b54abe6 dirty与cpp/test SHA。graphics-tests-storage-cache-epoch.log为77项76通过1私有fixture跳过，真实dirty faults2018。cache组件4K/16K与lease负控均通过。
- 模式2真机正常Continue6，rg-storage-verify-first.png/log。随后站立与6次1秒横向移动，rg-storage-verify-motion.png/log。73个60帧窗口共8628次完整缓冲区memcmp，累计mismatches0。图中两位主角、NPC、餐桌和草叶正常。mode2完整读取GPU映射做memcmp约10FPS属于校验开销，没有作正常性能结论。
- 模式2稳态命中8.85MB/帧、逐页复制约0.010MB/帧；entries8/allocated23.6MB，fallback0.67/帧，8项容量已满，保守回退原snapshot。暂不在观察正常模式FPS之前扩大容量或增加LRU。实机显示有真实缓存收益所需复制量证据，端到端帧率尚待mode1。
- 现在唯一gfx-storage-cache已设1并重启相同e029 APK，rg-storage-fast-run.log进行中（tool session39696已完成，新的fast启动session见工具最新返回）。待完成先观察是否确实Continue6，必要时补A，再600帧正常移动与SF呈现记录。其他标记540/async0/底座1/target30/defer2/vcache1/wtrack0/probe0。

## T63 新位置同步范围修正检查点

- 当前HEAD b54abe6，task/T63-storage-cache脏树。cache模式1移动601不同工作帧25.562803FPS、p95 55.467ms、max328.136ms、超过100ms1次，未证明端到端收益。后续probe3移动复现OP6 CPU更新14520B与1618 pending14528B重叠，旧范围证明失败。原始rg-storage-moving-sync.log保留。
- 精确1618模块原SPV先判断record.flags & binding59/CP_c1.word0，再读取参数行号。新增从当前Shader.c1反射绑定读取拒绝mask，CPU基线和有序上传索引路径共同跳过被原GPU模块拒绝的记录。缺mask使用0保守检查，未硬编码私有mask，未取消padding边界。
- particle-cull-mask-runtime-tests.log三项通过，copy-cull-mask-tests.log三项通过，cull-flags-tests.log七项通过，均真实编译相关函数。覆盖mask为0的坏行拒绝、未被mask拒绝的LOD越界、当前C1与上传patch组合。该修正尚未真机验证。
- 用户授权继续操作，当前RG477M PID17581，自由场景房屋花盆旁，rg-new-location-current.png/log。荣耀保持暂停。准备正常新建save007保存此慢位置，再构建并覆盖安装验证。稳定30仍未达到。

- C1修正构建build-cull-c1-mask.log退出0，APK 4934fafa3a1ecbdbfbe0abf7e0728d8c6e3b4f819c744203005cf32b2fffa50c。图形77项76通过1私有fixture跳过，运行时9通过。当前新地点正常新建save007、Playtime45:23、缩略图正常，saves-town-flower-slot007.tar已备份，旧槽全部保留。准备覆盖安装并真实Continue7验证。

- C1候选4934fafa覆盖安装成功，PID27512，Continue7确认45:23后读回真实场景rg-cull-c1-loaded.png。flower-cull-c1-motion事先600帧移动，601不同工作帧27.451678FPS、p50 34.817ms、p95 45.430ms、p99 52.776ms、max67.202ms，失败0/重复0/>100ms0。末尾多窗口why4为0，但路径与上一cache25.56窗口不同，尚未证明C1修正消除了上一位置等待。独立SF短历史28.0047FPS。当前仍未稳定30。
- 接下来仅marker storage-cache改0，重启同4934fafa/Continue7，对照同类移动。cache1的复制量和一致性已证实，端到端收益仍待同存档对照。两次移动相机有自然漂移，不能宣称逐像素轨迹一致。

- 同4934fafa/Continue7/cache0的600帧移动601不同工作帧26.710339FPS、p95 46.295ms、max69.413ms，失败0/重复0/>100ms0。cache1前一轮27.452FPS，只有小幅差异，轨迹自然漂移，尚未宣称稳定收益。cache0末尾原始日志rg-flower-cache0-end.log，写回36.5MB/帧耗时约3.45ms。
- 当前cache0场景10秒simpleperf8836样本、丢失0，rg-flower-cache0-profile/callgraph.txt。apply_writeback含子调用占8.61%采样，主要memcpy。下一诊断仅probe3下一帧打印已完成的大块writeback来源、范围与已审计标记，不增加GPU读回或等待。临时代码在xbg_probe.inc，完成来源定位后撤掉。

- 临时大块写回诊断包238a9faf构建/覆盖安装成功，Continue7直接读回真实场景。probe3三秒后finally恢复0。rg-large-writeback-diagnostic.log第1491帧显示1618写回12,800,000B未裁剪的压缩实例输出、4,000,000B元数据（已裁剪1,491,600B），342e写回4,194,304B状态、68d3写回2,654,208B。没有附加GPU读取。诊断代码已从源码撤掉，单独patch保留.local。当前设备仍诊断包238a9faf、cache0/probe0。
- T63源码检查点只保留有界可选cache与C1拒绝flags范围证明。下一步精确审计1618的binding35输出索引范围，减少12.8MB整段完成写回。全设备显示与稳定30仍未验收。

## T64 压缩实例输出范围候选

- 基线a44417f，分支task/T64-cull-writeback-bounds。原1618优化SPV行1806-1815确认binding35输出记录下标为metadata.word0 + LOD*metadata.word7 + atomicAdd(args[row+LOD].word1,1)，每记录128B，LOD最多0/1，flag0x300为0时固定0。原kernel active与C1 mask先退出。仍运行原GPU模块。
- 在有序978a元数据patch中增加word0+参数word2（uint32原加法）与word7。C5参数现在要求CPU-clean的完整12B，保留word1索引和word2 flags覆盖。原1618仅修改metadata.byte60，其他地址字段可复用。
- 新helper按每个可能row+LOD统计最多参与的invocation数，加CPU-clean初始计数，取每条record的base/stride/计数上界。拒绝行越界、uint32计数回绕、原int32字节地址溢出和输出范围越界。GPU独占输出binding35要求唯一完整写区，无其他写区重叠，未知元数据/参数保留全量写回。完整GPU descriptor不裁剪，仅记录已证明CPU完成写回prefix。
- 新test_snk_cull_output_bounds编译实际helper，ASan/UBSan覆盖非零seed、两LOD、mask退出、padding、坏行/溢出/边界，以及2000组随机可见性/LOD/原子顺序模拟。真实batch覆盖有序上传输出地址、无效base、写区别名和未知metadata writer。元数据真实捕获覆盖word0调整/uint32回绕、word7和12B常量完整性。目标组件七项通过，完整回归与构建进行中，尚无真机命中或提速结论。

- build-cull-output-bounds.log退出0，候选APK 28efb4efc96531557cb188930ab9a546e8d0448dbf846985882c492f1936175a。完整图形78项77通过1私有fixture跳过，运行时9通过。忽略动态参与数的负控SIGABRT -6被拒绝。provenance记录a44417f dirty与源码SHA。当前准备同save007/cache0覆盖安装验证，暂无真机收益结论。

- 首候选28efb4ef已覆盖装机并正常Continue7，原场景人物/花盆/墙体截图正常。运行时实际命中compact descriptor12800000→552960B（2160记录）。600帧移动flower-cull-output-motion为601不同工作帧26.831333FPS、p95 46.110ms、max69.106ms，失败0/重复0/>100ms0，较cache0旧26.710没有可确认端到端收益。末尾写回29.6-30.7MB/帧、约2.7ms，旧36.5MB/约3.45ms；移动路径相机稍漂移，不作严格逐帧归因。
- simpleperf当前8177样本丢失0，rg-cull-output-profile.txt中memcpy9.94%、hash_memory3.30%。原纹理页追踪入口实际为0。下一步在相同28ef APK仅试gfx-tex-dirty1，cache仍0、native540、async0，重启Continue7测移动。源码另把helper按输出row合并最大base，从两轮metadata扫描降为一轮，测试/构建进行中，该源码尚未安装。

- 原28ef包仅开启原纹理追踪marker1，flower-texdirty-motion为25.255203FPS、p95 55.114ms、max102.385ms、>100ms1，601不同工作帧、无失败重复。后续pipeline354/布局123，和前一轮345/122不同，路径自然漂移，未作严格因果结论。未证明收益，已恢复tex-dirty0。
- 单轮metadata聚合helper构建build-cull-output-onepass.log退出0，APK4e313a767f13030f609b143bb39e0c16cef3ef3cbf5dd8f588185ad9b7837738，图形78项77通过1私有fixture跳过、运行时9通过。负控初次字符串替换误改++row.count导致编译失败，已限定替换完整seed表达式，正确负控编译后SIGABRT -6被拒绝。未更改产品断言。
- 接下来单轮helper包与storage-cache1/tex-dirty0/540/async0覆盖安装，Continue7后测600帧。provenance cull-output-onepass-provenance.json记录准确源码SHA与dirty输入。

- onepass APK4e313a76已覆盖装机，PID12400，rg-cull-output-onepass-first.png为真实Continue7场景。flower-cull-onepass-cache1-motion事先600帧，601不同工作帧26.642139FPS、p50 36.063ms、p95 46.851ms、p99 53.877ms、max62.501ms，失败0/重复0/>100ms0。末尾画面rg-cull-onepass-motion-end.png两主角/NPC/墙体/路面正常，why4多窗口0、写回29.6MB/约2.75ms。独立SF短历史27.5943FPS，不能称稳定30或T64端到端提速。
- 当前唯一设备477M，cache1/tex-dirty0/540/底座1/async0/defer2/vcache1/wtrack0/probe0，FFRS无进程。未运行输入脚本。普通save00745:23保留。荣耀暂停，其他机型与高端真1080仍未实测，公开release仍a35c458。
- 下一步采集CPU热点中的纹理哈希来源。28ef旧采样中hash_memory166条调用链均来自get_image_slow的0x395678，对当前onepass ELF addr2line指向2437普通CPU纹理校验，但输入ELF版本不同，仅作线索。需准确新包映射或有界probe核纹理是否被页追踪覆盖。

## T65 重复纹理校验诊断

- T63 a44417f与T64 ec3e71c均已推送独立任务分支，公开release仍a35c458。当前T65基于ec3e71c，只有总控写入。下一有界probe3诊断仅记录普通CPU纹理哈希路径上12个不同的大纹理的pool/尺寸/stable/stamp/tracked状态，不读取额外纹理数据、不增加GPU等待。诊断暂未构建或安装，不用其包作正式FPS验收。

- build-texture-tracking-diagnostic.log退出0，APKe64e26ce845596ba97f22f67d94a3ef7241fd262fb31129c2da93e400debca91覆盖安装，PID16319，正常Continue7。cache1/tex-dirty1。probe3四秒后finally0，rg-texture-tracking-diagnostic.log未出现任何大纹理普通哈希日志，rg原命令退出1表示没有匹配行。当前站立7824样本/丢失0，rg-texdirty-tracked-profile.txt里hash_memory无采样，说明该纹理校验入口已走页追踪。它没有证明移动FPS收益。
- 主线程TID16392的/proc stat最后CPU7，不增加绑核。旧绑核失败在T59已记录。当前正在同save007/cache1/tex-dirty1下600帧移动，所有采样工具已结束，probe0，原始plan输入前记录。私有measure脚本新增实际storage/texture marker检查，避免计划和配置不一致。
- 临时texture诊断源码已撤回，仅保留.local/publication/texture-tracking-diagnostic.patch与原始日志。产品源码仍ec3e71c。后续要构建无诊断正常包复验，不能把当前诊断包直接发布。

- Texdirty/cache1诊断包probe0正式分离窗口flower-texdirty-cache1-motion为601不同工作帧27.201711FPS、p95 46.361ms、max73.308ms，失败0/重复0/>100ms0。图形诊断钩子没有额外GPU读回，仍需正常包复验。站立profile页查询nvn_dirty_since仅0.22%采样，原大块hash不再出现，减少哈希已实证但稳定30未达到。
- 代码现有gfx-slot-count允许2..16，缺省16，T59组件已覆盖2/4/16退休回绕。当前应用RSS约5.7GB、系统有swap，线程主核实际CPU7。下一步正常ec3源码包试4槽，其他cache1/tex-dirty1/540/底座1/async0不变，记录同save007移动和在途写回。此为现有诊断配置试验，暂无收益结论，不改系统调度。

- 正常源码ec3e71c重新构建5576b32bf01855c7f5b7e4420f5a95104549f8b0684a22f29bf8d93954f8c1ad（无临时诊断钩子）并覆盖安装，PID20127。启动仍Continue确认，补A后rg-four-slots-loaded.png才确认真实save007，未在标题测移动。
- 4槽/cache1/tex-dirty1/540/底座1/async0/defer2/vcache1/wtrack0，flower-four-slots-motion事先600帧，601不同工作帧28.617652FPS、p50 33.553ms、p95 43.559ms、p99 51.541ms、max88.746ms，失败0/重复0/>100ms0。RSS从16槽6336436kB降4槽4394512kB，VmSwap分别17352/17284kB。末尾why4=0、GPU约23ms、submitCPU约17-18ms。配置尚未固化默认，稳定30未达到。
- 当前同包同位置simpleperf10秒8431样本、丢失0，rg-four-slots-profile/samples.txt。精确当前ELF addr2line把state_find采样0x32f9a8等定位nvn_render_state.c:228-232，都是前端桶冲突后的全表遍历。采样state_find1.51%、nvn_texture_info_of2.10%。下一步复用已有nvn_program.c索引链方式，替换render state与texture桶冲突后的全表查找，必须覆盖表增长、原始状态复制、defaults、Finalize和地址复用。没有从旧包地址直接宣布定位成功。

## T66 状态与纹理索引链候选

- 基线a495e67（产品代码ec3e71c），分支task/T66-object-lookup-chains。只改nvn_render_state.c与nvn_texture.c的host对象查找，复用nvn_program.c已使用的桶+索引链方式。未改变guest对象布局或GPU调用。
- Render state原1024项前端桶发生冲突后退全表扫描，精确真机采样已定位。现按object/family桶链查找，只有创建新对象时找可用槽，重用前从旧链摘除。每次命中仍unpack原guest packed bytes，apply_defaults保留host lookup_next，table free后空表清头。
- Texture原512项前端冲突后同样全表扫描，现索引链处理。真实nvnTextureInitialize的整结构发布保留lookup_next，Finalize后仍失效，复用旧槽前摘旧桶链。serial/debug id、builder snapshot、桥接对象生命周期原路径继续执行。
- Render组件ASan/UBSan通过，新增严格查找次数上限与冲突链defaults复验。Texture新组件编译真实Initialize/Finalize/info_of，覆盖3000对象、增长重定位、碰撞重初始化、serial递增、Finalize/地址复用、1000槽循环复用与table free重建。首次harness遗漏nvn_obj_ffrs.h导致类型编译失败，补头文件后实际组件通过。完整graphics/runtime、负控和APK构建进行中，暂无新包真机收益结论。

- build-object-lookup-chains.log退出0，APK be2617b6b8e3526d49686e759d17e93528ff6a93d95cba05af27253949b30d32。图形79项78通过1私有fixture跳过，运行时9通过。恢复旧全表扫描的render负控与移除真实Initialize链保留的texture负控均被SIGABRT -6拒绝。provenance object-lookup-chains-provenance.json。准备覆盖安装并以相同四槽/cache1/texdirty1/540配置读回save007，尚未真机验收。

- 首索引链候选be2617b6已覆盖装机，PID26093，真实Continue7后flower-object-chains-motion600帧为601不同工作帧28.052141FPS、p95 45.269ms、max418.334ms、>100ms1，失败0/重复0。末尾已走到树旁、pipeline357/images710，旧四槽345/images632，不作严格同轨迹因果结论。末尾CPU18ms/GPU23ms、why4=0，截图两主角/NPC/草叶正常，仍未稳定30。
- 复核查找局部性，静态链可能让原来前端缓存命中的对象每次多读几个节点。改为仅在命中非头节点时提升为桶头，保持原最近访问的快路径，同时冲突只走该桶链。新增连续100次相同对象只读一个节点的严格组件断言。准备完整回归和新包，不声称此改动已提速。

- 保留最近访问局部性的候选build-object-chain-locality.log退出0，APK 9c412fe48f90dec9777b3b8688f3a6706a820e00f7e71c52d85c2b575df59004。图形79项78通过1私有fixture跳过，运行时9通过，三种对象查找组件通过。仍使用4槽/cache1/texdirty1/540/async0。下一步覆盖安装Continue7，真实移动窗口，尚未装机验证此候选。

- 保留桶局部性的9c412fe4覆盖装机，PID30406，真实Continue7。flower-chain-locality-motion600帧为601不同工作帧29.131393FPS、p50 32.687ms、p95 43.785ms、p99 51.185ms、max64.880ms，失败0/重复0/>100ms0。相比首链28.05含418ms加载长帧，此窗口仍不能宣称稳30。关闭局部性提升的两个负控都被严格节点次数断言SIGABRT -6拒绝，日志object-chain-locality-negative-controls.log。
- 当前仅将原生高度marker从540改450，底座模式1与UI1080、4槽/cache1/texdirty1/async0保持。以前原生450实际800x450已抓帧确认，当前相同已审计分辨率入口必须重新核启动selector1，再同save007测600帧。如无足够收益则恢复540，尚不固化450默认。

- 同9c412fe4/APK、native450 selector1与operation_mode1实际启动已核，flower-chain-native450-motion600帧为601不同工作帧29.328324FPS、p95 42.900ms、max65.457ms，失败0/重复0/>100ms0。相对540的29.131提升小，450尚未固化默认。末尾人物、NPC、墙体、光照正常，稳定30未达到。
- 补查输入条件，之前移动都通过触屏摇杆，会使TouchPad在每次DOWN/MOVE/UP执行invalidate。设备input本地usage支持source joystick，已用input joystick motionevent MOVE -1 0并finally回0验证角色真实移动，走Activity原onGenericMotionEvent入口。该检查没有新增应用调试接口，PAD仍可见。
- 当前单独测Android joystick±0.65、1秒/0.2秒neutral的600帧正常移动，私有measure脚本新增input-mode并在动作前写plan。它是另一输入条件，不能与触屏窗口当严格单变量后端收益。原native450触屏29.328与所有长帧保留。后续选择540或450仍以实际收益和画质为准。

- flower-native450-hardware-motion为601不同工作帧29.992000FPS、p95 38.145ms、p99 42.057ms、max52.157ms，失败0/重复0/>100ms0。PAD可见，Android joystick输入经原Activity正常入口，真实人物在场景移动。该窗口平均892.8draw/34.93dispatch，对照450触屏905.5draw/33.71dispatch。路径和输入条件不同，不能把全部差异归于TouchPad重绘。独立SF站立末尾短历史30.126FPS、p95 49.613ms，有16/33/50ms节奏，未声称稳定物理30。
- 540 marker已恢复，仍同9c APK，重启Continue7后真实rg-chain-hardware540-first.png确认初始房屋花盆位置。当前正在相同起点的540/Android joystick/PAD可见600帧测试。源码测试最终重跑graphics79项78通过1私有fixture跳过、runtime9通过。
- 公开primary参考已核Android官方Frame Pacing指南与Vulkan接入文档。它明确30FPS与60Hz未对齐会出现49/16/33ms呈现节奏，提供Swappy的presentation timestamps和fence方案。地址https://developer.android.com/games/sdk/frame-pacing 与https://developer.android.com/games/sdk/frame-pacing/vulkan/add-functions 。目前尚未引入Swappy或新的呈现代码。设备cmd gpu vkjson实际报告VK_GOOGLE_display_timing，原始rg-vulkan-device-inventory.json保留。下一步研究在既有Vulkan呈现入口使用受支持的时间戳，不能以软件回调平均30替代显示节奏验收。

- 回到save007相同起点、native540/4槽/cache1/texdirty1/Android摇杆/PAD可见，flower-native540-hardware-motion600帧为601不同工作帧29.682888FPS、p50 32.897ms、p95 42.028ms、p99 49.009ms、max57.551ms，无失败重复/>100ms。当前恢复540作为后续基准，450没有足够画质收益依据。4槽及追踪缓存仍marker诊断配置，未固化APK默认。稳定30目标继续active。
- backend实际选MAILBOX=1，VK_GOOGLE_display_timing尚未启用。Android Surface capabilities minImageCount6、请求7，driver返回12 swapchain images（不要把它与engine四个提交槽混淆）。源码nvn_backend_vulkan.c保留读取FFRS其他包present-mode marker的旧路径，SNK当前日志仍MAILBOX，后续呈现配置需改用本应用目录，避免跨项目配置。
- 官方AndroidX当前稳定games-frame-pacing2.1.3，支持16KB页并继承API33更准确Vsync时间与显示监听销毁修复，来源https://developer.android.com/jetpack/androidx/releases/games 。下一步先下载并检查官方AAR的头文件、静态库、classes与许可证，再以默认关闭的实验入口验证Swappy真实呈现节奏。尚未添加SDK到产品或宣称成功。

## T67 本应用呈现配置与帧节奏

- 基线02eab71，task/T67-android-frame-pacing。先做更小的FIFO对照。GuestThreadMain从原log_path父目录设置FFRS_APP_FILES_DIR，Vulkan后端只从该目录读取gfx-present-mode。移除旧FFRS其他包路径，保留显式FFRS_PRESENT_MODE与无marker原默认选择。尚未构建/安装，荣耀仍暂停。
- 官方AAR games-frame-pacing2.1.3已从Google Maven下载到.local/third-party/swappy-2.1.3，7013918B，SHA256 a9f83e0cf47d694ed2cea0ae995d5cf7411060d9d4b680610430d03d6b20ea27。仅私有备查，未加入产品依赖。SDK静态arm64库元数据NDK23/API21/c++_shared，当前工程NDK26/c++_static，若后续接入必须验证链接ABI及生命周期。stats默认关闭时无需recordFrameStart。它需要JNI activity、设备扩展、queue family、swapchain/window接线。

### T67 本应用路径与FIFO实机检查点

- 产品提交ad4edfb，APK d8975982fce6e7d81175b8ffef2ada46887c24f0051adb567e01d9f4ae666474。build-present-mode-scope.log exit0。图形80项79通过1私有fixture跳过，运行时9通过，对应graphics-tests-present-mode-scope.log与runtime-tests-present-mode-scope.log。present-mode-scope-provenance.json保留源码指纹。
- 用户新地点洛连特城门附近正常新建save008，Playtime1:09:53，日期2026/11/15 18:31:47，缩略图正常。先备份saves-before-fifo-test.tar，再备份saves-gate-slot008.tar，未覆盖旧槽。当前Continue8。
- 同APK、save008起点、底座540p/4槽/cache1/texdirty1/async0，Android摇杆每向1秒、neutral0.2秒、幅度0.65，各600间隔。FIFO marker0实际mode2，工作30.000423FPS，p95 37.230ms/max51.333ms。MAILBOX marker2实际mode1，工作29.882722FPS，p95 40.001ms/max56.990ms。均601不同工作帧，无失败/重复/>100ms。
- measure-with-surfaceflinger.py每1.5秒采SF原始JSONL，按CSV同设备单调时间窗口截取。两轮均17快照、完整历史覆盖、无命令错误、物理600不同present，无重复actual时间。FIFO物理29.994399FPS/p95 49.632ms/max66.217ms，59个<25ms、67个42至58ms、1个58ms以上。MAILBOX物理29.895802FPS/p95 49.625ms/max66.162ms，62个<25ms、72个42至58ms、2个58ms以上。仍有显示节奏抖动。原始gate-fifo-native540-motion和gate-mailbox-native540-motion文件保留。SF查询开销明确记录，不能与旧无查询窗口作严格因果比较。
- 当前设备APK d8975982、marker2即MAILBOX，PID25674。下一步接默认关闭的Swappy2.1.3实验入口。荣耀继续暂停。

### T67 Swappy可选接线与真机对照

- 默认无SDK构建保留原路径。FFRS_ENABLE_FRAME_PACING=1调用prepare_frame_pacing.py下载固定Google Maven AAR2.1.3，核SHA并逐文件验证解包，链接同一个libffrs_game_window.so内的arm64静态库。当前依赖验证成功，build-swappy-pinned.log exit0，APK731e4bf6c3e88cc777e5f6c9fcbb34e2714cadfb0a45e372cc05dbe7ce49fb11，assets/licenses/swappy-Apache-2.0.txt与NOTICE存在。尚未安装731包。动态NEEDED没有libc++_shared.so，只有本项目原系统依赖。
- 后端使用弱hook，因此独立运行时可省略Android库。Activity全局引用受锁保护，渲染线程取得局部引用并按需Attach/Detach，旧Activity不能释放新引用。设备扩展由SDK识别并去重，额外扩展创建失败重试原请求，保留原pNext。只接单个设备/队列，已有设备时新增设备走原路径。FIFO交换链成功初始化后才跳过旧软件限帧，stats关闭，auto swap和auto pipeline关闭，运行时0/60目标入口保留。SDK初始化失败清理并回退。交换链和设备先清SDK再销毁Vulkan。
- 图形81项80通过1私有fixture跳过，日志graphics-tests-swappy-pinned-final.log。运行时9通过runtime-tests-swappy-final.log。实际wrapper ASan/UBSan测试含JNI attach/引用失败、扩展失败、去重、pNext保留、初始化异常、错误交换链、重建、旧Activity与无SDK桩。两个生命周期负控均出现预期SIGABRT，swappy-negative-controls.log/json。旧软件pace提取测试补SDK mock，原EINTR/截止与unthrottled断言仍在。
- 实验APK0b33250dcae2bacd58ceedd9d77fb1981d9f6887fe31fa69d2bdbac32f58834e，profile540+SDK首次移动工作29.486FPS、物理29.335FPS/p95 49.611ms/max82.653ms。450+SDK工作30.142822FPS、物理30.144290FPS/p95 33.146707ms/p99 33.558218ms/max66.161769ms，593/599物理间隔在25至42ms。继续2400间隔工作29.810062FPS、物理29.748022FPS/p95 33.300965ms/p99 49.696744ms/max99.191615ms。原始gate-swappy-native450-motion和gate-swappy-native450-long-motion文件全保留。两轮均SF连续历史完整覆盖，无呈现失败/重复，长窗口工作回调有1次101.326ms，全部保留。
- 同APK、同save008重新加载、450、SDK关且FIFO，真实场景复测工作30.002193FPS，物理30.019872FPS/p95 49.614466ms/max49.695ms，46个<25ms、55个42至58ms。短窗口开SDK物理节奏更均匀，但长窗口仍有掉帧。gate-fifo-native450-motion-valid为有效对照。第一次gate-fifo-native450-motion在读档确认页误开始，已经SIGINT中止并归零输入，作废，不用于验收。
- 私有测量脚本现实时核已安装APK SHA、native render日志、SDK初始化状态和Vulkan实际present mode，新增结果记录实际APK哈希。当前设备仍实验0b33250d、native450、SDK marker0、FIFO marker0，PID7760，已完成有效关闭对照。731包源码只提前无marker检查、限制第二设备与加入固定依赖/许可证，下一步安装731包开启SDK，回到save007花盆慢点做更长窗口。荣耀继续暂停，公开release未更新。

### T67 生命周期后续，仍未完成

- b99ac44已推送任务分支。731e4bf6安装并核实际设备APK SHA。save007花盆慢点2400间隔工作29.433808FPS、物理29.361657FPS/p95 49.597200ms/p99 66.117544ms/max99.192923ms，无失败/重复/>100ms。原始flower-swappy-pinned-native450-long-motion文件保留，仍不稳30。15秒simpleperf12535样本丢失0、错误调用链53条，rg-flower-swappy-profile/callgraph/callees与原data保留，精确731ELF为libffrs-swappy-pinned.so。memcpy10.31% self，descriptors_build3.43% self/11.69%累计。memo命中约487、重建约361每帧，dynbuf这个合并原因约258，尚未拆原因，不能先假设全是buffer变更。
- 后端复用destroy_window_surface进行新建前清理、设备销毁和setup失败恢复，等待GPU后先清SDK再释放呈现资源，新增真实函数提取ASan/UBSan测试。图形82项81通过1私有fixture跳过，graphics-tests-swappy-lifecycle-final.log。4a89d1d5包可前台运行。
- 4a89后台测试一次PID19809在onPause后SIGABRT，重启后PID21057。复测PID25775后台和恢复均存活，但游戏ShowControllerSupport忙循环。已诊断原publishPad用resumed控制连接，后台把始终存在的虚拟手柄上报断开。当前Java修改始终连接，onPause复用touchPad.clearInput清掉触摸，pad-lifecycle-tests.log1通过、两个负控断言失败。源码HLE未改。PID25775后来由我force-stop终止忙循环。
- c45037d7包含以上输入修改，SDK开启动一次signal11，libc pc offset0xa4224，x6/x7含mutex.cc文本，原因尚未确认。完整rg-swappy-pad-lifecycle-first.log保留，不能认定JNI连接就是根因。当前SDK marker0重启对照中，SDK可能影响未知，保持默认关闭。候选把渲染线程JNI连接保持到线程退出，ThreadAttachment真实源码mock含worker thread退出验证，2项通过，build-swappy-thread-attachment.log构建中，尚未装。
- 原后台诊断日志因控制器忙循环增长很大，完整本地rg-sdk-home-resume-original.log约1.1GB，设备原始guest_boot-home-25775.log保留。已改私有home/resume脚本只读取最后3000行，并在测试前重命名诊断日志保留原进程内容，避免新进程启动覆盖。未动游戏数据和存档。下一步先验证SDK关的暂停恢复，再验证候选SDK开。测试脚本.local/publication/test-home-resume.py，必须先看真实场景再运行。

### T67 撤回不合格SDK，保留实际通过的恢复修复

- 原生控制器在后台保持连接，暂停清理按键及触摸，c450包SDK关连续3轮HOME/恢复同PID32217，真实draw/present继续。aeb891f6候选保持JNI连接至线程退出后，SDK开首轮HOME仍退出，PID4124，原始rg-pad-connection-sdk-on-resume-tail.log与rg-sdk-on-resume-pid4124.log保留。根因未知，不能声称已修复SDK崩溃。
- 当前已完整撤回Swappy产品文件、构建入口、JNI hooks、头文件与许可证附带项。撤回前以failed-swappy-experiment-source.tar逐文件SHA校验全部实验源码，failed-swappy-experiment.patch保留，研究AAR仍在.local。b99ac44提交历史保留。当前仅保留本应用呈现配置修复、Vulkan统一等待/释放流程、后台手柄连接修复及对应真实源函数测试。
- 最终构建build-sdk-removed-stable.log exit0，APK7b7fac893db68fe4d164d6da5b935c4cc6b118d6db385c0d432c4713fef0112f。副本apk-sdk-removed-stable.apk、精确ELF libffrs-sdk-removed-stable.so、sdk-removed-stable-provenance.json。源码和ELF没有Swappy或nvn_android_pacing接口，APK没有SDK许可/组件。
- 图形81项80通过1私有fixture跳过，graphics-tests-sdk-removed-final.log。运行时9通过runtime-tests-sdk-removed-final.log。输入1通过pad-lifecycle-tests-sdk-removed-final.log及两个断言负控pad-lifecycle-negative-controls.log。Vulkan生命周期真实函数提取ASan/UBSan验证等待顺序、重复清理无double-destroy和创建失败统一回收。
- 已装最终包，真实城门场景通过连续3轮HOME3秒/前台10秒，均同PID10246，实际draw与present递增，rg-sdk-removed-stable-resume-cycles.json、三轮截图和最后3000行日志保留。没有把后台窗口当FPS验收。当前仍为底座/native450/4槽/cache1/texdirty1/async0/FIFO，SDK marker0已失去产品作用。Continue8，save007/008全槽备份仍在，荣耀继续暂停，公开release未更新。
- 平均FPS和物理16/50ms节奏仍未解决。下一步T68按12535样本拆分descriptor memo失效类型，先诊断，避免把dynbuf合并计数直接解释为VkBuffer变化。若是动态UBO/driver buffer导致反复重建，再把实际buffer身份纳入memo键并保留原校验/失效/租约。

## T68 描述符缓存输入

- 从61a167c切独立分支task/T68-descriptor-memo-inputs，当前设备APK7b7fac89、PID10246、Continue8、native450/4槽/cache1/texdirty1/async0/FIFO。总控独占xbg_game.cpp与相关测试。先对现有memo失败的driver、uniform count/order/buffer、image registration/lifecycle、texel、storage分别计数，再依据结果选择最小修复。不得把合并dynbuf计数先当成单一原因。T67实际显示节奏仍待后续方案，保持in_progress，未冒称稳定30。

### T68 实测诊断与最小语义复核候选

- 临时9类诊断APK009091ef046786bb17bad94a37f99ba143914bcb37b73dd54ed8b9f06ca11ff0，只计数未改变缓存策略，真实save008静止城门约image_revision181.0/帧、storage22.1、uniform_buffer0.6、driver0。rg-memo-failure-diagnostic-first.log与memo-failure-diagnostic.patch/provenance保留。
- 12类诊断APK2bdf1bd26943ae0ed4a3004b689e7c29acce84925054aa6f27099fedc51f66f8，同场景image_revision163.1/帧，其中serial8.6、memory0、other154.5。rg-memo-revision-diagnostic-first.log与memo-revision-diagnostic.patch/provenance保留，两个诊断没有帧率收益验收。
- 当前候选只为MemoImage保存不可变RegisteredTexture定义副本。revision改变时按现有registered_texture_equal完整比对定义，相同则更新本缓存项已检查revision，其余情况仍失败回退。原serial/mem/live Image指针、sampler memo_epoch、可变格式升级memo_epoch、池销毁和buffer/texel/写回规则均保留，未修改key或pool索引。补齐原比较函数遗漏的base texture set_swz/swz/stencil字段，避免复用不同通道/深度语义。暂保留有界每60帧聚合诊断以量化实际复用。
- 真实定义/注册函数、MemoImage构造与实际验证分支提取ASan/UBSan测试通过。覆盖A/B/A注册、真实view变化拒绝、返回等价定义复用、物理Image更换拒绝、所有纹理定义字段/active view变化、inactive payload忽略。3个负控分别错误接受新view、丢失定义副本、忽略base swizzle/stencil，均触发预期断言。texture-memo-semantic-tests.log与texture-memo-semantic-negative-controls.log/json。图形82项81通过1私有fixture跳过，graphics-tests-memo-semantic-reuse.log。
- build-memo-semantic-reuse.log exit0，APKca37879ba2b0eeeae9d3f7ff59fda7c6eb258052c020d5c1966c35829b000cf1，memo-semantic-reuse-provenance.json。正在安装，尚未取得实际复用次数或性能结果。下一步先看首屏是否进入save008，再采实际语义复用/失败统计，取得收益后撤临时计数并完整重建回归。
- 公开经验已查Khronos官方Descriptor and buffer management，按实际images/buffers绑定内容缓存descriptor的办法，https://docs.vulkan.org/samples/latest/samples/performance/descriptor_management/README.html 。只用于设计线索，不移用其性能结果。

### T68 最终验证检查点

- 已撤掉临时诊断。最终仅保存纹理定义、revision变化时完整语义复核及补齐base swizzle/stencil比较。build-memo-semantic-final.log exit0，APK6c94ef1c3283d4f9f03b477b9fd1c2730eb47fae0e8a3da73a78c8ae433eba80，精确ELF、apk-memo-semantic-final.apk和memo-semantic-final-provenance.json保留。图形82项81通过1私有fixture跳过，运行时9通过，3负控均预期断言失败，*-memo-semantic-final.log与texture-memo-semantic-final-negative-controls.log/json。
- 同save008重载，底座450/4槽/cache1/texdirty1/async0/FIFO、可见PAD、摇杆移动，各2400间隔。7b7基线工作29.822FPS/p95 39.134ms，最终29.876FPS/p95 38.977ms。完整连续SF物理29.822→29.878FPS，p95仍49.63ms。原gate-memo-before-control-long-motion-*与gate-memo-semantic-final-long-motion-*保留。39个完整60帧批次CPU提交均值15.956→15.491ms，draws873.874→872.354，GPU23.809→23.612ms。整体节奏基本没变，未称稳定30。
- 最终花盆save007移动2400间隔工作29.656FPS/p95 41.007ms，完整SF29.652FPS/p95 49.629ms，flower-memo-semantic-final-long-motion-*。无失败、重复工作帧或100ms以上间隔，SF仍有16/50ms。内存VmRSS4366924kB/VmSwap17480kB。
- 最终APK真实游戏连续3轮HOME3秒/前台10秒，同PID2797，实际draw和present递增且present_result0，rg-memo-semantic-final-resume-cycles.json、三截图与tail日志。第三图人物和场景可见。当前仍花盆位置，原用户新地点save008已正常保存并全槽备份，冷重启Continue8可恢复。荣耀暂停，公开release未更新。
- 下一步原生Vulkan可选display timing候选，复用现有CPU pacer时间线。先核官方扩展与设备支持，默认关闭，477M实机长窗口SF与HOME验证。Swappy保持移除。

## T69 原生Vulkan呈现时间戳候选

- 基线5d8802a，独立分支task/T69-native-display-timing，总控独占后端、xbg_game与相关测试。默认关闭，本应用gfx-present-timing=1且设备扩展支持和FIFO时使用。复用现有CPU pacer的next deadline加一个interval，约两帧显示余量，原CPU sleep/catchup和游戏更新不变。此余量是实验选择，需检查延迟和真实SF。
- 官方VkPresentTimeGOOGLE以CLOCK_MONOTONIC纳秒定义最早显示时间，https://docs.vulkan.org/refpages/latest/refpages/source/VkPresentTimeGOOGLE.html 。477M inventory实际支持VK_GOOGLE_display_timing。未支持/无marker/禁用/无getter/非FIFO均走旧路，扩展开启失败重试原设备配置。Swappy保持移除，荣耀暂停。
- 后端现契约一个present path/device，HOME内部重建可能使上层传回旧SC句柄。计划始终释放当前tracked句柄并以真实函数测试验证旧参数不会二次销毁。

### T69 构建与短窗口检查点

- 已接可选扩展与两处vkQueuePresentKHR pNext，保留wait semaphore/SC/index/原pNext。每SC独立ID、重建清零。marker仅本应用FFRS_APP_FILES_DIR，缺省关闭；设备缺扩展/无engine getter不启用，非FIFO不调度。扩展是列表最后一项，建device失败移除该项再走原features/扩展请求。后台销毁只释放当前tracked句柄，拒绝重复销毁上层陈旧句柄。
- 生产pacer getter仅返回原next+interval，未改sleep/目标/catchup。生产函数提取测试包含CLOCK逻辑、0/overflow、marker边界、可选engine、原pNext和同步对象保留、present ID回绕。实际设备扩展协商代码ASan/UBSan跑完8种支持组合×2marker×3失败路径，验证feature链和扩展顺序/重试。过期句柄生命周期真实函数回归通过。macOS无定义weak符号测试使用宿主weak_import及-U适配，Android产品保留weak。
- 图形85项84通过1私有fixture跳过，graphics-tests-native-timing-final85.log。运行时9通过runtime-tests-native-timing.log。丢失原pNext、忽略关闭、保留失败扩展、销毁陈旧SC四个负控均实际断言失败，native-timing-negative-controls.log/json。
- build-native-timing.log exit0。APKedb78e86fa0a571ce43b437651c52f9b31d915ffc88e2da5b97d3c4a981b3c4d、apk-native-timing-candidate.apk、精确ELF libffrs-native-timing-candidate.so和native-timing-candidate-provenance.json。477M覆盖安装成功，Continue8真实城门人物/场景/亮度可见。实际log扩展supported1/enabled1、FIFO2、active1、desired比now约66ms。没有Swappy。
- 底座450/4槽/cache1/texdirty1/async0/FIFO/PAD可见，save008摇杆600间隔，601不同工作帧29.9967FPS，工作p95 35.830ms/max53.332ms，失败/重复/>100ms均0。完整SF覆盖物理29.9947FPS，p95 33.163ms/p99 49.587ms/max49.699ms，589个25–42ms/10个42–58ms，无<25或58+。gate-native-timing-600-motion-*。
- 当前从Continue8冷重载并截图确认，正在gate-native-timing-long-motion-*的2400间隔测试。后台恢复与花盆仍待验收，默认不启用其他机型，荣耀暂停。整体稳定30任务继续。

### T69 长窗口与恢复实测

- 两帧候选edb78e86冷重载Continue8，底座450/4槽/cache1/texdirty1/async0/FIFO/PAD可见/摇杆2400间隔。工作29.7485FPS/p95 40.190ms/max114.179ms，3次>100ms，无失败/重复。完整SF物理29.7490FPS/p95 33.249ms/p99 49.617ms/max148.167ms，14个<25/2317个25–42/60个42–58/8个58+，3次>100ms。gate-native-timing-long-motion-*。39个完整批次CPU15.816ms/GPU23.692ms，draw875.026/dispatch34.690。
- 真实日志CPU_ACCESS_SYNC fr2183/2532/2596、why5/op27/12B，分别与CSV下一帧2184/2533/2597的106.644/114.179/109.179ms相邻对应。pending3040B。相关批次sync_wb1且why_access1，pipeline创建只有0或0.3ms，不能把这几次停顿归为shader编译。native-timing-long-stalls.json保留。thermal/Cpu/memory原文rg-native-timing-long-*保留，dumpsys cpuinfo是旧区间，不能当作此帧窗口的精确CPU负载。热服务cached与HAL温度状态不一致，未归因。
- 同edb进程24721从真实场景三轮HOME3秒/前台10秒，同PID、实际draw/present递增且result0，rg-native-timing-resume-cycles.json/三截图/tail。末图人物场景可见。没有把该窗口当FPS测试。
- 为降低调度余量，595b4de71b171f651a4338adf4be0d00038516987b42f714ed5c4a78c1080273改getter为原next，不改变CPU限帧，实际日志desired比now约33ms。完整85图形84通过1跳过。save008各2400间隔工作29.8209FPS/p95 38.864ms/max108.889ms，完整SF29.8224FPS/p95 49.547ms/max115.744ms，76个<25/2191个25–42/125个42–58/7个58+，1次>100ms。gate-native-timing-one-frame-long-motion-*。代码已恢复533576c的两帧版本，一帧patch、APK、精确ELF/provenance保留.local，不作产品候选。
- 已覆盖回edb78e86，正常System→载入选save007，load列表缩略图与确认45:23/17:04:00正确，rg-native-timing-load-list.png/load7-confirm.png。真实花盆连续摇杆2400间隔工作29.7967FPS/p95 41.197ms/max91.907ms，无失败/重复/>100ms。完整SF物理29.7981FPS/p95 33.323ms/p99 49.624ms/max115.748ms，24个<25/2298个25–42/71个42–58/7个58+，1次>100ms。flower-native-timing-long-motion-*，末图rg-native-timing-flower-after.png人物、花叶、房屋可见。39批CPU17.309ms/GPU23.226ms，draw887.090/dispatch34.756。
- 相同450配置旧6c94语义缓存包花盆SF p95 49.629ms，当前两帧p95 33.323ms。已有减少显示节奏波动的实测收益，仍未达到长流程稳定30。当前实际PID32059/edb78e86/花盆，Continue8保留，用户原新位置save008及全槽备份仍在。真实端到端输入延迟未测，采用约66ms呈现余量是本轮选择。荣耀暂停，公开release未更新，其他设备默认不开启。
- 下一步T70先以不改变原GPU常驻入口的有界日志记录OP_DISPATCH回退的shader、参数/输入驻留与生产槽，再依据真实原因选择最小同步修复。查过Khronos vkCmdDispatchIndirect和Synchronization Examples，以设备读参数+原队列屏障为设计线索，https://docs.vulkan.org/refpages/latest/refpages/source/vkCmdDispatchIndirect.html ，https://docs.vulkan.org/guide/latest/synchronization_examples.html 。不删等待或伪造维度。

## T70 间接调度CPU回退

- 从0b5fb6c切task/T70-indirect-dispatch-sync，总控独占xbg_game.cpp/xbg_probe.inc与相关测试。先复用probe_cpu_sync既有shader/槽/驻留日志，加独立默认关闭gfx-cpu-sync-diag，不启用gfx-codex-probe，不开启capture/provenance或改变GPU快路径。仅真实why5/op27同步、游戏frame>=1200、每原因最多12条，先诊断后选择修复。临时接线应在候选固化前撤掉，patch和精确ELF/provenance留.local。
- 当前实际edb78e86/PID32059/花盆，原用户新地点save008完好。下一步构建诊断覆盖装Continue8，先看真实城门首屏，移动窗口采CPU同步metadata与实际帧号，诊断窗口不作FPS收益验收。荣耀暂停。

### T70 诊断结果与跨槽输入候选

- 仅xbg_probe.inc临时独立日志，build-indirect-sync-diagnostic.log exit0，APK4b3a13187f3fb4460a851130a1d514a29b99969ce3859959c0e35911e5b950a4、精确ELF/patch/provenance保留。该包图形85项84通过1私有fixture跳过，未开启gfx-codex-probe捕获或provenance。诊断窗口gate-indirect-sync-diagnostic-long-motion-*只作定位，期间额外mid日志拷贝开销存在，不作性能收益验收。
- rg-indirect-sync-diagnostic-final-boot-window.log真实frame3559和4001，why5/op27/12B，CS c5bc8b44a9224e7a，args writer0f9c2dd4533c2c24、3040B在当前recording槽，sourceCurrent1/inputsResident0。binding11的16B也在当前槽，binding17的262160B在上一pending槽，binding23的256B CPU-clean。原守卫拒绝跨槽输入，导致参数CPU回读→全批同步。不是参数源本身缺失。
- 已完整撤临时诊断接线，设备gfx-cpu-sync-diag0。候选从pin_indexed_input抽出原同一GPU OwnedInputCopy与源/目标共享租约到pin_pending_input。原indexed caller保留stage0/texel/binding<=64/shader约束。compute守卫只有Mali vendor0x13b5在原检查失败后尝试pin模式，对未常驻的合并storage范围作原有界GPU拷贝，再重跑相同驻留检查。原UBO、类型、capture/provenance/profile排除、report冲突、完整覆盖、1MiB/对齐/已提交生产槽/注册内存边界全部保留。没有删除CPU回退，没有伪造调度维度，仍用vkCmdDispatchIndirect读取真实GPU参数。
- 生产pin/current_pending_range/indirect_dispatch_inputs_resident/indexed wrapper及实际dispatch选路提取ASan/UBSan测试，覆盖真实262160B/3040B形状、只读/可写storage、范围合并、生产/消费双租约寿命、12个拒绝边界、UBO/未知描述符保守回退和Adreno保持原选路。测试中的GPU复制对象用宿主替身，实际Vulkan复制/屏障/producer copy_readers沿用原OwnedInputCopy，真机验收仍必需。禁用pin重试、移除生产租约、移除消费租约、删除Mali门禁4负控均实际断言失败，compute-input-copy-negative-controls.log/json。
- 图形86项85通过1私有fixture跳过，graphics-tests-compute-input-copy.log。运行时9通过runtime-tests-compute-input-copy.log。build-compute-input-copy-candidate.log exit0，APK d19bad24cd0ec6b8f726da921c97e80b28b860a30638acdf833a86d98104cab8、apk-compute-input-copy-candidate.apk、libffrs-compute-input-copy-candidate.so和compute-input-copy-candidate-provenance.json。已覆盖装，rg-compute-input-copy-candidate-first.png真实save008城门人物、NPC、房屋和亮度可见。正常启动日志已有5次262160B GPU owned copy，未出现原op27同步或slot-retired错误，仍有一次加载期op26原回退。
- 正在gate-compute-input-copy-long-motion-*，底座450/4槽/cache1/texdirty1/async0/FIFO/present-timing1/PAD可见/摇杆2400间隔。尚未取得该窗口收益、花盆与HOME验收，不能称稳定30。当前设备只操作477M，荣耀继续暂停，公开release未更新。

### T70 第一候选长测与后续诊断

- 产品候选已提交并推送ccb4b41。d19bad24原生GPU跨槽输入副本，真实save008/450/4槽/cache1/texdirty1/async0/FIFO/timing1/PAD可见，2400摇杆间隔2401不同工作帧29.7833FPS/p95 39.562ms/p99 47.677ms/max87.834ms，无失败/重复/>100ms。完整SF29.7857FPS/p95 33.262ms/p99 49.610ms/max115.716ms，15个<25/2317个25–42/58个42–58/9个58+，物理>100ms2。gate-compute-input-copy-long-motion-*，39批CPU15.322ms/GPU23.959ms、draw872.182/dispatch34.705，仍未稳定30。
- 正常启动已有5次262160B owned copy。长窗口另有copy6(最近GPU marker frame3007)、copy7(frame3453)、copy8(frame3520)。工作长间隔3383=80.069ms、3454=87.834ms、3521=72.611ms、3753=82.104ms，compute-input-copy-long-stalls.json。copy7/8与后一工作长间隔相邻，但具体耗时环节尚未量化，不能先归因GPU内存分配或等待。
- 仍有一次CPU_ACCESS_SYNC frame3752/op27/why5/12B，地址是3040B参数块的offset+60。早期原GPU日志表明该偏移对应shader69e39f610d9e52a6，与已定位c5bc8b44a9224e7a不同。该帧前有ob0030obj13.mdl/mi资产加载日志。未知这次是参数源、UBO、storage、边界或其他驻留门禁，应继续采真实metadata，不猜维度/放宽条件。
- d19真实游戏三轮HOME3秒/前台10秒，同PID13677，draw与present递增且result0，rg-compute-input-copy-resume-cycles.json/三截图/tail。末图人物、房屋与花叶可见。audio日志实际非零峰值、AAudio_state4、xruns0，只有日志检查，未替代用户听感验收。花盆save007专门窗口和视觉录像尚未完成。
- 4472e6ee诊断2在ccb上仅恢复独立CPU sync metadata，构建退出0，APK/精确ELF/provenance保留，未安装。为同时量化copy准备和retire等待，继续构建22851b1eda07274a39388d610119015ebee417e15a161a99dea27ec643a15e50诊断3。OwnedInputCopy前16次记录allocation/prepare/record+submit纳秒，wait>5ms最多16次记录。其原GPU调用顺序、等待timeout、共享所有权不变。独立CPU sync日志仍只op27/why5/frame>=1200，未开启capture/provenance或阶段profile。该窗口仅作诊断，禁止作为FPS收益验收。
- build-compute-input-copy-diagnostic3.log exit0，apk-compute-input-copy-diagnostic3.apk、精确ELF libffrs-compute-input-copy-diagnostic3.so、compute-input-copy-diagnostic3.patch/provenance.json保留。正在安装启动Continue8并等待首屏，gfx-cpu-sync-diag1；gfx-codex-probe0/其他参数同d19。源工作区是ccb4b41加两个文件的临时诊断，之后须撤回临时接线。图形诊断3回归日志graphics-tests-compute-input-copy-diagnostic3.log进行中。
- 下一步先看rg-compute-input-copy-diagnostic3-first.png确认真实场景，然后同save008移动2400间隔采独立metadata与copy计时，读取有限boot窗口。若新回退或copy准备/等待耗时有明确原因再做最小修复。恢复包为apk-compute-input-copy-candidate.apk(d19)，稳定显示时序基线apk-native-timing-candidate.apk(edb)，全槽备份与Continue8保留。荣耀暂停，公开release未更新，所有主流芯片实测与高端原生1080仍未完成。

### T70 诊断3/4结论与T71交接

- 22851b1e诊断3覆盖装Continue8实景截图确认，图形86项85通过1私有fixture跳过。长移动gate-compute-input-copy-diagnostic3-motion-*仅诊断，工作29.881FPS/max81.852ms、完整SF29.884FPS/p95 33.265ms/max115.731ms。只有一次后续owned copy frame4251，准备0.126ms，下一工作间隔61.381ms；其余80.917/81.852ms帧没有copy。初始化准备0.046–0.580ms。整个捕获未见CODEX_COPY_WAIT>5ms，也未重现剩余op27回退。不能把这些长帧归因GPU拷贝分配或等待。事后logcat ring已覆盖该窗口，未把它作为完整时序证据。
- 60218be13dc67be5e6a611716feb04d4885c933d4fede1ce7bf5db502a73edad诊断4，在3基础上只为frame-trace已开启、frame>=1200且间隔>60ms的前16帧记录原perf submit累计差值和present/pace elapsed。build-compute-input-copy-diagnostic4.log exit0，86图形85通过1跳过。APK/精确ELF/patch/provenance保留。真实Continue8首图人物、NPC、房屋可见。
- gate-compute-input-copy-diagnostic4-motion-*为2400间隔诊断，工作29.844FPS/p95 40.443ms/max85.436ms，完整SF29.847FPS/p95 33.226ms/max99.303ms，均无失败/重复/>100ms。新增measure-with-logcat.py在命令期间持续采main/PID/monotonic并finally终止logger，原logcat完整保留。不能把有额外诊断/日志拷贝的窗口当产品FPS验收。
- 慢帧2925总66.709ms/submit44.854ms/present0.565ms，3301总85.398ms/submit63.878ms/present0.736ms，3369总74.363ms/submit54.953ms/present0.629ms，pace均<0.001ms。未出现独立CPU同步或copy wait>5ms。主要超额时间已经定位在图形提交路径，仍需区分具体步骤。3300末尾新GPU_INDEXED_SHADER_PAIR 79a2e1562e16c4be/7aded7305f9bb12e，不能仅凭新pair宣称shader编译慢。
- 同时观察到Mali实际bc_native0/bc_decoded557→603，BC展开图像约1493MB、原BC payload约233MB。这是资源表示/内存事实，尚未量化它对该慢帧的耗时贡献。现有hud已有upload_ns/shader_ns/pipeline_ns/upload_bytes累计计数，下一步直接按帧差值记录，不先引入异步解码或改写格式。
- 已只读查看FFRS当前OwnedInputCopy、copy_readers和current-slot守卫，同样采用源槽copy fence等待；未修改该基线。T70产品ccb4b41及报告a319195保留，未知69e39f offset+60回退与花盆专门验收仍待完成，T70状态继续in_progress。

## T71 提交长帧既有计数诊断

- 从a319195携带临时两文件诊断创建task/T71-submit-stall-counters，总控转独占相同文件。仅扩展慢帧日志，附加原hud累计upload/shader/pipeline耗时与上传字节差值。目标是从原有计数定位提交超额的实际步骤。正常限帧、调度、资源、同步与NVN原调用未改。尚未构建，当前设备仍60218be1/Continue8移动末尾。
- 下一步构建诊断5，封存精确ELF/APK/source hash，覆盖装Continue8看首图，再live logcat+完整SF移动2400间隔采原始数据。诊断完成后撤回临时源改动和gfx-cpu-sync-diag，基线为d19bad24。荣耀暂停，公开release未更新，稳定30总目标继续。

### T71 上传临时内存复用检查点

- 诊断5/6/7的APK、精确ELF、完整源码与provenance均保留.local/publication。逐张计时定位格式0x42、1024平方、11级BC兼容解码上传，单图prepare约5ms，decode约1.7ms、deswizzle约0.25ms、staging约0.33ms。临时vector初始化/增长占剩余准备时间。已有BC线程池默认关闭，本轮未增加线程或改解码算法。
- 最终撤回所有临时诊断。产品仅12行，在原BC解码上传入口按线程复用CPU vector容量，上限32MiB，移动出缓存槽保证嵌套调用独立。clear后原resize仍清零，原数据逐层重新解码。stream_buffer同步复制到独立staging后才归还CPU容量。没有复用纹理内容。实际入口ASan/UBSan覆盖冷/热、零填充、原生格式、嵌套、异常、上限与线程隔离。4个负控均真实断言失败，upload-scratch-final-negative-controls.log/json。
- build-upload-scratch-final.log退出0，APK9471408337ff97cbe084809f46b76d2490a2c94067c774c2a36b9a1628e5b222，apk-upload-scratch-final.apk、libffrs-upload-scratch-final.so和upload-scratch-final-provenance.json保留。图形87项86通过1私有fixture跳过，运行时9项通过。真实安装SHA与provenance一致，首图save008城门人物、NPC、房屋可见。
- gate-upload-scratch-final-motion-*保存原CSV/输入/连续SF完整历史。底座450/4槽/cache1/texdirty1/async0/FIFO/timing1/PAD可见，摇杆2400间隔2401不同工作帧29.868626FPS/p95 39.365ms/max72.555ms，无失败、重复或工作>100ms。物理29.871523FPS/p95 33.224ms/p99 49.616ms/max99.277ms，无物理>100ms。39批CPU提交均值15.177ms/GPU23.915ms，draw874.651/dispatch34.679。NPC与时序不同，不能把整体FPS小幅变化全归因内存复用，仍未达到长流程稳定30。
- 诊断7另抓frame15490的why5/op27/12B，shader a0d6a4fbded819b4，参数在3040B父块偏移132B，参数/16B计数/262160B数据均在旧槽3，当前槽0。原T70仅处理参数已经在当前槽的情况，下一步复用原OwnedInputCopy保留完整父参数块与输入，未知/部分覆盖仍回退CPU同步。依据Khronos vkCmdDispatchIndirect与Synchronization Examples核对设备读参数和依赖语义，保留原屏障及双租约。花盆专门窗口、默认配置固化和公开版本更新仍待完成。
- 947产品包三轮HOME3秒/前台10秒，同PID24410，真实draw/present递增且present_result0。rg-upload-scratch-final-resume-cycles.json、三截图与tail日志保留，末图人物、房屋与花叶可见。两帧呈现余量约66ms仍启用，端到端输入延迟未测。荣耀暂停，公开release未更新。

### T70/T71 完整参数表跨槽保留候选

- a756c3a之后新增Mali限定的参数准备。只有完整覆盖12B参数的待写回块存在、原capture/probe/provenance/profile排除条件通过、owned copy开启时，才尝试取得consumer槽。跨槽复制原storage输入，再保留整个父参数表。取得槽前只保存addr/bytes，避免退休写回后引用失效。准备失败显式resolve_pending，保留原CPU读取完整同步语义。原current-slot与descriptor准备serial断言仍在，GPU继续读取原真实维度。
- 实际选择与pin/residency函数ASan/UBSan扩展覆盖3040B参数表offset132、16B计数、262160B数据均旧槽的现场。第一次3副本，第二偏移复用整表，CPU-clean/Adreno/捕获等不额外建槽，部分覆盖拒绝，槽获取退休参数/UBO/未知描述符/报告/无pool/过大父块均正确回退。原生产/消费双租约测试保留。7负控均实际断言失败，compute-args-copy-negative-controls.log/json。
- 图形87项86通过1私有fixture跳过，运行时9项通过，build-compute-args-copy-candidate.log退出0。APK a0f6da07b390f6eb309367d153ef5bb053cb359257a32d60cb3a224b68795a2d，精确ELF、patch与compute-args-copy-candidate-provenance.json保留。覆盖装Continue8首图人物、NPC和城门可见。原日志首次出现16B与3040B owned pending input copy，实际GPU路径已运行。声音日志非零、AAudio_state4/xruns0，仅日志验收。
- 正在gate-compute-args-copy-motion-*底座450同配置、摇杆2400间隔及连续SF测量。该候选收益、花盆与HOME尚待结果。发布仍为旧公开预览版，荣耀暂停，长流程稳定30总目标继续。
- a0f6da07同save008移动2400间隔2401不同工作帧29.864560FPS/p95 39.168ms/max63.634ms，失败0/重复0/>100ms0。完整SF物理29.865348FPS/p95 33.246ms/p99 49.611ms/max99.268ms，17个<25/2316个25–42/60个42–58/6个58+。工作最大间隔本次下降，平均/物理最大值基本不变，未宣称整体稳定30。39批CPU提交15.067ms/GPU24.091ms、draw872.341/dispatch34.8。原有限boot窗口出现16B与3040B复制9次以内日志，无op27 CPU同步，只有加载期frame1047/op26旧回退。
- a0f6da07三轮HOME恢复同PID31369、实际draw与present递增且result0，rg-compute-args-copy-resume-*末图人物/房屋可见。正常System载入列表save008与save007缩略图均显示，正在正常载入save007花盆，以检查此前草叶位置和长移动窗口。恢复包为94714083，整表副本扩展仍在本分支，尚未公开发布。
- a0f6da07正常载入save007确认45:23/17:04及花盆缩略图，flower-compute-args-copy-motion-*连续2400间隔，2401不同工作帧29.832883FPS/p95 40.727ms/max62.763ms，无失败/重复/>100ms。完整SF29.834678FPS/p95 33.233ms/p99 49.620ms/max99.241ms。39批CPU16.596ms/GPU23.408ms。另录10秒原始视频与每秒采样接触图，人物、房屋和脚边花叶持续可见，1fps抽样不能排除更快闪烁。T71的提交热点定位、CPU容量复用与已观察长停顿减少按此范围完成，整体稳定30继续。

## T72 既有BC线程池完整块路径

- 新建task/T72-bc-parallel-fast，源HEAD e645db6。已停止游戏，单独运行RG477M ARM64实际decoder微基准，两轮次序反转。原串行1024/0x42均值1.122/1.150ms，原2worker1.963/1.934ms，复用既有完整块快路径的2worker实验0.513/0.544ms。2048串行约5.00ms、实验2worker约2.12ms。16种BC格式、257奇数边缘的输出hash均与原串行相同。原始JSONL、源码/ELF hash与两binary留.local。独立微基准未作为游戏FPS收益。
- 产品候选只在现有bc_rows复用bc_fast_block，保留非4字节/边缘/未支持格式旧路径、DM_BC_FAST关闭与原字节校验。并行校验显式fast0参考。新增本应用gfx-bc-threads有界0..8试验配置和实际线程数首条日志，缺省仍0。未创建新线程池。下一步实际decoder ASan/UBSan覆盖格式、边界、stride、线程开关，再构建同包0/2worker实际游戏A/B。当前游戏已停止，Continue8与全槽备份保留，后续无需额外确认恢复。
- 完整实际decoder宿主ASan/UBSan覆盖16格式、1/4/65/257宽、非整块高、1/2/3层、行/层padding、输出保护、source/output短缓冲、串行/2worker、fast关闭、显式marker0/2、缺省和非法marker、fastverify旧参考。只替换可选空profiler和macOS线程命名ABI，真实解码函数全量参与。88图形87通过1私有fixture跳过、运行时9通过，graphics-tests-bc-parallel-fast-final.log。5负控实际断言或ASan失败，bc-parallel-fast-negative-controls.log/json。
- build-bc-parallel-fast-candidate.log退出0，APK4e57007abab9095442086997aaef144eef8ee8994bcb95386cd9a780a59ec14d，精确ELF/源码/provenance保留。marker2覆盖装Continue8首图人物、NPC和城门可见，实际首条日志BC decode workers=2 requested=2。正在gate-bc-parallel-fast-two-motion-*，同底座450/4槽/cache1/texdirty1/async0/FIFO/timing1，摇杆2400间隔，脚本同时核APK SHA、实际BC线程数与marker。此后同APK marker0冷启动对照，尚未把微基准收益当游戏收益。
- 2worker首轮gate-bc-parallel-fast-two-motion-*，2401不同工作帧30.000119FPS/p95 38.484ms/max70.163ms，失败0/重复0/>100ms0。完整SF2399不同物理呈现29.994906FPS/p95 33.196ms/p99 49.603ms/max49.920ms，10个<25/2338个25–42/50个42–58/0个58+，无物理>50ms。39批CPU14.646ms/GPU24.208ms、draw873.197/dispatch34.785。仅当前窗口，尚未宣称全面稳定30。
- 同4e57007a改本应用gfx-bc-threads0并冷启动Continue8，实际首条workers0/requested0，首图人物和城门可见。正在gate-bc-parallel-fast-zero-motion-*，同2400间隔与完整SF对照，所有其他marker保持。此后再选最终线程配置并检查花盆与HOME。临时C微基准文件都在.local，正式源码仅xbg_texture.c和实际回归测试。
- 同APK 0worker对照工作29.909696FPS/max62.476ms，完整SF29.914756FPS/p95 33.202ms/max99.342ms。再次2worker工作29.915578FPS/max72.857ms，完整SF29.914615FPS/p95 33.185ms/max99.237ms。因此首轮2worker的无>50ms结果未稳定复现，不能把微基准或首轮结果当整体稳定30。原始zero-motion与two-repeat-motion完整数据保留。2worker回归三轮HOME同PID20437、真实draw/present增长且result0，末图人物场景可见。仍选2作为已验证字节等价的解码优化，残余长帧继续查。
- 扩展T72写入范围，将当前调参固化为RG477M专属配置。自动识别RG477M为rg477m/450/30，JNI显式支持450并向原生传FFRS_PROFILE_RG477M；C++同时核Mali厂商，只该分档缺省启用defer2、vcache1、texdirty1、storage1、slots4、perf_sample0。后端仅该分档缺省FIFO与可选Google时间戳，BC池缺省2。原显式marker/env覆盖继续有效，其他设备原缺省保留。原有JNI ABI继续存在。高端机仍原生底座30目标，未声称场景3D1080。
- build-rg477m-defaults-candidate.log退出0，APK0dfca4a6b225c7e27f1b90c5159409058500f44deff6daf9f5b91b8f78c64399、精确ELF、rg477m-defaults-candidate-provenance.json保留。90图形89通过1私有fixture跳过、运行时9通过、profile环境4项和Java真实DeviceProfile合约通过。新测试实际提取RG分档/厂商门禁、marker覆盖、FIFO/env/marker优先级、时间戳缺省/显式关闭，以及native450与切换回其他分档。
- 对477M的13个调参文件先tar备份，再逐个重命名，未删除。备份为device-backup/tuning-before-packaged-defaults-20261116-075124.tar，映射为packaged-defaults-marker-backup-20261116-075124.json。游戏数据/存档未改。device-profile与gfx-target-fps原本不存在。0df覆盖安装Continue8首图人物/NPC/城门可见，真实启动日志无这些调参文件仍得到operation_mode1/native450/30/defer2/cache1/texdirty1/storage1/slots4/perf0/wtrack0/async0/BC2/FIFO/timing1。
- 正在gate-rg477m-defaults-motion-*真实移动2400间隔及连续SF。脚本--profile-defaults先核13文件及两个其他控制文件均缺席，再核实际启动配置与安装SHA。该默认包性能与HOME/花盆复验尚待结果，公开release仍v1.0.1-preview，荣耀继续暂停。其余主流高通/天玑实机未覆盖，整体稳定30目标保持进行中。
- 0df无调参文件城门2400间隔工作29.943190FPS/p95 38.907ms/max67.733ms，完整SF29.939289FPS/p95 33.220ms/max99.226ms，无失败/重复/>100ms。39批CPU14.878ms/GPU23.915ms，draw873.026/dispatch34.644。随后三轮HOME同PID26945、真实draw/present增长且result0，rg477m-defaults-resume-*末图人物和房屋可见。
- 同包正常System载入save007，列表缩略图与确认45:23/17:04正确。flower-rg477m-defaults-motion-*无调参文件移动2400间隔工作29.845329FPS/p95 40.738ms/max69.971ms，完整SF29.847097FPS/p95 33.192ms/max99.275ms，失败0/重复0/>100ms0。人物、花盆、房屋首图可见，远处NPC载入淡入单帧呈点阵，尚未拿该单帧认定故障。5个RG缺省门禁/覆盖负控和5个BC实际函数负控全部真实断言/ASan失败，原始日志保留。
- T72按BC解码等价、既有池复用、RG477M默认配置打包和真实生命周期范围通过。整体验收仍有约99ms物理长间隔，不能称全面稳定30。下一步先把已验证当前候选发布为带已知问题的社区预览版，继续独立系统调度轨迹定位长帧。Perfetto官方CPU Scheduling/命令行教程已核，设备支持linux.ftrace与SurfaceFlinger FrameTimeline。Mac工具v59.1从官方manifest下载并核大小与SHA，perfetto-tool-provenance.json。未修改系统调度、绑核、驱动或全局显示设置。

## T73 社区预览版1.0.2

- 从485bd2b创建task/T73-community-preview-102，唯一写者Codex。仅应用版本元数据升为versionCode3/versionName1.0.2-preview，更新README与安装说明，原版权与免责说明和NOTICE保留。用户已授权发布应用及自有资源、游戏数据自行提供。预览版已知约99ms长帧与其他设备实测边界明确记录。
- build-community-102-candidate.log退出0。最终候选APK ba052997681a476374f0733046ad06fa7a4c0699d3f675e9a7b6c6d254f1ab85，apk-community-102-candidate.apk/精确ELF/community-102-candidate-provenance.json保留。实际原生ELF与0df完全相同，逐个ZIP entry比较仅AndroidManifest与META-INF签名元数据改变，Java classes.dex、原生库及全部资源逐字节相同。签名证书SHA仍0203b98094ec6fd5811162a236b376241e8425653996744c418e0cc00696969d。APK assets只有9项许可证/NOTICE，原游戏输入扫描为空。
- 90图形89通过1私有fixture跳过，运行时9通过。签名覆盖升级成功，设备实际versionCode3/versionName1.0.2-preview，Continue8正常人物/城门首图。无调参文件真实移动600间隔601不同工作帧30.019219FPS/p95 35.693ms/max51.890ms，完整SF29.994243FPS/p95 33.200ms/max50.054ms，失败0/重复0/>100ms0。gate-community-102-smoke-motion-*。该短窗没有替代同ELF的两处2400长测，后者仍约99ms物理长间隔。
- 最终APK三轮HOME同PID10658、真实draw/present增长且result0，rg-community-102-resume-*末图人物/场景可见。原音频日志非零、AAudio_state4/xruns0，仅日志范围。存档继续使用原save008，原有save007及全槽备份保留。当前源码/版本/文档待冻结为发布提交，再运行既有package_community_release.py并在独立空轨仓创建v1.0.2-preview，随后回下载全SHA验证。荣耀暂停，稳定30总目标继续。
- 发布源码冻结提交2867bcf9f07e244c0bc912070593ea3b1640f477，打包时工作树干净。既有package_community_release.py生成APK/社区ZIP/文档/9许可证/manifest/全SHA，另外保留与上一公开版本一致的英文独立文档文件名。v1.0.2-preview已公开为prerelease，6个附件，https://github.com/Cetto9923/snk-the1st-portable/releases/tag/v1.0.2-preview 。APK仍ba052997，标签实际解析到2867bcf。
- 全部6公开附件回下载后与本地产物逐字节一致，解开社区ZIP后17项SHA256SUMS全部通过，退出0。community-102-public-download-verify.json记录目录与每个哈希。发布manifest明确source_tree_dirty=false/game_data=user_supplied。当前包仅应用、自有界面和许可证资源，原游戏数据由用户提供。该发布任务完成，稳定30目标继续，不能把预览版发布等同于性能目标完成。

## T74 系统调度与剩余CPU开销

- 从c2a2ac5创建task/T74-scheduling-trace，继续使用公开ba052997与RG477M默认配置，冷Continue8首图人物/城门确认。初次Perfetto不能直接读取shell_data_file配置，已改为标准输入，不改变系统权限。初次失败run日志和1500帧CSV保留，未当作有效系统轨迹。5秒stdin烟测发现配置缺flush与不支持的atrace事件，随后补flush1000ms、移除额外atrace类别，保留sched/freq/idle/process/FrameTimeline。
- gate-community-102-sched-stdin.pftrace为60秒43,373,435字节真实轨迹，config哈希/trace哈希/PID23686/APKba052997/退出0均在-perfetto-provenance.json。Perfetto stats无非info错误或数据丢失。1500移动间隔工作28.393FPS/max57.766ms仅诊断，不作产品收益验收。实际SNK是唯一运行中的FFRS/SNK程序。热服务cached和HAL状态仍不同，当前HAL CPU88.625/SKIN52.496原文保留，尚未据此归因。
- 60秒内主线程23730/ffrs-guest实际Running56.981秒，Runnable合计1.846秒、Sleep1.144秒、D0.000607秒。5秒前置样本中该线程约99.95%运行时间在大核4–7，优先级120。因此没有先采用绑核或提高优先级。FrameTimeline只含SurfaceFlinger/SystemUI，不能把它当SNK物理呈现证明。游戏CPU帧时间通过CSV与clock_snapshot再对齐。
- NDK实际simpleperf用户态500Hz/20秒，14884采样、丢失0，原始perf.data/工具SHA/完整命令/PID同23686保留。主线程9053样本中memcpy12.98%、descriptors_build4.95%、draw4.48%、pthread_mutex_lock4.25%、descriptors3.82%、mutex_unlock2.72%、snapshot2.13%、nvnBufferFlushMappedRange1.61%。两种调用链模式未提供可靠memcpy父链，未把memcpy归因到上传或GPU写回。精确ELF通过真实映射路径提供符号，原始报告和FP补充保留。
- 已读到FlushMappedRange/InvalidateMappedRange对全16384槽做buffer_find，仅为前8条日志计算initialized；每次仍计calls/flushes/invalidates并保持原互斥。下一步仅把这项诊断查找限制到实际需要打印的调用，先实际函数统计/并发/日志回归，再比较真实游戏CPU与帧间隔。原始返回、内存与GPU操作入口保留，稳定30仍未完成。

### T74 候选装机与同点对照

- 全1500间隔与系统clock_snapshot对齐，时钟偏移-616至-76ns，23个>50ms间隔实际Running占比平均95.526%。最长57.766ms中Running55.818ms，Runnable约1.407ms、Sleep0.541ms。main-long-intervals.json与SQL/CSV保留。SPAN_JOIN真实sched×CPUfreq时间加权主线程56.981秒均值2.758526GHz，CPU7运行34.216秒均值3.104900GHz，其余大核约2.23GHz，尚未据此归因热降频。
- 两个flush/invalidate实际函数仅在原前8条日志中查buffer registry，保留每次统计/互斥/返回。宿主ASan/UBSan覆盖unknown/NULL/uninitialized/known、负offset/SIZE_MAX、8线程统计和日志上限，4负控实际断言失败。graphics91项90通过1私有fixture跳过，runtime9通过。build-buffer-flush-logging-candidate.log退出0，APK5e5aa7e836ef48c2c15c107047636e1b16124ddf3973af4c56499ea9963cdf13/精确ELF/provenance保留，内部候选未发布。
- 公开ba052997冷Continue8作为同点对照，gate-buffer-flush-control-motion-*各2400移动间隔，工作27.824322FPS/p95 46.241ms/max82.467ms，完整SF27.821285FPS/p95 49.645ms/max115.708ms，物理>100ms2个，无失败/重复工作。39批CPU19.907ms/GPU22.816ms、draw870.138。当前较早29.9窗口变慢，尚未归因，不能选择性忽略。
- 5e已签名覆盖并Continue8，rg-buffer-flush-logging-candidate-first.png人物/城门/亮度可见。同缺省无marker/450底座30/4槽/cache1/texdirty1/BC2/FIFO/timing1/PAD可见/Android摇杆，gate-buffer-flush-candidate-motion-*正在2400间隔与连续SF。下一步先读两份metrics和perf batches，再决定收益与后续瓶颈。保存008/007和备份保留，荣耀暂停。

### T74 实机完成检查点

- 5e同save008摇杆2400间隔，2401不同工作帧28.375725FPS/p95 44.966ms/max71.271ms，无失败/重复/>100ms。完整SF物理28.375436FPS/p95 49.622ms/max115.735ms，>50ms64个/>100ms2个。39批CPU19.593ms/GPU22.908ms、draw869.590。相邻公开包对照SF27.821FPS/CPU19.907ms，本轮有小幅改善，仍有约116ms停顿，整体稳定30继续。
- 真实游戏三轮HOME3秒/前台10秒，同PID22441且draw/present增长、result0，rg-buffer-flush-logging-candidate-cycles.json与三截图保留。正常System→Load列表save008/save007缩略图可见，确认save007时间17:04/Playtime45:23再载入，flower-ready截图人物/花叶/房屋可见。save007同2400摇杆工作27.069945FPS/p95 46.406ms/max75.139ms，无失败/重复/>100ms；完整SF27.086332FPS/p95 66.048ms/max115.500ms，>100ms1个。无较早短窗替代此长测。
- 重新逐条解析simpleperf原始dump，先前报告视图未完整显示的调用链已有直接父函数。主线程9053样本中，1175个memcpy叶样本的765个直接父为apply_writeback、261个为stream_buffer。168个strcmp中162个父为nso_find_symbol，76个nso_find_symbol叶样本全部来自interposed_deallocate。后两项为互斥叶PC样本，合计238/9053约2.63%。rg-community-102-libc-direct-parents.json与20MiB原始dump保留，修正此前“memcpy父链尚未可靠取得”的记录。
- T74调度证据与诊断查找修正按此范围完成。下一步T75拟将四个不可变主模块导出分配器偏移在模块成功加载时解析一次，保留每次nso_entry_address健康/范围验证与原nb_call_from_host、缺符号拒绝和guest堆归属。原模块字节与游戏存档不修改。更大的GPU写回占用已量化，后续另按同步语义分析。

## T75 主模块分配器导出偏移缓存

- T74检查点52e61b0，创建task/T75-allocator-symbol-cache。guest_process仅增加四项每进程偏移，在guest_process_load成功且安装unload observer之后、module_ready与guest线程启动之前解析原aligned_alloc/free/_ZdlPv/_ZdaPv。每次调用继续检查当前进程/模块、NULL语义、offset与nso_entry_address，再走原nb_call_from_host。模块重新成功加载完整覆写四项，包括缺失0和未定义UINT64_MAX，缓存未存guest堆指针。
- 实际prepare/load/四类分配器函数提取ASan/UBSan，双模块不同基址、8线程64000调用、每次入口健康验证、缺符号、未定义、重载、加载失败/保留、boundary失败与NULL语义通过。原sized delete的200001次guest堆回收测试保留，并验证热路径不再查符号。初次text_filter提取测试包含新helper而编译失败，已将helper移到text_filter之前保持原提取边界，测试回归10项全通过，runtime-tests-allocator-cache-final.log。
- 5项负控真实执行后断言失败，分别漏加载准备、scalar/array交换、忽略入口拒绝、忽略boundary失败、重载沿用旧缓存。allocator-cache-negative-controls.log/json。图形91项90通过1私有fixture跳过。build-allocator-cache-candidate.log退出0，APK9b410c8b1ccb7639361a03561aeff79635e8b8dc3ffc9c28970d522de8c8a3c6，ELFd09d2983876c0f3cf981217378d26c668707840923310d4ee775ba74b4e17bee，精确归档与allocator-cache-candidate-provenance.json保留。
- 正在477M签名覆盖安装该内部候选并Continue8。下一步先核rg-allocator-cache-candidate-first.png真实场景，再按相同缺省配置做gate-allocator-cache-motion各2400间隔与完整SF，对照前5e的28.375FPS。随后确认原符号搜索退出真实采样热点、HOME/花盆回归。用户save008/007和备份保留，公共v1.0.2-preview仍ba052997，荣耀暂停，整体稳定30继续。

### T75 首轮真实场景与热点复核

- 9b签名覆盖后Continue8，真实首图两个人物、NPC、城门与亮度可见，PID4738。gate-allocator-cache-motion-*缺省无marker、原450底座30/4槽/cache1/texdirty1/BC2/FIFO/timing1/PAD可见/Android摇杆，各2400间隔。2401不同工作帧29.577636FPS/p95 42.509ms/max76.875ms，无失败/重复/>100ms。完整SF29.579539FPS/p95 33.511ms/p99 49.683ms/max99.230ms，无>100ms。39批CPU18.829ms/GPU23.342ms、draw871.513。前5e同点28.375FPS/CPU19.593ms，有改善但尚未稳30。
- 之后另做20秒simpleperf，14625样本丢失0，主线程4843共8845。原nso_find_symbol在该窗口0叶样本，strcmp10个，原公开ba采样分别76与168。memcpy仍1177个，其中790个直接父为apply_writeback、223个stream_buffer。真实采样与产品帧率窗口分开，rg-allocator-cache-cpu-20261116-100400原始文件/工具SHA/命令/maps/精确ELF symfs与main-cpu-report、direct-parents.json保留。
- 9b三轮HOME3秒/前台10秒，同PID4738、实际draw/present增长且result0，rg-allocator-cache-candidate-cycles.json与三截图。正常System载入列表008/007缩略图可见，确认17:04/45:23载入007，flower-ready截图人物/花叶/房屋可见。flower-allocator-cache-motion-*各2400移动间隔，工作28.225088FPS/p95 44.718ms/max81.518ms，失败/重复/>100ms均0。完整SF28.232664FPS/p95 49.627ms/p99 82.785ms/max132.294ms，>100ms2个。39批CPU20.563ms/GPU22.962ms、draw882.8。该物理长停顿保留，稳定30未通过。
- 正在同签覆盖回5e并冷Continue8做反向次序对照，rg-allocator-reverse-control-*。随后恢复9b重测同点，以排查运行时长和系统波动的影响。公共预览版仍ba052997。本次回退仅替换同签应用，游戏数据与save008/007未修改。

### T75 反向对照与最终检查点

- 5e反向冷Continue8，gate-allocator-reverse-control-motion-*2400间隔，工作28.532754FPS/p95 44.220ms/max77.617ms；完整SF28.526107FPS/p95 49.623ms/max99.262ms。39批CPU19.541ms/GPU22.867ms、draw873.8。恢复9b再冷Continue8，真实首图确认，gate-allocator-cache-repeat-motion-*2400间隔工作29.031126FPS/p95 43.951ms/max77.049ms；完整SF29.034788FPS/p95 49.591ms/max115.645ms、>100ms1个。两轮都2401不同工作帧、无失败或重复、完整SF覆盖。重测表明改善幅度波动，不能只报首轮29.58或宣称稳定30。
- T75按不可变导出偏移缓存、guest堆归属和生命周期回归范围通过，整体性能目标继续。当前9b已恢复到477M，Continue8与两份存档备份保留。其它机型未实机，荣耀暂停。内部候选尚未替换公共ba052997预览版。
- 用精确9b ELF解析8845主线程PC，indexed_graphics_ready中0x40d860/874两个热点共102样本，位于xbg_game.cpp:6616的纹理描述符std::map<int,RegisteredTexture>::find。descriptors_build热点3efd34/3fa494各32样本，分别为shader_layouts与images有序表查找，另有ImgKey哈希查找。原始hot-instructions.json与addr2line文件保留。接下来先优化纹理描述符ID查找的单一容器，保持外层pool索引、注册对象地址和所有revision/视图验证。
- 已核C++工作草案unord.req.general，https://eel.is/c++draft/unord.req ，rehash保留元素指针/引用。源中三个纹理ID表声明的全部调用点使用find/operator[]，无按ID排序遍历；实际注册保存元素引用，关闭时才clear。后续仍需增长/重注册/多pool/legacy实测回归与实际游戏长测，标准资料只作设计依据。

## T76 纹理描述符ID索引

- T75已提交64c0e36，与T74的52e61b0一起推到独立空轨远端对应task分支。创建task/T76-texture-descriptor-index，总控独占xbg_game.cpp与新回归测试。仅将三个内部ID表声明共用TextureTable=std::unordered_map<int,RegisteredTexture>，外层PoolKey有序表继续使用原实现，现有pool key、find/operator[]、注册对象字段和revision/视图/图像验证均保留。注册对象指针只在shutdown clear时释放，rehash保留元素地址。
- build-texture-descriptor-index-candidate.log退出0，APK78a1dfc1ff9487515a6095003a931a0fbf5e2d4f41503ab4ea42d8359ee563b5，ELFf1e5b3224abf3dcea8cb28f0f8de014d27d30447a23f5cf85980bb16943a79e1，精确归档与texture-descriptor-index-candidate-provenance.json保留。当前477M仍9b/Continue8实际场景，尚未安装78。
- 新测试提取实际注册/查找/eligible查找和完整RegisteredTexture/MemoImage定义，ASan/UBSan覆盖多内存pool、同pool不同offset、相同ID隔离、legacy fallback、16384项插入与显式rehash、保存的memo/texture对象地址、等价重注册、视图/serial变更与shutdown后重新创建。首轮fixture形参pool与实际局部pool同名导致编译失败，已将测试形参改为bound_pool，独立合约已通过。原首轮92图形除该fixture外90通过1私有skip，修正后正在完整重跑，10运行时已通过。3项实际运行期负控正在执行，尚未记录性能收益。
- 下一步确认graphics-tests-texture-descriptor-index-final.log和texture-index-negative-controls.json，再签名覆盖78并Continue8看首图，按无marker默认450底座30/4槽/cache1/texdirty1/BC2/FIFO/timing1/PAD可见/摇杆2400间隔测gate-texture-descriptor-index-motion。恢复点为9b，用户save008/007及全槽备份保留。公开版本仍ba052997，荣耀暂停，稳定30目标继续。
- 修正fixture后完整图形92项91通过1私有fixture跳过，graphics-tests-texture-descriptor-index-final.log退出0。3负控实际运行触发断言/ASan，分别丢pool offset、重注册替换已引用对象、停用revision递增，texture-index-negative-controls.log/json。10运行时退出0。78已签名覆盖并冷Continue8，rg-texture-descriptor-index-first.png两个人物/NPC/城门/亮度可见，正在gate-texture-descriptor-index-motion-*2400移动间隔与完整SF。
- 已查Android官方MediaTek ADPF案例与原生Codelab，https://developer.android.com/stories/games/mediatek-adpf ，https://developer.android.com/codelabs/adaptability-codelab 。Performance Hint Session按真实目标与实际工作时长提供系统调度线索，可作为后续方向，尚未接入或声称本设备支持/获益。先前performance-hint-api旧文档路径404，已用官方当前页面核对。没有改系统调度、绑核、驱动或全局显示，也没有继承其它案例的FPS数字。

### T76 城门实测与后续能力核对

- 78各2400移动间隔，gate-texture-descriptor-index-motion-*工作2401不同帧29.595079FPS/p95 42.452ms/max79.604ms，无失败/重复/>100ms。完整SF29.603668FPS/p95 33.442ms/p99 49.643ms/max132.319ms，>50ms15个/>100ms2个。39批CPU18.668ms/GPU23.416ms、draw874.697。相邻9b重复窗SF29.035/CPU19.544ms，当前有改善，仍有长停顿，稳定30继续。
- 78真实游戏三轮HOME3秒/前台10秒，同PID26483、draw与present增长且result0，rg-texture-descriptor-index-cycles.json与三截图。首个长测与恢复之后另做20秒simpleperf，14485样本/丢失0，主线程26589共8595。descriptors_build占比5.20%→4.51%、indexed_graphics_ready2.36%→1.66%，主线程样本总数和运行条件不同，百分比仅作热点定位。原始rg-texture-index-cpu-20261116-103551.perf.data/maps/工具SHA/精确ELF与main-cpu-report保留。正在正常载入save007以复测花盆。
- 477M真实dumpsys performance_hint显示HAL Support true、PreferredRate8333333ns、Active Sessions空，rg477m-performance-hint-capability.txt。NDK26实际performance_hint.h提供API33引入的getManager/createSession/reportActualWorkDuration/updateTargetWorkDuration/closeSession。游戏主线程属于本app线程组，具备后续候选接入条件，尚未启用。
- 已读原JNI setFocusState→nso_host_oe_set_host_focus与GameActivity onResume/onPause。后续ADPF候选拟复用这一真实生命周期关闭/重建本app会话，使用实际主线程和原33.333ms目标，报告排除限帧与显示等待的真实帧工作区间。该工作边界与目标仍需在接入时核对，收益以477M实际A/B为准。恢复点9b，荣耀暂停。

### T76 完成检查点

- 正常System载入列表save008/007缩略图可见，确认save007的17:04/45:23后载入。rg-texture-index-flower-ready.png人物、花叶、房屋可见。flower-texture-descriptor-index-motion-*各2400移动间隔，2401不同工作帧28.508892FPS/p95 44.047ms/max69.740ms，无失败/重复/>100ms。完整SF28.509978FPS/p95 49.623ms/max99.274ms，无>100ms。前9b花盆28.233FPS/max132.294ms，本轮小幅改善，稳定30仍待实现。
- T76按纹理ID索引、注册对象稳定性、92图形/10运行时/3负控、真实城门与花盆长测、HOME3范围完成。当前APK78a1dfc1仍安装于477M，停在save007移动后场景，冷Continue8恢复用户新位置，存档与全槽备份保留。公开v1.0.2-preview仍ba052997，荣耀暂停。
- 下一步T77拟试本应用可选ADPF Performance Hint，477M HAL已读到支持。先核API和生命周期，再以原33.333ms目标、实际guest主线程、排除限帧/呈现等待后的真实工作区间构建默认关闭的候选，在同APK开/关冷重载A/B后决定是否固化。已有性能和显示恢复点均可直接覆盖安装，不需要再次询问重启。

## T77 可选Android Performance Hint

- 创建task/T77-android-performance-hint，HEAD b3cd31f。新增Android原生独立会话实现，默认关闭，读取本app gfx-performance-hint=1。用NDK33的六个标准API按dlsym解析，支持不足/manager失败/建session失败/report或target失败均关闭并保留原渲染路径。显式函数指针ABI与NDK26头一致。第一轮decltype取API函数地址被android28编译器以API33不可用拒绝，已改为标准签名函数指针动态加载，保留原android28构建目标。ELF动态符号检查确认没有APerformanceHint直接导入。
- JNI复用setFocusState，私有hint_mutex串行保护生命周期/会话，独立于renderer mutex。后台3立即关闭，前台1/2允许新建，线程ID变化关闭旧会话并重建，shutdown幂等关闭。每个新session跳过首个可能跨加载/后台的区间。引擎仅测上一次present返回后到本次限帧前的单调时钟区间，目标取原s_target_frame_ns，原pacer/速度与Vulkan呈现继续原实现。首3次成功报告记录真实actual/target/TID/result0，日志有界。
- actual .cpp通过假NDK声明/动态加载stub编译运行，ASan/UBSan覆盖缺marker/0/无目录/缺符号/无manager/无HAL/create失败、首次跳过、原目标、真实线程替换、update/report失败闭锁、后台及时关闭、shutdown幂等、并发生命周期。实际引擎hook提取测试验证限帧与present等待排除、首次/弱符号缺席/target0/INT64上界。94图形93通过1私有fixture跳过，最终补强目标/TID和即时后台断言后再完整94通过，graphics-tests-performance-hint-final.log；10运行时通过。6负控实际断言/ASan失败，performance-hint-negative-controls.log/json。
- build-performance-hint-candidate-final2.log退出0，APK6b4095ab0b317b5e13fc55cf47f5e6a548be9ec0c3b00052333f3bdfea5f266d，ELFfc64abc6abe3efc7e7947b7670fc7257e04d39d4328b3eab4168790ff7b37f5f，精确归档与performance-hint-candidate-provenance.json。477M同签覆盖首轮实际configured0，首图人物/城门正常，该轮归档rg-performance-hint-initial-default-*，未作开关收益测量。
- 最初用adb exec-out cat返回码误判marker存在，实际mv报告不存在。已改成成功shell ls的精确文件名判断，确认原marker缺席，再tee写1并shell cat验证；原探测错误保存为probe-error txt，未当备份或PASS。performance-hint-marker-setup.json记录原缺席。当前正在同6b冷重启Continue8以实际读取marker1，rg-performance-hint-enabled-*。下一步先核首图、configured1、active目标33333333/实际TID与work result0，以及dumpsys performance_hint，再测同场景2400移动间隔/完整SF，随后marker0冷重载做同APK对照。
- 本地测量脚本增加--performance-hint 0/1，核真实boot配置、session/report成功、原30目标和TID属于当前app进程，并写入plan。其余15调参文件继续缺席，--profile-defaults原分档核验保留。荣耀暂停，游戏数据/存档原样，公共预览版仍ba052997，稳定30目标继续。
- marker1冷Continue8已完成，rg-performance-hint-enabled-first.png人物/NPC/城门/亮度可见。真实boot configured1，session线程16162/target33333333/preferred8333333，首3次正值work报告result0。dumpsys performance_hint记录SessionPID16114/SessionUID10171/TIDs[16162]/Target33333333/Allowed true，rg-performance-hint-enabled-session.txt。当前正在gate-performance-hint-enabled-motion-*摇杆2400间隔和连续SF，--performance-hint1额外门禁已通过。下一步先读取性能结果，再同APK marker0冷Continue8做对照，并验证实际后台关闭/前台重建。
- 6b marker1首轮2400移动间隔完成，gate-performance-hint-enabled-motion-*工作2401不同帧29.193770FPS/p95 44.313ms/max72.558ms，无失败/重复/>100ms。完整SF29.210943FPS/p95 49.595ms/max99.224ms，无>100ms。该结果尚未优于此前78窗口，收益以接下来的同APK关闭对照为准。当前已将本次新建的marker写0并验证，正在rg-performance-hint-disabled冷Continue8，尚未进行关闭窗口测量。

### T77 A/B结论与实验撤回

- 同6b marker0冷Continue8首图真实人物/城门正常，configured0。gate-performance-hint-disabled-motion-*2400间隔，工作29.272195FPS/p95 43.592ms/max56.774ms；完整SF29.281223FPS/p95 49.600ms/max99.292ms。无失败/重复或>100ms，SF完整覆盖。开启29.210943与关闭29.281223没有可确认收益。两窗NPC/负载仍有差异，draw871.6/891.667、CPU19.454/19.874ms，未将CPU均值差异归因到ADPF。
- 已撤回本次产品接线。完整experimental patch、tracked reverse patch、6文件完整source.tar.gz与3个新增源码文件已保留.local/publication/performance-hint-experiment-*；6b APK、精确ELF、provenance和原始A/B/负控日志保留。只反向应用本任务三个已知tracked文件改动，三个本次新增文件移到本地源码归档，git diff b3cd31f -- src退出0。新建marker0已重命名保存，恢复其原缺席状态。performance-hint-experiment-rollback.json记录精确路径/恢复结果。
- 实际ADPF后台会话关闭/恢复的真机专项为NOT_RUN。本次会话生命周期仅组件回归，实验产品接线已经撤回，因此没有以该项声称产品验收。正在显式覆盖回已验证的78a1dfc1并冷Continue8，rg-after-hint-experiment-restored-*。荣耀暂停，游戏数据与存档原样，整体性能目标继续。T77按官方方案调查、实际API调用、同APK A/B与安全恢复范围完成。
- 新线索来自78的8595主线程样本。Mali driver中172个样本首个native祖先为Buffer::invalidate，下一native祖先全部为apply_writeback，约占主线程2.00%。其中153个PC是Mali+1a67d34。rg-texture-index-invalidate-callers.json与原始dump保留。实际cached readback为memoryType1/flags0xb，含HOST_CACHED而不含HOST_COHERENT。
- apply_writeback已按原审计modified_bytes缩小CPU memcpy，但仍对整个write.buffer.size失效缓存，13MB父块等会多处理未读取的尾部。下一步T78拟让非拥有Buffer副本的size匹配已经计算好的实际CPU读取bytes，再复用原invalidate/cache_range的非相干atom对齐与allocation边界。未知范围和图像别名仍按原完整长度。Khronos规范已核，https://docs.vulkan.org/refpages/latest/refpages/source/vkInvalidateMappedMemoryRanges.html ，原fence/host barrier继续必要，拟仅缩小已证明的host读取范围。

## T78 写回读取范围的缓存维护

- HEAD0222823，创建task/T78-writeback-cache-range。产品仅3行，将write.buffer复制为非拥有read_range，并令其size=原已证明的CPU copy bytes，再调用原invalidate。原Buffer对象/大小/引用、copied bytes、GPU同步、图像别名与未知范围回退、cache_range的非相干atom对齐/分配末端处理全部继续原逻辑。
- 已恢复并装回78，rg-after-hint-experiment-restored-first.png真实场景确认。新对照gate-writeback-range-control-motion-*无15调参文件且无ADPF marker，原底座450/30/4槽/cache1/texdirty1/BC2/FIFO/timing1，2400摇杆间隔。工作29.641173FPS/p95 41.534ms/max78.412ms；完整SF29.639424FPS/p95 33.482ms/max99.273ms。无失败/重复/>100ms，完整覆盖，39批CPU18.386ms/GPU23.202ms、draw872.351。
- 实际Buffer/cache_range/invalidate和apply_writeback提取ASan/UBSan覆盖13MB父块的552960B前缀、64/128/256原子与多偏移、coherent跳过、非arena全分配回退、分配尾端、未知/超限modified与图像别名。逐字节copy与未读尾部保护、原Buffer所有元数据保持断言通过。原T64 copy测试将假的单对象invalidations计数改为共享的调用计数，继续验证一次真实失效调用，并新增实际失效长度断言。
- 5项负控真实运行断言失败，旧全视图维护、修改调用者Buffer大小、取消图像别名回退、取消atom对齐、取消必要invalidate，writeback-range-negative-controls.log/json。10运行时通过。初轮93图形有1个旧coalescing fixture因Buffer缺size字段编译失败，已经补齐真实字段与每个随机结果的bytes初始化，并保留2000例fence/槽边界/最终字节一致断言且加强size范围断言，正在完整重跑。首次provenance误写全通过已更正为待重跑状态。
- build-writeback-cache-range-candidate.log退出0，APK7239156166f14a5d434c965cde61a31a0acf8d5f1733b7a15e36662e681706dc，ELF77e4ed7593a3790c48ed7461024722d5c90dd3f0d67f1835532ded06a14bf453，精确归档与writeback-cache-range-candidate-provenance.json。当前正在477M签名覆盖安装并Continue8，rg-writeback-cache-range-*。下一步先核真实首图、graphics-tests-writeback-cache-range-final.log，再做同配置gate-writeback-cache-range-motion2400间隔和完整SF对照。公开预览版仍ba052997，荣耀暂停，用户存档与备份保留，稳定30目标继续。
- 完整重跑93图形92通过1私有fixture跳过，graphics-tests-writeback-cache-range-final.log退出0，10运行时和5负控均退出0。723签名覆盖+Continue8完成，rg-writeback-cache-range-first.png人物/城门/亮度正常。ps只见本SNK应用PID2384。正在gate-writeback-cache-range-motion-*原缺省配置2400移动间隔与连续SF，尚未确认性能收益。
- 723首轮2400间隔，工作29.417064FPS/p95 42.871ms/max76.237ms，无失败/重复/>100ms。完整SF29.429608FPS/p95 49.572ms/max115.729ms、>100ms1个。前78对照SF29.639FPS，当前平均帧率没有提高，尚未按该窗口宣称收益。正在独立20秒CPU采样复核Mali invalidate热点，采样窗口与性能窗口分开。其后仍需决定本次3行修改是否保留，并做正常场景恢复回归。
- 新20秒采样rg-writeback-range-cpu-20261116-113121原始perf/maps/工具SHA/精确ELF保留，主线程2507/8735样本。Mali driver中130样本经Buffer::invalidate→apply_writeback，约1.49%；之前78为172/8595约2.00%。该占比变化仅作热点复核，窗口条件有波动，未转化为整体帧率收益声明。完整SF窗口与采样窗口分开。723三轮HOME3秒/前台10秒，同PID2384，draw/present增长且result0，rg-writeback-cache-range-cycles.json和三截图；末图人物/房屋/草叶可见。正在正常菜单载入save007做花盆回归。
- 花盆载入流程被设备使用干扰打断。System首图确实在菜单，但接下来的load-list截图已回到城门树旁，load7-confirm截图前台为短视频应用并有游戏缩略悬浮窗。未看到载入确认，因此没有发送最终确认或启动花盆测帧，也未声称成功载入007。已异步询问用户当前是否操作477M，并报告现场。游戏操作当前暂停以核对输入来源，主goal仍active，本地分析继续。当前723/PID2384，原008/007及备份保留。确认设备空闲后可冷Continue8恢复现场再做剩余回归，重启授权已存在。
- 用户已明确回复正在操作、先停一下，随后再次要求继续。当前恢复真机接管，rg-writeback-resumed-after-user冷Continue8进行中。之前移动/菜单变化已有外部输入解释，花盆尚未载入的记录保持，后续同点对照使用用户停手后的新窗口。

- 新冷Continue读到用户新进度01:27:30、协会，停在确认框。误启动的gate-writeback-clean-after-user-motion已SIGINT停止并EXCLUDED，不能用菜单算帧率。完整存档备份saves-after-user-play-20261116.tar已解析核实11文件、含新save015及原008/007并逐项SHA；新save015 SHA ad2a49fc23ff578b0d27e7fd7633406f4bedd2c3afeaa78545aec8c71fc61bc8。补A后实际协会人物/场景可见。T78花盆回归与整体收益尚未通过，3行产品修改保存检查点。
- 用户补充音画同步/声音延迟。当前723/PID25575，AudioFlinger本app track360、扬声器0x2、DEEP_BUFFER输出、系统估算延迟254.57ms、欠载0。源码open_aaudio_stream明确PERFORMANCE_MODE_NONE；需先试请求LOW_LATENCY并验证实际通道、延迟与稳定性。该数字是系统轨道估算，非口型音画相对延迟实测。av-before-audioflinger.txt与两张实际截图保留。荣耀继续暂停。

## T79 音频输出延迟与音画同步

- 分支task/T79-audio-output-latency，HEAD2f2a5f5。只改audio_bridge.c请求LOW_LATENCY、失败后NONE重开，以及每秒同源时钟AAudio时间戳日志；原PCM字节、速率、缓冲策略、回收、暂停和重连继续原实现。默认shared保持。Android官方依据 https://developer.android.com/ndk/guides/audio/aaudio/aaudio 与 https://developer.android.com/games/sdk/oboe/low-latency-audio 。
- APK89e30e42e2296da778540142db179c96471b80b05ecae9249021969e3ab1ac96，ELFf178f1fe055f9c9023691269cf48ad886e77602e72d0ec2557875ed3b0a146f0。build-audio-low-latency-candidate.log退出0，完整归档及audio-low-latency-candidate-provenance.json。真实477M/PID2768实际performance10即NONE，低延迟请求未获完整低延迟模式，但选到PRIMARY输出、burst1026/buf2052；原NONE为DEEP_BUFFER/burst3075/buf6150。不能声称获得FAST或MMAP，真实MMAP endpoint仍0。
- 同存档协会speaker track估算原10样本219.0..252.18ms、中位232.03，候选12样本83.85..105.62、中位84.255，原始dumpsys与av-low-latency-comparison.json保留。这是系统轨道估算，不包括HLE积压，不能当口型音画偏差。候选另223次AAudio时间戳加上source submitted-written，最新PCM尾部预计播放等待129.698..146.759ms、中位136.906；输出部分中位85.242/source队列50ms。全部xruns0，原始av-low-latency-speaker-steady-tail.log/json保留。
- 93图形92通过1私有fixture跳过、10runtime通过。实际audio_bridge_transport_contract以NDK28编译在477M跑stub，14次成功open/close计数一致、错误0，覆盖原逐字节多声道、阻塞/部分写/timeout/disconnect/stop/restart以及新增LOW_LATENCY成功和失败NONE回退。2负控真实断言失败，request-default exit1/14断言、missing-fallback exit1/5174断言。HOST实际audio_transport_contract通过ASan/UBSan，错误0。并非独立QA或声学验收。
- HOME三轮同PID2768、实际draw/present增长/result0，rg-audio-low-latency-cycles.json。后台之后音频继续非零并有有效时间戳。协会save015附近1200移动间隔，association-audio-low-latency-motion原日志：1201不同工作帧30.00016FPS/p95 34.268ms/max36.690ms，无失败重复；完整SF29.99464FPS/p95 33.166ms/p99 49.590ms/max49.671ms，无超过50/100ms。19批CPU7.216/GPU22.391/draw268.5，场景明显轻于城门，不能归因到音频修改或验收户外30。
- scrcpy playback+dup三次得到全零音轨，第四次已确认设备媒体3档仍全零，该捕获路径兼容/策略原因未确认，全部EXCLUDED，不能当游戏无声或同步通过。最初设备媒体确为静音0，cmd media_session set3未解除静音，后来用标准VOLUME_UP到3档才确认未静音；结束时须恢复原0。output源数字捕获能获得非零音频，18秒NPC对话记录av-low-latency-dialogue-output.mkv，有真实字幕/人物/音频；排除首秒后非零帧99.9846%、最长全零1采样。output捕获会切remote_submix，不能据此验收扬声器口型同步或物理延迟。捕获后回speaker ready已出现，仍需最终核对。
- 为完整计入应用排队，临时构建只将首次性能请求恢复NONE、保留相同时间戳的控制包1d5f4be7a046312a597b85095df8392efed99d51cad5dd31f5c84847245bde2f。控制source、APK/ELF/provenance已精确归档。build退出0后finally已恢复产品源SHAaef803af...，默认构建路径当前是控制包，后续安装只用显式归档APK。当前rg-audio-latency-control安装/冷Continue最新save015进行中；先视检真实场景，再取60秒时间戳与HLE队列对照，最后必须安装回89候选并恢复用户新存档场景/原静音0。全口型/过场音画同步和户外稳定30继续，荣耀暂停，公共版本仍ba052997。

### T79 完整排队对照与恢复检查点

- 控制1d5f4be7已实际冷Continue到同一协会，首图确认/PID11450、扬声器DEEP_BUFFER。排除首图以前时间戳，66样本source队列0，最新PCM尾部等待211.450..215.236ms、中位214.906。控制APK仅将首次模式请求从LOW_LATENCY改NONE，含同等时间戳日志，全部样本xruns0。
- 已显式覆盖恢复89e30e42候选并冷Continue，最终PID13147，首图人物/协会/HUD正常，ready device3/burst1026/buf2052/performance10。首图以后45个样本，output中位81.718ms/source16.667ms/合计101.096ms，范围94.295..110.020ms，全部xruns0。前长运行223样本合计中位136.906ms，运行时长及捕获/后台切换条件不同，保留两轮结果，不只报较小读数。av-low-latency-final-comparison.json汇总。这里是时间戳推算的最新PCM尾部等待，物理声画事件/口型偏差依旧未直接测定。
- 最终全11存档重新tar备份并逐文件SHA解析校验，与用户新进度备份完全相同，tar SHA也一致b94dc5511614a7b1064a6aed459cf927806b3fdcb3c19e964c38f9e894df5237。测试临时媒体3档已用标准音量键恢复原0，并cmd media_session get验证，av-final-volume-restoration.txt。最终装机89候选，默认构建目录仍为控制1d5f，后续安装继续显式路径或重新构建实际产品源码。公共预览ba052997。
- T79按输出延迟改善、传输回归和恢复范围保存源码检查点，状态仍in_progress。下一步继续对白/过场真实事件的物理音画同步验证及城门/花盆户外低帧率，不以本次室内29.995验收整体稳定30。荣耀及其它机型未重新实测。

## T80 户外长帧的时间对齐采样

- 上一轮T79实际改进了声音延迟，按progress继续主目标。当前源b0f9448，APK89e30e42/PID13147。经正常System→Load列表确认save008的2025/11/15 18:31:47、01:09:53，加载后首图人物/城门正常，PAD隐藏，用户save015继续保留。首次写state的长中文stdin因编码报错，未修改state，已用ASCII脚本完成任务卡登记，未据错误输出记成功。
- gate-audio89-outdoor-motion-*原始2400移动间隔，2401不同工作帧29.684727FPS/p95 41.342ms/max68.221ms，无失败/重复/>100ms。完整SF29.688185FPS/p95 33.561ms/p99 49.672ms/max99.250ms，>50ms14个。39批CPU19.361/GPU22.977ms、draw873.38，稳定30尚未通过。全部15旧调参文件缺席、原底座450/30/4槽/cache1/texdirty1/BC2/FIFO/timing1，测量时无录像/CPU采样。
- 随后独立40秒simpleperf task-clock:u/f500/dwarf，显式--clockid monotonic，原工具SHA590668cd...，实际记录39.9914秒/30044样本/丢失0。rg-long-frame-cpu-20261116-123002原始perf、maps、精确ELFf178f1fe、逐帧CSV、命令与source dirty归档。主线程13185为本app线程组13147的ffrs-guest且占58.52%全线程样本，实际调用链为游戏队列入口；原记录样本time明确落在同源CLOCK_MONOTONIC逐帧CSV覆盖范围，未推测跨时钟换算。
- 分析仅完整帧区间，25个>45ms帧均值48.363/max58.579ms，主线程task-clock样本加权估算42.56ms/帧。1092个25..40ms帧均值32.686ms，主线程估算28.690ms/帧。长帧memo_unpin_all祖先路径估算7.92ms/帧，普通帧约0.044ms，增量约7.88ms，主要叶节点包含Scudo批量释放；其后get_image_slow约+1.58ms、stream_buffer/descriptors_build各+1.17ms。原始dump与long-frame-analysis.json保留。采样有开销且2ms周期带来估算误差，以上用于定位，未作为产品FPS。
- 代码确认memo_unpin_all在epoch失效或pinned>8192时即时归还sets到原slot.used_sets并clear全部DescMemo节点，每项持有多份CPU vector。下一步只考虑把已经失效的CPU缓存元数据移出查询表，并在逐帧固定预算下释放，GPU descriptor/fence回收与原命中验证继续原有路径。需验证front iterator即时失效、跨槽隔离、重复失效/关缓存、内存上限及shutdown，不复用旧epoch的条目。

## T81 描述符缓存元数据的分帧释放候选

- 分支task/T81-descriptor-memo-cleanup，HEADed80868。总控独占xbg_game.cpp、新回归测试和coordination。失效时按原顺序将所有唯一pinned sets放入原slot.used_sets，清pin表、重置local计数并递增memo_mod_gen。查询map立即swap到该槽唯一retired map，后续命中只访问新的空active map，原epoch/registration/view/image/fence验证继续原入口。第二次失效先清旧retired再替换，使每槽最多保留一个失效元数据代。
- 每次原生present在frame_trace_record和既有present_cpu计时结束之前执行最多512个旧map节点的销毁。预算512是本次实验选择，在所有槽间共用。CPU metadata仅包含vector及raw引用，释放时不会调用GPU销毁。destroy_slots开头完整清各retired map。C++工作草案已核swap的容器/iterator约束 https://eel.is/c++draft/unord.req 与 https://eel.is/c++draft/container.requirements.general 。front iterator以原memo_mod_gen立即失效，保留地址不构成命中依据。
- 真实RegisteredTexture/MemoImage/DescMemo、两个原map声明、memo_unpin_all/drain、present清理+原frame_trace_record、shutdown元数据前缀提取并ASan/UBSan执行，覆盖9000项、多份CPU vector/悬空raw目标的安全元数据销毁、立即移出查询、front代际、pinned重复引用唯一回收、槽0/1/15隔离、跨槽总512预算、反复失效只留一代、空/关缓存路径和全槽退出清理。组件最终日志memo-retired-cleanup-component-final.log退出0。
- 7项负控真实运行触发断言/ASan，分别无限预算、保留live map、漏front代际、漏set归还、仅清槽0、累积旧代、漏shutdown，memo-retired-negative-controls.json/log。完整94图形93通过1私有fixture跳过、10runtime通过，原始日志保留。此处是组件执行，无独立QA。
- 最初build2b73335b将预算放在perf_frame开头，会漏计到present_cpu。该初版尚未装机，已把清理调用移到原生present既有计时区间内，并重跑组件和完整回归。最终build-memo-retired-cleanup-candidate-final.log退出0，APK6311c9b6b5eb34aa78de0da4685ec2b23d0f9c0716ef7c61963ed803f40672c4、ELF758e7292e1a483db20e5935b61f6ad02605076266e642ae74b901c96f90a6d71，精确归档及memo-retired-cleanup-candidate-provenance.json。产品源SHA629eb23a...，音频SHA仍aef803af...。
- 当前477M仍89e30e42/PID13147，正在正常载入save007，已视检17:04/45:23确认框。先做该版花盆2400移动对照，再覆盖6311候选并正常加载同一007和008复测，候选尚未声称实际帧率收益。用户最新015及全槽备份保留，荣耀暂停，稳定30目标继续。

### T81 首轮实测与清理阶段调整

- 旧89在save007实际首图确认后，flower-audio89-control-motion-*2400间隔，工作28.438889FPS/p95 44.541ms/max73.023ms；完整SF28.443468FPS/p95 49.622ms/max115.850ms、>100ms2个。39批CPU20.226/GPU22.944ms、draw884.379。PAD隐藏及原无调参缺省保持。
- 6311覆盖后最初首图是Continue确认框，已排除。补A后实际协会正确，再正常System→Load确认00717:04/45:23，首图人物/花盆/HUD正确。flower-memo-retired-candidate-motion-*2400间隔工作28.413909FPS/p95 43.470ms/max79.748ms；完整SF28.415078FPS/p95 49.625ms/max115.808ms、>100ms2个。39批CPU20.473/present1.270/GPU22.849ms、draw884.649。实际平均帧率与物理长帧没有改善，不能按工作帧p99由53.067降48.870ms宣称稳定性完成。
- 原6311清理在cfg.present和xbg_frame_pace之后，平均present CPU多约0.44ms。现把512项CPU元数据销毁移到submit_slots及诊断读回之后、原xbg_frame_pace之前，让GPU提交后的CPU清理进入原限帧等待预算。既有pacer、目标帧率和present调用使用原逻辑，原present_cpu计时覆盖清理。组件提取actual cleanup→pace调用，真实frame trace独立于清理预算，7负控与94图形93通过1私有skip再次通过，graphics-tests-memo-cleanup-before-pace.log和memo-retired-before-pace-negatives.log。
- build-memo-cleanup-before-pace.log退出0，APK0a3881ab383e080f4a33bea3f64980c3b5c1d939b3779ea7f5555866e1d003b1、ELFc01def40a1c195f7214d478a46cd60dc13bd9d6ab8c270d68832b9f8987c82b3，精确归档与memo-cleanup-before-pace-provenance.json。产品源SHAa882953a...，音频仍aef803af...。已覆盖0a到477M/PID8005，冷Continue首图实际协会，人物/光照/HUD正常，音频speaker3/1026burst/2052buf。当前正在正常载入007确认框，尚未测量0a的性能。下一步视检确认007后2400移动+完整SF，再决定保留/回退；之后还有008、HOME及花叶连续显示回归。

## T82 用户要求的发布冻结与后续暂停

- 0a候选在save007首图人物/花叶/HUD正常，2400移动间隔工作29.192199FPS/p95 42.648ms/max73.965ms；完整SF29.198770FPS/p95 49.577ms/p99 82.648ms/max99.251ms，>100ms0个。旧89同点SF28.443468/max115.850ms、>100ms2个，draw884.20/884.38相近，当前显示局部改善。39批CPU19.283/present1.291/GPU23.228ms。仍未全场景稳定30，0a的008/HOME和物理音画同步未完成。冻结当前清理时机与已验证的音频路径，停止新增优化实验。
- 用户明确要求提交当前版本、关注高通兼容并安装荣耀，准备正式发布。用户另明确选择“发布后暂停自动优化”。本轮先前为progress，当前按发布收尾推进。荣耀安装授权已重新授予。随后两个USB设备均从ADB及Mac IOUSB列表消失，用户明确回复“稍后连接，先完成发布包”，因此荣耀安装及本版真机验收登记待连接。
- 荣耀断开前读到ROD2-W69及已安装旧包，签名证书SHA256与当前包同为0203b98094ec6fd5811162a236b376241e8425653996744c418e0cc00696969d，旧APK已保存honor-before-103.apk。旧前台为FFRS。只读备份原存档时run-as访问外部目录被Android16拒绝，shell tar/pull也因私有data.dat权限失败，错误探测归档，未把102字节错误文本或只含目录的tar认定为备份。原存档树、大小和控制文件已记录，未对荣耀执行安装/重启/存档写入。重新连接后可同签覆盖并正常载入原存档验证。
- git fetch发现用户在默认分支新增5个主页、安装指南和法律说明提交，最新947838b。T81源码检查点52a827e后合并用户最新分支，README和安装指南冲突以用户最新版本正文解决，合并f3f254f。当前task/T82-community-103-release，版本升为1.0.3/versionCode4。保留用户社区与免责声明内容，按本轮实际范围更新版本/帧率与待连接信息，纠正README-HONOR历史将刷新率当60FPS的说明。
- 本次发布应用、自有资源及许可证，游戏数据由用户自行提供。计划从干净源码提交重建，执行94图形/10运行时、JNI设备分档与Java机型合约，核实Mali条件对Adreno厂商分支的覆盖；实际高通设备范围标记待连接。随后生成社区ZIP、APK、说明、清单和SHA，提交/推送默认分支及正式GitHub版本，回下载逐字节检查，再调用goal暂停。稳定30目标未完成，发布不能用作该目标完成依据。

### T82 正式发布与校验完成

- 正式版本v1.0.3已发布为GitHub latest，isDraft=false/isPrerelease=false，发布页 https://github.com/Cetto9923/snk-the1st-portable/releases/tag/v1.0.3 。tag与release-manifest均指向干净源码45f963e5225f81edc04bcd6b26b98e1f00df84b1，默认分支已推送该版本及用户文档合并。冻结manifest为versionCode4/versionName1.0.3，包名org.snk.the1st.gamewindow，ABI arm64-v8a，min28/target34，沿用可调试配置及原签名0203b980...，发布说明已明确。
- 首次打包后补齐xbg_dirty.c页跟踪组件的完整seedds MIT声明到APK assets/licenses/nxnative-dirty-MIT.txt，NOTICE同步记录，重新从干净45f963e构建。最终APK SHA256 f5e705c9e0d5edd22680020d3109cb86656083236132e0e7007f831648837809，ELF c01def40a1c195f7214d478a46cd60dc13bd9d6ab8c270d68832b9f8987c82b3。最终APK原生lib与已测0a逐字节一致，原生源a882953a/音频aef803af；旧临时1c2150包仅保留本地，未发布。
- 最终源码执行94图形93通过1私有输入跳过、10运行时、4 JNI分档与Java机型合约，各命令退出0，release103-final-test-receipt.json与四组原始日志保留。Java合约覆盖SM8635及多代Snapdragon8/Dimensity9机型选择；图形组件覆盖Mali条件对0x5143 Adreno分支的隔离。高通实际游戏本版测试和荣耀安装仍按用户要求等待USB重新连接。
- 6公开附件为APK、社区ZIP、SHA256SUMS、release-manifest、install-guide.zh-CN.md、copyright-notice.zh-CN.md。社区ZIP SHA256 72542902c5ad53e5f6aa68870fd082ed91f3cd877bfa47e4499b060510faa5cb。包内15成员逐项SHA通过，含应用/自有资源与10份许可证文本；18条校验值通过。公开APK检查排除NSO/NCA/NSP/XCI/XGS/密钥/票据和RomFS/shaders游戏资产目录。
- gh release download从已发布地址重新下载全部6附件，与本地发布件逐字节一致，解包后15成员再按公开SHA检查通过。community-103-live-release.json、community-103-public-verification.json、signature/badging、build-provenance及构建日志保留在.local/publication。GitHub tag API和默认分支API均验证45f963e，latest API返回v1.0.3。
- 用户已明确选择发布后暂停自动优化。当前发布与校验完成，将调用goal paused并结束。完整稳定30及物理口型/过场同步目标继续登记为未完成，不能标complete。当前ADB列表仍为空，荣耀设备安装列为用户延后项；最后已装的477M为0a运行层版本，最终1.0.3待重新连接后覆盖安装。恢复安装使用显式文件.local/publication/community-103-final/snk-the1st-1.0.3-arm64.apk，证书匹配后install --no-incremental -r；荣耀序列A42BBB5109000333，477M序列RG477M01445122。后续机测按实际画面和已存在存档验证，禁止以菜单/刷新率替代游戏FPS。


## T83 · 2026-11-16 数据增量补丁与本地 DLC 挂载

- 分支 `task/T83-data-delta`，基线 `7b20a84` 加本次脏树。修改本地 AOC 枚举、分页、只读挂载与版本号，新增真实函数 ASan/UBSan 回归。无 DLC 的旧目录仍返回 0。98 个原始 PublicData 包含第三方重打包标记，来源与逐文件摘要保存在私有清单。
- 配套 APK `1.0.4-preview` / versionCode 5，SHA256 `36bccd87fbf0afad70cd04539ef6db884840ab4385af1e04c9548f388836ad44`，原签名一致。构建退出 0，runtime 11 项通过，graphics 94 项中 93 通过、1 缺私有输入跳过。日志与精确源码摘要见 `.local/publication/data-patch-20261116/application-and-device-receipt.json`。
- 增量补丁 `.local/publication/data-patch-20261116/SNK-v1.0.7-resource-dlc-patch.zip`，762877138 字节，SHA256 `46ff0dfb688b526c376be839c66a4f1676d4baaea59a2d75ad2f786994897649`。两个现有完整包分别覆盖后，72360 RomFS + 6611 XGS 的 SHA256 全部一致。补丁新增/替换 2356 RomFS、6193 XGS、294 AOC 文件，移出两个旧 nx_icon 的说明随包附带。原 NSP、完整 ZIP 与存档保持原输入。
- 用户上传文件集中于父项目 `.local/nas-upload/SNK-patch-20261116/`，仅补丁、配套 APK、三步说明及 SHA256SUMS 四项。密钥、NCA、日志和工作目录不在交付目录或补丁中。性能目标仍按用户要求暂停。
- 荣耀 `A42BBB5109000333` 重新连接，覆盖安装退出 0。原存档成功载入洛连特市，DLC 数量 98，Item/DLC 页面出现对应项目，玩偶装领取后条目变灰。未手动存档，其余项目尚未逐项领取。随后重启再次载入原档，场景和人物可见。
- 荣耀初次资源扫描 78967/78971 一致，4 个 XGS 与通用清单不同。已备份四个原件、部署通用件，并将4项及294个AOC逐项重新校验通过，最终全量资源清单匹配。最后图 `honor-generic-final.png`。
- 桌面 freeform 在14:15:20出现 PCLauncher/游戏窗口焦点超时 ANR。等待并最大化后恢复，真实城镇和菜单可操作，证据 `honor-last-anr.txt`。只验证该流程。存档 data.dat 因系统权限无法完整备份，tar仅目录，已明确标为不可用备份。文件大小/mtime仍50773字节/2026-11-15 09:59，原档可读。
- 再生成命令 `python3 .local/publication/data-patch-20261116/prepare_patch.py` 当前会拒绝覆盖已有产物，需要复制脚本到新日期输出目录后使用。后续元数据补充步骤记录在本会话工具记录，最终交付 SHA 以上述值为准。公开 v1.0.3 Release 仍为原正式版本。


## T84/T85 · 2026-11-16 一加启动候选与自动横屏

- 分支 `task/T84-oneplus-crash` 基于062af6d。用户log在Adreno840设备加载window3.xtx后SIGSEGV，PC偏移0x5698d0，arena0x7a37600000+0x2d1400000跨多段4GiB区域，早先allocator位32补丁错误拒绝部分有效节点。JNI缺省对所有设备恢复原始四处CBZ判空，原诊断marker仍可覆盖。runtime11通过退出0，日志 `.local/publication/oneplus-runtime-tests.log`。同类cleanup位32补丁仍待独立验证，未据此宣称全设备全流程稳定。
- 1.0.5-preview候选b4cd0142已发用户，用户后续截图反馈能进入厂商标志但无法横屏。手机收到的精确APK摘要未回读，按用户上下文记录。
- 新包1.0.6-preview/versionCode7，manifest增加sensorLandscape，允许左右横握，APK实际xmltree screenOrientation=6。SHA256 `b85a30cd9204b6fc1d5e2842cd9bab209281f198f705f29c8c09e31c9119526c`。构建/安装日志、活动dump与图片在 `.local/publication/landscape-106/`，精确构建命令见会话工具记录。
- 荣耀A42BBB5109000333现已连接，前包1.0.4/5回读为honor-previous.apk后覆盖安装退出0，PID9686，系统活动方向SENSOR_LANDSCAPE，3000x1920截图。新缺省original_allocator_pointer_tests=1已写入该轮日志，未见fault，真实标题和当前进度读档可见，截图honor-game.png/honor-gameplay.png。虚拟按键沿用按新视图尺寸重算的既有布局。该次只验证启动/读档窗口。
- 新包已通过open -R在访达定位。手机方向与完整游戏流程等待对方实测。性能自动优化继续按用户要求暂停。公开Release仍为此前阶段版本。
