# 基线与复用差距分析（2026-11-05）

## 1. 游戏身份

| 项 | 值 | 证据 |
|---|---|---|
| 标题 | 《空之轨迹 the 1st / Sora no Kiseki the 1st》 | TID `01001E9023920000` 检索；Falcom 2025-09-19 作品 |
| 包 | `[本体v1.0.0][01001E9023920000][20.2.0][中文][KR].nsp`（9.81GB）+ `[升级档v1.0.7]`（630MB）+ 98 个 DLC | `/Users/yuyan9923/GitHub/FC` |
| Rights ID | `01001e90239200000000000000000012` | 票据 0x2A0 |
| title key | `titlekek_11` → `5586aabfc96ddf4939952c21f2cf27d5` | 本项目 `scripts/extract/nsp_extract.py` 暴力枚举 23 个 kek 后命中 NSO0 魔数 |
| 引擎 | Falcom 自研（同《界之轨迹》），HD-2D | 官方访谈；游戏数据内 `map#*.nvn` 等 NVN 图形文件 |

## 2. 解包工具链（本项目自有，不依赖 hactool）

- `scripts/extract/nsp_extract.py`：PFS0 → NCA 头（XTS，`header_key`）→ 分区（CTR，title key）→ ExeFS 提取 + RomFS 清单。
  - **已用 FFRS 基线逐字节校验**：FFRS 本体的 5 个 ExeFS 文件 SHA-256 与基线仓 `.local/exefs/` 完全一致。
  - hactool 本机版本对 rights-id 头解不开（`Invalid NCA header`），因此自建实现。
- `scripts/extract/nso_decompress.py`：ExeFS 内 NSO 是 LZ4 压缩版，自带纯 Python LZ4 block 解码器，重建未压缩镜像（段文件偏移 = 内存偏移 + 0x100，模块名按原位回填）。
- `scripts/analysis/hle_coverage.py` / `scripts/analysis/module_graph.py`：导入表与模块图分析。

## 3. ExeFS 与模块

| 模块 | 压缩 | 未压缩 | 模块名 | import | export |
|---|---|---|---|---|---|
| main | 3.85MB | 6.67MB | `sora_deploy` | 395 | 18 |
| rtld | 8.5KB | 16.6KB | `nnrtld` | 1 | 0 |
| sdk | 6.25MB | 12.12MB | `nnSdk` | 7961 | 22998 |
| subsdk0 | 3.43MB | 5.69MB | `multimedia` | 4025 | 9729 |

模块构成与 FFRS 基线一致（main + rtld + sdk + subsdk0），**继承的 NSO 加载器与模块装载顺序可直接复用**。

## 4. 复用差距（继承 FFRS 荣耀基线）

模块图（导入解析：HLE 按名字应答 + 同伴模块导出）：

| 模块 | import | HLE 应答 | 同伴模块应答 | 未解析 |
|---|---|---|---|---|
| main | 395 | 135 | 260 | **0** |
| rtld | 1 | 0 | 1 | 0 |
| sdk | 7961 | 213 | 6 | 7742 |
| subsdk0 | 4025 | 106 | 426 | 3493 |

- **游戏模块本身零缺口**：main 的 395 个导入，135 个由继承的 HLE 应答，260 个由 nnSdk 提供。
- 真正的新增在 SDK 层：sdk 的 7742 个未解析里绝大多数是 libc/其它（5368）与 nn 旧式符号（702）——FFRS 运行时的 musl 与 HLE 已覆盖其中大部分，真实增量要看差集。
- 与 FFRS 同模块差集：**main +173、sdk +262、subsdk0 +211** 个 FFRS 从未触碰过的符号。
- main 侧已确认的 HLE 缺口（示例）：`nn::os::SendMessageQueue`、`nn::os::TimedWaitLightEvent`、`nn::os::AllocateMemoryBlock`、`nn::oe::PopNotificationMessage`。
- 音频：`multimedia` 模块自带 Opus（`opus_decode`、`_celt_*` 等在其动态符号表内为已定义），无需外部 Opus 依赖。

## 5. 图形与引擎层

- 游戏数据含 `.nvn` 文件 → 与 FFRS 同为 NVN 图形栈，`src/graphics/nvn_device`、`src/graphics/nvn_vulkan` 的 NVN→Vulkan 层可继承。
- `src/graphics/nvn_vulkan/engine/xbg_*` 是 FFRS 那款 UE5 游戏的引擎胶水（舞台/着色器/写回策略），与 Falcom 引擎无关 → 需按本游戏实际调用面重写或裁剪，这是 T03 的主体工作量。

## 6. 未决项

- **RomFS 物理元数据映射**：分区 1（3.91GB）内的 RomFS 头在分区内 +0x1be4000，其元数据偏移是逻辑偏移（约 14.9GB），与分区物理长度（9.79GB）不一致；按 FFRS 的 IVFC 路径无法直接取到目录/文件表。已见到的真实文件名（`shader`、`scene`、`ani`、`obj`、`vfx`、`map#*.nvn`、`personalTemplate.dat`、`*.xtx`、`*.nxopus`）证明数据可读，但完整清单待定位（T07）。
- 升级档 v1.0.7 与本体 v1.0.0 的差异（ExeFS 覆盖 + 增量数据）尚未合并；当前分析基于本体 v1.0.0。
