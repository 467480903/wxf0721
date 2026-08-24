#!/usr/bin/env python3
"""PNC 底盘原地左转 90°

坐标系约定: X-前, Y-左, Z-上；左转 = yaw 增大 π/2（逆时针，俯视）。
四元数 (qx, qy, qz, qw) = (0, 0, sin(θ/2), cos(θ/2))，θ=+π/2 → (0,0,0.7071,0.7071)。

环境自举：
- PYTHONPATH       -> /home/agi/app/gdk/lib          （agibot_gdk 包）
- LD_LIBRARY_PATH  -> /home/agi/app/lib 等            （libgdk_core/adapter/dds 等 native 库）

注意：实际驱动底盘需要在 IDE 集成终端运行（TRAE 沙箱会阻止共享内存）。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# GDK native 库目录（libgdk_adapter.so.3 / libgdk_core.so.3 / libgdk_dds.so.3 等）
_LIB_DIRS = [
    os.path.normpath(os.path.join(_HERE, "..", "..", "..", "lib")),                          # /home/agi/app/lib
    os.path.normpath(os.path.join(_HERE, "..", "..", "build_dep", "cpp", "aarch64", "lib")),  # gdk/build_dep/.../lib
    os.path.normpath(os.path.join(_HERE, "..", "..", "build_dep", "cpp", "aarch64", "lib", "dds")),
]
_cur_ld = os.environ.get("LD_LIBRARY_PATH", "")
if any(d not in _cur_ld.split(":") for d in _LIB_DIRS):
    os.environ["LD_LIBRARY_PATH"] = ":".join(_LIB_DIRS + ([_cur_ld] if _cur_ld else []))
    # ld.so 仅在进程启动时读取 LD_LIBRARY_PATH，需重新执行自身使新值生效
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:])

# Python 模块路径：/home/agi/app/gdk/lib（含 agibot_gdk 包）
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "lib")))

import math
import time
import agibot_gdk


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def wait_task_done(pnc, timeout=30.0):
    """轮询任务状态，state 9=成功，8=失败"""
    log(f"开始轮询任务状态，超时 {timeout}s")
    start = time.time()
    poll_count = 0
    while time.time() - start < timeout:
        poll_count += 1
        try:
            task_state = pnc.get_task_state()
            state = task_state.state

            if poll_count == 1 or poll_count % 5 == 0:
                elapsed = time.time() - start
                log(f"第{poll_count}次轮询 ({elapsed:.1f}s): state={state}, id={task_state.id}")

            if state == 9:
                log(f"已到达目标 (轮询{poll_count}次, 耗时{time.time()-start:.1f}s)")
                return True
            if state == 8:
                log(f"任务失败 (state=8)")
                return False
        except Exception as e:
            log(f"轮询异常: {e}")

        time.sleep(0.5)

    log(f"任务超时")
    return False

