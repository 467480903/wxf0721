"""拍照 → 保存基准位姿和照片 (按基准名 + 时间命名)。

用法:
    python set_reference.py --ids 1 2 --spacing 600 --size 100
    python set_reference.py --ids 3 4 --spacing 800 --size 100

name 由 ids 固定生成 (如 1-2), 同一组码永远是同一个 name。
每个基准自包含 ids/间距/码边长, 存到 references/ref_<name>_<时间戳>.json,
并更新软链 references/reference_<name>.json → 最新该基准。
"""

import os
import json
import shutil
import sys
import argparse
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AprilTag"))
from aruco_pose import save_reference_pose, compute_midline_geometry

from minth import Minth
from capture import capture_head_color

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(BASE_DIR, "references")
os.makedirs(REF_DIR, exist_ok=True)


def parse_args():
    p = argparse.ArgumentParser(description="采集基准位姿 (多基准)")
    p.add_argument("--ids", type=int, nargs=2, required=True,
                   help="本基准的两个码 ID, 如 --ids 1 2")
    p.add_argument("--spacing", type=float, required=True,
                   help="两码中心距 mm")
    p.add_argument("--size", type=float, required=True,
                   help="单码边长 mm")
    p.add_argument("--depth-method", type=str, default="pnp",
                   choices=["pnp", "spacing"],
                   help="深度算法: pnp(AprilTag, 默认) / spacing(YOLO 相似三角形)")
    return p.parse_args()


args = parse_args()
target_ids = args.ids
spacing_mm = args.spacing
marker_size_mm = args.size
depth_method = args.depth_method
# name 由 ids 固定生成, 同一组码永远是同一个 name
name = "-".join(str(i) for i in target_ids)

print(f"=== 采集基准 [{name}] ===")
print(f"  ids={target_ids}, 间距={spacing_mm}mm, 码边长={marker_size_mm}mm")

# 1. 拍照
print("=== 拍照 ===")
G2 = Minth.G2()
img_path = None
try:
    img_path = capture_head_color(G2)
    if img_path is None:
        print("[错误] 拍照失败")
        sys.exit(1)
    print(f"[拍照] {img_path}")
finally:
    G2.close()

# 2. 按基准名 + 时间命名
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
ref_img = os.path.join(REF_DIR, f"ref_{name}_{ts}.jpg")
ref_json = os.path.join(REF_DIR, f"ref_{name}_{ts}.json")

shutil.copy2(img_path, ref_img)
print(f"基准图: {ref_img}")

# 3. 解算并保存基准位姿 (带 ids/间距/码边长)
result = save_reference_pose(
    img_path, ref_json,
    target_ids=target_ids, spacing_mm=spacing_mm,
    marker_size_mm=marker_size_mm, name=name,
    depth_method=depth_method)

err = result["reprojection_error_px"]
if err > 1.0:
    print(f"\n[警告] 重投影误差 {err:.3f}px > 1.0px, 基准位姿不可靠")

print(f"\n✓ 基准位姿已保存: {ref_json}")
print(f"  名称: {name}")
print(f"  ids: {result['target_ids']} (左 ID{result['left_marker_id']}, 右 ID{result['right_marker_id']})")
print(f"  间距: {result['marker_spacing_mm']}mm, 码边长: {result['marker_size_mm']}mm")
print(f"  左码朝向: {result['left_orientation']}, 右码朝向: {result['right_orientation']}")
print(f"  重投影误差: {err:.3f}px")

# 4. 确保像素几何字段存在 (供 positioning.py 像素法收敛判据使用); 已有则忽略
with open(ref_json, "r", encoding="utf-8") as f:
    ref_data = json.load(f)

PIXEL_FIELDS = ["mid_x_px_ref", "mid_y_px_ref", "tilt_deg_ref"]
if all(k in ref_data for k in PIXEL_FIELDS):
    print(f"  像素几何字段已存在, 跳过: "
          f"mid_x={ref_data['mid_x_px_ref']:.1f}px, "
          f"mid_y={ref_data['mid_y_px_ref']:.1f}px, "
          f"tilt={ref_data['tilt_deg_ref']:.2f}°")
else:
    mid_x, mid_y, tilt = compute_midline_geometry(img_path, target_ids=target_ids)
    ref_data["mid_x_px_ref"] = mid_x
    ref_data["mid_y_px_ref"] = mid_y
    ref_data["tilt_deg_ref"] = tilt
    with open(ref_json, "w", encoding="utf-8") as f:
        json.dump(ref_data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 已补存像素几何字段: mid_x={mid_x:.1f}px, mid_y={mid_y:.1f}px, tilt={tilt:.2f}°")

# 5. 更新该基准的 latest 软链 (每个基准一个, 多基准互不干扰)
latest_json = os.path.join(REF_DIR, f"reference_{name}.json")
if os.path.islink(latest_json) or os.path.exists(latest_json):
    os.remove(latest_json)
os.symlink(os.path.basename(ref_json), latest_json)
print(f"✓ 已更新: {latest_json} → {os.path.basename(ref_json)}")
print(f"\n定位时调用: python positioning.py {latest_json}")

