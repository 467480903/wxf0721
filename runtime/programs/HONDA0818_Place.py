#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HONDA0818_Place.py — A/B 件放置流程

流程概览：
  A 件（右手）：
    导航 7 → WBC 取件姿 → WBC 持件姿 → 导航 8 → 导航 0
    → YOLO(place_product.pt@192.168.0.8) → 腰/底盘纠正
    → 右臂 A_PLACE_LOOK → YOLO(holes.pt) → 右臂 A_PLACE_WAIT
    → 右手前 100mm 下 50mm → 右爪半开 -0.4
    → 右手前 5mm 下 5mm → 右爪全开 -0.7
    → 右手后退 300mm → 右臂 A_DONE

  B 件（左手）：
    底盘左移 1.2m → 前进 2m → 右移 1.2m → 转 180°
    → 导航 9 → 导航 3
    → YOLO(place_product.pt@192.168.0.8) → 腰/底盘纠正
    → 左臂 B_PLACE_LOOK → 左臂 B_PLACE_WAIT
    → 左手前 100mm 下 50mm → 左爪半开 -0.4
    → 左手前 5mm 下 5mm → 左爪全开 -0.7
    → 左手后退 300mm → 左臂 B_DONE

  收尾：
    导航 7（回等待位）

说明：
  - 动作变量名（HOLD_2_PIECES_APART / A_PLACE_LOOK 等）对应的
    datas/joints/<type>/<name>.json 文件可能尚未创建，先用字符串
    字面量调用，等数据文件就绪后即可执行。
  - minth.G2 的所有方法都是同步阻塞调用。
