#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import os
import shutil
import sys
import time

import cv2
import numpy as np

from AprilTag_pose import (
    detect_tags_from_image, joint_solve_pnp,
    HAND_RIGHT_CAMERA_MATRIX as CAMERA_MATRIX,
    HAND_RIGHT_DIST_COEFFS as DIST_COEFFS,
    HAND_RIGHT_IMAGE_SIZE as EXPECTED_IMAGE_SIZE,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(os.path.dirname(BASE_DIR), "images")
REF_DIR = os.path.join(BASE_DIR, "tag_ref")
ANNOTATED_PATH = os.path.join(BASE_DIR, "tag_correct_annotated.jpg")
REF_SYMLINK = os.path.join(REF_DIR, "latest.json")

CAMERA_NAME = "kHandRightColor"

TAG_SIZE_MM = 39.0
TARGET_TAG_ID = None

TAG_OBJ_POINTS = np.array([
    [-TAG_SIZE_MM / 2,  TAG_SIZE_MM / 2, 0],
    [ TAG_SIZE_MM / 2,  TAG_SIZE_MM / 2, 0],
    [ TAG_SIZE_MM / 2, -TAG_SIZE_MM / 2, 0],
    [-TAG_SIZE_MM / 2, -TAG_SIZE_MM / 2, 0],
], dtype=np.float64)
CORNER_ORDER_IPPE = [3, 2, 1, 0]
MAX_REPROJ_ERR_PX = 2.0

END_CAMERA_QUAT = (0.011872406805271707, 0.0027948274752750955,
                   -0.36695245525389036, 0.9301597338517591)

MAX_ITER = 3
TOL_MM = 2.0
TOL_ANG_DEG = 2.0
MAX_OFFSET_MM = 100.0
SETTLE_TIME = 0.3

EXEC_GAIN_LARGE = 0.80
EXEC_GAIN_MID = 0.90
EXEC_GAIN_SMALL = 1.0


def _exec_gain(dist_mm):
    if dist_mm > 50.0:
        return EXEC_GAIN_LARGE
    if dist_mm > 20.0:
        return EXEC_GAIN_MID
    return EXEC_GAIN_SMALL


def capture_hand_right(G2, timeout=10.0, poll_interval=0.1, settle_time=0.3):
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
    if img is None:
        return None

    h, w = img.shape[:2]
    if (w, h) != EXPECTED_IMAGE_SIZE:
        print(f"[AprilTag] 图像尺寸 {w}×{h} 与内参配套 "
              f"{EXPECTED_IMAGE_SIZE[0]}×{EXPECTED_IMAGE_SIZE[1]} 不匹配")
        return None

    target_ids = [TARGET_TAG_ID] if TARGET_TAG_ID is not None else None
    try:
        markers = detect_tags_from_image(img, target_ids=target_ids)
    except RuntimeError as e:
        print(f"[AprilTag] {e}")
        return None

    if TARGET_TAG_ID is not None:
        tag_id, corners = TARGET_TAG_ID, markers[TARGET_TAG_ID]
    else:
        tag_id, corners = max(
            markers.items(),
            key=lambda kv: cv2.contourArea(kv[1].astype(np.float32)))
    corners = np.asarray(corners, dtype=np.float64).reshape(4, 2)
    area = cv2.contourArea(corners.astype(np.float32))

    cx, cy = corners.mean(axis=0)

    top_l, top_r = corners[3], corners[2]
    ang = np.degrees(np.arctan2(top_r[1] - top_l[1], top_r[0] - top_l[0]))
    if ang > 90:
        ang -= 180
    elif ang < -90:
        ang += 180

    print(f"[AprilTag] ID={tag_id}, 中心=({cx:.1f}, {cy:.1f}), "
          f"面积={area:.0f}px², 角度={ang:.1f}°")

    corners_ippe = corners[CORNER_ORDER_IPPE]
    try:
        rvec, tvec, reproj_err, _ = joint_solve_pnp(
            TAG_OBJ_POINTS, corners_ippe, CAMERA_MATRIX, DIST_COEFFS)
    except (RuntimeError, cv2.error) as e:
        print(f"[AprilTag] PnP 解算失败: {e}")
        return None

    if reproj_err > MAX_REPROJ_ERR_PX:
        print(f"[AprilTag] PnP 重投影误差过大: {reproj_err:.2f}px > {MAX_REPROJ_ERR_PX}px, 丢弃")
        return None

    tvec_flat = tvec.flatten()
    print(f"[PnP] tvec=({tvec_flat[0]:.1f}, {tvec_flat[1]:.1f}, {tvec_flat[2]:.1f})mm, "
          f"重投影={reproj_err:.2f}px")

    return {
        "cx": float(cx),
        "cy": float(cy),
        "angle_deg": float(ang),
        "tag_id": int(tag_id),
        "corners": corners,
        "area": float(area),
        "tvec": tvec_flat.tolist(),
        "rvec": rvec.flatten().tolist(),
        "reproj_err": reproj_err,
    }


def _draw_annotation(img, ref, cur, error, out_path):
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


def _update_symlink(ref_json):
    try:
        if os.path.islink(REF_SYMLINK) or os.path.exists(REF_SYMLINK):
            os.remove(REF_SYMLINK)
        os.symlink(os.path.basename(ref_json), REF_SYMLINK)
        print(f"[参考] 软链已更新 → {REF_SYMLINK}")
    except OSError as e:
        print(f"[参考] 软链更新失败: {e}")


def load_reference(ref_path):
    if not os.path.exists(ref_path):
        print(f"[参考] 文件不存在: {ref_path}")
        return None
    with open(ref_path, "r", encoding="utf-8") as f:
        return json.load(f)


ROS_TO_MOVE = np.array([
    [0.0, 0.0, 1.0],
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
], dtype=np.float64)


def load_extrinsics():
    w, x, y, z = END_CAMERA_QUAT
    R_ros = np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - w*z),     2*(x*z + w*y)],
        [2*(x*y + w*z),     1 - 2*(x*x + z*z), 2*(y*z - w*x)],
        [2*(x*z - w*y),     2*(y*z + w*x),     1 - 2*(x*x + y*y)],
    ], dtype=np.float64)
    R = ROS_TO_MOVE @ R_ros
    print(f"[外参] 光轴(运动系) = {np.round(R[:, 2], 4)} "
          f"(与 x 轴夹角 {np.degrees(np.arccos(R[0, 2])):.1f}°)")
    return R


