#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
back_1m.py — 直接使用 agibot_gdk 的独立底盘运动测试脚本

不依赖 minth.py，也不依赖 services 里的程序。

功能：
  底盘相对运动：往后运动 1 米（只下发命令，不等待完成）

环境：
  GDK 需要 LD_LIBRARY_PATH 等环境变量，本脚本会自动检测：
  若 agibot_gdk 不可用，自动 source /home/agi/app/env.sh 后重新执行自身。
  也可手动先 source 再运行，效果相同：
    source /home/agi/app/env.sh
    python3 back_1m.py
"""

import os
import sys
import time

# ── 常量 ─────────────────────────────────────────────────
ENV_SH  = "/home/agi/app/env.sh"
GDK_LIB = "/home/agi/app/gdk/lib"

BACK_DIST = 2.0    # 后退 1 米（x 负方向）


def _ensure_gdk_env():
    """确保 agibot_gdk 可用；若环境缺失则 source env.sh 后重 exec 自身"""
    if GDK_LIB not in sys.path and os.path.isdir(GDK_LIB):
        sys.path.insert(0, GDK_LIB)
    try:
        import agibot_gdk  # noqa: F401
        return
    except ImportError:
        pass

    if not os.path.isfile(ENV_SH):
        print(f"[错误] agibot_gdk 不可用，且 {ENV_SH} 不存在")
        sys.exit(1)

    print("[提示] GDK 环境未加载，正在 source env.sh 后重新执行...")
    sys.stdout.flush()
    cmd = (
        f'source "{ENV_SH}" >/dev/null 2>&1 && '
        f'exec "{sys.executable}" "{os.path.abspath(__file__)}"'
    )
    os.execvp("bash", ["bash", "-c", cmd])


def go_back(pnc, dx):
    """底盘相对运动（x 负=后退），只下发命令，不等待完成

    Returns
    -------
    bool : True=命令发送成功，False=发送异常
    """

    # 构建相对移动请求（yaw=0 → 四元数 (0,0,0,1)）
    import agibot_gdk
    req = agibot_gdk.NaviReq()
    req.target.position.x    = dx
    req.target.position.y    = 0.0
    req.target.position.z    = 0.0
    req.target.orientation.x = 0.0
    req.target.orientation.y = 0.0
    req.target.orientation.z = 0.0
    req.target.orientation.w = 1.0

    print(f"🚀 相对运动: dx={dx:+.2f}m (后退)")
    try:
        pnc.relative_move(req)
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False
    print("   请求已发送，不等待完成")
    return True


def main():
    _ensure_gdk_env()
    import agibot_gdk

    print("=" * 60)
    print("  back_1m: GDK 独立测试 — 后退 1 米")
    print("=" * 60)

    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("[错误] gdk_init 失败")
        sys.exit(1)

    try:
        pnc = agibot_gdk.Pnc()
        time.sleep(1.0)

        # 底盘相对运动：后退 1 米（只下发，不等待）
        ok = go_back(pnc, BACK_DIST)

        print(f"\n完成: 后退命令 {'✓ 已下发' if ok else '✗ 发送失败'}")

    finally:
        if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
            print("[警告] gdk_release 失败")


if __name__ == "__main__":
    main()
