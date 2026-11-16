# 当前项目状态（生成文件）

状态事件时间：2026-11-16T12:25:02.733009+08:00
阶段：T79 音频输出延迟与音画同步排查
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
| T65 | GRAPHICS | in_progress | Codex | T58 | 无额外门禁 | task/T65-texture-check-cost |
| T66 | GRAPHICS | in_progress | Codex | T58 | 无额外门禁 | task/T66-object-lookup-chains |
| T67 | GRAPHICS | in_progress | Codex | T58 | 无额外门禁 | task/T67-android-frame-pacing |
| T68 | GRAPHICS | passed | Codex | T58 | 无额外门禁 | task/T68-descriptor-memo-inputs |
| T69 | GRAPHICS | in_progress | Codex | T58, T68 | 无额外门禁 | task/T69-native-display-timing |
| T70 | GRAPHICS | in_progress | Codex | T58, T68 | 无额外门禁 | task/T70-indirect-dispatch-sync |
| T71 | GRAPHICS | passed | Codex | T58, T68 | 无额外门禁 | task/T71-submit-stall-counters |
| T72 | GRAPHICS | passed | Codex | T71 | 无额外门禁 | task/T72-bc-parallel-fast |
| T73 | RELEASE_ANDROID | passed | Codex | T72 | 无额外门禁 | task/T73-community-preview-102 |
| T74 | GRAPHICS_RUNTIME | passed | Codex | T72, T73 | 无额外门禁 | task/T74-scheduling-trace |
| T75 | RUNTIME | passed | Codex | T74 | 无额外门禁 | task/T75-allocator-symbol-cache |
| T76 | GRAPHICS_RUNTIME | passed | Codex | T75 | 无额外门禁 | task/T76-texture-descriptor-index |
| T77 | ANDROID_RUNTIME | passed | Codex | T76 | 无额外门禁 | task/T77-android-performance-hint |
| T78 | GRAPHICS_RUNTIME | in_progress | Codex | T76, T77 | 无额外门禁 | task/T78-writeback-cache-range |
| T79 | CORE | in_progress | Codex | T76 | 无额外门禁 | task/T79-audio-output-latency |

## 独占写入

