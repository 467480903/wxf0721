#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
右手 AprilTag 36h11 纠偏 (单码 39mm)

基于右手腕相机 (kHandRightColor, 1280×1056) 检测单个 AprilTag 36h11 (边长 39mm),
通过 G2.OFFSET 的 rx (前伸/后退) 和 ry (左移/右移) 将码对齐到参考位置。

相比胶带方案的优势:
  - 亚像素角点 (refine_edges), 位置精度 ~0.1px
  - 角度由 4 角点精确计算
  - 对光照/形状不规则鲁棒 (二值自适应分割 + 编码校验)

流程:
  1. set_reference   采集参考 (拍一张正确位置的图, 保存码中心和角度)
  2. correct         迭代纠偏 (拍照 → 检测 → 算误差 → OFFSET → 重复)

用法:
  cd /data/wxf/wxf0721/runtime

  # 采集参考 (码在正确位置时运行)
  python tag_correct.py set_reference

  # 纠偏 (默认用最新参考)
  python tag_correct.py correct

坐标约定:
  - 图像坐标: x 右增, y 下增 (OpenCV 标准)
  - dx = ref_cx - cur_cx (正值=码偏左, 需右移)
  - dy = ref_cy - cur_cy (正值=码偏上, 需前伸)
  - da = cur_ang - ref_ang (正值=码顺时针偏, 需左转; 当前不纠只显示)
  - OFFSET 映射:
      ry = GAIN_Y * dx   (dx>0 偏左 → ry>0 左移 → 码右移)
      rx = GAIN_X * dy   (dy>0 偏上 → rx>0 前伸 → 码下移)
    注: 若方向反了改 GAIN 符号
