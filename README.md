# NDX 打分系统 — 零依赖可移植版

> 给纳斯达克 100 指数做"PE/M200/VIX"三维打分（A-E 等级）的本地离线看板。
> 完全自带 Python，整包可直接拷到任何 Windows 电脑运行。

---

## 它是什么

一个原雪球用户「招财喵土豆」提出的「纳斯达克100打分系统」本地复刻：

| 维度 | 算法 |
| --- | --- |
| PE 估值 | 30 × (1 − 5年滚动百分位/100) |
| 200日均线偏离 | 40 × (1 − max(0, 偏离%)/15)^1.5（≥12% 归零） |
| VIX 恐慌 | max(0, (VIX − 14) × 1.7) |
| 总分 | A ≥ 80 / B ≥ 60 / C ≥ 40 / D ≥ 20 / E < 20 |

回溯 10 年（2016-01 至今，2664 个交易日）。

## 文件结构

```
AI NDX\
├── setup.bat                ← 一键安装（首次在别的电脑用时运行）
├── start.bat                ← 立即启动（不依赖自启）
├── uninstall.bat            ← 卸载
├── fetch_data.py            ← 数据获取 + 打分 + 生成 HTML
├── template.html            ← 看板模板
├── index.html               ← 离线静态看板（每次运行 fetch_data.py 重新生成）
├── ndx_history.json         ← 10 年历史分数（喂给雷达图/进度条）
├── ndx_snapshot.json        ← 最近一天的分数快照
├── echarts.min.js           ← ECharts 5.4.3，本地避免 CDN 翻车
├── serve.py                 ← 本地 HTTP 服务器（端口 8765，按钮触发的刷新走这里）
├── watchdog.py              ← 守护进程：serve.py 挂了自动重启
├── register_autostart.py    ← 注册开机自启
├── service.py               ← 可选：注册为 Windows Service（要管理员）
├── python\
│   ├── python.exe / pythonw.exe  ← 嵌入版 Python 3.13.12
│   ├── python313.dll / *.pyd
│   └── Lib\site-packages\        ← yfinance / pandas / numpy 已装好
└── python-embed.zip         ← Python 嵌入包种子（首次解压后可以删掉）
```

## 三种启动方式

### 1）开机自启（推荐，看完就忘）
跑一次：
```
setup.bat
```
之后再开电脑，浏览器输 `http://localhost:8765/index.html` 就有数据（按
钮触发即时刷，或后台每天 9:00 自动刷）。

### 2）手动启动（不想开机挂着）
```
start.bat
```

### 3）完全离线另拷一台电脑
1. 把整个 `AI NDX\` 文件夹拷过去（比如压缩包 / U 盘 / 网盘）
2. 在新电脑上双击 `setup.bat`
3. 完成。

要不要预先装 Python、要不要管理员权限、要不要任何环境配置 —— 全部不要。

## 看板页面

四个 API 端点（serve.py 提供）：

| URL | 用途 |
| --- | --- |
| `GET /` / `GET /index.html` | 看板（数据已内嵌，无需服务器也能双击开） |
| `GET /echarts.min.js` | ECharts 库 |
| `GET /api/snapshot` | 当前快照 JSON |
| `GET /api/status` | 服务状态 + 下次刷新时间 |
| `GET /refresh` | 立即重新拉数据 / 重新生成 index.html |

页面上的"刷新数据"按钮会触发 `GET /refresh`。

## 卸载

```
uninstall.bat
```
可选清理运行时产物（index.html / 数据 / 日志）。项目目录要彻底删就手
动 `rm` 即可。

## 数据更新策略

- **首次安装**：setup.bat 立即拉一次
- **手动**：点页面上的「刷新数据」按钮
- **自动（serve.py 在跑）**：
  - 开页面时若数据 > 24h，立即后台刷一次
  - 每天 9:00 后台刷一次
  - 任何时候挂了，watchdog.py 3 秒内拉起

## 已知约束

- 嵌入 Python 不带 `pywin32`，所以注册自启走"启动文件夹 + VBS"兜底
  而不是 Task Scheduler（系统服务需要管理员，装在普通用户电脑上不
  友好）。
- yfinance 偶尔抽风（429/502），刷新会自动重试。
- 数据源 Yahoo Finance `^NDX` / `^VIX`。
