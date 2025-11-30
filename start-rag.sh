#!/usr/bin/env bash
set -euo pipefail

# 激活 RAG 环境
source /home/reggie/miniconda3/etc/profile.d/conda.sh
conda activate RAG

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${PROJECT_ROOT}/rag-system:${PYTHONPATH:-}"

echo "当前 Python 环境路径: $(which python)"
echo "Python 版本: $(python --version)"
echo "PYTHONPATH=${PYTHONPATH}"

# 检查关键依赖
python -c "
import diskcache
print('✅ diskcache 可用')
try:
    from langchain.agents import initialize_agent, AgentType
    print('✅ LangChain agents 可用')
except ImportError as e:
    print('❌ LangChain agents 不可用:', e)
"

# 清除可能导致问题的代理环境变量
unset ALL_PROXY
unset all_proxy

# 运行原始启动脚本
exec ./start.sh
