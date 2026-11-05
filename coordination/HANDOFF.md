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

