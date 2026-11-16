# 空之轨迹 the 1st — Android Native Port

Switch 原生游戏《空之轨迹 the 1st》（TID `01001E9023920000`）在 Android 设备上的原生兼容运行工程。

采用 ARM64 原生加载与指令执行 + HLE 系统服务桥接 + NVN-to-Vulkan 图形兼容层，实现用户自备游戏数据在移动端的高效运行。

当前社区版本为 **`1.0.2-preview`**，重点优化了掌机/手持设备的底座模式适配策略、图形渲染流水线及 CPU/GPU 调度效率。目前已在 RG477M 上完成实测验证，人物、音画、原版存档及城镇流程可正常运行；荣耀平板及其他主流高通、天玑机型正在进行回归验证与适配。最新测试细节与已知限制见 [Releases 发布页](https://github.com/Cetto9923/snk-the1st-portable/releases)。

> ⚠️ **重要声明**：公开应用包仅提供兼容运行程序与项目自有界面资源，**不包含、不托管、亦不分发任何受版权保护的游戏资产、数据包或密钥（prod.keys）**。运行所需的游戏数据须由使用者自行从合法持有的原版游戏中提取。

---

## 📖 相关文档与使用指南

- 📦 [安装与使用指南](docs/release/安装与使用.md)
- ⚖️ [版权与免责说明](docs/release/版权与免责说明.md)
- 📄 [第三方开源许可证说明 (NOTICE.md)](NOTICE.md)
- 🚀 [下载入口 (Releases)](https://github.com/Cetto9923/snk-the1st-portable/releases)

---

## 🛠️ 构建与工具

```sh
# 解包本体（提取 ExeFS 与清单）
python3 scripts/extract/nsp_extract.py --nsp "<本体 nsp>" --keys .local/keys.txt \
    --out .local/nca/exefs --report .local/nca/inventory.json

# 解压 NSO 模块（自带 LZ4 解码器）
python3 scripts/extract/nso_decompress.py .local/nca/exefs/main --out .local/nca/nso/main.bin

# 构建 Android APK
bash scripts/android/build_game_window_apk.sh
```

---

## ⚖️ 免责声明

本项目为非官方、非商业性质的技术兼容性研究与社区学术交流项目。游戏名称、商标、人物、音乐及原始程序等全部知识产权归 **Nihon Falcom Corporation** 及相关权利人所有。使用者应遵守所在地法律法规并支持正版游戏。
