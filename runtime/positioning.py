"""拍照 → 解算 → 机器人回位 (旋转+平移同步, 1280×800)。

流程 (严格最多 max_rounds 次拍照, 默认 2):
  每轮: 拍照 → 解算 → 已收敛则结束, 否则旋转+平移同步纠偏
  最后一轮纠偏后不再拍照验证
  max_rounds=0: 只拍照解算写残余误差 JSON, 不纠偏

容差: 旋转 ±2.5°, 平移 ±10mm。
增益: GAIN_X/GAIN_Y 补偿实际移动与指令的偏差 (x 实测 ~93%)。
安全: |dt|>500mm 或 |dyaw|>45° 时等用户确认; reproj>2.0px 不执行。
G2.REL 坐标系: x 前进(朝墙), y 左移, yaw_rad 逆时针。

调用:
    python positioning.py [基准JSON路径] [--max-rounds N]
    不传则默认 references-tag/reference_latest.json
"""

import os
import sys
import json
import time
import numpy as np
from datetime import datetime


_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PARENT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aruco import compute_offset
from minth import Minth
from capture import capture_head_color

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REF_JSON = os.path.join(BASE_DIR, "references-tag", "reference_latest.json")
RESIDUAL_JSON = os.path.join(BASE_DIR, "positioning_residual.json")

# ============ 容差 ============
YAW_TOL_DEG = 1.3          # 旋转容差
TRANS_TOL_MM = 10.0        # 平移容差
FAIL_REPROJ_ERR_PX = 1.5   # 重投影超此值不执行

# ============ 纠偏增益 (补偿实际移动量与指令的偏差) ============
GAIN_X = 1.1               # x 实测效率 ~93%, 放大指令
GAIN_Y = 1.0               # y 实测 ~112%, 暂不补偿

# ============ 安全约束 ============
CONFIRM_LARGE_MOVE = True
LARGE_MOVE_THRESHOLD_MM = 500.0
LARGE_YAW_THRESHOLD_DEG = 45.0


def confirm_large_move(move_x_m, move_y_m, yaw_deg):
    """大位移或大旋转时等用户确认。"""
    if not CONFIRM_LARGE_MOVE:
        return True
    dist_mm = float(np.hypot(move_x_m, move_y_m) * 1000.0)
    if dist_mm <= LARGE_MOVE_THRESHOLD_MM and abs(yaw_deg) <= LARGE_YAW_THRESHOLD_DEG:
        return True
    print(f"\n  [确认] 位移 {dist_mm:.0f}mm 或 旋转 {yaw_deg:.1f}° 超阈值")
    ans = input("  输入 y 执行 / 其它跳过: ").strip().lower()
    return ans == "y"


def load_reference(ref_path):
    """加载基准 JSON。"""
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
    """拍照 + 解算偏移。"""
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
        "dpitch_deg": float(result["dpitch_deg"]),
        "droll_deg": float(result["droll_deg"]),
        "reproj": reproj,
    }


def step_move(G2, ref_path, step):
    """拍照 → 解算 → 已收敛则标记, 否则旋转+平移同步纠偏。返回 (r, converged)。"""
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

    # 平移: dt[0]>0 远离墙 → 后退; dt[1]>0 偏左 → 右移; 乘增益补偿欠移
    move_x = -dt[0] / 1000.0 * GAIN_X
    move_y = -dt[1] / 1000.0 * GAIN_Y

    if step == 1:
        # 第1次: 旋转+平移同步走底盘 (dyaw>0 左转残差 → 右转, yaw_cmd 负)
        yaw_cmd = -np.radians(dyaw)
        print(f"  [纠偏-底盘] yaw={np.degrees(yaw_cmd):+.2f}°, x={move_x:+.4f}m, y={move_y:+.4f}m")
        if not confirm_large_move(move_x, move_y, dyaw):
            print("  [跳过] 用户未确认")
            return r, False
        if not G2.REL({"x": move_x, "y": move_y, "yaw_rad": yaw_cmd}):
            print("[错误] 纠偏失败")
            return None, False
    else:
        # 后续: 旋转走腰部 (offset 负=逆时针/左转, 故右转纠偏=负), 平移走底盘
        waist_offset = -np.radians(dyaw)
        print(f"  [纠偏-腰部] offset={waist_offset:+.4f}rad ({dyaw:+.2f}°), "
              f"x={move_x:+.4f}m, y={move_y:+.4f}m")
        if not confirm_large_move(move_x, move_y, dyaw):
            print("  [跳过] 用户未确认")
            return r, False
        if not G2.JOINT("idx05_body_joint5", offset=waist_offset):
            print("[错误] 腰部纠偏失败")
            return None, False
        if not G2.REL({"x": move_x, "y": move_y}):
            print("[错误] 纠偏失败")
            return None, False
    time.sleep(0.5)
    return r, False


def write_residual(r, ref_path, converged):
    """把残余误差存 JSON (每次覆盖, 带时间戳和收敛标注)。"""
    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ref": os.path.basename(ref_path),
        "converged": bool(converged),
        "dt_mm": {
            "dx": float(r["dt"][0]),
            "dy": float(r["dt"][1]),
            "dz": float(r["dt"][2]),
        },
        "euler_deg": {
            "yaw": r["dyaw_deg"],
            "pitch": r["dpitch_deg"],
            "roll": r["droll_deg"],
        },
        "reprojection_error_px": r["reproj"],
    }
    with open(RESIDUAL_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[残余] 误差已保存 (converged={converged}): {RESIDUAL_JSON}")


def save_residual(G2, ref_path):
    """未收敛终检: 再拍一次, 把残余误差存 JSON。"""
    r = take_photo_and_solve(G2, "final", "终检", ref_path)
    if r is None:
        return None
    write_residual(r, ref_path, converged=False)
    return r


# ============ 主流程 ============

MAX_ROUNDS = 2

def positioning(ref_path, G2=None, max_rounds=MAX_ROUNDS):
    """纠偏: 旋转+平移同步, 严格最多 max_rounds 次拍照。

    每轮: 拍照 → 解算 → 已收敛则结束, 否则纠偏
    最后一轮纠偏后不再拍照验证 (如需验证把 max_rounds 当检查轮理解即可)
    max_rounds=0: 只拍照解算写残余误差 JSON, 不纠偏。
    """
    ref_path = load_reference(ref_path)

    own_g2 = G2 is None
    if own_g2:
        G2 = Minth.G2()

    results = []
    try:
        if max_rounds <= 0:
            # 只拍照记录模式: 拍一张 → 解算 → 写残余误差 JSON, 不执行任何纠偏
            print("=== 只拍照记录模式 (不纠偏) ===")
            r = take_photo_and_solve(G2, "measure", "记录", ref_path)
            if r is not None:
                write_residual(r, ref_path, converged=False)
                results.append(r)
            return results

        print(f"=== 开始纠偏 (最多 {max_rounds} 次拍照) ===")
        for i in range(1, max_rounds + 1):
            print(f"\n━━━ 第 {i}/{max_rounds} 次拍照 ━━━")
            r, converged = step_move(G2, ref_path, i)
            results.append(r)
            if r is None:
                break
            if converged:
                print(f"\n=== ✓ 收敛, 结束 ===")
                write_residual(r, ref_path, converged=True)
                break
        else:
            print(f"\n=== 未收敛 (已达 {max_rounds} 次拍照上限), 终检保存误差 ===")
            r_final = save_residual(G2, ref_path)
            if r_final is not None:
                results.append(r_final)
    finally:
        if own_g2:
            G2.close()

    return results
