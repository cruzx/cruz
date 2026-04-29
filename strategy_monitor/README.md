# 免费听设计策略日更监控

这个目录用于每天监控汽水音乐的“免费听 / 看视频 / 会员转化”弹窗策略，并和我们自己的参考图做对比，输出 Markdown 结论。

## 目录

```text
strategy_monitor/
  references/              # 我们自己的参考图、参考文案、策略笔记
  qishui_daily/YYYY-MM-DD/ # 汽水音乐当天截图、录屏关键帧或链路笔记
  reports/                 # 每天生成的对比报告
  monitor.py               # 生成报告的脚本
```

## 使用方式

### 音乐 APP 截图收集工具

启动本地截图库：

```bash
uvicorn strategy_monitor.screenshot_app:app --reload --port 8020
```

打开：

```text
http://127.0.0.1:8020
```

这个工具可以直接完成：

- 上传 Apple Music、Spotify、汽水音乐、网易云音乐、QQ 音乐、酷狗音乐截图。
- 按平台、页面、设备、账号状态、版本号归档。
- 自动计算截图指纹，重复截图不会重复入库。
- 自动生成初始模块标签和功能标签。
- 浏览截图图墙，进入详情页查看元数据。
- 连接 Android 设备后，通过 `adb` 执行一次截图采集。
- 使用 iOS Simulator 时，通过 `simctl` 截取当前模拟器画面。
- 在网页里编辑 `screenshot_targets.json` 平台配置。
- 使用“流程抓图”按步骤自动进入目标链路，并在指定节点截图。
- 使用“读取当前页面元素”查看 Android 当前页面的 text/content-desc/resource-id，方便编写稳定的 `tap_text` / `wait_text` 步骤。

数据会保存在：

```text
strategy_monitor/screenshot_library/
```

如果要用 Android 自动采集，请先连接手机或模拟器，并确认：

```bash
adb devices
```

如果页面提示找不到 `adb`，可以先运行：

```bash
python3 strategy_monitor/install_adb.py
```

流程抓图示例：

```json
[
  {"action": "sleep", "seconds": 2},
  {"action": "screenshot", "screen_name": "首页推荐"},
  {"action": "tap_text", "text": "搜索"},
  {"action": "wait_text", "text": "搜索", "timeout": 8},
  {"action": "text", "value": "周杰伦"},
  {"action": "keyevent", "code": "KEYCODE_ENTER"},
  {"action": "sleep", "seconds": 2},
  {"action": "screenshot", "screen_name": "搜索结果"}
]
```

支持的动作：

```text
sleep / tap / tap_text / tap_exact / wait_text / wait_exact / text / keyevent / swipe / back / screenshot
```

### 用本地 App 上传和生成报告

启动本地网页 App：

```bash
uvicorn strategy_monitor.web_app:app --reload --port 8010
```

打开：

```text
http://127.0.0.1:8010
```

页面里可以直接完成：

- 上传“我们的参考图/笔记”
- 上传“汽水音乐当天样本”
- 拖拽上传、缩略图预览、删除素材
- 安装/检测本地 `adb`
- 通过 `adb` 自动采集汽水音乐免费模式截图
- 一键生成/刷新对比报告
- 预览当天报告

如果你使用这个网页 App，就不需要手动把图片放到某个文件夹里；上传后 App 会自动归档。

### 命令行方式

1. 把我们自己的参考图或笔记放入：

```bash
strategy_monitor/references/
```

2. 把汽水音乐当天截图或笔记放入：

```bash
strategy_monitor/qishui_daily/2026-04-20/
```

3. 配置视觉模型 API Key：

```bash
export OPENAI_API_KEY="your-key"
export OPENAI_MODEL="gpt-4.1-mini"
```

4. 生成当天报告：

```bash
python3 strategy_monitor/monitor.py --date 2026-04-20
```

报告会生成在：

```text
strategy_monitor/reports/2026-04-20.md
```

## 自动采集汽水音乐截图

如果你有 Android 手机，可以用 `adb` 自动截图。采集器会先检测当前手机界面是否出现免费模式相关关键词，只有命中后才保存截图，避免采到无关页面。

如果页面提示“未找到 adb”，先在网页 App 点击“安装/检测本地 adb”，或运行：

```bash
python3 strategy_monitor/install_adb.py
```

```bash
python3 strategy_monitor/collect_qishui_adb.py --date 2026-04-20
```

如果你已经在手机上打开了汽水音乐的免费模式弹窗，可以跳过启动 App，只检测并采集当前画面：

```bash
python3 strategy_monitor/collect_qishui_adb.py --date 2026-04-20 --no-launch
```

默认会尝试启动汽水音乐包名：

```text
com.luna.music
```

如果你的包名不同，先查包名：

```bash
adb shell pm list packages | grep -i luna
adb shell pm list packages | grep -i music
```

再指定包名：

```bash
python3 strategy_monitor/collect_qishui_adb.py --date 2026-04-20 --package 真实包名
```

常用参数：

```bash
# 不启动 App，只截当前屏幕
python3 strategy_monitor/collect_qishui_adb.py --date 2026-04-20 --no-launch

# 连续截 5 张，每 3 秒一张
python3 strategy_monitor/collect_qishui_adb.py --date 2026-04-20 --count 5 --interval 3
```

截图会保存到：

```text
strategy_monitor/qishui_daily/2026-04-20/
```

然后再运行报告：

```bash
python3 strategy_monitor/monitor.py --date 2026-04-20
```

## 推荐记录内容

如果当天没有截图，也可以放一个 `.md` 或 `.txt` 笔记，至少记录：

- 入口场景：比如播放会员歌曲、听歌时长耗尽、搜索结果点击会员歌。
- 标题、副标题、主按钮、次按钮。
- 免费权益：比如 20 分钟、30 分钟、当前歌曲。
- 成本表达：看视频、看广告、等待、跳过倒计时。
- 会员锚点：价格、免广告、会员曲库、连续包月。
- 链路闭环：视频结束后是否自动回到播放、是否有到账 Toast。

## 输出结论

脚本会输出：

- 今日结论
- 汽水音乐观察
- 和我们参考图的差异
- 可借鉴点
- 不建议照搬
- 下一版 A/B 建议
- 证据与缺口
