#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="${PROJECT_ROOT}/rag-system/backend"
FRONTEND_ROOT="${PROJECT_ROOT}/rag-system/frontend"

ENV_FILES=(
  "${PROJECT_ROOT}/.env"
  "${PROJECT_ROOT}/rag-system/.env"
)

DEFAULT_REDIS_URL="redis://localhost:6379/0"

load_env_files() {
  for file in "${ENV_FILES[@]}"; do
    if [[ -f "${file}" ]]; then
      echo "加载环境变量 ${file}"
      set -a
      # shellcheck disable=SC1090
      source "${file}"
      set +a
    fi
  done
}

require_cmd() {
  local cmd="$1"
  local hint="${2:-}"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "缺少命令: ${cmd}. ${hint}" >&2
    exit 1
  fi
}

ensure_dir() {
  local dir="$1"
  if [[ ! -d "${dir}" ]]; then
    echo "目录不存在: ${dir}" >&2
    exit 1
  fi
}

kill_port() {
  local port="$1"
  if [[ -z "${port}" ]]; then
    return
  fi
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti tcp:"${port}" || true)"
    if [[ -n "${pids}" ]]; then
      echo "释放端口 ${port} (kill ${pids})"
      kill -9 ${pids} 2>/dev/null || true
    fi
  elif command -v fuser >/dev/null 2>&1; then
    echo "释放端口 ${port} (fuser)"
    fuser -k "${port}/tcp" 2>/dev/null || true
  fi
}

cleanup_celery_workers() {
  local app_pattern="$1"
  if [[ -z "${app_pattern}" ]]; then
    return
  fi

  if ! command -v pgrep >/dev/null 2>&1; then
    return
  fi

  local user_id
  user_id="$(id -u)"
  mapfile -t celery_pids < <(pgrep -u "${user_id}" -f "celery -A ${app_pattern}" 2>/dev/null || true)
  if ((${#celery_pids[@]} == 0)); then
    return
  fi

  echo "清理残留 Celery 进程 (${celery_pids[*]})"
  kill "${celery_pids[@]}" 2>/dev/null || true
  sleep 1
  for pid in "${celery_pids[@]}"; do
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill -9 "${pid}" 2>/dev/null || true
    fi
  done
}

start_process() {
  local name="$1"
  local workdir="$2"
  shift 2

  echo "启动 ${name}"
  (
    cd "${workdir}"
    "$@"
  ) &

  local pid=$!
  CHILD_PIDS+=("${pid}")
  CHILD_NAMES+=("${name}")
  echo "  ${name} PID=${pid}"
}

is_flag_disabled() {
  local flag="${1:-}"
  case "${flag,,}" in
    false | 0 | no | off)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_loopback_host() {
  local host="${1:-}"
  case "${host}" in
    "" | localhost | 127.* | 0.0.0.0 | ::1)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

normalize_loopback_host() {
  local host="${1:-127.0.0.1}"
  case "${host}" in
    "" | localhost | 0.0.0.0)
      echo "127.0.0.1"
      ;;
    "[::1]" | ::1)
      echo "::1"
      ;;
    *)
      echo "${host}"
      ;;
  esac
}

