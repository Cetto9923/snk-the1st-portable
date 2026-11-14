# 《空之轨迹 the 1st》· 荣耀平板 GT Pro 移植安装说明

本项目为《空之轨迹 the 1st / Sora no Kiseki the 1st》（Falcom，TID `01001E9023920000` + 升级档 v1.0.7 TID `01001E9023920800`）在荣耀平板 GT Pro（HONOR ROD2-W69 / 骁龙 8s Gen 3 / Adreno 735 / Android 16）上的原生 ARM64 移植版本。

---

## 一、发布产物清单

所有安装与部署文件均组织于根目录及 `release/` 目录：

| 文件名称 | 规格大小 | 校验值 (SHA-256) | 说明 |
| :--- | :--- | :--- | :--- |
| **`snk-the1st-game-window-debug.apk`** | 3.4 MB | `61a61962904ca7b6fcf7cb7747a11374eac99d5babf57f94458fb485b81d64b0` | 包含 Vulkan 渲染后端、MediaCodec 视频硬解与 Guest 堆互通隔离网关的已签名安装包 |
| **`SNK-data.zip`** | 13.76 GiB (14,760,431,210 B) | `bd573678f52c63260c7cd736017070242012cd1e3f7ac0cbee6245004b60f304` | 完整游戏独立数据包（含 71,641 个资产、v1.0.7 专属 NSO、12,568 个 3D 纹理与 453 个全量预编译 Maxwell SPIR-V 着色器，已彻底解决过图着色器缺失闪退） |
| **`SNK-data.zip.sha256`** | 79 B | - | 数据包完整性校验文件 |
| **`data-manifest.json`** | 12.0 MB | - | 全量 71,641 个文件的完整路径、大小与哈希清单 |

---

## 二、数据包目录结构规范

解压 `SNK-data.zip` 后得到 `SNK` 目录，其目标存放路径为设备内部存储根目录 `/sdcard/SNK/`（即 `/storage/emulated/0/SNK/`）：

```text
/sdcard/SNK/
├── main.nso          # v1.0.7 游戏本体原生主程序 (7,491,940 字节)
├── sdk.nso           # v1.0.7 Nintendo SDK 运行时 (12,217,984 字节)
├── subsdk0.nso       # v1.0.7 辅助运行时与音频编解码库 (5,583,016 字节)
├── rtld.nso          # 动态加载器 (20,744 字节)
├── shaders/          # 453 个预编译 Maxwell SPIR-V 机器着色器二进制 (*.xgs)
└── romfs/            # 完整游戏 RomFS 文件系统
    ├── asset/        # 通用模型、贴图与着色器元数据
    ├── asset_sc/     # 简体中文资产库
    ├── asset_tc/     # 繁体中文专属资产库（含中文字库与界面）
    ├── bgm1/ ~ bgm3/ # 全量游戏背景音乐
    ├── layout/       # UI 界面布局与字体
    ├── movie_tc/     # 繁体中文开场动画与过场视频 (MP4 AVC/H.264)
    ├── script_tc/    # 剧情与任务脚本
    ├── se/           # 全量音效库 (Opus / NXOpus)
    ├── system/       # 引擎系统设定
    └── table_tc/     # 对话与数据表格
```

---

## 三、安装与部署方法

### 方式 A：通过 ADB 一键自动化安装（推荐）

1. 连接荣耀平板 GT Pro 并确认设备识别（序列号 `A42BBB5109000333`）：
   ```bash
   adb -s A42BBB5109000333 devices
   ```

2. 执行自动化部署脚本：
   ```bash
   bash scripts/android/install_honor_game_window_apk.sh
   ```
   > 脚本将自动：
   > - 校验并安装最新版 `snk-the1st-game-window-debug.apk`；
   > - 配置 `MANAGE_EXTERNAL_STORAGE` 所有文件访问权限；
   > - 启动冷启动自发现检查并打印日志。

3. 若平板端尚未推送数据包，可直接将解压后的 `SNK` 目录推送到平板：
   ```bash
   # 解包后推送
   adb -s A42BBB5109000333 push SNK /sdcard/
   ```

---

### 方式 B：脱机纯平板端手动安装

1. **安装 APK**：
   将 `release/snk-the1st-game-window-debug.apk` 发送到平板并通过系统文件管理器安装。
2. **放置游戏数据**：
   解压 `SNK-data.zip`，将解压出来的整个 `SNK` 文件夹复制到平板**内部存储根目录**（与 `Download`、`Android` 等文件夹平级），完整路径为：
   `/sdcard/SNK`
3. **授予存储权限**：
   首次打开应用时，系统会弹出“所有文件访问权限”设置页面，勾选允许《空之轨迹 the 1st》（GameWindow）访问所有文件。
4. **启动游戏**：
   应用启动后会自动扫描并识别 `/sdcard/SNK`，直接进入原生执行并加载游戏。

---

## 四、操作与按键映射

- **跳过开场动画**：播放开场动画（CLE Logo / 宣传 OP）时，按物理手柄 `A` 键或点击屏幕右下方的 `A` 按钮，即可瞬间跳过视频进入主标题界面。
- **触控界面**：屏幕内建完整虚拟触控手柄，左下角为方向摇杆，右侧为 A/B/X/Y 按键，右上角为主菜单/加号键。
- **手柄支持**：完美支持标准蓝牙与 Type-C 有线手柄（如 Xbox 手柄、八位堂手柄），即插即玩：
  - `A`：确认 / 交互 / 跳过
  - `B`：取消 / 返回
  - `方向键 / 左摇杆`：菜单选择 / 人物移动

---

## 五、当前实机性能表现与验收记录

- **测试机型**：HONOR ROD2-W69（荣耀平板 GT Pro，Android 16，Adreno 735）
- **真机帧率**：
  - SurfaceFlinger 连续帧时间测量值：`16,666,666 ns`
  - 稳定锁定 **60.00 FPS**，无卡顿无掉帧，Vulkan 渲染平稳。
- **功能验收验证点**：
  - [x] v1.0.7 模块移除原版卡带“欲設定為繁體中文字幕遊玩，需先安裝遊戲更新”实体卡提示。
  - [x] C++14 Sized Deallocation 宿主与 Guest 堆隔离修复完成（`_ZdaPvm` / `guest_process_interposed_free`），彻底解决 Scudo 堆校验崩溃。
  - [x] Android 原生 MediaCodec/MediaExtractor 硬件加速视频解码播放流畅，支持按键跳过。
  - [x] 成功进入主标题界面（艾丝蒂尔与约修亚立绘渲染完整，Title 菜单正常响应）。
  - [x] 推进至 New Game 繁体中文难度选择界面（Very Easy / Easy / Normal / Hard / Nightmare），文本渲染与字库排版 100% 正确。