- {"owner": "Codex", "task": "T79", "paths": ["coordination/", "src/runtime/hle/audio_bridge.c", "tests/native/audio_bridge_transport_contract.c"]}

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
- T65正常ec3e71c源码包5576b32b、slot4/cache1/texdirty1/540/async0，Continue7真实移动601不同工作帧28.617652FPS、p95 43.559ms、max88.746ms，失败0/重复0/>100ms0。RSS从6336436kB降4394512kB，纹理哈希退出采样热点，仍未稳定30。
- T66状态和纹理查找桶链及局部性回归，79图形78通过1私有fixture跳过、运行时9通过，旧全表遍历/破坏链与取消局部性负控均SIGABRT -6被拒绝。APK9c412fe4真实540触屏移动29.131FPS，450触屏29.328FPS，450 Android摇杆路由29.992FPS，三窗口各601不同工作帧，无失败重复/>100ms。输入/路径条件不同，不作严格单变量归因。
- T67本应用present-mode路径修复，图形80项79通过1私有fixture跳过，运行时9通过。477M底座540p/4槽/cache1/texdirty1/async0，同save008摇杆各601不同工作帧，FIFO30.000FPS、MAILBOX29.883FPS。连续SF历史覆盖完整窗口，物理29.994/29.896FPS、p95均49.6ms，仍有16/50ms节奏。原始gate-fifo-native540-motion和gate-mailbox-native540-motion文件保留，未达到稳定物理30。
- T67官方Swappy2.1.3实验入口默认关闭，完整JNI引用、扩展/队列/交换链生命周期、固定30目标、无SDK/失败回退测试。81图形80通过1私有fixture跳过，运行时9通过，2个生命周期负控预期断言失败。450p同存档601工作帧，SDK开物理30.144FPS/p95 33.147ms，关物理30.020FPS/p95 49.614ms。继续2400间隔SDK开物理29.748FPS/p95 33.301ms/p99 49.697ms/max99.192ms，仍偶发长帧，未验收稳定30。
- T67最终撤回Swappy产品接线和依赖，实验源码完整哈希核验备份failed-swappy-experiment-source.tar与patch。真实APK7b7fac89已覆盖装，ELF符号和APK内容均确认无SDK。保留本应用present-mode路径、Vulkan统一清理与后台清按键保留手柄连接修复。图形81项80通过1私有fixture跳过，运行时9通过，输入生命周期1通过及2负控。477M从实际游戏场景连续3轮HOME3秒再回前台10秒，均同PID10246恢复实际draw与present，最后截图人物和场景可见。
- T68临时9类诊断009091ef显示静止城门每帧约181次image_revision，storage约22，driver0、uniform_buffer不足1。2bdf1bd2细分后texture serial仅约8.6，memory0，其他约154.5。原始日志与两份诊断patch和provenance保留。不能把这些失败视为UBO句柄问题。
- T68最终6c94ef1c同save008各2400间隔，CPU提交均值15.956→15.491ms，工作29.822→29.876FPS，SF p95仍49.6ms。图形82项81通过1私有fixture跳过、运行时9通过、3负控及同PID2797三轮HOME通过。
- T69原生VK_GOOGLE_display_timing默认关闭，APKedb78e86在477M marker1/FIFO真实移动，save008物理29.749FPS/p95 33.249ms，save007物理29.798FPS/p95 33.323ms，均2400间隔和完整SF覆盖。同PID24721三轮HOME恢复真实draw/present，图形85项84通过1私有fixture跳过、运行时9通过，4个实际断言负控通过。仍有100ms以上长停顿，稳定30未达成。
- T72 RG477M专属底座450/30及缓存/4槽/FIFO/显示时间戳/BC2已打包，0dfca4a6实际13调参文件备份重命名后启动配置一致。90图形89通过1私有跳过、运行时9通过、profile4与Java合约及10实际负控通过，HOME3同PID26945。
- T73 v1.0.2-preview已在独立空轨仓公开，标签2867bcf，APKba052997。6附件回下载逐字节一致，社区包解开后17项SHA通过，原游戏数据由用户提供。

## 未验证

- T76 installed78a1dfc1: save008 SF29.604 max132.319ms;save007 SF28.510 max99.274ms. Overall stable30 remains pending.
- T75 latest installed9b410c8b: gate SF29.580 then29.035;flower28.233 with132.294ms physical max. Stable30 remains pending.
- T74 latest long motion: save008 SF28.375FPS,max115.735ms;save007 SF27.086FPS,max115.500ms. Overall stable30 remains pending.
- RG477M稳定30尚未完全达到。0dfca4a6无调参文件，城门与花盆各2400移动间隔的物理帧率29.939/29.847，p95约33.2ms，仍有约99ms长间隔。
- 高端机先使用原生底座渲染配置，1080p场景原生分辨率与60帧仍待验证。其他主流高通/天玑只有分档与通用代码覆盖，逐机实测未完成，荣耀仍暂停真机。
- RG477M缓存/defer2/450/4槽/FIFO/timing/BC2已固化并发布1.0.2-preview，草叶/天空更多场景、过图和长流程仍待回归，物理约99ms长间隔继续定位。
- Swappy2.1.3实验SIGABRT/signal11根因仍未确认，产品已完整移除。当前原生呈现候选T69已通过三轮HOME，但GPU间接调度参数CPU回读触发全批同步的长停顿仍待优化。两帧呈现余量约66ms是当前实验选择，实际端到端输入延迟尚未测量，默认未固化到其他设备。

具体恢复命令与未完成修改见 HANDOFF.md。
