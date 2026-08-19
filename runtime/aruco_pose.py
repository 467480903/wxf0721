"""双 AprilTag 36h11 标记联合 PnP 位姿解算 + 相对位姿输出。

设计见 AGENTS.md。

核心: 两码水平并排同墙 → 朝向自检 → 8 角点联合 PnP (S=100mm + D=600mm 同时参与)。

对外接口:
  save_reference_pose(image_path, output_path)
    → 拍照后解算, 保存基准位姿到 JSON (只做一次)

  compute_offset(image_path, ref_path)
    → 加载基准, 解算当前图, 返回 dt_mm/dyaw_deg/reprojection_error_px

  process_image(image_path, ref_rvec=None, ref_tvec=None)
    → 底层接口, 返回 (result_dict, rvec, tvec)
"""
import os

import cv2
import numpy as np


# ============ 相机内参 (头部摄像头 head_front_rgb, 640×400) ============
# 来源: /data/parameters/sensor/intrinsic_head_front_depth.json
#       /data/parameters/sensor/camera_resolution.json (head_front_rgb)
CAMERA_MATRIX = np.array([
    [310.0705871582, 0.0, 318.5],
    [0.0, 310.0705871582, 203.5],
    [0.0, 0.0, 1.0],
], dtype=np.float64)

# OpenCV 顺序: [k1, k2, p1, p2, k3]
DIST_COEFFS = np.array([
    0.0, 0.0, 0.0, 0.0, 0.0
], dtype=np.float64).reshape(-1, 1)


# ============ 标记参数 ============
# 注: 码边长 / 间距 / 目标 ID 全部由每个基准 JSON 提供, 代码内不再固定。
ARUCO_DICT_TYPE = cv2.aruco.DICT_APRILTAG_36h11


# ============ 阈值 ============
MAX_REPROJ_ERR_PX = 0.5     # 5mm 精度要求
WARN_REPROJ_ERR_PX = 1.0    # 解算可疑
FAIL_REPROJ_ERR_PX = 2.0    # 解算失败


# ============ 检测参数 ============

def make_detector_parameters():
    """构造 AprilTag 检测参数 (标记小, 需调宽)。"""
    p = cv2.aruco.DetectorParameters()
    p.minMarkerPerimeterRate = 0.01
    p.maxMarkerPerimeterRate = 4.0
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.cornerRefinementWinSize = 3
    p.cornerRefinementMaxIterations = 50
    p.cornerRefinementMinAccuracy = 0.001
    p.errorCorrectionRate = 1.0
    p.minOtsuStdDev = 3.0
    p.polygonalApproxAccuracyRate = 0.08
    return p


# ============ 标记检测 ============

