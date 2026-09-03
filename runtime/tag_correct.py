#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import time
import cv2
import numpy as np
from aruco import solve_single_tag, get_extrinsics
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(os.path.dirname(BASE_DIR), "images")
ANNOTATED_PATH = os.path.join(BASE_DIR, "tag_correct_annotated.jpg")
CAMERA_NAME = "kHandRightColor"
CAMERA_KEY = "hand_right"

# ── 码参数 ───────────────────────────────────────────────
TAG_SIZE_MM = 39.0             # 码边长 (mm), PnP 用
TARGET_TAG_ID = None           # None=自动取最大面积的码; 指定则锁定该 ID
MAX_REPROJ_ERR_PX = 2.0        # PnP 重投影误差阈值 (px)

# ── 纠偏参数 ─────────────────────────────────────────────
MAX_ITER = 3                   # 最大轮数: 严格"拍一次跑一次", 拍照与移动各≤MAX_ITER次
TOL_MM = 2.0                   # 位置收敛容差 (mm, 相机系 tvec 误差范数)
TOL_ANG_DEG = 2.0              # 角度收敛容差 (度), 当前只显示不纠
MAX_OFFSET_MM = 50.0          # 单次 OFFSET 上限 (mm)
SETTLE_TIME = 0.3              # 运动后等待时间 (秒)

# ── 执行增益 (实测 OFFSET 超程补偿) ──────────────────────
EXEC_GAIN_LARGE = 0.80         # |d| > 50mm (执行率 1.25~1.30 → ×0.80)
EXEC_GAIN_MID = 0.90           # 20mm < |d| ≤ 50mm (执行率 ~1.10)
EXEC_GAIN_SMALL = 1.0          # |d| ≤ 20mm (小位移基本 1:1)


def _exec_gain(dist_mm):
    """按位移大小返回执行增益 (超程补偿)。"""
    if dist_mm > 50.0:
        return EXEC_GAIN_LARGE
    if dist_mm > 20.0:
        return EXEC_GAIN_MID
    return EXEC_GAIN_SMALL

# ═══════════════════════════════════════════════════════════
#  拍照 (右手腕相机, 与 tape_correct 同构)
# ═══════════════════════════════════════════════════════════

def capture_hand_right(G2, timeout=10.0, poll_interval=0.1, settle_time=0.3):
    """通过 MQTT save_photo 拍右手腕相机, 返回新图片路径。"""
    if settle_time > 0:
        time.sleep(settle_time)

    before = set(os.listdir(IMAGE_DIR)) if os.path.exists(IMAGE_DIR) else set()

    G2._done_event.clear()
    payload = {"command": "save_photo", "cameras": [CAMERA_NAME]}
    G2._client.publish("/humanoid/camera/control", json.dumps(payload, ensure_ascii=False), qos=2)
    print(f"[拍照] 已发送 save_photo ({CAMERA_NAME})")

    done = G2._done_event.wait(timeout=15)
    if not done:
        print("[拍照] MQTT 回执超时")
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        after = set(os.listdir(IMAGE_DIR)) if os.path.exists(IMAGE_DIR) else set()
        new_files = [f for f in (after - before)
                     if f.endswith(".jpg") and CAMERA_NAME in f]
        if new_files:
            return os.path.join(IMAGE_DIR, sorted(new_files)[-1])
        time.sleep(poll_interval)

    print(f"[拍照] 超时 {timeout}s 未检测到新图片")
    return None


def detect_tag(img):
    """检测并解算, 返回中心"""
    result = solve_single_tag(
        img, TAG_SIZE_MM, target_id=TARGET_TAG_ID, camera=CAMERA_KEY)
    if result is None:
        return None

    if result["reproj_err"] > MAX_REPROJ_ERR_PX:
        print(f"[AprilTag] PnP 重投影误差过大: {result['reproj_err']:.2f}px "
              f"> {MAX_REPROJ_ERR_PX}px, 丢弃")
        return None

    return result


