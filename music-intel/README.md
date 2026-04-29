# 音乐情报雷达 🎵

自动采集 Dribbble、Behance、小红书的音乐 APP 设计内容，  
Claude AI 分析设计风格，本地浏览器图片墙看板展示。

---

## 快速开始

### 第一步：安装

```bash
bash setup.sh
```

### 第二步：配置 API Key

编辑 `.env`（已从 `.env.example` 自动创建）：

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxx   # 必填，用于 AI 分析图片

DRIBBBLE_TOKEN=                     # 选填，从 dribbble.com 申请
BEHANCE_KEY=                        # 选填，从 behance.net/dev 申请

# 图片存储模式（local 或 supabase）
STORAGE_MODE=local
```

### 第三步：启动

```bash
bash start.sh
```

启动时自动询问是否进行小红书扫码登录，  
浏览器自动打开 `http://localhost:8765`，  
点击右上角「立即采集」开始获取内容。

---

## 小红书登录

启动时程序会弹出询问，选择「是」后：

1. 自动弹出有界面的 Chrome 浏览器，打开小红书
2. 用手机 App 扫描页面上的二维码
3. 登录成功后，Cookie 自动保存到本地
4. 之后采集时静默运行，无需再次扫码

Cookie 大约每 2-4 周失效，失效后运行 `python main.py login` 重新扫码。

---

## 存储模式切换

在 `.env` 中修改 `STORAGE_MODE`：

| 值 | 说明 | 适用场景 |
|---|---|---|
| `local` | 图片存在 `data/images/` 本地文件夹 | 个人使用，简单 |
| `supabase` | 上传到 Supabase Storage 云端 | 多设备共享、团队协作 |

切换到 Supabase 还需填写：
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJxxx...
SUPABASE_BUCKET=design-images    # 需在 Supabase 控制台提前创建，设为 public
```

---

## 所有命令

```bash
bash start.sh              # 启动服务（推荐）
python main.py             # 同上
python main.py login       # 只做小红书扫码登录
python main.py collect     # 只跑一次采集，不启动服务器
```

---

## 目录结构

```
music-intel/
├── main.py                  # 入口
├── server.py                # Web 服务 + 看板 HTML
├── collectors/
│   ├── dribbble.py          # Dribbble API
│   ├── behance.py           # Behance API
│   ├── xhs.py               # 小红书采集
│   └── xhs_login.py         # 小红书扫码登录
├── processors/
│   ├── collector.py         # 采集调度器
│   └── claude_analyzer.py   # Claude AI 图片分析
├── storage/
│   ├── db.py                # SQLite 数据库
│   └── image_store.py       # 可切换存储适配器
├── data/                    # 自动创建
│   ├── intel.db
│   ├── xhs_cookies.json     # 小红书 Cookie（自动生成）
│   └── images/
│       ├── dribbble/
│       ├── behance/
│       └── xhs/
├── .env.example
├── requirements.txt
└── setup.sh
```
