# syntax=docker/dockerfile:1

############################
# 前端构建：保持不变
############################
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build


############################
# 后端：CUDA 12.8 + cuDNN
############################
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04 AS backend

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
    
# 安装 Python 3.10 + 基础依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip \
    build-essential \
    git \
    tesseract-ocr \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*
    
# 统一 python / pip 命令
RUN ln -s /usr/bin/python3.10 /usr/local/bin/python && \
    ln -s /usr/bin/pip3 /usr/local/bin/pip

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set global.timeout 600
    
# 拷贝你本地打包好的 cu128 wheel（保持原始文件名，pip 才能识别）
COPY backend/pytorch_triton-3.5.0+git27664085-cp310-cp310-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl /tmp/
COPY backend/torch-2.10.0.dev20251031+cu128-cp310-cp310-manylinux_2_28_x86_64.whl /tmp/
COPY backend/torchaudio-2.10.0.dev20251101+cu128-cp310-cp310-manylinux_2_28_x86_64.whl /tmp/
COPY backend/torchvision-0.25.0.dev20251101+cu128-cp310-cp310-manylinux_2_28_x86_64.whl /tmp/

# 拷贝依赖列表（已去掉 torch 那几行）
COPY backend/requirements.txt /tmp/requirements.txt

# 升级 pip
RUN pip install --upgrade pip

# 先装 PyTorch 相關 wheel（使用 --no-deps 避免官方 triton 版本約束）
RUN pip install --no-cache-dir --no-deps /tmp/torch-2.10.0.dev20251031+cu128-cp310-cp310-manylinux_2_28_x86_64.whl && \
    pip install --no-cache-dir --no-deps /tmp/torchvision-0.25.0.dev20251101+cu128-cp310-cp310-manylinux_2_28_x86_64.whl && \
    pip install --no-cache-dir --no-deps /tmp/torchaudio-2.10.0.dev20251101+cu128-cp310-cp310-manylinux_2_28_x86_64.whl && \
    pip install --no-cache-dir --no-deps /tmp/pytorch_triton-3.5.0+git27664085-cp310-cp310-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl

# 再装其它 Python 依赖（requirements.txt 已列出完整依赖树，使用 --no-deps 避免 pip 重新解析）
RUN pip install --no-cache-dir --no-deps -r /tmp/requirements.txt

# 做一次依赖冲突与缺失检查（忽略自编译 pytorch-triton 版本告警）
RUN set -eu; \
    pip_check_output="$(pip check 2>&1 || true)"; \
    if [ -n "$pip_check_output" ]; then \
        printf '%s\n' "$pip_check_output"; \
        unexpected="$(printf '%s\n' "$pip_check_output" | grep -v 'has requirement pytorch-triton==3.5.0+git7416ffcb' || true)"; \
        if printf '%s\n' "$unexpected" | grep -q 'has requirement'; then \
            echo 'pip check 出現額外依賴錯誤，請修復後再建置。'; \
            exit 1; \
        fi; \
        echo '忽略已知的 pytorch-triton 版本不匹配（使用自編譯 wheel）。'; \
    fi

# 拷贝后端代码
COPY backend /app/backend

# 拷贝前端构建产物
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