def detect_apriltags(image_path, target_ids=None):
    """检测所有 AprilTag 标记, 返回 {id: corners_2d} 和 BGR 原图。

    若给定 target_ids, 则校验这两个目标标记都在画面里, 否则报错退出。
    target_ids=None 时只检测不校验 (返回所有检测到的码)。
    先尝试原图检测, 失败则放大 2× 重试。

    返回:
        markers: dict {int: np.array(4,2)}  检测到的标记角点
        img: BGR 原图
    """
    target_ids = list(target_ids) if target_ids is not None else None
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError(f"无法读取图片: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
    parameters = make_detector_parameters()
    detector = cv2.aruco.ArucoDetector(dictionary, parameters)

    def run(g):
        return detector.detectMarkers(g)

    corners, ids, rejected = run(gray)
    used_scale = 1.0

    if ids is None:
        big = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        corners_b, ids_b, rejected_b = run(big)
        if ids_b is not None:
            corners = [c / 2.0 for c in corners_b]
            ids = ids_b
            rejected = rejected_b
            used_scale = 2.0
            print(f"[提示] 原图未识别, 已在 {used_scale}× 放大图上检测到标记")

    if ids is None:
        n_rejected = 0 if rejected is None else len(rejected)
        raise RuntimeError(
            f"未检测到任何 AprilTag 标记 (rejected 候选 {n_rejected} 个)。"
            f"请确认图片中存在 AprilTag 36h11 字典的标记。")

    ids_flat = ids.flatten()
    print(f"检测到 {len(ids_flat)} 个 AprilTag 36h11 标记: ID = {ids_flat.tolist()}")

    # 收集所有标记
    markers = {}
    for i, mid in enumerate(ids_flat):
        markers[int(mid)] = corners[i][0].astype(np.float64)

    # 检查是否包含两个目标标记
    if target_ids is not None:
        missing = [tid for tid in target_ids if tid not in markers]
        if missing:
            raise RuntimeError(
                f"缺少目标标记 ID={missing}, 检测到的 ID: {ids_flat.tolist()}")

    return markers, img


# ============ 两码连线几何 (像素系, 不依赖 PnP) ============

def _marker_center(corners):
    """单码 4 角点的几何中心 (像素)。"""
    return corners.mean(axis=0)


def points_midline_geometry(p1_px, p2_px):
    """两个像素点 → 中点/倾斜/间距 (纯几何, 跟检测器无关)。

    YOLO 方案直接调用此函数: 把两个黄块 bbox 中心传入即可。
    AprilTag 方案通过 compute_midline_geometry 间接调用。

    参数:
        p1_px, p2_px: 两个点的像素坐标 (x, y), 顺序无关

    返回:
        mid_x_px: 两点中点 x (像素)
        mid_y_px: 两点中点 y (像素)
        tilt_deg: 连线倾斜角 (度, 正=右端低于左端=顺时针倾斜)
        sep_px:   两点像素间距 (用于相似三角形估深度)
    """
    p1 = np.asarray(p1_px, dtype=np.float64).reshape(-1)
    p2 = np.asarray(p2_px, dtype=np.float64).reshape(-1)
    # 按画面左/右排序, cx 小者为左
    if p1[0] > p2[0]:
        c_left, c_right = p2, p1
    else:
        c_left, c_right = p1, p2

    mid_x = (c_left[0] + c_right[0]) / 2.0
    mid_y = (c_left[1] + c_right[1]) / 2.0
    dx = c_right[0] - c_left[0]
    dy = c_right[1] - c_left[1]
    tilt_deg = float(np.degrees(np.arctan2(dy, dx)))
    sep_px = float(np.hypot(dx, dy))

    return float(mid_x), float(mid_y), tilt_deg, sep_px


def compute_midline_geometry(image_path, target_ids):
    """AprilTag 检测 → 两码中心 → 像素几何 (便利封装)。

    target_ids: 本基准的两个码 ID (必填)。
    YOLO 方案不要调这个, 直接调 points_midline_geometry。

    返回 (兼容旧调用, 不含 sep_px):
        mid_x_px, mid_y_px, tilt_deg
    """
    markers, img = detect_apriltags(image_path, target_ids=target_ids)
    c1 = _marker_center(markers[target_ids[0]])
    c2 = _marker_center(markers[target_ids[1]])
    mid_x, mid_y, tilt_deg, _sep = points_midline_geometry(c1, c2)
    return mid_x, mid_y, tilt_deg


# ============ 角点顺序矫正 (用两码连线方向作朝向锚) ============

def _orientation_candidates(half_s):
    """返回两种可能的 3D 角点布局 (以标记中心为原点)。

    half_s: 单码半边长 (mm)。
    布局 1 (normal): aruco corners 顺序 = [TL, TR, BR, BL]
    布局 2 (flipped): 贴倒 180°, corners 顺序 = [BR, BL, TL, TR]
    """
    normal = np.array([
        [0,  half_s,  half_s],   # TL
        [0, -half_s,  half_s],   # TR
        [0, -half_s, -half_s],   # BR
        [0,  half_s, -half_s],   # BL
    ], dtype=np.float64)

    flipped = np.array([
        [0, -half_s, -half_s],   # BR
        [0,  half_s, -half_s],   # BL
        [0,  half_s,  half_s],   # TL
        [0, -half_s,  half_s],   # TR
    ], dtype=np.float64)

    return normal, flipped


def align_corners_by_midline(left_corners, right_corners):
    """用两码中心连线方向矫正角点顺序, 消除单码 180° 朝向歧义。

    原理: 两码共面/同高/同朝向, 两码中心连线在世界系是水平线 (Y 轴)。
          在图像中, 这条连线因相机姿态可能倾斜, 但两码"上边"指向同一方向。
          用连线方向作锚, 把两码角点重排为 (TL, TR, BR, BL) 一致顺序。

    返回:
        left_aligned, right_aligned: (4, 2) 重排后的角点 (TL, TR, BR, BL)
    """
    cL = left_corners.mean(axis=0)
    cR = right_corners.mean(axis=0)
    d = cR - cL                          # 连线方向 (画面左→右)
    d_norm = np.linalg.norm(d)
    if d_norm < 1e-3:
        raise RuntimeError("两码中心重合, 无法确定连线方向")
    d_unit = d / d_norm

    # 垂直方向: 选 y 分量更小 (画面更朝上) 的作为世界 Z+ 在图像中的方向
    n1 = np.array([-d_unit[1], d_unit[0]])   # 逆时针 90°
    n2 = np.array([ d_unit[1], -d_unit[0]])  # 顺时针 90°
    n_up = n1 if n1[1] < n2[1] else n2

    def reorder(corners):
        """重排 4 角点为 (TL, TR, BR, BL)。"""
        proj_up = corners @ n_up
        proj_lr  = corners @ d_unit
        order_up = np.argsort(-proj_up)[:2]    # 上两点
        order_dn = np.argsort(proj_up)[:2]    # 下两点
        tl = order_up[np.argmin(proj_lr[order_up])]
        tr = order_up[np.argmax(proj_lr[order_up])]
        br = order_dn[np.argmax(proj_lr[order_dn])]
        bl = order_dn[np.argmin(proj_lr[order_dn])]
        return corners[[tl, tr, br, bl]]

    return reorder(left_corners), reorder(right_corners)


# ============ 世界坐标构建 ============

def build_world_points(half_d, half_s, orient="normal"):
    """构建 8 个角点的统一世界坐标 (角点已对齐为 TL, TR, BR, BL)。

    half_d: 两码中心距的一半 (mm)。
    half_s: 单码半边长 (mm)。
    世界系: 原点 = 两码中心连线中点, Y+ = 左码方向 (机器人左),
            X+ = 墙面外法线, Z+ = X×Y 竖直向上。
    左码中心 Y = +D/2, 右码中心 Y = -D/2。

    返回:
        all_corners_3d: (8, 3) 世界坐标 (左码 4 + 右码 4)
    """
    normal, flipped = _orientation_candidates(half_s)
    local = {"normal": normal, "flipped": flipped}[orient]

    left_world = local.copy()
    left_world[:, 1] += half_d   # 左码中心 Y = +D/2

    right_world = local.copy()
    right_world[:, 1] -= half_d  # 右码中心 Y = -D/2

    return np.vstack([left_world, right_world])


# ============ 联合 PnP ============

def joint_solve_pnp(all_points_3d, all_points_2d):
    """联合 PnP: 8 角点同时解算 (角点已用连线方向对齐, 无单码歧义)。

    用 IPPE 拿初值 → iterative (LM) 精修。

    返回:
        rvec, tvec: 相机位姿 (世界系)
        reproj_err: 重投影 RMSE (px)
        per_point_err: 每个角点的重投影误差 (8,)
    """
    # 初值: IPPE (适合平面物体)
    try:
        _, rvec, tvec = cv2.solvePnP(
            all_points_3d, all_points_2d, CAMERA_MATRIX, DIST_COEFFS,
            flags=cv2.SOLVEPNP_IPPE)
    except cv2.error:
        # IPPE 失败, 退到 DLS
        _, rvec, tvec = cv2.solvePnP(
            all_points_3d, all_points_2d, CAMERA_MATRIX, DIST_COEFFS,
            flags=cv2.SOLVEPNP_DLS)

    # 精修: iterative (LM)
    success, rvec, tvec = cv2.solvePnP(
        all_points_3d, all_points_2d, CAMERA_MATRIX, DIST_COEFFS,
        rvec=rvec, tvec=tvec, useExtrinsicGuess=True,
        flags=cv2.SOLVEPNP_ITERATIVE)

    if not success:
        raise RuntimeError("联合 PnP 优化失败")

    # 重投影误差
    proj, _ = cv2.projectPoints(all_points_3d, rvec, tvec, CAMERA_MATRIX, DIST_COEFFS)
    proj = proj.reshape(-1, 2)
    per_point_err = np.linalg.norm(proj - all_points_2d, axis=1)
    reproj_err = float(np.sqrt(np.mean(per_point_err ** 2)))

    return rvec, tvec, reproj_err, per_point_err


# ============ 欧拉角分解 ============

def rotation_to_euler_zyx_deg(R):
    """旋转矩阵 → ZYX 欧拉角 (度), 返回 (roll, pitch, yaw)。
    R = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    """
    pitch = np.arctan2(-R[2, 0], np.sqrt(R[2, 1] ** 2 + R[2, 2] ** 2))
    yaw = np.arctan2(R[1, 0], R[0, 0])
    roll = np.arctan2(R[2, 1], R[2, 2])
    return np.array([np.degrees(roll), np.degrees(pitch), np.degrees(yaw)])


# ============ 世界系位姿 ============

def camera_position_in_world(rvec, tvec):
    """相机在世界(墙面)系中的位置 C = -R^T @ tvec"""
    R, _ = cv2.Rodrigues(rvec)
    return -R.T @ tvec


def compute_relative_pose(rvec_ref, tvec_ref, rvec_cur, tvec_cur):
    """当前位姿相对参考位姿的偏移 (在墙面系下)。

    返回:
        delta_C_mm: [dx, dy, dz] 相机在墙面系中的位移 (mm)
        dyaw_deg, dpitch_deg, droll_deg: 旋转差 (度)
    """
    R_ref, _ = cv2.Rodrigues(rvec_ref)
    R_cur, _ = cv2.Rodrigues(rvec_cur)

    C_ref = -R_ref.T @ tvec_ref
    C_cur = -R_cur.T @ tvec_cur
    delta_C = C_cur - C_ref

    delta_R = R_cur.T @ R_ref
    droll, dpitch, dyaw = rotation_to_euler_zyx_deg(delta_R)

    return delta_C.flatten(), float(dyaw), float(dpitch), float(droll)


# ============ 深度估算 (两种方法, 检测器无关) ============
# depth_method 写入基准 JSON, 由检测器能力决定:
#   "pnp"     — AprilTag 方案, 用 8 角点联合 PnP 算位姿差 (精度高, 需角点)
#   "spacing" — YOLO 方案, 用 fx×D/sep_px 相似三角形估深度 (只需两点中心)

def depth_offset_mm(depth_method, spacing_mm,
                    ref_tvec=None, ref_sep_px=None,
                    cur_tvec=None, cur_sep_px=None):
    """计算当前相对基准的前后位移 (mm, >0 表示当前更靠前/近)。

    depth_method="pnp":
        用 PnP 解出的相机系 tvec[2] (光轴深度) 之差。
        需提供 ref_tvec, cur_tvec。
    depth_method="spacing":
        用相似三角形: depth = fx × D / sep_px。
        需提供 ref_sep_px, cur_sep_px, fx 由 CAMERA_MATRIX 读取。
        返回 (depth_ref - depth_cur), >0 表示当前更近。
    """
    if depth_method == "pnp":
        if ref_tvec is None or cur_tvec is None:
            raise RuntimeError("pnp 深度法需要 ref_tvec/cur_tvec")
        depth_ref = float(np.asarray(ref_tvec).reshape(-1)[2])
        depth_cur = float(np.asarray(cur_tvec).reshape(-1)[2])
        return depth_ref - depth_cur     # >0: 当前更近 (tvec.z 更小)
    elif depth_method == "spacing":
        if ref_sep_px is None or cur_sep_px is None:
            raise RuntimeError("spacing 深度法需要 ref_sep_px/cur_sep_px")
        fx = CAMERA_MATRIX[0, 0]
        depth_ref = fx * spacing_mm / ref_sep_px
        depth_cur = fx * spacing_mm / cur_sep_px
        return depth_ref - depth_cur     # >0: 当前更近 (sep_px 更大)
    else:
        raise RuntimeError(f"未知 depth_method: {depth_method}")


# ============ 可视化 ============

def visualize(image_path, all_points_2d, all_points_3d, rvec, tvec,
              output_path, markers, left_id, right_id,
              left_orient, right_orient):
    """可视化: 两码边框 + 角点 + 重投影 + 坐标轴。"""
    img = cv2.imread(image_path)
    if img is None:
        print(f"[警告] 无法读取 {image_path}, 跳过可视化")
        return

    result = img.copy()

    # 左码 4 角点 (红, 实心)
    left_pts = np.int32(all_points_2d[:4])
    cv2.polylines(result, [left_pts], True, (0, 0, 255), 2)
    # 右码 4 角点 (青, 实心)
    right_pts = np.int32(all_points_2d[4:])
    cv2.polylines(result, [right_pts], True, (255, 255, 0), 2)

    # 所有角点标注 (红=左码, 青=右码)
    for i in range(4):
        p = tuple(np.int32(all_points_2d[i]))
        cv2.circle(result, p, 4, (0, 0, 255), -1)
        cv2.putText(result, f"L{i}", (p[0] + 6, p[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
    for i in range(4, 8):
        p = tuple(np.int32(all_points_2d[i]))
        cv2.circle(result, p, 4, (255, 255, 0), -1)
        cv2.putText(result, f"R{i - 4}", (p[0] + 6, p[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)

    # 重投影点 (蓝)
    proj, _ = cv2.projectPoints(all_points_3d, rvec, tvec, CAMERA_MATRIX, DIST_COEFFS)
    for p in proj.reshape(-1, 2):
        cv2.circle(result, tuple(np.int32(p)), 2, (255, 0, 0), -1)

    # 坐标轴: X 红 / Y 绿 / Z 蓝 (长度 100mm)
    axis_3d = np.array([[0, 0, 0], [100, 0, 0], [0, 100, 0], [0, 0, 100]],
                       dtype=np.float64)
    axis_2d, _ = cv2.projectPoints(axis_3d, rvec, tvec, CAMERA_MATRIX, DIST_COEFFS)
    axis_2d = axis_2d.reshape(-1, 2).astype(int)
    cv2.arrowedLine(result, tuple(axis_2d[0]), tuple(axis_2d[1]), (0, 0, 255), 2)  # X 红
    cv2.arrowedLine(result, tuple(axis_2d[0]), tuple(axis_2d[2]), (0, 255, 0), 2)  # Y 绿
    cv2.arrowedLine(result, tuple(axis_2d[0]), tuple(axis_2d[3]), (255, 0, 0), 2)  # Z 蓝
    cv2.putText(result, "X", tuple(axis_2d[1] + (5, -5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    cv2.putText(result, "Y", tuple(axis_2d[2] + (5, -5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(result, "Z", tuple(axis_2d[3] + (5, -5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)

    # 图例
    cv2.putText(result,
                f"red=left(ID{left_id},{left_orient}) cyan=right(ID{right_id},{right_orient}) blue=reproject",
                (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    cv2.imwrite(output_path, result)
    print(f"可视化已保存: {output_path}")


# ============ 主处理流程 ============

def process_image(image_path, target_ids, spacing_mm, marker_size_mm,
                  ref_rvec=None, ref_tvec=None):
    """处理单张图片, 返回 (result_dict, rvec, tvec)。

    target_ids/spacing_mm/marker_size_mm: 本基准的两个码 ID、间距、码边长 (必填)。
    若提供 ref_rvec/ref_tvec, 计算相对偏移; 否则返回全 0 偏移。
    """
    half_d = spacing_mm / 2.0
    half_s = marker_size_mm / 2.0

    print(f"\n=== 处理图片: {image_path} ===")
    print(f"基准: ids={target_ids}, 间距={spacing_mm}mm, 码边长={marker_size_mm}mm")

    # 1. 检测两个标记
    markers, img = detect_apriltags(image_path, target_ids=target_ids)
    left_corners = markers[target_ids[0]]
    right_corners = markers[target_ids[1]]

    # 按像素 x 判断左右 (画面左 = target_ids[0], 画面右 = target_ids[1])
    lcx = left_corners[:, 0].mean()
    rcx = right_corners[:, 0].mean()
    if lcx > rcx:
        # 像素 x 更大 → 画面右, 交换
        left_corners, right_corners = right_corners, left_corners
        left_id, right_id = target_ids[1], target_ids[0]
    else:
        left_id, right_id = target_ids[0], target_ids[1]

    print(f"\n画面左 = ID{left_id} (中心 x={lcx:.0f}), 画面右 = ID{right_id} (中心 x={rcx:.0f})")

    # 2. 角点顺序矫正: 用两码连线方向作朝向锚, 消除单码 180° 歧义
    print("\n--- 角点顺序矫正 (连线方向锚定) ---")
    left_aligned, right_aligned = align_corners_by_midline(left_corners, right_corners)
    left_orient = right_orient = "normal"  # 已物理对齐, 统一用 normal 布局

    # 3. 构建世界坐标 + 联合 PnP (8 角点同时解算)
    all_3d = build_world_points(half_d, half_s, orient="normal")
    all_2d = np.vstack([left_aligned, right_aligned])

    rvec, tvec, reproj_err, per_point_err = joint_solve_pnp(all_3d, all_2d)

    print(f"\n世界坐标: 左码 Y=+{half_d:.0f}mm, 右码 Y=-{half_d:.0f}mm, 间距={spacing_mm:.0f}mm")
    print(f"8 角点像素坐标 (对齐后):")
    for i in range(8):
        label = f"L{i}" if i < 4 else f"R{i - 4}"
        print(f"  {label} = ({all_2d[i, 0]:.2f}, {all_2d[i, 1]:.2f})")
    print(f"\n联合 PnP 结果:")
    print(f"  rvec = {rvec.flatten()}")
    print(f"  tvec = {tvec.flatten()}  (mm)")
    print(f"  重投影误差 = {reproj_err:.4f} px")
    for i, e in enumerate(per_point_err):
        label = f"L{i}" if i < 4 else f"R{i - 4}"
        print(f"    {label}: 误差={e:.4f}px")
    if reproj_err > FAIL_REPROJ_ERR_PX:
        print(f"  [警告] 重投影误差 > {FAIL_REPROJ_ERR_PX}px, 解算失败")
    elif reproj_err > WARN_REPROJ_ERR_PX:
        print(f"  [提示] 重投影误差 > {WARN_REPROJ_ERR_PX}px, 解算可疑")
    elif reproj_err > MAX_REPROJ_ERR_PX:
        print(f"  [注意] 重投影误差 > {MAX_REPROJ_ERR_PX}px, 5mm 精度可能不足")
    else:
        print(f"  ✓ 重投影误差 ≤ {MAX_REPROJ_ERR_PX}px, 精度达标")

    # 5. 相机在墙面系位置 + 姿态
    C = camera_position_in_world(rvec, tvec)
    R, _ = cv2.Rodrigues(rvec)
    roll, pitch, yaw = rotation_to_euler_zyx_deg(R)
    print(f"  相机在墙面系位置 C = [{C[0, 0]:.1f}, {C[1, 0]:.1f}, {C[2, 0]:.1f}] mm")
    print(f"  相机姿态 (roll, pitch, yaw) = [{roll:.2f}, {pitch:.2f}, {yaw:.2f}]°")

    # 6. 相对位姿
    if ref_rvec is not None and ref_tvec is not None:
        delta_C, dyaw, dpitch, droll = compute_relative_pose(
            ref_rvec, ref_tvec, rvec, tvec)
        print(f"\n--- 相对参考位姿 ---")
        print(f"  位移: dx={delta_C[0]:.2f} mm, dy={delta_C[1]:.2f} mm, dz={delta_C[2]:.2f} mm")
        print(f"  旋转: dyaw={dyaw:.3f}°, dpitch={dpitch:.3f}°, droll={droll:.3f}°")
    else:
        delta_C = np.zeros(3)
        dyaw = dpitch = droll = 0.0
        print(f"\n--- (无参考图, 默认偏移全 0) ---")

    # 7. 可视化
    output_path = os.path.splitext(image_path)[0] + "_corrected.jpg"
    visualize(image_path, all_2d, all_3d, rvec, tvec, output_path,
              markers, left_id, right_id, left_orient, right_orient)

    # 8. 组装结果
    result = {
        "left_marker_id": left_id,
        "right_marker_id": right_id,
        "target_ids": list(target_ids),
        "left_orientation": left_orient,
        "right_orientation": right_orient,
        "marker_size_mm": marker_size_mm,
        "marker_spacing_mm": spacing_mm,
        "dict": "DICT_APRILTAG_36h11",
        "all_marker_ids": sorted(markers.keys()),
        "tvec_current": tvec.flatten().tolist(),
        "rvec_current": rvec.flatten().tolist(),
        "camera_position_world_mm": C.flatten().tolist(),
        "dt_mm": delta_C.tolist(),
        "dyaw_deg": dyaw,
        "dpitch_deg": dpitch,
        "droll_deg": droll,
        "reprojection_error_px": reproj_err,
        "per_point_error_px": per_point_err.tolist(),
    }
    if ref_rvec is not None:
        result["tvec_ref"] = ref_tvec.flatten().tolist()
        result["rvec_ref"] = ref_rvec.flatten().tolist()

    return result, rvec, tvec


# ============ 对外接口 ============

def save_reference_pose(image_path, output_path, target_ids, spacing_mm,
                        marker_size_mm, name=None, depth_method="pnp"):
    """拍照 → 解算 → 保存基准位姿到 JSON 文件。

    参数:
        image_path: str  基准图片路径
        output_path: str  保存 JSON 的路径
        target_ids: list  本基准的两个码 ID (必填)
        spacing_mm: float  两码中心距 (必填)
        marker_size_mm: float  单码边长 (必填)
        name: str  基准名称 (可选, 写入 JSON 便于辨识)
        depth_method: str  深度算法 "pnp"(AprilTag, 默认) 或 "spacing"(YOLO)

    返回:
        result: dict  包含 tvec/rvec/reprojection_error_px 等
    """
    import json

    result, rvec, tvec = process_image(
        image_path, target_ids=target_ids,
        spacing_mm=spacing_mm, marker_size_mm=marker_size_mm)

    # 两码连线几何 (像素系, 含 sep_px, 检测器无关; spacing 法深度依赖此字段)
    markers, _ = detect_apriltags(image_path, target_ids=target_ids)
    c1 = _marker_center(markers[target_ids[0]])
    c2 = _marker_center(markers[target_ids[1]])
    mid_x_ref, mid_y_ref, tilt_ref, sep_px_ref = points_midline_geometry(c1, c2)

    ref_data = {
        "name": name,
        "depth_method": depth_method,
        "rvec": rvec.flatten().tolist(),
        "tvec": tvec.flatten().tolist(),
        "left_marker_id": result["left_marker_id"],
        "right_marker_id": result["right_marker_id"],
        "target_ids": list(result["target_ids"]),
        "left_orientation": result["left_orientation"],
        "right_orientation": result["right_orientation"],
        "reprojection_error_px": result["reprojection_error_px"],
        "marker_size_mm": result["marker_size_mm"],
        "marker_spacing_mm": result["marker_spacing_mm"],
        "dict": result["dict"],
        "mid_x_px_ref": mid_x_ref,
        "mid_y_px_ref": mid_y_ref,
        "tilt_deg_ref": tilt_ref,
        "sep_px_ref": sep_px_ref,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ref_data, f, ensure_ascii=False, indent=2)
    print(f"✓ 基准位姿已保存: {output_path}")
    print(f"  重投影误差 = {ref_data['reprojection_error_px']:.4f} px")
    return result


def compute_offset(image_path, ref_path):
    """加载基准位姿 → 解算当前图 → 返回相对偏移。

    参数:
        image_path: str  当前图片路径
        ref_path: str  基准位姿 JSON 文件路径 (由 save_reference_pose 生成)

    返回:
        result: dict  包含 dt_mm / dyaw_deg / reprojection_error_px 等
    """
    import json

    with open(ref_path, "r", encoding="utf-8") as f:
        ref_data = json.load(f)

    ref_rvec = np.array(ref_data["rvec"], dtype=np.float64).reshape(-1, 1)
    ref_tvec = np.array(ref_data["tvec"], dtype=np.float64).reshape(-1, 1)

    # 从基准 JSON 读取本基准的 ids/间距/码边长 (缺字段直接报错, 不回退默认)
    target_ids = ref_data.get("target_ids")
    if target_ids is None:
        if "left_marker_id" in ref_data and "right_marker_id" in ref_data:
            target_ids = [ref_data["left_marker_id"], ref_data["right_marker_id"]]
        else:
            raise RuntimeError(f"基准 JSON 缺少 target_ids: {ref_path}")
    spacing_mm = ref_data.get("marker_spacing_mm")
    marker_size_mm = ref_data.get("marker_size_mm")
    if spacing_mm is None or marker_size_mm is None:
        raise RuntimeError(f"基准 JSON 缺少 marker_spacing_mm/marker_size_mm: {ref_path}")

    print(f"使用基准: {ref_path}")
    if ref_data.get("name"):
        print(f"  名称={ref_data['name']}")
    print(f"  ids={target_ids}, 间距={spacing_mm}mm, 码边长={marker_size_mm}mm")

    result, _, _ = process_image(
        image_path, target_ids=target_ids, spacing_mm=spacing_mm,
        marker_size_mm=marker_size_mm, ref_rvec=ref_rvec, ref_tvec=ref_tvec)

    # 两码连线几何偏差 (像素系, 不依赖 PnP, 检测器无关)
    # YOLO 方案: 这里换成 YOLO 检测两点后调 points_midline_geometry 即可
    markers, _ = detect_apriltags(image_path, target_ids=target_ids)
    c1 = _marker_center(markers[target_ids[0]])
    c2 = _marker_center(markers[target_ids[1]])
    mid_x_cur, mid_y_cur, tilt_cur, sep_px_cur = points_midline_geometry(c1, c2)
    mid_x_ref = ref_data.get("mid_x_px_ref")
    mid_y_ref = ref_data.get("mid_y_px_ref")
    tilt_ref = ref_data.get("tilt_deg_ref")
    sep_px_ref = ref_data.get("sep_px_ref")
    if mid_x_ref is None or mid_y_ref is None or tilt_ref is None:
        print("[警告] 基准文件缺少像素几何字段, 请重新运行 set_reference.py 生成新基准")
        mid_x_ref = mid_x_cur
        mid_y_ref = mid_y_cur
        tilt_ref = tilt_cur
    if sep_px_ref is None:
        sep_px_ref = sep_px_cur

    # 深度算法选择 (depth_method 缺省视为 "pnp", 兼容旧基准)
    depth_method = ref_data.get("depth_method", "pnp")
    cur_tvec = np.array(result["tvec_current"], dtype=np.float64).reshape(-1, 1)
    depth_off_mm = depth_offset_mm(
        depth_method, spacing_mm,
        ref_tvec=ref_tvec, ref_sep_px=sep_px_ref,
        cur_tvec=cur_tvec, cur_sep_px=sep_px_cur)
    # 覆盖 PnP 深度结果: dt_mm[0] 改为所选算法的前后位移
    dt_mm = np.array(result["dt_mm"], dtype=np.float64)
    dt_mm[0] = depth_off_mm
    result["dt_mm"] = dt_mm.tolist()

    result["depth_method"] = depth_method
    result["mid_x_px_cur"] = mid_x_cur
    result["mid_y_px_cur"] = mid_y_cur
    result["tilt_deg_cur"] = tilt_cur
    result["sep_px_cur"] = sep_px_cur
    result["d_mid_x_px"] = mid_x_cur - mid_x_ref       # >0: 当前两码中心偏右 (相机比基准左移)
    result["d_mid_y_px"] = mid_y_cur - mid_y_ref       # >0: 当前两码中心偏下 (相机比基准上移)
    result["d_tilt_deg"] = tilt_cur - tilt_ref         # >0: 两码连线更顺时针倾斜 (相机左转或 roll 变化)

    print(f"\n--- 两码连线几何 (像素系, 检测器无关) ---")
    print(f"  基准: mid_x={mid_x_ref:.1f}px, mid_y={mid_y_ref:.1f}px, tilt={tilt_ref:.2f}°, sep={sep_px_ref:.1f}px")
    print(f"  当前: mid_x={mid_x_cur:.1f}px, mid_y={mid_y_cur:.1f}px, tilt={tilt_cur:.2f}°, sep={sep_px_cur:.1f}px")
    print(f"  偏差: d_mid_x={result['d_mid_x_px']:+.1f}px, "
          f"d_mid_y={result['d_mid_y_px']:+.1f}px, "
          f"d_tilt={result['d_tilt_deg']:+.2f}°")
    print(f"  深度法: {depth_method}, 前后位移={depth_off_mm:+.1f}mm (>0=当前更近)")

    return result



