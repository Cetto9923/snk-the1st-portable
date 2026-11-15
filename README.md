# 空之轨迹 the 1st → 荣耀平板 GT Pro

Switch 原生游戏《空之轨迹 the 1st》（TID `01001E9023920000`）在 Android 平板上的原生移植工程。

当前社区版本为 `1.0.1-preview`，整合了声音、纹理、亮度、植被显示、内存释放与渲染提交修复，并同步了可编辑触屏按键。RG477M 与天玑配置采用 720p / 30 帧目标。实际场景帧率和兼容性仍需持续验证，最新结果见发布页与 `coordination/HANDOFF.md`。

公开应用包提供兼容运行程序与项目自有界面资源，运行所需游戏数据由使用者自行准备。安装方法见 [安装与使用](docs/release/安装与使用.md)，版权与使用边界见 [版权与免责说明](docs/release/版权与免责说明.md)。下载入口为本仓库的 [Releases](https://github.com/Cetto9923/snk-the1st-portable/releases)。

## 恢复入口

- [AGENTS.md](AGENTS.md)：本项目唯一工程规范。
- [docs/PROJECT.md](docs/PROJECT.md)：目标、阶段与验收标准。
- [docs/analysis/2026-11-05-baseline-and-reuse.md](docs/analysis/2026-11-05-baseline-and-reuse.md)：本轮基线、模块图与复用差距分析。
- [TASKS.md](TASKS.md)：T00–T06 任务规格。
- [coordination/STATUS.md](coordination/STATUS.md)：当前状态（脚本生成）。
- [coordination/HANDOFF.md](coordination/HANDOFF.md)：交接记录。

## 常用命令

```sh
# 解包本体（只落 ExeFS 与清单，不落 9GB 全量 RomFS）
python3 scripts/extract/nsp_extract.py --nsp "<本体 nsp>" --keys .local/keys.txt \
    --out .local/nca/exefs --report .local/nca/inventory.json

# 解压 NSO 模块（自带 LZ4 解码器）
python3 scripts/extract/nso_decompress.py .local/nca/exefs/main --out .local/nca/nso/main.bin

# 模块图与 HLE 缺口
python3 scripts/analysis/module_graph.py --modules main=... --hle src/runtime/hle/guest_process.c \
    --resolver <基线>/scripts/runtime/resolve_import_callers.py --out .local/analysis/module_graph.json

# 设备资源空闲后构建 Android APK（当前包名已独立）
bash scripts/android/build_game_window_apk.sh
```

## Token 与接力

不要把全部状态留在一个聊天里。总控维护 `coordination/state.json` 与 `HANDOFF.md`，每个工作 Agent 有独立任务、写入范围与回报文件。换模型时继续未完成任务，不从头调研。