def _draw_annotation(img, ref, cur, error, out_path):
    """画标记图: 绿=参考十字, 红=当前码, 黄=角点, 蓝=误差箭头"""
    vis = img.copy()

    if cur is not None:
        pts = np.int32(cur["corners"]).reshape(-1, 1, 2)
        cv2.polylines(vis, [pts], True, (0, 255, 255), 2)
        for p in cur["corners"]:
            cv2.circle(vis, (int(p[0]), int(p[1])), 4, (0, 128, 255), -1)

    if ref is not None:
        rx, ry = int(ref["cx"]), int(ref["cy"])
        cv2.drawMarker(vis, (rx, ry), (0, 255, 0), cv2.MARKER_CROSS, 30, 2)
        cv2.putText(vis, "REF", (rx + 10, ry - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    if cur is not None:
        cx, cy = int(cur["cx"]), int(cur["cy"])
        cv2.drawMarker(vis, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 30, 2)
        cv2.putText(vis, f"ID{cur['tag_id']}", (cx + 10, cy + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        if ref is not None:
            cv2.arrowedLine(vis, (cx, cy), (int(ref["cx"]), int(ref["cy"])),
                            (255, 0, 0), 2, tipLength=0.1)
            dx, dy = error
            label = (f"dx={dx:+.1f} dy={dy:+.1f} "
                     f"ang={cur['angle_deg']:+.1f}")
            cv2.putText(vis, label, (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

    cv2.imwrite(out_path, vis)
    print(f"[AprilTag] 标记图已保存: {out_path}")


# ═══════════════════════════════════════════════════════════
#  参考加载
# ═══════════════════════════════════════════════════════════

def load_reference(ref_path):
    """加载参考 JSON"""
    if not os.path.exists(ref_path):
        print(f"[参考] 文件不存在: {ref_path}")
        return None
    with open(ref_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_extrinsics():
    """相机→OFFSET 运动系旋转 R。

    复用 AprilTag_pose.get_extrinsics (camera=CAMERA_KEY):
    四元数与 ROS→运动系轴变换均封装在 AprilTag_pose 模块内部,
    本文件不接触外参数值。

    Returns:
        R: 3x3 (相机系→OFFSET 运动系)
    """
    R = get_extrinsics(camera=CAMERA_KEY)
    print(f"[外参] 光轴(运动系) = {np.round(R[:, 2], 4)} "
          f"(与 x 轴夹角 {np.degrees(np.arccos(R[0, 2])):.1f}°)")
    return R



def _clamp(v, vmax):
    return max(-vmax, min(vmax, v))


def _take_photo_and_detect(G2, ref):
    """拍照 + 检测 (单次, 不重试: 频繁拍照易失败/拿到运动中图片), 返回 (result, img_path)"""
    img_path = capture_hand_right(G2, settle_time=SETTLE_TIME)
    if img_path is None:
        print("[纠偏] 拍照失败")
        return None, None

    img = cv2.imread(img_path)
    if img is None:
        print(f"[纠偏] 无法读取图片: {img_path}")
        return None, None

    result = detect_tag(img)
    if result is None:
        print("[纠偏] 未检测到 AprilTag")
        return None, img_path

    dx = ref["cx"] - result["cx"]
    dy = ref["cy"] - result["cy"]
    _draw_annotation(img, ref, result, (dx, dy), ANNOTATED_PATH)

    return result, img_path


def tag_correct(ref_path, G2):
    """迭代纠偏: 拍照 → PnP(tvec) → d = R·Δt → OFFSET 三轴 → 重复"""
    ref = load_reference(ref_path)
    if ref is None:
        print("[纠偏] 无法加载参考, 退出")
        return False
    if "tvec" not in ref:
        print("[纠偏] 参考文件缺少 tvec (旧像素法参考), 请重新采集参考")
        return False

    R = load_extrinsics()
    t_ref = np.asarray(ref["tvec"], dtype=np.float64)

    print(f"[纠偏] 参考: tvec=({t_ref[0]:.1f}, {t_ref[1]:.1f}, {t_ref[2]:.1f})mm, "
          f"ID={ref.get('tag_id')}")
    print(f"[纠偏] 容差={TOL_MM}mm, 最大轮数={MAX_ITER} (拍一次跑一次)")
    print(f"[纠偏] 外参 R (相机系→OFFSET 运动系):\n{np.round(R, 4)}")
    print()

    moves = 0
    for i in range(1, MAX_ITER + 1):
        print(f"━━━ 轮次 {i}/{MAX_ITER} (已移动 {moves} 次) ━━━")

        result, img_path = _take_photo_and_detect(G2, ref)
        if result is None:
            # 不重试: 频繁拍照易失败/拿到运动中图片, 失败即终止
            print(f"[纠偏] 第 {i} 轮拍照/检测失败, 终止 (已移动 {moves} 次)")
            return False

        # 相机系误差: Δt = tvec_cur - tvec_ref
        t_cur = np.asarray(result["tvec"], dtype=np.float64)
        dt = t_cur - t_ref
        dist = float(np.linalg.norm(dt))
        da = result["angle_deg"] - ref["angle_deg"]
        if da > 90:
            da -= 180
        elif da < -90:
            da += 180

        print(f"  误差(相机系): dt=({dt[0]:+.1f}, {dt[1]:+.1f}, {dt[2]:+.1f})mm, "
              f"距离={dist:.1f}mm, 角度偏差={da:+.1f}° (不纠)")

        if dist < TOL_MM:
            print(f"  ✓ 已收敛 (距离 {dist:.1f}mm < 容差 {TOL_MM}mm)")
            return True

        # 码固定 + 法兰纯平移: Δt = -R^T·d  ⇒  d = R·Δt (法兰系)
        d = R @ dt

        # 执行增益补偿 (大位移超程) + 单轴上限
        gain = _exec_gain(float(np.linalg.norm(d)))
        d = d * gain
        d = np.array([_clamp(v, MAX_OFFSET_MM) for v in d])

        if np.all(np.abs(d) < 0.1):
            print(f"  ✓ 偏移太小 (d=({d[0]:.2f}, {d[1]:.2f}, {d[2]:.2f})mm), 不执行")
            return True

        suffix = f" (执行增益×{gain:.2f})" if gain != 1.0 else ""
        print(f"  → OFFSET rx={d[0]:+.2f}mm, ry={d[1]:+.2f}mm, rz={d[2]:+.2f}mm{suffix}")
        ok = G2.OFFSET({"rx": float(d[0]), "ry": float(d[1]), "rz": float(d[2])})
        if not ok:
            print(f"  ✗ OFFSET 执行失败")
            return False
        moves += 1

        time.sleep(SETTLE_TIME)

    print(f"[纠偏] 达到轮次上限 {MAX_ITER} (拍照/移动各 {moves} 次), 未收敛")
    return False


