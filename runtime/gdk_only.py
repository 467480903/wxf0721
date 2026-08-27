#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gdk_only.py — 纯 GDK 直控脚本

不使用 MQTT / minth.py，也不依赖 services/ 下任何模块，
只调用 agibot_gdk 原生 API 完成动作。

流程：
  1. 左臂在当前姿态基础上向上移动 0.1 米
  2. 左臂向下移动 0.1 米
  3. 打开左夹爪
  4. 等待 0.5 秒
  5. 关闭左夹爪

坐标系（末端）：X+ 向前，Y+ 向左，Z+ 向上

运行方式（需先加载 GDK 环境）：
  source /home/agi/app/env.sh
  python3 -u gdk_only.py
"""

import time
import math

import agibot_gdk

# ── 运动参数 ──────────────────────────────────
UP_M   = 0.1    # 向上移动（米）
DOWN_M = 0.1    # 向下移动（米）

# ── 末端位姿流参数 ────────────────────────────
LEFT_LINK = "arm_l_end_link"   # 左臂末端 link 名（在 get_motion_control_status 中查找）
STEP_CM   = 0.1                # 插值单步最大位移（厘米）
LIFETIME  = 0.02               # 单条位姿指令生命周期（秒）
RATE_HZ   = 50.0               # 位姿流发送频率（Hz）

# ── 夹爪参数 ──────────────────────────────────
GRIPPER_OPEN    = -0.78   # 左爪张开（与 runtime/main.py 取值一致）
GRIPPER_CLOSE   = -0.05   # 左爪关闭
EE_SETTLE_S     = 2.0     # 位姿流结束后等待会话释放（否则夹爪指令被静默丢弃）
GRIPPER_TOL     = 0.05    # 夹爪位置到达容差
GRIPPER_TIMEOUT = 6.0     # 夹爪验证总超时（秒）


# ═══════════════════════════════════════════════════════════
#  臂运动（纯 GDK：读当前位姿 → 直线插值 → 50Hz 位姿流）
# ═══════════════════════════════════════════════════════════

def get_left_pose(robot):
    """读取左臂末端当前位姿

    通过 get_motion_control_status() 在 frame_names 中查找
    arm_l_end_link，返回其位置与姿态。

    Returns:
        dict: {"position": [x, y, z], "orientation": [x, y, z, w]}
    """
    status = robot.get_motion_control_status()
    for i, name in enumerate(status.frame_names):
        if name == LEFT_LINK:
            p = status.frame_poses[i].position
            q = status.frame_poses[i].orientation
            return {
                "position":    [p.x, p.y, p.z],
                "orientation": [q.x, q.y, q.z, q.w],
            }
    raise RuntimeError(f"motion status 中未找到 link: {LEFT_LINK}")


def move_left_arm(robot, dz):
    """左臂沿 Z 轴相对移动 dz 米（正=向上，负=向下），姿态保持不变

    原理：
      1) get_motion_control_status 读取末端当前位姿
      2) 目标位置 = 当前位置 + dz
      3) 按单步 ≤0.1cm 直线插值，以 50Hz 频率调用
         end_effector_pose_control 下发位姿流（kLeftArm 组）

    Returns:
        bool: True=轨迹发送成功
    """
    # 1. 读取当前位姿，计算目标
    pose = get_left_pose(robot)
    start = pose["position"]
    target = [start[0], start[1], start[2] + dz]
    quat = pose["orientation"]   # 姿态不变，直接沿用

    # 2. 计算插值步数（0.1m → 100 步）
    dist = math.sqrt(sum((t - s) ** 2 for s, t in zip(start, target)))
    n_steps = max(int(math.ceil(dist * 100.0 / STEP_CM)), 2)
    print(f"  起点 {' '.join(f'{v:.3f}' for v in start)} → "
          f"终点 {' '.join(f'{v:.3f}' for v in target)}  "
          f"({n_steps} 步 @ {RATE_HZ:.0f}Hz, 约 {n_steps / RATE_HZ:.1f}s)")

    # 3. 50Hz 位姿流下发
    dt = 1.0 / RATE_HZ
    for i in range(n_steps):
        t = float(i) / (n_steps - 1)

        ep = agibot_gdk.EndEffectorPose()
        ep.life_time = LIFETIME
        ep.group     = agibot_gdk.EndEffectorControlGroup.kLeftArm

        lp = ep.left_end_effector_pose
        lp.position.x = start[0] + t * (target[0] - start[0])
        lp.position.y = start[1] + t * (target[1] - start[1])
        lp.position.z = start[2] + t * (target[2] - start[2])
        lp.orientation.x = quat[0]
        lp.orientation.y = quat[1]
        lp.orientation.z = quat[2]
        lp.orientation.w = quat[3]

        ret = robot.end_effector_pose_control(ep)
        if ret != 0:
            print(f"  [警告] 第 {i} 步指令返回非零: {ret}")
            return False
        time.sleep(dt)

    return True


# ═══════════════════════════════════════════════════════════
#  夹爪控制（纯 GDK：move_ee_pos 下发 + get_end_state 验证）
# ═══════════════════════════════════════════════════════════

def read_gripper_pos(robot):
    """读取左夹爪当前实际位置，失败返回 None"""
    try:
        end_state = robot.get_end_state()
        states = (end_state["left_end_state"] or {}).get("end_states") or []
        if not states:
            return None
        return float(states[0].get("position", 0.0))
    except Exception:
        return None


def control_gripper(robot, position):
    """控制左夹爪：下发 → 轮询实际位置 → 未生效自动重试

    背景：end_effector_pose_control 位姿流结束后的一段时间内，
    move_ee_pos 夹爪指令会被运动控制器静默丢弃（API 返回成功但爪不动），
    因此下发后必须读 get_end_state 验证实际位置。

    Returns:
        bool: True=夹爪到位
    """
    # 构造 left_tool 组的夹爪位置指令
    joint_states = agibot_gdk.JointStates()
    joint_states.group = "left_tool"
    joint_states.target_type = "omnipicker"
    joint_state = agibot_gdk.JointState()
    joint_state.position = position
    joint_states.states = [joint_state]
    joint_states.nums = 1

    deadline = time.time() + GRIPPER_TIMEOUT
    attempt = 0
    actual = None
    while time.time() < deadline:
        attempt += 1
        robot.move_ee_pos(joint_states)

        # 观察窗口内轮询夹爪实际位置
        window_end = time.time() + 0.5
        while time.time() < window_end:
            actual = read_gripper_pos(robot)
            if actual is not None and abs(actual - position) <= GRIPPER_TOL:
                print(f"  到位 (第 {attempt} 次下发生效, 实际 {actual:.3f})")
                return True
            time.sleep(0.05)

        print(f"  尚未到位 (实际 {actual})，重试第 {attempt + 1} 次...")

    print(f"  超时失败：未到达目标位置 {position}")
    return False


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def main():
    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("[GDK] 初始化失败")
        return
    print("[GDK] 初始化成功")

    robot = agibot_gdk.Robot()
    time.sleep(2)  # 等待 DDS 就绪

    try:
        # 1. 左臂向上 0.1 m
        print(f"\n[1/5] 左臂向上 {UP_M} 米")
        move_left_arm(robot, +UP_M)

        # 2. 左臂向下 0.1 m（在移动后的姿态基础上）
        print(f"\n[2/5] 左臂向下 {DOWN_M} 米")
        move_left_arm(robot, -DOWN_M)

        # 位姿流结束后等待会话释放，否则紧随其后的夹爪指令会被丢弃
        print(f"\n[等待] 位姿流会话释放 {EE_SETTLE_S}s")
        time.sleep(EE_SETTLE_S)

        # 3. 打开左爪
        print("\n[3/5] 打开左夹爪")
        control_gripper(robot, GRIPPER_OPEN)

        # 4. 等 0.5 秒
        print("\n[4/5] 等待 0.5 秒")
        time.sleep(0.5)

        # 5. 关闭左爪
        print("\n[5/5] 关闭左夹爪")
        control_gripper(robot, GRIPPER_CLOSE)

    except Exception as e:
        print(f"[运行错误] {e}")
    finally:
        if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
            print("[GDK] 释放失败")
        else:
            print("\n[GDK] 释放成功，脚本结束")


if __name__ == "__main__":
    main()