parse_redis_host_port() {
  local url="${1:-}"
  [[ "${url}" == redis://* ]] || return 1

  local remainder="${url#redis://}"
  local hostinfo="${remainder%%/*}"
  hostinfo="${hostinfo##*@}"

  local host=""
  local port=""
  if [[ "${hostinfo}" =~ ^\[(.+)\]:(.+)$ ]]; then
    host="${BASH_REMATCH[1]}"
    port="${BASH_REMATCH[2]}"
  elif [[ "${hostinfo}" == *:* ]]; then
    host="${hostinfo%%:*}"
    port="${hostinfo##*:}"
  else
    return 1
  fi

  [[ -n "${host}" && -n "${port}" ]] || return 1
  REDIS_TARGET_HOST="${host}"
  REDIS_TARGET_PORT="${port}"
  return 0
}

precleanup_redis_port() {
  local broker_url="${CELERY_BROKER_URL:-${DEFAULT_REDIS_URL}}"
  if ! parse_redis_host_port "${broker_url}"; then
    return
  fi
  if ! is_loopback_host "${REDIS_TARGET_HOST}"; then
    return
  fi
  local redis_bind
  redis_bind="$(normalize_loopback_host "${REDIS_TARGET_HOST}")"
  echo "启动前检查 Redis 端口 ${REDIS_TARGET_PORT} (${redis_bind})"
  kill_port "${REDIS_TARGET_PORT}"
}

maybe_start_redis() {
  local manage_flag="${MANAGE_REDIS:-true}"
  if is_flag_disabled "${manage_flag}"; then
    echo "MANAGE_REDIS=${MANAGE_REDIS}，跳过自动启动 Redis。"
    return
  fi

  local broker_url="${CELERY_BROKER_URL:-${DEFAULT_REDIS_URL}}"
  if ! parse_redis_host_port "${broker_url}"; then
    echo "无法解析 CELERY_BROKER_URL=${broker_url}，跳过内置 Redis。"
    return
  fi

  if ! is_loopback_host "${REDIS_TARGET_HOST}"; then
    echo "检测到 Redis Broker 指向 ${REDIS_TARGET_HOST}，假定由外部服务提供。"
    return
  fi

  local redis_bind
  redis_bind="$(normalize_loopback_host "${REDIS_TARGET_HOST}")"

  local ping_ok=false
  if command -v redis-cli >/dev/null 2>&1; then
    local ping_cmd=(redis-cli -h "${redis_bind}" -p "${REDIS_TARGET_PORT}" ping)
    if command -v timeout >/dev/null 2>&1; then
      if timeout 3 "${ping_cmd[@]}" >/dev/null 2>&1; then
        ping_ok=true
      fi
    else
      if "${ping_cmd[@]}" >/dev/null 2>&1; then
        ping_ok=true
      fi
    fi

    if [[ "${ping_ok}" == true ]]; then
      echo "Redis (${redis_bind}:${REDIS_TARGET_PORT}) 已在运行，跳过自动启动。"
      return
    else
      echo "Redis (${redis_bind}:${REDIS_TARGET_PORT}) 未响应，准备重启。"
    fi
  fi

  echo "清理可能残留的 Redis 进程 (${redis_bind}:${REDIS_TARGET_PORT})"
  kill_port "${REDIS_TARGET_PORT}"

  require_cmd redis-server "请安装 redis-server 或设置 CELERY_BROKER_URL 指向可用的 Redis 服务"
  echo "未检测到本地 Redis，自动启动 redis-server (${redis_bind}:${REDIS_TARGET_PORT})"
  start_process "Redis (${redis_bind}:${REDIS_TARGET_PORT})" "${PROJECT_ROOT}"     redis-server --save "" --appendonly no --bind "${redis_bind}" --port "${REDIS_TARGET_PORT}"
}

clear_gpu_memory() {
  local behaviour="${CLEAR_GPU_ON_EXIT:-true}"
  if [[ "${behaviour}" != "true" ]]; then
    return
  fi

  if ! command -v nvidia-smi >/dev/null 2>&1; then
    return
  fi

  mapfile -t gpu_pids < <(
    nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | awk 'NF' | sort -u
  )

  if ((${#gpu_pids[@]} == 0)); then
    echo "GPU 上无残留进程需要清理。"
    return
  fi

  local current_user
  current_user="$(id -un)"
  local cleared=0

  for pid in "${gpu_pids[@]}"; do
    [[ -z "${pid}" ]] && continue
    [[ ! "${pid}" =~ ^[0-9]+$ ]] && continue
    if [[ ! -e "/proc/${pid}" ]]; then
      continue
    fi

    local owner
    owner="$(ps -o user= -p "${pid}" 2>/dev/null | awk '{print $1}')"
    if [[ "${owner}" != "${current_user}" ]]; then
      continue
    fi

    local command
    command="$(ps -o comm= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"

    case "${command}" in
      python* | python3* )
        echo "清理 GPU 进程 PID=${pid} CMD=$(ps -o cmd= -p "${pid}" 2>/dev/null)"
        kill -9 "${pid}" 2>/dev/null || true
        cleared=1
        ;;
      *)
        ;;
    esac
  done

  if ((cleared == 0)); then
    echo "没有符合条件的 GPU 进程需要清理。"
  fi
}

cleanup() {
  local exit_code=$?
  for idx in "${!CHILD_PIDS[@]}"; do
    local pid="${CHILD_PIDS[$idx]}"
    local name="${CHILD_NAMES[$idx]}"
    if kill -0 "${pid}" >/dev/null 2>&1; then
      echo "停止 ${name} (PID=${pid})"
      kill "${pid}" 2>/dev/null || true
    fi
  done
  if ((${#CHILD_PIDS[@]} > 0)); then
    wait "${CHILD_PIDS[@]}" 2>/dev/null || true
  fi
  clear_gpu_memory
  return "${exit_code}"
}

declare -a CHILD_PIDS=()
declare -a CHILD_NAMES=()

trap cleanup EXIT INT TERM

# 清除可能导致问题的代理环境变量
unset ALL_PROXY
unset all_proxy

load_env_files

ensure_dir "${BACKEND_ROOT}"
ensure_dir "${FRONTEND_ROOT}"

require_cmd uvicorn "请先运行: pip install -r rag-system/backend/requirements.txt"
require_cmd npm "请先安装 Node.js 和 npm"
require_cmd celery "请先在后端环境中安装 Celery (pip install celery[redis])"

BACK_HOST="${BACK_HOST:-0.0.0.0}"
BACK_PORT="${BACK_PORT:-${GPU_PORT:-8000}}"
CPU_HOST="${CPU_HOST:-0.0.0.0}"
CPU_PORT="${CPU_PORT:-8001}"
FRONT_PORT="${FRONT_PORT:-5173}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-1}"
CELERY_LOGLEVEL="${CELERY_LOGLEVEL:-info}"
MANAGE_REDIS="${MANAGE_REDIS:-true}"

kill_port "${BACK_PORT}"
kill_port "${CPU_PORT}"
kill_port "${FRONT_PORT}"
precleanup_redis_port
cleanup_celery_workers "${CELERY_APP}"

UVICORN_GPU_RELOAD="${UVICORN_GPU_RELOAD:-true}"
UVICORN_CPU_RELOAD="${UVICORN_CPU_RELOAD:-true}"

GPU_APP_MODULE="${GPU_APP_MODULE:-backend.main:app}"
CPU_APP_MODULE="${CPU_APP_MODULE:-backend.cpu_tasks_app:app}"
CELERY_APP="${CELERY_APP:-backend.task.celery_app}"

GPU_CMD=(
  uvicorn "${GPU_APP_MODULE}"
  --host "${BACK_HOST}"
  --port "${BACK_PORT}"
)

if [[ "${UVICORN_GPU_RELOAD}" == "true" ]]; then
  GPU_CMD+=(--reload)
fi

start_process "GPU FastAPI (${BACK_PORT})" "${PROJECT_ROOT}/rag-system"   env PYTHONPATH="${PROJECT_ROOT}/rag-system"   "${GPU_CMD[@]}"

CPU_CMD=(
  uvicorn "${CPU_APP_MODULE}"
  --host "${CPU_HOST}"
  --port "${CPU_PORT}"
)

if [[ "${UVICORN_CPU_RELOAD}" == "true" ]]; then
  CPU_CMD+=(--reload)
fi

start_process "CPU FastAPI (${CPU_PORT})" "${PROJECT_ROOT}/rag-system"   env PYTHONPATH="${PROJECT_ROOT}/rag-system"   "${CPU_CMD[@]}"

maybe_start_redis

if [[ -f "${BACKEND_ROOT}/task.py" ]]; then
  start_process "Celery Worker" "${PROJECT_ROOT}/rag-system"     env PYTHONPATH="${PROJECT_ROOT}/rag-system"     celery -A "${CELERY_APP}" worker       --loglevel="${CELERY_LOGLEVEL}"       --concurrency="${CELERY_CONCURRENCY}"
else
  echo "警告: 未找到 ${BACKEND_ROOT}/task.py，跳过 Celery Worker。" >&2
fi

start_process "Vite 前端 (${FRONT_PORT})" "${FRONTEND_ROOT}"   npm run dev -- --port "${FRONT_PORT}"

echo "所有服务已启动。按 Ctrl+C 结束。"

status=0
if ! wait -n; then
  status=$?
fi

exit "${status}"
