# 项目规格

## 目标

把《空之轨迹 the 1st》的 Switch 原生 ARM64 代码在荣耀平板 GT Pro 上原生跑起来，达到可持续游玩的真实场景。

| 项 | 值 |
|---|---|
| 游戏 | 《空之轨迹 the 1st / Sora no Kiseki the 1st》 |
| TID | 01001E9023920000（本体 v1.0.0 / 升级档 v1.0.7 / 98 个 DLC） |
| Rights ID | 01001e90239200000000000000000012 |
| title key | `titlekek_11` → `5586aabfc96ddf4939952c21f2cf27d5` |
| 引擎 | Falcom 自研（与《界之轨迹》同引擎），HD-2D；游戏数据含 `.nvn` 文件 |
| 设备 | 荣耀平板 GT Pro（HONOR ROD2-W69 / SM8635 / Adreno 735 / Android 16） |
| 路线 | 原生移植：NSO 原生执行 + NVN→Vulkan + Android 壳 |
| 基线 | ff-resonance-honor-gtpro（032e5f6 + 工作区改动） |

## 阶段与验收

| 阶段 | 目标 | 出口标准 |
|---|---|---|
| T00 基线 | 解包、身份确认、模块图、复用差距 | 本文件与 analysis 文档中的数据可复现 |
| T01 guest 启动 | 用继承的 NSO 加载器在真机拉起 `sora_deploy` | 真机日志显示 guest 进入初始化，退出码可解释 |
| T02 import 闭环 | 补齐 nn::os/nn::oe 等缺口 | 未解析 import 归零或明确记录为不需要 |
| T03 图形链 | NVN 家族按本游戏调用面补齐 | 出现第一帧真实画面（真机截图） |
| T04 场景可玩 | 标题画面 → 存档 → 真实场景 | 真机进入实际游戏场景 |
| T05 表现 | 帧率、音频、输入、稳定性 | 目标场景 P95 帧时间达标；音频无 XRun |
| T06 交付 | 傻瓜安装包 | 拷数据即玩的中文向导 APK |

## 设备与数据纪律

- 设备 ONLY `adb -s A42BBB5109000333`；禁止 `adb kill-server`，禁止卸载平板上其它包。
- 游戏数据、解密产物、APK 放 `.local/`；不提交、不上传。
- 本项目包名与 FFRS 基线区分，避免同设备互相覆盖。
