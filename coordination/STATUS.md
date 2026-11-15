# 当前项目状态（生成文件）

状态事件时间：2026-11-15T22:00:34.024413+08:00
阶段：T59程序桶链回归与真实移动复测完成，稳定30未达成
总控：Codex
更新方式：按事件更新，没有后台自动刷新。

| 任务 | 角色 | 状态 | 实际负责人 | 启动依赖 | 验收门禁 | 分支 |
|---|---|---|---|---|---|---|
| T00 | RE | passed | MiniMax Code | 无 | 无额外门禁 | work/snk-the1st-honor-gtpro |
| T01 | CORE | passed | Antigravity | T00 | 无额外门禁 | work/snk-the1st-honor-gtpro |
| T02 | CORE | passed | Antigravity | T01 | 无额外门禁 | work/snk-the1st-honor-gtpro |
| T03 | GRAPHICS | passed | Antigravity | T01 | 无额外门禁 | work/snk-the1st-honor-gtpro |
| T04 | ANDROID | passed | Antigravity | T01 | 无额外门禁 | work/snk-the1st-honor-gtpro |
| T05 | ANDROID | passed | Antigravity | T03 | 无额外门禁 | work/snk-the1st-honor-gtpro |
| T06 | QA | passed | Antigravity | T04 | 无额外门禁 | work/snk-the1st-honor-gtpro |
| T07 | RESOURCE | passed | Antigravity | T00 | 无额外门禁 | work/snk-the1st-honor-gtpro |
| T58 | RELEASE_ANDROID | passed | Codex | 无 | 无额外门禁 | task/T58-community-release |
| T59 | GRAPHICS | in_progress | Codex | T58 | 无额外门禁 | task/T59-rg477m-frame-time |

## 独占写入

- {"owner": "Codex", "task": "T59", "paths": ["src/", "scripts/", "tests/", "docs/release/", "NOTICE.md", "AGENTS.md", "coordination/"]}

## 阻塞

- 无

## 已验证

- 已核对独立 SNK GitHub 仓库与 RG477M MT6897 / Android 14 设备身份。
- 社区预览候选 b5837d53 在 RG477M 覆盖安装成功，原签名 SHA256 0203b980… 一致。
- RG477M 触屏菜单、编辑面板与显示切换已截图验证。6611 个着色器设备 SHA256 一致。
- 混音器默认关闭导致新装无声，已修复默认开关。用户已确认“有声音了”。
- 58 项图形测试通过 57 项，缺少本地私有 UINT 输入而跳过 1 项。6 项运行时测试通过。
- RG477M 完整 RomFS 72360 项与 shader6611 项逐文件哈希一致。
- Mali人物输入整数类型修正已接正常draw与warm路径。用户确认人物已显示。
- Mali vendor门禁真实分支组件用例通过，Adreno保留原shader模块。
- RG477M 硬件断点捕获重叠分配；原始allocator null tests诊断通过一次新建至自由移动，未作稳定30验收
- 用户确认关闭事件延迟后的当前版本天空无闪烁。关闭wtrack单独仍有条纹，未宣称完整根因解决。
- 原游戏540档位真实viewport960x540已抓取验证。无闪烁配置已固化为Mali默认，MT68/MT69默认使用原始allocator null tests。
- 缺省/marker/env/vendor编译门禁通过。graphics64项63通过1私有fixture跳过，runtime8通过，设备profile脚本通过。
- 1.0.1-preview已在独立空轨仓发布，APK SHA ea32adb3d3e0fe8061dc33c5fb5ade73ca8ace9ce4cdfd2638787164fa864dc1，公开包回下载全SHA256SUMS验证通过。
- 缺调试marker入口正常。原游戏新建save002艾里兹街道9:08，重启覆盖安装后Continue读回同位置和两个人物，缩略图正确。
- T59轮询缓存候选通过graphics65项64通过1私有输入跳过。载入户外与城门人物正常。先后采样含移动/剧情状态变化，不作为严格同点FPS提升证据。
- T59图形66项65通过1私有fixture跳过，运行时9项通过。有限阶段采集到期后恢复GPU快路径的修正已构建装机。
- T59实际poll_retire回归覆盖2/4/16槽全部回绕点通过，旧物理顺序循环负控被断言拒绝。完整图形67项66通过1私有fixture跳过。
- T59槽位代际写跟踪回归通过。批末事件模式2城门600帧真实移动窗口25.588FPS，p95 48.658ms，601个不同工作帧，失败0和重复0，尚未稳定30。
- 大块几何写跟踪没有实际命中。同提交前缀复用、缓存上传及批量刷新均无可确认性能收益，试验改动已撤回，原始patch和日志只保留.local/publication。
- 新simpleperf城门采样8413个且无丢失，memcpy15.93%、descriptors_build4.03%、nvn_program_info_if_changed2.90%。程序查找桶冲突仍回退全表扫描，正在构建索引链修正。
- 程序桶链APK a66bd9ed正常读回城门。simpleperf中program_info退出至少1%热点，真实移动601个不同工作帧25.405FPS、p95 48.765ms、最大86.724ms，未优于前一移动窗口。

## 未验证

- RG477M稳定30帧尚未达成。最新程序桶链600帧真实移动25.405FPS，p95 48.765ms。公开版仍保留a35c458无延迟事件默认。
- 除RG477M外的天玑机型仍待逐机验证，荣耀真机继续暂停。
- 批末事件模式2尚待更长时间和草叶区域显示回归。完整vertex/index写入跟踪尚未接入，保持vcache0。

具体恢复命令与未完成修改见 HANDOFF.md。