def _clamp(v, vmax):
    return max(-vmax, min(vmax, v))


def _take_photo_and_detect(G2, ref):
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
    ref = load_reference(ref_path)
    if ref is None:
        print("[纠偏] 无法加载参考, 退出")
        return False
    if "tvec" not in ref:
        print("[纠偏] 参考文件缺少 tvec (旧像素法参考), 请重新采集:")
        print("       python tag_correct.py set_reference")
        return False

    R = load_extrinsics()
    t_ref = np.asarray(ref["tvec"], dtype=np.float64)

    print(f"[纠偏] 参考: tvec=({t_ref[0]:.1f}, {t_ref[1]:.1f}, {t_ref[2]:.1f})mm, "
          f"ID={ref.get('tag_id')}")
    print(f"[纠偏] 容差={TOL_MM}mm, 最大轮数={MAX_ITER} (拍一次跑一次)")
    print(f"[纠偏] 外参 R (相机系→法兰系):\n{np.round(R, 4)}")
    print()

    moves = 0
    for i in range(1, MAX_ITER + 1):
        print(f"━━━ 轮次 {i}/{MAX_ITER} (已移动 {moves} 次) ━━━")

        result, img_path = _take_photo_and_detect(G2, ref)
        if result is None:
            print(f"[纠偏] 第 {i} 轮拍照/检测失败, 终止 (已移动 {moves} 次)")
            return False

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

        d = R @ dt

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
