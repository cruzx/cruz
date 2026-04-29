#!/bin/bash
# setup.sh · 一键安装脚本（macOS）
# 用法: bash setup.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "══════════════════════════════════════"
echo "   音乐情报雷达 · 安装脚本"
echo "══════════════════════════════════════"
echo ""

# 检查 Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ 未找到 python3，请先安装 Python 3.10+${NC}"
    echo "  推荐: brew install python@3.11"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}✓ Python $PY_VER${NC}"

# 创建虚拟环境
if [ ! -d ".venv" ]; then
    echo "→ 创建虚拟环境..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# 安装依赖
echo "→ 安装 Python 依赖..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo -e "${GREEN}✓ 依赖安装完成${NC}"

# 安装 Playwright Chromium
echo "→ 安装 Playwright 浏览器（首次约需 2-3 分钟）..."
playwright install chromium
echo -e "${GREEN}✓ Playwright 安装完成${NC}"

# 创建 .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${YELLOW}→ 已创建 .env 文件${NC}"
    echo -e "${YELLOW}  请用文本编辑器打开 .env，填写你的 API Key：${NC}"
    echo ""
    echo "  必填: ANTHROPIC_API_KEY"
    echo "  选填: DRIBBBLE_TOKEN、BEHANCE_KEY、XHS_COOKIE"
    echo ""
else
    echo -e "${GREEN}✓ .env 文件已存在${NC}"
fi

# 创建启动脚本
cat > start.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python main.py
EOF
chmod +x start.sh

echo ""
echo "══════════════════════════════════════"
echo -e "${GREEN}  安装完成！${NC}"
echo "══════════════════════════════════════"
echo ""
echo "  下一步："
echo "  1. 编辑 .env 填写 API Key"
echo "  2. 双击 start.sh 或运行:"
echo "     bash start.sh"
echo ""
echo "  浏览器将自动打开看板 → http://localhost:8765"
echo ""
