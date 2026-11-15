# 当前项目状态（生成文件）

状态事件时间：2026-11-16T01:29:05.608561+08:00
阶段：T64按原1618模块约束实例输出写回范围
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
| T60 | GRAPHICS | in_progress | Codex | T58 | 无额外门禁 | task/T60-docked-profiles |
| T61 | GRAPHICS | in_progress | Codex | T58 | 无额外门禁 | task/T61-town-indirect-gpu |
| T62 | GRAPHICS | in_progress | Codex | T58 | 无额外门禁 | task/T62-rg477m-30fps |
| T63 | GRAPHICS | in_progress | Codex | T58 | 无额外门禁 | task/T63-storage-cache |
| T64 | GRAPHICS | in_progress | Codex | T58 | 无额外门禁 | task/T64-cull-writeback-bounds |

## 独占写入

- {"owner": "Codex", "task": "T64", "paths": ["src/", "scripts/", "tests/", "docs/release/", "NOTICE.md", "AGENTS.md", "coordination/"]}

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
- 宿主几何缓存候选每帧命中约22.3MB，顶点与索引实际复制约0.04MB，城门站立27.4-27.6FPS。同边界退休描述符复用后，临时池注册累计79209次时仅369槽、13活跃池，未按注册次数持续增长。
- T60源码将底座模式与内部渲染分辨率分开。RG新包ab12ac3e真实日志operation_mode1、native render540 selector2、target_fps30，保存save004洛连特市22:44并重启读回。
- T60图形69项68通过1私有fixture跳过，运行时9通过，设备环境与底座/限帧重点5项通过，Java分档合约通过。
- 洛连特市底座模式600帧真实移动601次queue回调且601个不同工作帧，11.670685FPS，p95 104.982ms，最大132.375ms，超过100ms70个。每帧why5 GPU读回一次，已定位未有模板证明的342eaea42136f6fc生产1280字节索引间接参数。
- T61精确342e原模块模板证明装机3fcc2a9c，同save005站立300帧从12.606提高29.561FPS，601帧移动26.580FPS、p95 52.187ms、max82.156ms，失败0和重复0。graphics72项71通过1跳过，runtime9通过，去掉参数边界负控SIGABRT被拒绝。
- T61有序捕获978a上传索引/flags后，原每两帧padding读回等待消除。shadow APK461fa7aa，600帧真实移动27.641FPS、p95 43.842ms、max79.347ms、601不同工作帧、无失败重复。graphics75项74通过1私有fixture跳过、runtime9通过。
- T62用户新地点save006正常新建，缩略图正常并完整备份。540p同点站立async1为23.887FPS，async0为30.004FPS，独立SF短呈现历史30.007FPS。540p600帧移动26.726FPS，尚未稳定30。
- T62原生450入口运行日志selector1/operation_mode1，PID26798单帧capture END3156，3D viewport800x450、UI1920x1080，画面人物/餐桌正常。graphics75项74通过1私有fixture跳过、runtime9通过，正在测600帧移动。
- T63 C1 mask候选4934fafa图形77项76通过1私有fixture跳过、运行时9通过。save007房屋花盆旁正常新建45:23并备份。600帧真实移动601不同工作帧27.451678FPS、p95 45.430ms、max67.202ms，失败0/重复0，超过100ms0。末尾同步等待0，仍未稳定30。
- T64精确1618实例输出范围命中12800000→552960B，正常移动末尾写回约29.6MB/2.75ms，旧36.5MB/3.45ms。onepass APK4e313a76与cache1，600帧移动601不同工作帧26.642139FPS、p95 46.851ms、max62.501ms，失败0/重复0/>100ms0。图形78项77通过1私有fixture跳过、运行时9通过、动态计数负控-6被拒绝。

## 未验证

- RG477M移动稳定30仍未达到。save007在T64输出范围/cache1下26.642FPS，实际减少写回但未证明端到端FPS收益，原生540保持。
- 高端机先使用原生底座渲染配置，1080p场景原生分辨率与60帧仍待验证。其他主流高通/天玑只有分档与通用代码覆盖，逐机实测未完成，荣耀仍暂停真机。
- 新宿主几何缓存与延迟事件模式2仍待更长时间草叶/天空动态和过图回归。默认缓存开关尚未公开改为开启。

具体恢复命令与未完成修改见 HANDOFF.md。
