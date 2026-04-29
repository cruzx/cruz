# music-intel 吸收笔记

## 它是什么

这是一个「音乐 App 设计图情报雷达」：从 Dribbble、Behance、小红书抓音乐 App/UI 相关图片，存到本地或 Supabase，用 Claude Vision 做设计标签分析，再用本地 FastAPI 看板展示成图片墙。

## 主链路

1. `main.py` 负责启动、登录小红书、单次采集和服务模式。
2. `processors/collector.py` 并发调用三个采集器：`dribbble`、`behance`、`xhs`。
3. 每条结果必须带 `image_bytes`，然后进入 `storage/image_store.py`。
4. `image_store` 先按图片字节算 MD5 短 hash，压缩为 600x600 内的 WebP，再保存到 `data/images/<source>/`。
5. `storage/db.py` 用 SQLite 的 `design_images.img_hash UNIQUE` 去重，并保存原始元数据和 AI 分析字段。
6. `processors/claude_analyzer.py` 把图片发给 Claude Vision，返回风格标签、配色、布局、参考价值和建议。
7. `server.py` 暴露 `/api/images`、`/api/stats`、`/api/collect`，首页是内嵌 HTML/CSS/JS 图片墙。

## 能直接复用的设计

- 采集器统一返回 dict，调度器不关心平台细节，扩展新平台比较轻。
- 图片去重放在存储层，用 hash 当跨平台唯一指纹。
- AI 分析结果结构化，方便前端筛选和之后生成报告。
- `STORAGE_MODE=local|supabase` 的适配器思路可以移植到现有截图库。
- 小红书登录和采集拆成两个模块，Cookie 持久化在 `data/xhs_cookies.json`。

## 当前风险

- Dribbble 和 Behance 依赖官方 API key；接口可用性和配额需要实测。
- 小红书采集依赖页面 DOM，选择器会随页面改版失效。
- `/api/collect` 已有基础运行状态，但还没有细粒度进度，比如当前平台、当前图片、剩余数量。
- Claude 分析是同步调用，图片多时会慢，也容易触发 API 限速。
- 看板 HTML 全塞在 `server.py`，后续迭代 UI 会比较不舒服。

## 已做的小修

- 小红书中文关键词搜索 URL 改为 `urllib.parse.quote` 编码。
- Claude Vision 的 `media_type` 改为按图片字节识别，不再固定声明为 PNG。
- `/api/collect` 增加采集状态和并发锁，前端能正确识别完成、失败和新增 0 张。
- 清理了解压产生的 macOS 元数据目录和错误花括号空目录。

## 推荐下一步

1. 先本地跑通 `bash setup.sh`，填 `.env`，用 `python main.py collect` 做一次无服务采集验证。
2. 把内嵌前端拆成 `templates/` 和 `static/`，让看板更好改。
3. 如果要并入现有 `strategy_monitor`，建议先只并入数据库字段和图片墙，不急着合并采集器。
