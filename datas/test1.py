#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test1.py — 直接使用 agibot_gdk 的独立测试脚本

不依赖 minth.py，也不依赖 services 里的程序。

功能：
  1. 底盘相对运动：往后运动（BACK_DIST 米，只下发不等待）
  2. TTS 语音播报："你好你好"
  3. 右手第 7 关节（idx67_arm_r_joint7）加 15 度旋转

环境：
  GDK 需要 LD_LIBRARY_PATH 等环境变量，本脚本会自动检测：
  若 agibot_gdk 不可用，自动 source /home/agi/app/env.sh 后重新执行自身。
  也可手动先 source 再运行，效果相同：
    source /home/agi/app/env.sh
    python3 test1.py
"""

import math
import os
import sys
import time

# ── 常量 ─────────────────────────────────────────────────
ENV_SH  = "/home/agi/app/env.sh"
GDK_LIB = "/home/agi/app/gdk/lib"

BACK_DIST = 2   # 后退距离（米，x 负方向）

# 右臂关节（与 services/joints.py 保持一致）
RIGHT_ARM_JOINT_KEYS = [
    "idx61_arm_r_joint1", "idx62_arm_r_joint2", "idx63_arm_r_joint3",
    "idx64_arm_r_joint4", "idx65_arm_r_joint5", "idx66_arm_r_joint6",
    "idx67_arm_r_joint7",
]
LEFT_ARM_JOINT_KEYS = [
    "idx21_arm_l_joint1", "idx22_arm_l_joint2", "idx23_arm_l_joint3",
    "idx24_arm_l_joint4", "idx25_arm_l_joint5", "idx26_arm_l_joint6",
    "idx27_arm_l_joint7",
]
ARM_SPEED = 0.2

TARGET_JOINT  = "idx67_arm_r_joint7"   # 右手第 7 关节
JOINT_DELTA_DEG = 15                   # 旋转增量（度）


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


def rotate_right_joint7(robot, delta_deg):
    """右手第 7 关节加 delta_deg 度旋转（角度转弧度后下发）

    先读当前关节角，仅修改目标关节，其余保持不动（含左臂），
    避免关节被意外拉到零位。

    Returns
    -------
    bool : True=命令发送成功，False=发送异常
    """
    # 读取当前关节角
    current = {}
    for state in robot.get_joint_states()['states']:
        current[state['name']] = state['motor_position']

    cur = current.get(TARGET_JOINT, 0.0)
    target = cur + math.radians(delta_deg)

    # 双臂 14 关节：保持当前值，仅改右手 joint7
    left  = [current.get(k, 0.0) for k in LEFT_ARM_JOINT_KEYS]
    right = [current.get(k, 0.0) for k in RIGHT_ARM_JOINT_KEYS]
    right[RIGHT_ARM_JOINT_KEYS.index(TARGET_JOINT)] = target

    print(f"🦾 {TARGET_JOINT}: {cur:.4f} → {target:.4f} rad (+{delta_deg}°)")
    try:
        robot.move_arm_joint(left + right, [ARM_SPEED] * 14, 2)
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False
    print("   请求已发送，不等待完成")
    return True


def main():
    _ensure_gdk_env()
    import agibot_gdk

    print("=" * 60)
    print("  test1: GDK 独立测试 — 后退 0.4m + TTS")
    print("=" * 60)

    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("[错误] gdk_init 失败")
        sys.exit(1)

    try:
        pnc        = agibot_gdk.Pnc()
        robot      = agibot_gdk.Robot()
        interaction = agibot_gdk.Interaction()
        time.sleep(1.0)

        # 1. 底盘相对运动：后退（只下发，不等待）
        ok = go_back(pnc, BACK_DIST)

        # 2. 立刻 TTS 播报
        print(f"\n🔊 TTS: 你好你好")
        try:
            interaction.play_tts("你好你好")
            print("   播放命令已发送")
        except Exception as e:
            print(f"   播放失败: {e}")

        # 3. 右手第 7 关节 +15°
        ok_joint = rotate_right_joint7(robot, JOINT_DELTA_DEG)

        print(f"\n完成: 后退命令 {'✓ 已下发' if ok else '✗ 发送失败'}，"
              f"TTS 已下发，关节 {'✓ 已下发' if ok_joint else '✗ 发送失败'}")

    finally:
        if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
            print("[警告] gdk_release 失败")


if __name__ == "__main__":
    main()
