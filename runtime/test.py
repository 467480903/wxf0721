"""拍照保存位姿照片 (tag36h11, 1280×800)。

用法:
    python test.py --size 97
    python test.py --size 97 --spacing 730        # 给实测值, 精度更高
    python test.py --size 97 --name A             # 命名基准
    python test.py --size 97 --image /path/x.jpg  # 用已有图片, 不拍照
"""

import os
import sys
import json
import shutil
import argparse
from datetime import datetime
from aruco import save_reference_pose

# 加父目录到 sys.path, 复用 runtime/ 下的 minth.py 和 capture.py
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PARENT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minth import Minth
from capture import capture_head_color

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(BASE_DIR, "references-tag")
os.makedirs(REF_DIR, exist_ok=True)


def parse_args():
    p = argparse.ArgumentParser(description="采集基准位姿 (tag36h11, 1280×800)")
    p.add_argument("--size", type=float, required=True,
                   help="单码边长 mm (打印后实测值, 如 97)")
    p.add_argument("--spacing", type=float, default=None,
                   help="两码中心距 mm (实测值, 不传则自动标定)")
    p.add_argument("--name", type=str, default=None,
                   help="基准名称前缀 (可选, 默认只用 id+时间)")
    p.add_argument("--image", type=str, default=None,
                   help="直接用已有图片路径 (不拍照)")
    return p.parse_args()


args = parse_args()
marker_size_mm = args.size
spacing_mm = args.spacing
name = args.name
image_arg = args.image

print(f"=== 采集基准 ===")
print(f"  码边长={marker_size_mm}mm, 间距={'自动' if spacing_mm is None else spacing_mm}")

# 1. 取图: --image 跳过拍照
if image_arg is not None:
    if not os.path.isfile(image_arg):
        print(f"[错误] 图片不存在: {image_arg}")
        sys.exit(1)
    img_path = image_arg
    print(f"[图片] {img_path}")
else:
    print("=== 拍照 ===")
    G2 = Minth.G2()
    try:
        img_path = capture_head_color(G2)
        if img_path is None:
            print("[错误] 拍照失败")
            sys.exit(1)
        print(f"[拍照] {img_path}")
    finally:
        G2.close()

# 2. 先解算拿到码 ID, 再按 id+时间命名
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
from aruco import process_image
pnp_tuple = process_image(img_path, marker_size_mm, spacing_mm=spacing_mm)
ids = pnp_tuple[0]["target_ids"]
id_str = "_".join(f"id{i}" for i in sorted(ids))
base_name = f"{id_str}_{ts}" if name is None else f"{name}_{id_str}_{ts}"

ref_img = os.path.join(REF_DIR, f"ref_{base_name}.jpg")
ref_json = os.path.join(REF_DIR, f"ref_{base_name}.json")

shutil.copy2(img_path, ref_img)
print(f"基准图: {ref_img}")

# 3. 保存基准位姿 (复用已解算结果, 不重复计算)
result = save_reference_pose(
    img_path, ref_json,
    marker_size_mm=marker_size_mm,
    spacing_mm=spacing_mm,
    name=base_name,
    precomputed=pnp_tuple)

err = result["reprojection_error_px"]
if err > 2.0:
    print(f"\n[警告] 重投影误差 {err:.3f}px > 2.0px, 基准不可靠, 建议重采")

print(f"\n✓ 基准位姿已保存: {ref_json}")
print(f"  名称: {base_name}")
print(f"  ids: {result['target_ids']} (左 ID{result['left_marker_id']}, 右 ID{result['right_marker_id']})")
print(f"  间距: {result['marker_spacing_mm']:.1f}mm ({result['spacing_source']})")
print(f"  码边长: {result['marker_size_mm']}mm")
print(f"  重投影误差: {err:.3f}px")

# 4. 更新该基准的 latest 软链
latest_json = os.path.join(REF_DIR, f"reference_{id_str}.json")
if os.path.islink(latest_json) or os.path.exists(latest_json):
    os.remove(latest_json)
os.symlink(os.path.basename(ref_json), latest_json)
print(f"\n✓ 已更新: {latest_json} → {os.path.basename(ref_json)}")
print(f"\n定位时调用: python positioning_tag.py {latest_json}")
