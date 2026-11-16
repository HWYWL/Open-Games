# Open-Games · 飞牛 fnOS 游戏合集

把开源网页游戏整理成飞牛 NAS 应用：应用中心装好后，桌面出现一个图标，点开是类 Steam 的游戏库面板，点任意游戏封面即在新标签页直接开玩。

当前内置五款游戏（模型 / 纹理 / 音效均由代码程序化生成，无外部资源依赖）：

| 游戏 | 类型 | 说明 | 开源地址 |
| --- | --- | --- | --- |
| 🚲 鹈鹕骑自行车 | 海岸公路休闲骑行 | 布料物理围巾、昼夜循环、实时合成音乐，14 个成就 / 5 种镜头 | [riba2534/claude-opus-5-5-demo · pelican-bike](https://github.com/riba2534/claude-opus-5-5-demo/tree/main/pelican-bike) |
| 🔫 穿越火线 · 运输船 | FPS 团队枪战 | 考据还原「运输船」地图，枪械弹道与后坐力、bots 对战、击杀播报 | [riba2534/claude-opus-5-5-demo · cf-transport-ship](https://github.com/riba2534/claude-opus-5-5-demo/tree/main/cf-transport-ship) |
| 🎯 几猫 · 国产 3A 大作 | 单关 FPS | 雨夜集装箱港口，切断三个上行链路中继器，躲开无人机与机器狗，1.4 MB 单文件 | [realcodebear/saltline-fable-5.2](https://github.com/realcodebear/saltline-fable-5.2) |
| 🏎️ QQ 飞车 | 竞速漂移 | 漂移集气、小喷 / 双喷 / 氮气、四张原创赛道、道具赛 | [riba2534/claude-opus-5-5-demo · qq-speed](https://github.com/riba2534/claude-opus-5-5-demo/tree/main/qq-speed) |
| 👶 以撒的结合 · 地下室的束缚 | 肉鸽弹幕地牢 | 12 层随机地牢、13 个 Boss、11 种敌人、55 件可叠加道具，Canvas 全程序化绘图 | [liyupi/binding-of-isaac-webgame](https://github.com/liyupi/binding-of-isaac-webgame) |

> 面板里每款游戏的详情弹窗右下角也有「开源项目」按钮，可直接跳到上面的原始仓库。

## 界面与交互

- 深色游戏库面板：顶部精选横幅 + 卡片式游戏墙，每张卡片有封面、简介、分类、首个键位提示
- 点击卡片（或横幅的「开始游戏」）→ **新标签页**打开游戏，鼠标右键卡片 /「查看详情」可看完整玩法、键位表与开源地址
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
        ├── index.html       # 游戏库面板（含 GAMES 清单）
        ├── assets/          # 封面 / 横幅
        └── games/
            ├── pelican-bike.html        # 单文件游戏
            ├── cf-transport-ship.html   # 单文件游戏
            ├── saltline.html            # 单文件游戏（1.4 MB，含内联 three.js）
            ├── qq-speed.html            # 单文件游戏
            └── isaac/                   # 零构建的多文件游戏（index.html + css/ + js/）
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

| 游戏 | 上游仓库 | 集成方式 |
| --- | --- | --- |
| 鹈鹕骑自行车 | [claude-opus-5-5-demo/pelican-bike](https://github.com/riba2534/claude-opus-5-5-demo/tree/main/pelican-bike) | `node build.mjs` 用 esbuild 打成一个 HTML |
| 穿越火线 · 运输船 | [claude-opus-5-5-demo/cf-transport-ship](https://github.com/riba2534/claude-opus-5-5-demo/tree/main/cf-transport-ship) | 同上（JS + CSS 内联） |
| QQ 飞车 | [claude-opus-5-5-demo/qq-speed](https://github.com/riba2534/claude-opus-5-5-demo/tree/main/qq-speed) | 同上 |
| 几猫 · 国产 3A 大作 | [realcodebear/saltline-fable-5.2](https://github.com/realcodebear/saltline-fable-5.2) | 上游本身是单个 `index.html`，改名 `saltline.html` 后直接放入 |
| 以撒的结合 · 地下室的束缚 | [liyupi/binding-of-isaac-webgame](https://github.com/liyupi/binding-of-isaac-webgame) | 零依赖零构建，原样拷贝 `index.html` + `css/` + `js/` |

三款 Three.js 游戏（鹈鹕 / 运输船 / QQ 飞车）重新构建：

```bash
git clone https://github.com/riba2534/claude-opus-5-5-demo
cd claude-opus-5-5-demo/pelican-bike     # 或 cf-transport-ship / qq-speed
npm install                              # 国内网络可加 --registry=https://registry.npmmirror.com
node build.mjs                           # 产出 dist/index.html
cp dist/index.html <本仓库>/app/www/games/pelican-bike.html
```

以撒游戏更新：

```bash
git clone https://github.com/liyupi/binding-of-isaac-webgame
cd binding-of-isaac-webgame
cp -r index.html css js <本仓库>/app/www/games/isaac/
```

几猫 / Saltline 更新（上游只有一个 `index.html`）：

```bash
git clone https://github.com/realcodebear/saltline-fable-5.2
cp saltline-fable-5.2/index.html <本仓库>/app/www/games/saltline.html
```

面板里的游戏清单、简介、键位表、开源地址都在 `app/www/index.html` 顶部的 `GAMES` 数组里，新增游戏只要把文件放进 `app/www/games/`，再补一条带 `href` 与 `repo` 的记录即可。

## 致谢与声明

- 游戏源代码与美术分别来自 [claude-opus-5-5-demo](https://github.com/riba2534/claude-opus-5-5-demo)、[binding-of-isaac-webgame](https://github.com/liyupi/binding-of-isaac-webgame) 与 [saltline-fable-5.2](https://github.com/realcodebear/saltline-fable-5.2)，均为 MIT 许可；本仓库只做移植、封装与面板，封面横幅为展示用途的 AI 生成插图
- 《穿越火线》《QQ 飞车》《以撒的结合》相关作品均为致敬性质的演示作品，与原厂 / 原作者无关；Saltline 为原作者的独立作品，此处仅作本地托管
- 本仓库代码以 MIT 许可证发布，见 [LICENSE](LICENSE)
