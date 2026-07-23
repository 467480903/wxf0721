#!/bin/bash
# ─────────────────────────────────────────────────────────
#  G2 Minth 服务批量启动脚本
#
#  功能：
#    1. source /home/agi/app/env.sh 加载环境变量
#    2. 后台启动以下 5 个 Python 服务：
#       - g2_minth_app_service.py
#       - g2_minth_camera_publisher.py
#       - g2_minth_data_service.py
#       - g2_minth_status_publisher.py
#       - runtime/run.py
#    3. 使用 nohup + & 实现：session 断开后服务继续运行
#
#  日志：
#    每个服务的 stdout/stderr 重定向到 logs/<服务名>.log
#
#  用法：
#    chmod +x run.sh
#    ./run.sh           # 启动
#    ./run.sh stop       # 停止
#    ./run.sh status     # 查看状态
# ─────────────────────────────────────────────────────────

# 切换到脚本所在目录（mqtt/）—— 使用唯一变量名 RUN_DIR 避免被 env.sh 覆盖
RUN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 项目根目录（mqtt 的上一级，用于定位 runtime/run.py 等）
PROJECT_DIR="$(cd "$RUN_DIR/.." && pwd)"
cd "$RUN_DIR"

# 加载环境变量（env.sh 内部可能 cd 到其他目录并覆盖变量，source 后需切回）
ENV_FILE="/home/agi/app/env.sh"
if [ -f "$ENV_FILE" ]; then
    echo "[run.sh] 正在加载环境变量: source $ENV_FILE"
    source "$ENV_FILE"
    # env.sh 可能改变了工作目录，切回脚本所在目录
    cd "$RUN_DIR"
else
    echo "[run.sh] ⚠ 警告: 环境文件不存在: $ENV_FILE"
fi

# 服务列表：格式 "服务名|相对项目根目录的路径"
#   - mqtt 目录下的服务：路径相对于 PROJECT_DIR 写为 mqtt/xxx.py
#   - 其他目录的服务：写对应相对路径，如 runtime/run.py
#   - 命令形式：格式 "服务名|CMD:命令|相对项目根目录的工作目录"
#     用于启动 python -m 等模块命令，工作目录决定命令执行位置
SERVICES=(
    "g2_minth_app_service|services/g2_minth_app_service.py"
    "camera|services/camera.py"
    "g2_minth_data_service|services/g2_minth_data_service.py"
    "g2_minth_status_publisher|services/g2_minth_status_publisher.py"
    "runtime_run|runtime/run.py"
    "web_server|CMD:python3 -m http.server 8002|web"
)

# 日志目录
LOG_DIR="$RUN_DIR/logs"
mkdir -p "$LOG_DIR"

# ── 启动 ──────────────────────────────────────────────────
start_service() {
    # 入参格式：
    #   name|relative_path          启动 python3 文件
    #   name|CMD:command|cwd_rel    以 cwd_rel 为工作目录执行命令
    local entry="$1"
    local name="${entry%%|*}"
    local rest="${entry#*|}"
    local log_file="$LOG_DIR/${name}.log"
    local pid_file="$LOG_DIR/${name}.pid"
    local pid

    # 检查是否已在运行
    if [ -f "$pid_file" ]; then
        local old_pid=$(cat "$pid_file")
        if kill -0 "$old_pid" 2>/dev/null; then
            echo "[run.sh] ⚠ $name 已在运行 (PID=$old_pid)，跳过"
            return 0
        else
            rm -f "$pid_file"
        fi
    fi

    if [[ "$rest" == CMD:* ]]; then
        # 命令形式：CMD:command|relative_cwd
        local cmd="${rest#CMD:}"
        local cwd_rel="."
        if [[ "$cmd" == *"|"* ]]; then
            cwd_rel="${cmd##*|}"
            cmd="${cmd%|*}"
        fi
        local work_dir="$PROJECT_DIR/$cwd_rel"
        if [ ! -d "$work_dir" ]; then
            echo "[run.sh] ❌ 工作目录不存在: $work_dir"
            return 1
        fi
        # 后台启动（nohup 让进程在 session 断开后继续运行）
        (cd "$work_dir" && nohup bash -c "$cmd" > "$log_file" 2>&1 & echo $! > "$pid_file")
    else
        # 文件形式：relative_path
        local py_file="$PROJECT_DIR/$rest"
        local work_dir="$(dirname "$py_file")"
        if [ ! -f "$py_file" ]; then
            echo "[run.sh] ❌ 文件不存在: $py_file"
            return 1
        fi
        # 后台启动（nohup 让进程在 session 断开后继续运行）
        # 在 py_file 所在目录启动，便于程序读取同目录下的相对资源
        nohup python3 "$py_file" > "$log_file" 2>&1 &
        echo "$!" > "$pid_file"
    fi

    pid=$(cat "$pid_file")
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        echo "[run.sh] ✅ $name 已启动 (PID=$pid, 日志=$log_file)"
    else
        echo "[run.sh] ❌ $name 启动失败，请查看日志: $log_file"
        rm -f "$pid_file"
        return 1
    fi
}

# ── 停止 ──────────────────────────────────────────────────
stop_service() {
    local name="$1"
    local pid_file="$LOG_DIR/${name}.pid"

    if [ ! -f "$pid_file" ]; then
        echo "[run.sh] ⚠ $name 未在运行 (无 PID 文件)"
        return 0
    fi

    local pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            echo "[run.sh] 强制终止 $name (PID=$pid)"
            kill -9 "$pid"
        fi
        echo "[run.sh] ✅ $name 已停止 (PID=$pid)"
    else
        echo "[run.sh] ⚠ $name 进程不存在 (PID=$pid 可能已退出)"
    fi
    rm -f "$pid_file"
}

# ── 状态 ──────────────────────────────────────────────────
status_service() {
    local name="$1"
    local pid_file="$LOG_DIR/${name}.pid"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo "[run.sh] ● $name 运行中 (PID=$pid)"
        else
            echo "[run.sh] ○ $name 已停止 (PID=$pid 已退出)"
        fi
    else
        echo "[run.sh] ○ $name 未启动"
    fi
}

# ── 命令分发 ──────────────────────────────────────────────
case "${1:-start}" in
    start)
        echo "════════════════════════════════════════════════════"
        echo "  G2 Minth 服务启动  $(date '+%Y-%m-%d %H:%M:%S')"
        echo "════════════════════════════════════════════════════"
        for svc in "${SERVICES[@]}"; do
            start_service "$svc"
        done
        echo "────────────────────────────────────────────────────"
        echo "  日志目录: $LOG_DIR"
        echo "  查看状态: ./run.sh status"
        echo "  停止服务: ./run.sh stop"
        echo "════════════════════════════════════════════════════"
        ;;

    stop)
        echo "正在停止所有服务..."
        for svc in "${SERVICES[@]}"; do
            stop_service "$svc"
        done
        echo "停止完成。"
        ;;

    status)
        echo "════════════════════════════════════════════════════"
        echo "  G2 Minth 服务状态  $(date '+%Y-%m-%d %H:%M:%S')"
        echo "════════════════════════════════════════════════════"
        for svc in "${SERVICES[@]}"; do
            status_service "$svc"
        done
        ;;

    restart)
        "$0" stop
        sleep 2
        "$0" start
        ;;

    *)
        echo "用法: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac
