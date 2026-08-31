"""拍照 → AprilTag 解算偏移 → 机器人回位 (两轮: 先旋转, 再平移)。

策略 (光轴平行地面, 正对墙面):
  - 第 1 轮: 拍照 → 解算 → 旋转 (不管角度多少都转一次)
  - 第 2 轮: 拍照 → 解算 → 平移一次到位 (左右用像素法, 深度用 PnP)
  - 结束

调用方式:
    from positioning import positioning
    positioning("references/reference_A.json")

命令行直接运行:
    python positioning.py <基准JSON路径>
    不传则默认 runtime/reference_pose.json
"""

import os
import sys
import json
import time
import numpy as np
from aruco_pose import compute_offset, CAMERA_MATRIX

from minth import Minth
from capture import capture_head_color

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REF_JSON = os.path.join(BASE_DIR, "reference_pose.json")

# 大位移确认: 单次平移合位移超过此阈值时, 暂停等用户确认
CONFIRM_LARGE_MOVE = True
LARGE_MOVE_THRESHOLD_MM = 500.0


def confirm_large_move(move_x_m, move_y_m):
    """平移合位移超阈值时提示并等待用户确认; 返回是否放行。"""
    if not CONFIRM_LARGE_MOVE:
        return True
    dist_mm = float(np.hypot(move_x_m, move_y_m) * 1000.0)
    if dist_mm <= LARGE_MOVE_THRESHOLD_MM:
        return True
    print(f"\n  [确认] 单次平移 {dist_mm:.0f}mm > {LARGE_MOVE_THRESHOLD_MM:.0f}mm "
          f"(x={move_x_m:+.3f}m, y={move_y_m:+.3f}m)")
    ans = input("  输入 y 执行 / 其它跳过: ").strip().lower()
    return ans == "y"


def load_reference(ref_path):
    """加载基准 JSON, 返回 (ref_path, mm_per_px)。

    mm_per_px 按基准距离动态算: fx / 基准深度(mm)。
    基准深度取 tvec[2] (相机系 Z, 光轴方向)。
    """
    if not os.path.exists(ref_path):
        raise FileNotFoundError(f"基准位姿文件不存在: {ref_path}")
    with open(ref_path, "r", encoding="utf-8") as f:
        ref = json.load(f)
    tvec = np.array(ref["tvec"], dtype=np.float64)
    fx = CAMERA_MATRIX[0, 0]
    depth_ref = float(tvec[2])   # 基准光轴深度 (mm)
    # mm_per_px: 1 像素对应的物理尺寸 = depth / fx (不是 fx / depth)
    mm_per_px = depth_ref / fx if depth_ref > 0 else 3.6
    name = ref.get("name", "?")
    print(f"=== 加载基准 [{name}]: {ref_path} ===")
    print(f"  ids={ref.get('target_ids')}, 间距={ref.get('marker_spacing_mm')}mm")
    print(f"  基准深度={depth_ref:.0f}mm, fx={fx:.1f} → mm/px={mm_per_px:.3f}")
    return ref_path, mm_per_px


def take_photo_and_solve(G2, iteration, phase, ref_path):
    """拍照 + 解算偏移, 返回解算结果。"""
    print(f"\n=== 第 {iteration} 轮纠偏 [{phase}]: 拍照 ===")
    img_path = capture_head_color(G2)
    if img_path is None:
        print("[错误] 拍照失败")
        return None
    print(f"[拍照] {img_path}")

    print("\n--- 解算偏移 ---")
    result = compute_offset(img_path, ref_path)

    dt_mm = np.array(result["dt_mm"], dtype=np.float64)
    depth_mm = float(dt_mm[0])
    reproj_err = float(result["reprojection_error_px"])

    lateral_px = float(result.get("d_mid_x_px", 0))    # 左右像素偏移
    vertical_px = float(result.get("d_mid_y_px", 0))   # 上下像素偏移 (仅监测)
    yaw_deg = float(result.get("d_tilt_deg", 0))       # 旋转残差 (连线倾斜角差)

    print(f"  [深度 PnP]   dt_x={depth_mm:+.1f}mm (|t|={np.linalg.norm(dt_mm):.1f}mm, reproj={reproj_err:.2f}px)")
    print(f"  [像素法]     左右={lateral_px:+.1f}px, 上下={vertical_px:+.1f}px, 旋转={yaw_deg:+.2f}°")

    return {
        "depth_mm": depth_mm,
        "lateral_px": lateral_px,
        "vertical_px": vertical_px,
        "yaw_deg": yaw_deg,
        "reproj_err": reproj_err,
        "dt_mm": dt_mm,
    }


