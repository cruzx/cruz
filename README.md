# 免费听策略监控

这个项目用于监控和对比音乐 App 的“免费听 / 看视频 / 会员转化”策略，当前支持汽水音乐和 QQ 音乐。

## 功能

- 上传我们的参考图、方案图或策略笔记
- 上传竞品当天截图、录屏关键帧或链路笔记
- 通过本地 `adb` 采集 Android 真机上的竞品截图
- 使用视觉模型生成 Markdown 对比报告
- 在网页中预览和刷新当天报告

## 目录结构

```text
strategy_monitor/
  references/              # 我们自己的参考图、参考文案、策略笔记
  qishui_daily/YYYY-MM-DD/ # 汽水音乐当天截图或笔记
  qqmusic_daily/YYYY-MM-DD/# QQ 音乐当天截图或笔记
  reports/                 # 生成的对比报告
  web_app.py               # 本地网页 App
  monitor.py               # 命令行报告生成脚本
```

## 运行方式

```bash
python3 -m venv .runvenv
.runvenv/bin/python -m pip install -e .
.runvenv/bin/python -m uvicorn strategy_monitor.web_app:app --reload --port 8010
```

打开：

```text
http://127.0.0.1:8010
```

## 命令行生成报告

```bash
python3 strategy_monitor/monitor.py --date 2026-04-21 --app qishui
```

报告会写入：

```text
strategy_monitor/reports/
```
