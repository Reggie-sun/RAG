#!/bin/bash
set -euo pipefail

echo "🔍 检查 RAG 系统服务状态..."
echo "=================================================="

# 检查端口占用
check_port() {
    local port=$1
    local service_name=$2

    if lsof -i :$port >/dev/null 2>&1; then
        echo "✅ $service_name (端口 $port) - 运行中"
        lsof -i :$port | tail -n +2 | while read line; do
            echo "   $line"
        done
    else
        echo "❌ $service_name (端口 $port) - 未运行"
    fi
    echo
}

# 检查各个服务
check_port 8000 "GPU FastAPI 服务器"
check_port 8001 "CPU FastAPI 服务器"
check_port 5173 "Vite 前端开发服务器"

# 检查 Redis (如果有的话)
if command -v redis-cli >/dev/null 2>&1; then
    if redis-cli ping >/dev/null 2>&1; then
        echo "✅ Redis 服务 - 运行中"
    else
        echo "❌ Redis 服务 - 未运行"
    fi
else
    echo "⚠️  Redis CLI 未安装"
fi

echo
echo "🌐 服务访问地址:"
echo "   前端: http://localhost:5173"
echo "   后端 API: http://localhost:8000/docs"
echo "   后端 CPU API: http://localhost:8001/docs"

echo
echo "💡 如需停止所有服务，请按 Ctrl+C 或运行: pkill -f 'uvicorn\|celery\|vite'"