"""

import math
import time

from minth import Minth

# ── YOLO 服务配置 ────────────────────────────────────────
YOLO_IP = "192.168.0.8"
YOLO_PLACE_MODEL = "place_product.pt"
YOLO_HOLES_MODEL = "holes.pt"

# ── 动作变量名（对应 datas/joints/<type>/<name>.json）────
#   这些 .json 文件后续会创建，先用字符串字面量占位
HOLD_2_PIECES_APART = "HOLD_2_PIECES_APART"
HOLD_2_PIECES_FRONT = "HOLD_2_PIECES_FRONT"
A_PLACE_LOOK        = "A_PLACE_LOOK"
A_PLACE_WAIT        = "A_PLACE_WAIT"
A_DONE              = "A_DONE"
B_PLACE_LOOK        = "B_PLACE_LOOK"
B_PLACE_WAIT        = "B_PLACE_WAIT"
B_DONE              = "B_DONE"

# ── 夹爪位置 ──────────────────────────────────────────────
#   贠值=张开，正值=闭合
GRIPPER_HALF_OPEN = -0.4   # 半开（轻持件）
GRIPPER_FULL_OPEN = -0.7   # 全开（释放）

# ── 末端相对移动距离（毫米）──────────────────────────────
#   x: 前+/后-    y: 左+/右-    z: 上+/下-
PLACE_FORWARD_MM     = 100   # 放置时前移
PLACE_DOWN_MM        = -50   # 放置时下移
NUDGE_FORWARD_MM     = 5     # 微调前移
NUDGE_DOWN_MM        = -5    # 微调下移
RETREAT_BACKWARD_MM  = -300  # 释放后后退

# ── 底盘相对运动（米 / 弧度）─────────────────────────────
#   x: 前进+    y: 左+    yaw_rad: 左转+
CHASSIS_LEFT_M   = 1.2
CHASSIS_FWD_M    = 2.0
CHASSIS_RIGHT_M  = -1.2
CHASSIS_TURN_RAD = math.pi   # 180°

# ── 超时配置 ─────────────────────────────────────────────
#   导航/动作耗时较长，统一用 120s
G2 = Minth.G2(timeout=120)


def _step(idx, total, desc):
    print(f"\n{'═' * 60}")
    print(f"  [{idx}/{total}] {desc}")
    print(f"{'═' * 60}")


# ═══════════════════════════════════════════════════════════
#  A 件放置（右手）
# ═══════════════════════════════════════════════════════════
def place_a():
    total = 16
    _step(1, total, "A 件：导航到点位 7")
    G2.GO(7)
    time.sleep(1)

    _step(2, total, "A 件：WBC 持件分离姿 HOLD_2_PIECES_APART")
    G2.WBC(HOLD_2_PIECES_APART)

    _step(3, total, "A 件：WBC 持件前置姿 HOLD_2_PIECES_FRONT")
    G2.WBC(HOLD_2_PIECES_FRONT)

    _step(4, total, "A 件：导航到点位 8")
    G2.GO(8)
    time.sleep(1)

    _step(5, total, "A 件：导航到点位 0")
    G2.GO(0)
    time.sleep(1)

    _step(6, total, f"A 件：YOLO 检测 {YOLO_PLACE_MODEL} @ {YOLO_IP}")
    G2.YOLO(YOLO_PLACE_MODEL, YOLO_IP)

    _step(7, total, "A 件：底盘 + 腰部纠正")
    G2.CHASSIS_CORRECT()
    G2.WAIST_CORRECT()

    _step(8, total, "A 件：右臂 A_PLACE_LOOK")
    G2.RIGHT(A_PLACE_LOOK)

    _step(9, total, f"A 件：YOLO 检测 {YOLO_HOLES_MODEL} @ {YOLO_IP}")
    G2.YOLO(YOLO_HOLES_MODEL, YOLO_IP)

    _step(10, total, "A 件：右臂 A_PLACE_WAIT")
    G2.RIGHT(A_PLACE_WAIT)

    _step(11, total, f"A 件：右手前移 {PLACE_FORWARD_MM}mm，下移 {-PLACE_DOWN_MM}mm")
    G2.OFFSET({"rx": PLACE_FORWARD_MM, "rz": PLACE_DOWN_MM})

    _step(12, total, f"A 件：右爪半开 {GRIPPER_HALF_OPEN}")
    G2.GRIPPER({"right": GRIPPER_HALF_OPEN})
    time.sleep(0.5)

    _step(13, total, f"A 件：右手微调 前移 {NUDGE_FORWARD_MM}mm，下移 {-NUDGE_DOWN_MM}mm")
    G2.OFFSET({"rx": NUDGE_FORWARD_MM, "rz": NUDGE_DOWN_MM})

    _step(14, total, f"A 件：右爪全开 {GRIPPER_FULL_OPEN}")
    G2.GRIPPER({"right": GRIPPER_FULL_OPEN})
    time.sleep(0.5)

    _step(15, total, f"A 件：右手后退 {-RETREAT_BACKWARD_MM}mm")
    G2.OFFSET({"rx": RETREAT_BACKWARD_MM})

    _step(16, total, "A 件：右臂 A_DONE")
    G2.RIGHT(A_DONE)


# ═══════════════════════════════════════════════════════════
#  B 件放置（左手）
# ═══════════════════════════════════════════════════════════
def place_b():
    total = 16
    _step(1, total, f"B 件：底盘左移 {CHASSIS_LEFT_M}m")
    G2.REL({"x": 0, "y": CHASSIS_LEFT_M, "yaw_rad": 0})

    _step(2, total, f"B 件：底盘前进 {CHASSIS_FWD_M}m")
    G2.REL({"x": CHASSIS_FWD_M, "y": 0, "yaw_rad": 0})

    _step(3, total, f"B 件：底盘右移 {-CHASSIS_RIGHT_M}m")
    G2.REL({"x": 0, "y": CHASSIS_RIGHT_M, "yaw_rad": 0})

    _step(4, total, f"B 件：底盘转弯 180°")
    G2.REL({"x": 0, "y": 0, "yaw_rad": CHASSIS_TURN_RAD})

    _step(5, total, "B 件：导航到点位 9")
    G2.GO(9)
    time.sleep(1)

    _step(6, total, "B 件：导航到点位 3")
    G2.GO(3)
    time.sleep(1)

    _step(7, total, f"B 件：YOLO 检测 {YOLO_PLACE_MODEL} @ {YOLO_IP}")
    G2.YOLO(YOLO_PLACE_MODEL, YOLO_IP)

    _step(8, total, "B 件：底盘 + 腰部纠正")
    G2.CHASSIS_CORRECT()
    G2.WAIST_CORRECT()

    _step(9, total, "B 件：左臂 B_PLACE_LOOK")
    G2.LEFT(B_PLACE_LOOK)

    _step(10, total, "B 件：左臂 B_PLACE_WAIT")
    G2.LEFT(B_PLACE_WAIT)

    _step(11, total, f"B 件：左手前移 {PLACE_FORWARD_MM}mm，下移 {-PLACE_DOWN_MM}mm")
    G2.OFFSET({"lx": PLACE_FORWARD_MM, "lz": PLACE_DOWN_MM})

    _step(12, total, f"B 件：左爪半开 {GRIPPER_HALF_OPEN}")
    G2.GRIPPER({"left": GRIPPER_HALF_OPEN})
    time.sleep(0.5)

    _step(13, total, f"B 件：左手微调 前移 {NUDGE_FORWARD_MM}mm，下移 {-NUDGE_DOWN_MM}mm")
    G2.OFFSET({"lx": NUDGE_FORWARD_MM, "lz": NUDGE_DOWN_MM})

    _step(14, total, f"B 件：左爪全开 {GRIPPER_FULL_OPEN}")
    G2.GRIPPER({"left": GRIPPER_FULL_OPEN})
    time.sleep(0.5)

    _step(15, total, f"B 件：左手后退 {-RETREAT_BACKWARD_MM}mm")
    G2.OFFSET({"lx": RETREAT_BACKWARD_MM})

    _step(16, total, "B 件：左臂 B_DONE")
    G2.LEFT(B_DONE)


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════
def main():
    print("\n" + "█" * 60)
    print("  HONDA0818_Place 流程开始")
    print("█" * 60)

    try:
        print("\n▶▶▶ 阶段 1/3：A 件放置（右手）")
        place_a()

        print("\n▶▶▶ 阶段 2/3：B 件放置（左手）")
        place_b()

        print("\n▶▶▶ 阶段 3/3：回到等待位置")
        _step(1, 1, "收尾：导航到点位 7")
        G2.GO(7)

        print("\n" + "█" * 60)
        print("  HONDA0818_Place 全部完成")
        print("█" * 60)
    except KeyboardInterrupt:
        print("\n[!] 用户中断流程")
    except Exception as e:
        print(f"\n[!] 流程异常: {e}")
        raise
    finally:
        G2.close()


if __name__ == "__main__":
    main()
