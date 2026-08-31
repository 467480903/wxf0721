import os
import sys
import json
import time
import numpy as np

_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PARENT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from AprilTag_pose import compute_offset
from minth import Minth
from capture import capture_head_color

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REF_JSON = os.path.join(BASE_DIR, "references-tag", "reference_latest.json")

YAW_TOL_DEG = 2.5
TRANS_TOL_MM = 10.0
FAIL_REPROJ_ERR_PX = 1.5

GAIN_X = 1.1
GAIN_Y = 1.0

CONFIRM_LARGE_MOVE = True
LARGE_MOVE_THRESHOLD_MM = 500.0
LARGE_YAW_THRESHOLD_DEG = 45.0


def confirm_large_move(move_x_m, move_y_m, yaw_deg):
    if not CONFIRM_LARGE_MOVE:
        return True
    dist_mm = float(np.hypot(move_x_m, move_y_m) * 1000.0)
    if dist_mm <= LARGE_MOVE_THRESHOLD_MM and abs(yaw_deg) <= LARGE_YAW_THRESHOLD_DEG:
        return True
    print(f"\n  [确认] 位移 {dist_mm:.0f}mm 或 旋转 {yaw_deg:.1f}° 超阈值")
    ans = input("  输入 y 执行 / 其它跳过: ").strip().lower()
    return ans == "y"


def load_reference(ref_path):
    if not os.path.exists(ref_path):
        raise FileNotFoundError(f"基准文件不存在: {ref_path}")
    with open(ref_path, "r", encoding="utf-8") as f:
        ref = json.load(f)
    name = ref.get("name", "?")
    print(f"=== 加载基准 [{name}]: {ref_path} ===")
    print(f"  ids={ref.get('target_ids')}, 间距={ref.get('marker_spacing_mm'):.1f}mm, "
          f"码边长={ref.get('marker_size_mm')}mm")
    return ref_path


def take_photo_and_solve(G2, step, phase, ref_path):
    print(f"\n=== 步骤 {step} [{phase}]: 拍照 ===")
    img_path = capture_head_color(G2)
    if img_path is None:
        print("[错误] 拍照失败")
        return None
    print(f"[拍照] {img_path}")

    print("--- 解算偏移 ---")
    result = compute_offset(img_path, ref_path)

    dt = np.array(result["dt_mm"], dtype=np.float64)
    dyaw = float(result["dyaw_deg"])
    reproj = float(result["reprojection_error_px"])

    print(f"  dx={dt[0]:+.1f}mm, dy={dt[1]:+.1f}mm, dz={dt[2]:+.1f}mm")
    print(f"  dyaw={dyaw:+.3f}°, reproj={reproj:.3f}px")

    if reproj > FAIL_REPROJ_ERR_PX:
        print(f"  [拦截] 重投影 {reproj:.3f}px > {FAIL_REPROJ_ERR_PX}px, 不执行")
        return None

    return {
        "dt": dt,
        "dyaw_deg": dyaw,
        "reproj": reproj,
    }


def step_move(G2, ref_path, step):
    r = take_photo_and_solve(G2, step, "纠偏", ref_path)
    if r is None:
        return None, False

    dt = r["dt"]
    dyaw = r["dyaw_deg"]
    dist = float(np.hypot(dt[0], dt[1]))
    yaw_ok = abs(dyaw) <= YAW_TOL_DEG
    trans_ok = dist <= TRANS_TOL_MM

    if yaw_ok and trans_ok:
        print(f"  ✓ 已收敛: |dyaw|={abs(dyaw):.2f}° ≤ {YAW_TOL_DEG}°, |位移|={dist:.1f}mm ≤ {TRANS_TOL_MM}mm")
        return r, True

    yaw_cmd = -np.radians(dyaw)
    move_x = -dt[0] / 1000.0 * GAIN_X
    move_y = -dt[1] / 1000.0 * GAIN_Y

    print(f"  [纠偏] yaw={np.degrees(yaw_cmd):+.2f}°, x={move_x:+.4f}m, y={move_y:+.4f}m")

    if not confirm_large_move(move_x, move_y, dyaw):
        print("  [跳过] 用户未确认")
        return r, False
    if not G2.REL({"x": move_x, "y": move_y, "yaw_rad": yaw_cmd}):
        print("[错误] 纠偏失败")
        return None, False
    time.sleep(0.5)
    return r, False


MAX_ROUNDS = 2

def positioning(ref_path, G2=None, max_rounds=MAX_ROUNDS):
    ref_path = load_reference(ref_path)

    print(f"=== 开始纠偏 (最多 {max_rounds} 次拍照) ===")
    own_g2 = G2 is None
    if own_g2:
        G2 = Minth.G2()

    results = []
    try:
        for i in range(1, max_rounds + 1):
            print(f"\n━━━ 第 {i}/{max_rounds} 次拍照 ━━━")
            r, converged = step_move(G2, ref_path, i)
            results.append(r)
            if r is None:
                break
            if converged:
                print(f"\n=== ✓ 收敛, 结束 ===")
                break
        else:
            print(f"\n=== 结束 (已达 {max_rounds} 次拍照上限) ===")
    finally:
        if own_g2:
            G2.close()

    return results


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="AprilTag 纠偏 (旋转+平移同步)")
    p.add_argument("ref", type=str, nargs="?", default=DEFAULT_REF_JSON,
                   help="基准 JSON 路径 (默认: references-tag/reference_latest.json)")
    p.add_argument("--max-rounds", type=int, default=MAX_ROUNDS,
                   help=f"最大拍照次数 (默认: {MAX_ROUNDS})")
    args = p.parse_args()
    positioning(args.ref, max_rounds=args.max_rounds)
