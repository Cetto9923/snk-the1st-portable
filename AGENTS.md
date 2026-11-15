# 空之轨迹 the 1st → 荣耀平板 GT Pro 移植项目 — 工程规范

本文件是本仓库唯一工程规范来源。用户直接指令优先。

## 目标与边界

- 目标游戏：《空之轨迹 the 1st / Sora no Kiseki the 1st》（Falcom，2025-09-19）。TID `01001E9023920000`，Rights ID `01001e90239200000000000000000012`。
- 目标设备：荣耀平板 GT Pro（HONOR ROD2-W69 / SM8635 / Adreno 735 / Android 16）。荣耀设备使用 `adb -s A42BBB5109000333`。当前用户要求暂停荣耀真机操作，转到已授权的 RG477M（MT6897 / Android 14），使用 `adb -s RG477M01445122`。天玑通用配置与逐机实测结果分别记录。
- 技术路线：**原生移植**。游戏本体是 Switch 原生 ARM64 NSO，在 Android ARM64 上原生执行；NVN 图形接口由本项目的 Vulkan 兼容层提供。不用模拟器、串流、空窗口、硬编码菜单或视频替代。
- 继承基线：`/Users/yuyan9923/GitHub/ff-resonance-honor-gtpro`（分支 `work/honor-gtpro-30hz`，提交 `032e5f6` + 该工作区的未提交改动）。基线仓只读，不在其上继续开发，不删除其 `.local` 数据。
- 可直接继承：`src/runtime`（NSO 加载器、HLE）、`src/graphics/nvn_*`（NVN→Vulkan）、`src/android`（应用壳）、`scripts/`（构建与分析工具）。
- 必须重做：`src/graphics/nvn_vulkan/engine/xbg_*` 是 FFRS 那款 UE5 游戏的引擎胶水层，与 Falcom 引擎无关，需按本游戏实际调用重写或裁剪。
- 不改游戏包、升级档、DLC、存档与基线仓；所有生成物在本项目独立目录；密钥、票据、游戏数据、APK 不进 Git。

## 数据与密钥

- 密钥文件：本机 `~/.switch/prod.keys` 与基线仓 `.local/keys.txt`（含 `header_key`、`key_area_key_application_*`、`titlekek_*`）。本项目使用 `titlekek_11` 解出本游戏 title key。
- 解包工具（本项目自有）：`scripts/extract/nsp_extract.py`、`scripts/extract/nso_decompress.py`、`scripts/analysis/hle_coverage.py`、`scripts/analysis/module_graph.py`。
- 提取产物放 `.local/`，不入库；关键产物记录路径、大小与再生成命令。

## 协作与接力

- 总控是 `coordination/state.json` 与 `coordination/HANDOFF.md` 的唯一写者；`coordination/STATUS.md` 由脚本生成，不手工编辑。
- 同一文件只有一个写者。优先独立分支/worktree；分支命名 `task/Txx-<role>`，仅总控串行集成。
- 每张任务卡有 ID、角色、目标、输入、输出、依赖、写入范围、验收与恢复点；总控在 `state.json` 记录写入占用。
- 实际构建/测试/有意义的原子修改后保存检查点；交接时写明分支、HEAD、命令、产物、失败与下一步精确命令。
- 不虚构并行执行、消息或独立 QA；没有独立执行能力就写 NOT_RUN/BLOCKED。

## 验收纪律

- 所有 PASS 关联 commit/dirty 状态、输入版本、构建 ID、测试条件、原始日志与退出码；不用恒真断言或删测试改绿。
- 真机 PASS 必须来自报告中明确标识的授权目标设备上的真实游戏场景，不能用菜单、空场景、屏幕刷新率或重复呈现帧替代。
- 保留原游戏行为：帧率提升不得改变战斗、动画、物理、音频、输入与过场速度。
- 只验证一段流程时，称该流程验证版，不声称完整兼容。
- 模拟器报告只作线索，不继承其中 PASS/帧率/引擎归属。
