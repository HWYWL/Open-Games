# Open-Games · 飞牛 fnOS 游戏合集

把开源 3D 网页游戏整理成飞牛 NAS 应用：应用中心装好后，桌面出现一个图标，点开是类 Steam 的游戏库面板，点任意游戏封面即在新标签页直接开玩。

当前内置三款游戏（全部为单文件 HTML，模型 / 纹理 / 音效均由代码程序化生成，无外部资源依赖）：

| 游戏 | 类型 | 说明 |
| --- | --- | --- |
| 🚲 鹈鹕骑自行车 | 海岸公路休闲骑行 | 布料物理围巾、昼夜循环、实时合成音乐，14 个成就 / 5 种镜头 |
| 🔫 穿越火线 · 运输船 | FPS 团队枪战 | 考据还原「运输船」地图，枪械弹道与后坐力、bots 对战、击杀播报 |
| 🏎️ QQ 飞车 | 竞速漂移 | 漂移集气、小喷 / 双喷 / 氮气、四张原创赛道、道具赛 |

## 界面与交互

- 深色游戏库面板：顶部精选横幅 + 卡片式游戏墙，每张卡片有封面、简介、分类、首个键位提示
- 点击卡片（或横幅的「开始游戏」）→ **新标签页**打开游戏，鼠标右键卡片 / 「查看详情」可看完整玩法与键位表
- 分类筛选、搜索框（`/` 聚焦）、最近游玩标记（浏览器本地存储）
- 移动端自动切换为单列布局，游戏本身也支持触屏

## 目录结构

```
Open-Games/
├── manifest                 # fnOS 应用清单（appname / 版本 / 端口 8468 / 桌面入口）
├── ICON.PNG, ICON_256.PNG   # 应用图标
├── cmd/                     # 生命周期脚本（start / stop / status 等）
│   ├── main                 # ← 启动内置静态服务
│   └── install_callback …   # 安装 / 升级钩子
├── config/
│   ├── privilege            # 以 package 用户身份运行
│   └── resource             # 默认共享目录
└── app/
    ├── server/server.py     # 静态服务端（仅用 Python 标准库）
    ├── ui/                  # 桌面入口配置与图标
    └── www/                 # 网站根目录
        ├── index.html       # 游戏库面板
        ├── assets/          # 封面 / 横幅
        └── games/           # 三款游戏（单文件 HTML）
```

## 安装

用 [fnpack](https://developer.fnnas.com/docs/guide/) 打包成 `.fpk` 后在飞牛应用中心手动安装：

```bash
fnpack build                     # 产物在 dist/ 下
```

或在开发机上直接跑起来预览：

```bash
python app/server/server.py --host 127.0.0.1 --port 8468 --root app/www
# 浏览器打开 http://127.0.0.1:8468/
```

> 打包机为 Windows 时，请确认 `cmd/` 下的脚本在包内保留可执行权限（LF 换行 + 755）；建议在 WSL / Linux 环境下打包。

## 运行说明

- 服务由 `cmd/main start` 拉起：`python3 server/server.py`，监听 `0.0.0.0:${TRIM_SERVICE_PORT}`（默认 8468），日志写入 `${TRIM_PKGVAR}/info.log`
- 端口不在安装向导里开放，改端口需要同步修改两处：`manifest` 的 `service_port` 与 `app/ui/config` 的 `port`
- 健康检查接口：`GET /healthz` → `{"status":"ok"}`
- 全部游戏离线可玩，除首屏外不请求任何外网资源

排查启动问题：

```bash
/var/apps/Open-Games/cmd/main status   # 0 运行中 / 3 未运行
tail -n 50 "$(ls -d /vol*/@appdata/Open-Games 2>/dev/null | head -1)/info.log"
```

## 游戏来源与重新构建

三款游戏移植自 `claude-opus-5-5-demo`（Claude Opus 5.5 one-shot 生成的三个 3D 网页游戏，Three.js + esbuild）。源码经 esbuild 打包内联成单个 HTML 后放入 `app/www/games/`。

重新构建某一款游戏：

```bash
cd claude-opus-5-5-demo/pelican-bike     # 或 cf-transport-ship / qq-speed
npm install                              # 国内网络可加 --registry=https://registry.npmmirror.com
node build.mjs                           # 产出 dist/index.html
cp dist/index.html <本仓库>/app/www/games/pelican-bike.html
```

面板里的游戏清单、简介、键位表都在 `app/www/index.html` 顶部的 `GAMES` 数组里，新增游戏只需放一份 HTML 到 `app/www/games/` 并加一条记录。

## 致谢与声明

- 游戏源代码与美术由 claude-opus-5-5-demo 项目提供；封面与横幅为面板展示用途的 AI 生成插图
- 《穿越火线》《QQ 飞车》相关作品为技术演示性质的致敬作品，与原厂无关
- 本仓库代码以 MIT 许可证发布，见 [LICENSE](LICENSE)