def solve_and_rotate(G2, iteration, ref_path):
    """第 1 轮: 拍照 → 解算 → 旋转 (不管角度多少都转一次)。"""
    r = take_photo_and_solve(G2, iteration, "旋转", ref_path)
    if r is None:
        return None

    yaw_deg = r["yaw_deg"]
    # 不管角度多少都转一次 (方向与 d_tilt 反号, 一次到位)
    yaw_cmd = -np.radians(yaw_deg)
    print(f"  [策略] 旋转: yaw={np.degrees(yaw_cmd):+.2f}° (残差 {yaw_deg:+.2f}°)")
    if not G2.REL({"x": 0, "y": 0, "yaw_rad": yaw_cmd}):
        print("[错误] 旋转失败")
        return None

    time.sleep(0.5)
    return r


def solve_and_move(G2, iteration, ref_path, mm_per_px):
    """第 2 轮: 拍照 → 解算 → 平移一次到位。"""
    r = take_photo_and_solve(G2, iteration, "平移", ref_path)
    if r is None:
        return None

    depth_mm = r["depth_mm"]
    lateral_px = r["lateral_px"]
    vertical_px = r["vertical_px"]

    # 平移: 一次到位, 不管大小都执行
    # 深度 (body X): PnP dt_x, >0 靠前 → 后退
    move_x_m = -depth_mm / 1000.0
    # 左右 (body Y): 像素法, >0 相机左移 → 底盘向右 (move_y 负)
    lateral_mm = lateral_px * mm_per_px
    move_y_m = -lateral_mm / 1000.0

    print(f"  [策略] 平移一次到位: x={move_x_m:+.4f}m, y={move_y_m:+.4f}m (mm/px={mm_per_px:.3f})")
    if abs(vertical_px) > 3:
        print(f"  [注意] 上下偏差 {vertical_px:+.1f}px, 底盘无法纠正, 需调整手臂高度")
    if not confirm_large_move(move_x_m, move_y_m):
        print("  [跳过] 用户未确认, 跳过本次平移")
        return r
    if not G2.REL({"x": move_x_m, "y": move_y_m, "yaw_rad": 0}):
        print("[错误] 平移失败")
        return None

    time.sleep(0.5)
    return r


# ============ 主流程: 两轮 (先旋转, 再平移) ============

def positioning(ref_path, G2=None):
    """闭环纠偏主流程 (两轮: 先旋转, 再平移)。

    参数:
        ref_path: str  基准位姿 JSON 路径
        G2: Minth.G2 实例, None 则内部创建并管理生命周期
    返回:
        (r1, r2): 两轮解算结果, 失败则对应位置为 None
    """
    ref_json, mm_per_px = load_reference(ref_path)

    print("=== 开始闭环纠偏 (先旋转, 再平移, 共 2 轮) ===")
    own_g2 = G2 is None
    if own_g2:
        G2 = Minth.G2()
        # G2.GRIPPER({"left": -1, "right": -1})

    try:
        # 第 1 轮: 旋转
        #G2.ARMS("car3")
        r1 = solve_and_rotate(G2, 1, ref_json)

        # 第 2 轮: 平移 (执行两次平移到位)
        r2 = solve_and_move(G2, 2, ref_json, mm_per_px)
        r2 = solve_and_move(G2, 3, ref_json, mm_per_px)
        #G2.ARMS("car2")

        if r1 and r2:
            print(f"\n=== 结束 ===")
            print(f"  R1: 旋转 {r1['yaw_deg']:+.2f}° (前) → R2: 旋转 {r2['yaw_deg']:+.2f}° (后)")
            print(f"  R2: 深度 {r2['depth_mm']:+.1f}mm, 左右 {r2['lateral_px']:+.1f}px, 上下 {r2['vertical_px']:+.1f}px")

        # print("\n✓ 回位完成")

        # if own_g2:
        #     G2.GRIPPER({"left": 0, "right": 0})
    finally:
        if own_g2:
            G2.close()

    return r1, r2


if __name__ == "__main__":
    ref = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REF_JSON
    positioning(ref)

