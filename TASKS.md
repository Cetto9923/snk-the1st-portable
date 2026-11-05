# 任务规格

| ID | 角色 | 目标 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|---|
| T00 | RE | 解包本体/升级档，确认身份、模块图与 HLE 复用差距 | — | analysis 文档数据可复现 | passed |
| T01 | CORE | 用继承的 NSO 加载器在真机拉起 guest（`sora_deploy`） | T00 | 真机日志出现 guest 初始化，退出码可解释 | pending |
| T02 | CORE | 补齐 main/sdk 模块的未解析 import（nn::os 消息队列/灯事件/内存块、nn::oe 通知等） | T01 | 未解析 import 归零或明确豁免 | pending |
| T03 | GRAPHICS | 按本游戏实际 NVN 调用面裁剪/重写 `xbg_*` 胶水，补齐 NVN 家族 | T01 | 真机出现第一帧真实画面 | pending |
| T04 | ANDROID | 应用壳改包名、数据目录自动发现、傻瓜安装向导 | T01 | 拷贝数据即可启动，缺数据有中文指引 | pending |
| T05 | ANDROID | 音频（AAudio）、输入（手柄/触屏）、存档 | T03 | 目标场景无 XRun、输入可控 | pending |
| T06 | QA | 性能与稳定性验收（帧时间分布、长时间运行、热节流） | T04, T05 | 真机真实场景指标达标 | pending |
| T07 | RESOURCE | 定位 RomFS 物理元数据映射，完成 3.9GB 数据清单 | T00 | 可列出全部游戏文件 | pending |
