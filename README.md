# 空之轨迹 the 1st → 荣耀平板 GT Pro

Switch 原生游戏《空之轨迹 the 1st》（TID `01001E9023920000`）在 Android 平板上的原生移植工程。

当前状态：guest 曾在真机执行到资源加载，但尚无真实可玩画面验收。资源读取器已补充压缩块解码，并从本体解析出文件清单与少量原始资源；音频、图形及完整游戏流程仍待实现和验证。最新记录见 `coordination/HANDOFF.md`。

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
