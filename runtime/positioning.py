"""拍照 → 解算 → 机器人回位 (旋转+平移同步, 1280×800)。

流程 (严格最多 max_rounds 次拍照, 默认 2):
  每轮: 拍照 → 解算 → 已收敛则结束, 否则旋转+平移同步纠偏
  最后一轮纠偏后不再拍照验证
  max_rounds=0: 只拍照解算写残余误差 JSON, 不纠偏

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
YAW_TOL_DEG = 0.8          # 旋转容差
TRANS_TOL_MM = 5.0        # 平移容差
FAIL_REPROJ_ERR_PX = 1.5   # 重投影超此值不执行

# ============ 纠偏增益 (补偿实际移动量与指令的偏差) ============
GAIN_X = 1.1               # x 实测效率 ~93%, 放大指令
GAIN_Y = 1.0               # y 实测 ~112%, 暂不补偿

# ============ 底盘死区补偿 ============
CHASSIS_MIN_MM = 15.0      # 底盘最小可执行位移, 小于此值跑不动
BACKLASH_MM = 30.0         # 小位移时先反向预跑量, 再正向跑 BACKLASH+目标
YAW_BACKLASH_DEG = 3.0     # |dyaw|<此值且xy死区补偿时, 旋转也加死区补偿

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


def split_chassis_move(move_x, move_y):
    """底盘死区补偿: 某轴 0<|v|<CHASSIS_MIN_MM 时底盘跑不动,
    先反向跑 BACKLASH_MM, 再正向跑 BACKLASH_MM+|v| (净位移=v)。
    返回 (seg1, seg2); seg2=None 表示无需分段。"""
    seg1 = [move_x, move_y]
    seg2 = None
    for i, v in enumerate((move_x, move_y)):
        if 0.0 < abs(v) < CHASSIS_MIN_MM / 1000.0:
            if seg2 is None:
                seg2 = [0.0, 0.0]
            back = -np.copysign(BACKLASH_MM / 1000.0, v)
            seg1[i] = back
            seg2[i] = v - back   # = v + 30mm*sign(v)
    return seg1, seg2


def step_move(G2, ref_path, step, max_rounds, waist_used, trans_converged):
    """拍照 → 解算 → 已收敛则标记, 否则纠偏。返回 (r, converged, waist_used, trans_converged)。

    腰部时机: xy在容差内(或曾收敛)且yaw超差 → 只动腰底盘不动; 后续yaw仍超差 → 继续动腰。
    底盘: xy超差(且未收敛过) → 旋转+平移同步; xy死区补偿时若|dyaw|<3°, 旋转也加死区补偿。
    trans_converged: xy平移曾进入容差, 后续不再动底盘平移 (避免检测误差导致来回移动)。"""
    r = take_photo_and_solve(G2, step, "纠偏", ref_path)
    if r is None:
        return None, False, waist_used, trans_converged

    dt = r["dt"]
    dyaw = r["dyaw_deg"]
    dist = float(np.hypot(dt[0], dt[1]))
    yaw_ok = abs(dyaw) <= YAW_TOL_DEG
    trans_ok = dist <= TRANS_TOL_MM

    # xy曾收敛或本次在容差内 → 锁定, 不再动底盘平移
    if trans_ok:
        trans_converged = True

    if yaw_ok and trans_converged:
        print(f"  ✓ 已收敛: |dyaw|={abs(dyaw):.2f}° ≤ {YAW_TOL_DEG}°, |位移|={dist:.1f}mm ≤ {TRANS_TOL_MM}mm")
        return r, True, waist_used, trans_converged

    # 平移: dt[0]>0 远离墙 → 后退; dt[1]>0 偏左 → 右移; 乘增益补偿欠移
    move_x = -dt[0] / 1000.0 * GAIN_X
    move_y = -dt[1] / 1000.0 * GAIN_Y

    # 腰部时机: yaw超差 且 (xy曾收敛 或 腰部已用过)
    # xy收敛后只动腰, 转底盘会影响xy
    use_waist = (not yaw_ok) and (trans_converged or waist_used)

    # 是否需要底盘平移: xy超差 且 未曾收敛
    need_chassis_trans = (not trans_ok) and (not trans_converged)

    if use_waist:
        # 腰部纯转 yaw, xy在容差内/曾收敛则底盘完全不动
        waist_offset = -np.radians(dyaw)
        print(f"  [纠偏-腰部] offset={waist_offset:+.4f}rad ({dyaw:+.2f}°)")
        if not confirm_large_move(move_x, move_y, dyaw):
            print("  [跳过] 用户未确认")
            return r, False, waist_used, trans_converged
        if not G2.JOINT("idx05_body_joint5", offset=waist_offset):
            print("[错误] 腰部纠偏失败")
            return None, False, waist_used, trans_converged
        waist_used = True
        # xy超差且未曾收敛才平移
        if need_chassis_trans:
            seg1, seg2 = split_chassis_move(move_x, move_y)
            if seg2:
                print(f"  [死区补偿] 先反向 x={seg1[0]:+.3f}m y={seg1[1]:+.3f}m, "
                      f"再正向 x={seg2[0]:+.3f}m y={seg2[1]:+.3f}m")
            if not G2.REL({"x": seg1[0], "y": seg1[1]}):
                print("[错误] 纠偏失败")
                return None, False, waist_used, trans_converged
            if seg2 and not G2.REL({"x": seg2[0], "y": seg2[1]}):
                print("[错误] 死区补偿第二段失败")
                return None, False, waist_used, trans_converged
    else:
        # 底盘: 旋转+平移同步 (dyaw>0 左转残差 → 右转, yaw_cmd 负)
        yaw_cmd = -np.radians(dyaw)

        if need_chassis_trans:
            seg1, seg2 = split_chassis_move(move_x, move_y)
        else:
            seg1, seg2 = [0.0, 0.0], None  # 只转不平移

        # xy死区补偿时, |dyaw|<3° 也加旋转死区补偿
        if seg2 is not None and abs(dyaw) < YAW_BACKLASH_DEG:
            yaw_back = -np.copysign(np.radians(YAW_BACKLASH_DEG), yaw_cmd)
            seg1_yaw = yaw_back
            seg2_yaw = yaw_cmd - yaw_back
            print(f"  [纠偏-底盘] yaw=±{YAW_BACKLASH_DEG}°→{np.degrees(yaw_cmd):+.2f}° (旋转死区补偿), "
                  f"x={move_x:+.4f}m, y={move_y:+.4f}m" + (" [平移锁定]" if not need_chassis_trans else ""))
        else:
            seg1_yaw = yaw_cmd
            seg2_yaw = None
            print(f"  [纠偏-底盘] yaw={np.degrees(yaw_cmd):+.2f}°, x={move_x:+.4f}m, y={move_y:+.4f}m"
                  + (" [平移锁定]" if not need_chassis_trans else ""))

        if seg2:
            print(f"  [死区补偿] 先反向 x={seg1[0]:+.3f}m y={seg1[1]:+.3f}m yaw={np.degrees(seg1_yaw):+.1f}°, "
                  f"再正向 x={seg2[0]:+.3f}m y={seg2[1]:+.3f}m"
                  + (f" yaw={np.degrees(seg2_yaw):+.1f}°" if seg2_yaw is not None else "") + ")")
        if not confirm_large_move(move_x, move_y, dyaw):
            print("  [跳过] 用户未确认")
            return r, False, waist_used, trans_converged
        if not G2.REL({"x": seg1[0], "y": seg1[1], "yaw_rad": seg1_yaw}):
            print("[错误] 纠偏失败")
            return None, False, waist_used, trans_converged
        if seg2:
            cmd = {"x": seg2[0], "y": seg2[1]}
            if seg2_yaw is not None:
                cmd["yaw_rad"] = seg2_yaw
            if not G2.REL(cmd):
                print("[错误] 死区补偿第二段失败")
                return None, False, waist_used, trans_converged
    time.sleep(0.5)
    return r, False, waist_used, trans_converged


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
        waist_used = False
        trans_converged = False
        for i in range(1, max_rounds + 1):
            print(f"\n━━━ 第 {i}/{max_rounds} 次拍照 ━━━")
            r, converged, waist_used, trans_converged = step_move(
                G2, ref_path, i, max_rounds, waist_used, trans_converged)
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