"""

import argparse
import json
import os
import sys
import time

import cv2
import numpy as np
from pyapriltags import Detector

# ── 路径 ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(os.path.dirname(BASE_DIR), "images")
REF_DIR = os.path.join(BASE_DIR, "tag_ref")
ANNOTATED_PATH = os.path.join(BASE_DIR, "tag_correct_annotated.jpg")
REF_SYMLINK = os.path.join(REF_DIR, "latest.json")

# ── 相机配置 ─────────────────────────────────────────────
CAMERA_NAME = "kHandRightColor"
EXPECTED_IMAGE_SIZE = (1280, 1056)   # (width, height)

# ── 相机内参 (右手腕相机, 1280×1056) ─────────────────────
# 来源: /data/parameters/sensor/intrinsic_hand_right_rgb.json
CAMERA_MATRIX = np.array([
    [484.13450533567277, 0.0, 642.9731345849336],
    [0.0, 483.75752780401365, 526.1533084887114],
    [0.0, 0.0, 1.0],
], dtype=np.float64)

# OpenCV 顺序: [k1, k2, p1, p2, k3]
DIST_COEFFS = np.array([
    -0.05168978308940051, -0.00794850229307811,
    0.00033148236384535073, 8.682628848347434e-05,
    0.0015538101546491098,
], dtype=np.float64).reshape(-1, 1)

# ── 码参数 ───────────────────────────────────────────────
TAG_FAMILY = "tag36h11"
TAG_SIZE_MM = 39.0             # 码边长 (mm), 像素纠偏不用, 留作 PnP 扩展
TARGET_TAG_ID = None           # None=自动取最大面积的码; 指定则锁定该 ID

# ── 纠偏参数 ─────────────────────────────────────────────
MAX_ITER = 10                  # 最大迭代次数
TOL_PX = 4                     # 位置收敛容差 (像素), AprilTag 精度高可收紧
TOL_ANG_DEG = 2.0              # 角度收敛容差 (度), 当前只显示不纠
GAIN_X = 1.0                   # rx 增益 (mm/px), 实测 1.6~1.9, 留余量防过冲
GAIN_Y = 0.5                   # ry 增益 (mm/px), 左移/右移 (dx 一直很小, 暂无实测依据)
MAX_OFFSET_MM = 100.0          # 单次 OFFSET 上限 (mm), 允许一次到位
SETTLE_TIME = 0.3              # 运动后等待时间 (秒)

# ── 检测器 (单例) ────────────────────────────────────────
_detector = None


def _get_detector():
    """单例 pyapriltags Detector (tag36h11, nthreads=4, refine_edges)。"""
    global _detector
    if _detector is None:
        _detector = Detector(
            families=TAG_FAMILY,
            nthreads=4,
            quad_decimate=1.0,
            quad_sigma=0.0,
            refine_edges=1,
            decode_sharpening=0.25,
            debug=0,
        )
    return _detector


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


# ═══════════════════════════════════════════════════════════
#  AprilTag 检测
# ═══════════════════════════════════════════════════════════

def detect_tag(img):
    """检测单个 AprilTag 36h11, 返回中心/角度/角点。

    角点顺序 (pyapriltags, 图像坐标 y 下增):
      corners[0]=左下, [1]=右下, [2]=右上, [3]=左上
    角度: 上边 (左上→右上) 相对水平的倾角, [-90, 90], 0=水平。

    Returns:
        dict | None:
            {"cx", "cy", "angle_deg", "tag_id", "corners"(4,2), "area"}
    """
    if img is None:
        return None

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    detector = _get_detector()

    _clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    # 3 档: 原图 → 2× 放大 → CLAHE+2×
    attempts = [
        ("原图",     lambda g: g,               1.0),
        ("2×放大",   lambda g: g,               2.0),
        ("CLAHE+2×", lambda g: _clahe.apply(g), 2.0),
    ]

    best = None  # (area, det, corners, used)
    for name, prep_fn, scale in attempts:
        try:
            g_proc = prep_fn(gray)
        except Exception:
            continue
        g_try = (cv2.resize(g_proc, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
                 if scale != 1.0 else g_proc)
        dets = detector.detect(g_try)
        if not dets:
            continue

        # 锁定 ID 时只认该 ID; 否则取角点包围面积最大
        if TARGET_TAG_ID is not None:
            cands = [d for d in dets if int(d.tag_id) == TARGET_TAG_ID]
        else:
            cands = dets
        if not cands:
            continue

        for det in cands:
            c = np.asarray(det.corners, dtype=np.float64).reshape(4, 2)
            if scale != 1.0:
                c /= scale
            area = cv2.contourArea(c.astype(np.float32))
            if best is None or area > best[0]:
                best = (area, det, c, name)

        # 原图成功且够大就不用再试放大档
        if best is not None and best[0] > 400:
            break

    if best is None:
        print("[AprilTag] 未检测到 tag36h11")
        return None

    area, det, corners, used = best
    corners = np.asarray(corners, dtype=np.float64).reshape(4, 2)

    # 中心 = 4 角点均值
    cx, cy = corners.mean(axis=0)

    # 角度: 上边方向 (corners[3]左上 → corners[2]右上)
    top_l, top_r = corners[3], corners[2]
    ang = np.degrees(np.arctan2(top_r[1] - top_l[1], top_r[0] - top_l[0]))
    # 归一化到 [-90, 90]
    if ang > 90:
        ang -= 180
    elif ang < -90:
        ang += 180

    print(f"[AprilTag] ID={det.tag_id}, 中心=({cx:.1f}, {cy:.1f}), "
          f"面积={area:.0f}px², 角度={ang:.1f}° [{used}]")
    return {
        "cx": float(cx),
        "cy": float(cy),
        "angle_deg": float(ang),
        "tag_id": int(det.tag_id),
        "corners": corners,
        "area": float(area),
    }


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
#  参考管理
# ═══════════════════════════════════════════════════════════

def save_reference(img_path, ref_json):
    """拍照检测码, 保存参考 JSON"""
    img = cv2.imread(img_path)
    if img is None:
        print(f"[参考] 无法读取图片: {img_path}")
        return None

    result = detect_tag(img)
    if result is None:
        print("[参考] 未检测到 AprilTag, 无法保存参考")
        return None

    ref_data = {
        "cx": result["cx"],
        "cy": result["cy"],
        "angle_deg": result["angle_deg"],
        "tag_id": result["tag_id"],
        "area": result["area"],
        "tag_size_mm": TAG_SIZE_MM,
        "image_size": [img.shape[1], img.shape[0]],
        "image_path": img_path,
        "timestamp": time.strftime("%Y%m%d_%H%M%S"),
    }

    os.makedirs(os.path.dirname(ref_json), exist_ok=True)
    with open(ref_json, "w", encoding="utf-8") as f:
        json.dump(ref_data, f, ensure_ascii=False, indent=2)

    # 用原始 result (含 corners) 画图
    _draw_annotation(img, ref_data, result, (0.0, 0.0), ANNOTATED_PATH)

    _update_symlink(ref_json)

    print(f"[参考] 已保存: {ref_json}")
    print(f"  中心=({ref_data['cx']:.1f}, {ref_data['cy']:.1f}), "
          f"角度={ref_data['angle_deg']:.1f}°, ID={ref_data['tag_id']}")
    return ref_data


def _update_symlink(ref_json):
    """更新 latest.json 软链指向最新参考"""
    try:
        if os.path.islink(REF_SYMLINK) or os.path.exists(REF_SYMLINK):
            os.remove(REF_SYMLINK)
        os.symlink(os.path.basename(ref_json), REF_SYMLINK)
        print(f"[参考] 软链已更新 → {REF_SYMLINK}")
    except OSError as e:
        print(f"[参考] 软链更新失败: {e}")


def load_reference(ref_path):
    """加载参考 JSON"""
    if not os.path.exists(ref_path):
        print(f"[参考] 文件不存在: {ref_path}")
        return None
    with open(ref_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════
#  纠偏
# ═══════════════════════════════════════════════════════════

def _clamp(v, vmax):
    return max(-vmax, min(vmax, v))


def _take_photo_and_detect(G2, ref):
    """拍照 + 检测, 返回 (result, img_path)"""
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
    """迭代纠偏: 拍照 → 检测 → 算误差 → OFFSET → 重复 (只纠位置)"""
    ref = load_reference(ref_path)
    if ref is None:
        print("[纠偏] 无法加载参考, 退出")
        return False

    print(f"[纠偏] 参考: 中心=({ref['cx']:.1f}, {ref['cy']:.1f}), "
          f"角度={ref['angle_deg']:.1f}°, ID={ref.get('tag_id')}")
    print(f"[纠偏] 容差={TOL_PX}px, 最大迭代={MAX_ITER}, "
          f"增益=({GAIN_X}, {GAIN_Y}) mm/px")
    print()

    for i in range(1, MAX_ITER + 1):
        print(f"━━━ 迭代 {i}/{MAX_ITER} ━━━")

        result, img_path = _take_photo_and_detect(G2, ref)
        if result is None:
            print(f"[纠偏] 第 {i} 轮检测失败, 跳过")
            continue

        dx = ref["cx"] - result["cx"]
        dy = ref["cy"] - result["cy"]
        dist = np.hypot(dx, dy)
        da = result["angle_deg"] - ref["angle_deg"]
        if da > 90:
            da -= 180
        elif da < -90:
            da += 180

        print(f"  误差: dx={dx:+.1f}px, dy={dy:+.1f}px, "
              f"距离={dist:.1f}px, 角度偏差={da:+.1f}° (不纠)")

        if dist < TOL_PX:
            print(f"  ✓ 已收敛 (距离 {dist:.1f}px < 容差 {TOL_PX}px)")
            return True

        # OFFSET 平移纠偏
        # ry = GAIN_Y * dx  (dx>0 码偏左 → ry>0 左移 → 码右移)
        # rx = GAIN_X * dy  (dy>0 码偏上 → rx>0 前伸 → 码下移)
        ry = _clamp(GAIN_Y * dx, MAX_OFFSET_MM)
        rx = _clamp(GAIN_X * dy, MAX_OFFSET_MM)

        if abs(rx) < 0.1 and abs(ry) < 0.1:
            print(f"  ✓ 偏移太小 (rx={rx:.2f}mm, ry={ry:.2f}mm), 不执行")
            return True

        print(f"  → OFFSET rx={rx:+.2f}mm, ry={ry:+.2f}mm")
        ok = G2.OFFSET({"rx": rx, "ry": ry})
        if not ok:
            print(f"  ✗ OFFSET 执行失败")
            return False

        time.sleep(SETTLE_TIME)

    print(f"[纠偏] 达到最大迭代 {MAX_ITER}, 未收敛")
    return False


# ═══════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════

def _gen_ref_path(name=None):
    """生成参考文件路径"""
    os.makedirs(REF_DIR, exist_ok=True)
    if name:
        return os.path.join(REF_DIR, f"{name}.json")
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(REF_DIR, f"ref_{ts}.json")


def cmd_set_reference(args):
    """采集参考: 拍照 → 检测 → 保存"""
    from minth import Minth

    G2 = Minth.G2()
    try:
        img_path = capture_hand_right(G2, settle_time=0.5)
        if img_path is None:
            print("[参考] 拍照失败")
            sys.exit(1)

        ref_json = _gen_ref_path(args.name)
        ref = save_reference(img_path, ref_json)
        if ref is None:
            sys.exit(1)
    finally:
        G2.close()


def cmd_correct(args):
    """纠偏: 加载参考 → 迭代 OFFSET"""
    from minth import Minth

    ref_path = args.ref if args.ref else REF_SYMLINK
    if not os.path.exists(ref_path):
        print(f"[纠偏] 参考文件不存在: {ref_path}")
        print("  请先运行: python tag_correct.py set_reference")
        sys.exit(1)

    G2 = Minth.G2()
    try:
        ok = tag_correct(ref_path, G2)
        if ok:
            print("\n[纠偏] ✓ 完成")
        else:
            print("\n[纠偏] ✗ 未收敛")
            sys.exit(1)
    finally:
        G2.close()


def main():
    p = argparse.ArgumentParser(
        description="右手 AprilTag 36h11 纠偏 (39mm, kHandRightColor)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # set_reference
    p_ref = sub.add_parser("set_reference", help="采集参考")
    p_ref.add_argument("--name", type=str, default=None,
                       help="参考名称 (不传则用时间戳)")
    p_ref.set_defaults(func=cmd_set_reference)

    # correct
    p_cor = sub.add_parser("correct", help="迭代纠偏")
    p_cor.add_argument("--ref", type=str, default=None,
                       help="参考文件路径 (不传则用 latest.json)")
    p_cor.set_defaults(func=cmd_correct)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
