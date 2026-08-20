#!/usr/bin/env python3
"""
yolo_server.py
YOLO 检测服务：预加载模型，监听 9998 端口，接收客户端请求执行检测并返回结果。
"""

import cv2
import numpy as np
import os
import sys
import json
import base64
import socket
import time
import traceback

from ultralytics import YOLO

# ===================== 配置 =====================
HOST = '0.0.0.0'
PORT = 9998
DEPTH_SHAPE = (400, 640)
DEPTH_OFFSET = 12
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = WORK_DIR
# 检测输出目录：保存每次请求的原图与结果图片
OUTPUT_DIR = os.path.join(WORK_DIR, 'detect_output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 预加载模型
PRELOAD_MODELS = ['holes.pt', 'shelf.pt', 'place_product.pt']

# ===================== 深度图工具函数 =====================

def load_depth_from_raw(raw_path: str, shape: tuple = None) -> np.ndarray | None:
    if not os.path.exists(raw_path):
        print(f"深度文件不存在: {raw_path}")
        return None
    raw_bytes = open(raw_path, "rb").read()
    total = len(raw_bytes)
    n_pixels = total // 2
    if shape is not None:
        H, W = shape
        if n_pixels != H * W:
            return _auto_reshape(raw_bytes)
        depth = np.frombuffer(raw_bytes, dtype=np.uint16).reshape((H, W))
    else:
        depth = _auto_reshape(raw_bytes)
    return depth


def _auto_reshape(raw_bytes: bytes) -> np.ndarray | None:
    n_pixels = len(raw_bytes) // 2
    common_resolutions = [
        (400, 640), (480, 640), (480, 848), (360, 640),
        (720, 1280), (240, 424), (400, 848), (720, 960),
    ]
    for H, W in common_resolutions:
        if H * W == n_pixels:
            return np.frombuffer(raw_bytes, dtype=np.uint16).reshape((H, W))
    side = int(np.sqrt(n_pixels))
    return np.frombuffer(raw_bytes, dtype=np.uint16).reshape((side, side))


def get_depth_at_pixel(depth_raw: np.ndarray, x: int, y: int, search_radius: int = 10) -> float:
    h, w = depth_raw.shape[:2]
    if 0 <= x < w and 0 <= y < h:
        val = depth_raw[y, x]
        if val > 0:
            return float(val)
    for r in range(1, search_radius + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if abs(dx) + abs(dy) != r:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    val = depth_raw[ny, nx]
                    if val > 0:
                        return float(val)
    return -1.0


def get_average_depth(depth_raw: np.ndarray, x: int, y: int, radius: int = 5) -> float:
    h, w = depth_raw.shape[:2]
    depths = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    val = depth_raw[ny, nx]
                    if val > 0:
                        depths.append(val)
    if len(depths) == 0:
        return -1.0
    return float(np.mean(depths))


# ===================== YOLO 检测逻辑（基于 demo.py） =====================

def label_color(label):
    return {'a': (255, 0, 0), 'b': (0, 255, 0), 'c': (0, 0, 255), 'd': (0, 165, 255)}.get(label, (128, 128, 128))


def yolo_detect(model: YOLO, model_name: str, image_path: str, depth_raw_path: str, output_dir: str):
    """YOLO 检测，返回标准格式结果，所有输出文件保存到 output_dir"""
    results = model(image_path)
    img = results[0].orig_img.copy()
    img_h, img_w = img.shape[:2]
    img_center_x = img_w / 2.0
    boxes = results[0].boxes
    names = results[0].names

    def collect_boxes_by_class(target_label: str):
        class_id = None
        for cid, cname in names.items():
            if cname == target_label:
                class_id = cid
                break
        collected = []
        if class_id is None:
            return collected
        for box in boxes:
            cls_id = int(box.cls[0])
            if cls_id != class_id:
                continue
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            collected.append((cx, cy, x1, y1, x2, y2, conf))
        collected.sort(key=lambda x: x[6], reverse=True)
        return collected

    boxes_a = collect_boxes_by_class('a')
    boxes_b = collect_boxes_by_class('b')
    boxes_c = collect_boxes_by_class('c')
    boxes_d = collect_boxes_by_class('d')

    # 策略选择两个画线点
    pt1 = pt2 = None

    if len(boxes_a) >= 1 and len(boxes_b) >= 1:
        pt1, pt2 = boxes_a[0], boxes_b[0]
    elif len(boxes_b) >= 2:
        pt1, pt2 = boxes_b[0], boxes_b[1]
    elif len(boxes_a) >= 2:
        pt1, pt2 = boxes_a[0], boxes_a[1]
    elif len(boxes_c) >= 1 and len(boxes_d) >= 1:
        pt1, pt2 = boxes_c[0], boxes_d[0]
    elif len(boxes_c) >= 2:
        pt1, pt2 = boxes_c[0], boxes_c[1]
    elif len(boxes_d) >= 2:
        pt1, pt2 = boxes_d[0], boxes_d[1]

    if pt1 is None or pt2 is None:
        return {
            'model_path': model_name,
            'image_path': image_path,
            'depth_raw_path': depth_raw_path,
            'depth_offset_px': DEPTH_OFFSET,
            'depth_shape': list(DEPTH_SHAPE),
            'image_size': {'height': img_h, 'width': img_w},
            'detection': None,
            'offset': None,
            'slope': None,
            'depth': None,
            'output_files': [],
            'error': '无法满足任何画线条件',
        }

    cx1, cy1, x1_1, y1_1, x1_2, y1_2, conf1 = pt1
    cx2, cy2, x2_1, y2_1, x2_2, y2_2, conf2 = pt2

    def get_label(pt):
        if pt in boxes_a: return 'a'
        if pt in boxes_b: return 'b'
        if pt in boxes_c: return 'c'
        if pt in boxes_d: return 'd'
        return '?'

    label1 = get_label(pt1)
    label2 = get_label(pt2)
    color1 = label_color(label1)
    color2 = label_color(label2)

    line_center_x = (cx1 + cx2) / 2
    line_center_y = (cy1 + cy2) / 2
    h_offset = line_center_x - img_center_x
    direction = '偏右' if h_offset > 0 else '偏左' if h_offset < 0 else '居中'

    dx = cx2 - cx1
    dy = cy2 - cy1
    angle_rad = float(np.arctan2(dy, dx))
    slope_val = float(dy / dx) if abs(dx) >= 1e-6 else float('inf')

    # —— 画检测框 ——
    cv2.rectangle(img, (int(x1_1), int(y1_1)), (int(x1_2), int(y1_2)), color1, 2)
    cv2.rectangle(img, (int(x2_1), int(y2_1)), (int(x2_2), int(y2_2)), color2, 2)
    cv2.putText(img, f'{label1} {conf1:.2f}', (int(x1_1), int(y1_1) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color1, 2)
    cv2.putText(img, f'{label2} {conf2:.2f}', (int(x2_1), int(y2_1) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color2, 2)

    # —— 画中心连线（红色） ——
    cv2.line(img, (int(cx1), int(cy1)), (int(cx2), int(cy2)), (0, 0, 255), 2)

    # —— 线的中心点 ——
    cv2.circle(img, (int(line_center_x), int(line_center_y)), 8, (255, 0, 0), -1)
    cv2.putText(img, f'({line_center_x:.1f}, {line_center_y:.1f})',
                (int(line_center_x) + 10, int(line_center_y) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

    # —— 画两个中心点 ——
    cv2.circle(img, (int(cx1), int(cy1)), 5, (0, 255, 255), -1)
    cv2.circle(img, (int(cx2), int(cy2)), 5, (0, 255, 255), -1)

    # —— 画图像中线 ——
    cv2.line(img, (int(img_center_x), 0), (int(img_center_x), img_h), (0, 255, 0), 1)
    cv2.line(img, (int(img_center_x), int(line_center_y)),
             (int(line_center_x), int(line_center_y)), (255, 255, 0), 2)
    cv2.circle(img, (int(img_center_x), int(line_center_y)), 5, (0, 255, 0), -1)
    cv2.putText(img, f'h_offset: {h_offset:.1f}px',
                (int(min(img_center_x, line_center_x)) + 5, int(line_center_y) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    # —— 斜率标注 ——
    slope_text = f'slope: inf' if slope_val == float('inf') else f'slope: {slope_val:.2f}'
    cv2.putText(img, slope_text,
                (max(int((cx1 + cx2) / 2) - 80, 10), max(int((cy1 + cy2) / 2) - 15, 20)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    output_files = []

    # 保存 result.jpg (YOLO 原始结果)
    results[0].save(filename=os.path.join(output_dir, 'result.jpg'))
    output_files.append('result.jpg')

    # 保存 yolo_depth_rgb.jpg
    out_rgb = os.path.join(output_dir, 'yolo_depth_rgb.jpg')
    cv2.imwrite(out_rgb, img)
    output_files.append('yolo_depth_rgb.jpg')

    # 深度采样
    depth_result = None
    depth_raw = load_depth_from_raw(depth_raw_path, DEPTH_SHAPE)

    if depth_raw is not None:
        sample_a_x = int(cx1)
        sample_a_y = int(cy1) + DEPTH_OFFSET
        sample_b_x = int(cx2)
        sample_b_y = int(cy2) + DEPTH_OFFSET
        sample_center_x = int((cx1 + cx2) / 2)
        sample_center_y = int((cy1 + cy2) / 2)

        depth_a_center = get_depth_at_pixel(depth_raw, int(cx1), int(cy1))
        depth_a_left = get_average_depth(depth_raw, sample_a_x, sample_a_y, radius=2)
        depth_b_center = get_depth_at_pixel(depth_raw, int(cx2), int(cy2))
        depth_b_right = get_average_depth(depth_raw, sample_b_x, sample_b_y, radius=2)
        depth_center = get_average_depth(depth_raw, sample_center_x, sample_center_y, radius=5)

        depth_result = {
            'point1_center_mm': depth_a_center,
            'point1_left_offset_mm': depth_a_left,
            'point1_left_sample_pixel': [sample_a_x, sample_a_y],
            'point2_center_mm': depth_b_center,
            'point2_right_offset_mm': depth_b_right,
            'point2_right_sample_pixel': [sample_b_x, sample_b_y],
            'center_mm': depth_center,
            'center_sample_pixel': [sample_center_x, sample_center_y],
        }

        # 生成伪彩色深度图
        valid_mask = depth_raw > 0
        if np.any(valid_mask):
            min_d = depth_raw[valid_mask].min()
            max_d = depth_raw[valid_mask].max()
            if max_d > min_d:
                normalized = ((depth_raw - min_d) / (max_d - min_d) * 255).astype(np.uint8)
            else:
                normalized = np.zeros_like(depth_raw, dtype=np.uint8)
        else:
            normalized = np.zeros_like(depth_raw, dtype=np.uint8)
        depth_colored = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)

        # 保存深度图
        cv2.imwrite(os.path.join(output_dir, 'yolo_depth_depth.jpg'), depth_colored)
        output_files.append('yolo_depth_depth.jpg')

        # 在 RGB 图上标注深度采样点
        if 0 <= sample_a_x < img_w and 0 <= sample_a_y < img_h:
            cv2.circle(img, (sample_a_x, sample_a_y), 5, (255, 0, 255), -1)
            cv2.putText(img, f'L{DEPTH_OFFSET}:{depth_a_left:.0f}mm',
                        (sample_a_x - 65, sample_a_y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
            cv2.arrowedLine(img, (int(cx1), int(cy1)),
                            (sample_a_x, sample_a_y), (255, 0, 255), 1, tipLength=0.3)

        if 0 <= sample_b_x < img_w and 0 <= sample_b_y < img_h:
            cv2.circle(img, (sample_b_x, sample_b_y), 5, (255, 255, 0), -1)
            cv2.putText(img, f'R{DEPTH_OFFSET}:{depth_b_right:.0f}mm',
                        (sample_b_x + 5, sample_b_y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 2)
            cv2.arrowedLine(img, (int(cx2), int(cy2)),
                            (sample_b_x, sample_b_y), (255, 255, 0), 1, tipLength=0.3)

        if 0 <= sample_center_x < img_w and 0 <= sample_center_y < img_h:
            cv2.circle(img, (sample_center_x, sample_center_y), 6, (0, 255, 0), -1)
            cv2.putText(img, f'Center:{depth_center:.0f}mm',
                        (sample_center_x + 10, sample_center_y + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        cv2.imwrite(os.path.join(output_dir, 'yolo_depth_rgb_with_depth.jpg'), img)
        output_files.append('yolo_depth_rgb_with_depth.jpg')

        # 深度图上标注采样点
        depth_marked = depth_colored.copy()
        if 0 <= sample_a_x < img_w and 0 <= sample_a_y < img_h:
            cv2.circle(depth_marked, (sample_a_x, sample_a_y), 5, (255, 0, 255), -1)
            cv2.putText(depth_marked, f'{label1}_L{DEPTH_OFFSET}:{depth_a_left:.0f}mm',
                        (sample_a_x - 75, sample_a_y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
        if 0 <= sample_b_x < img_w and 0 <= sample_b_y < img_h:
            cv2.circle(depth_marked, (sample_b_x, sample_b_y), 5, (255, 255, 0), -1)
            cv2.putText(depth_marked, f'{label2}_R{DEPTH_OFFSET}:{depth_b_right:.0f}mm',
                        (sample_b_x + 5, sample_b_y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 2)
        cv2.circle(depth_marked, (int(cx1), int(cy1)), 5, (0, 255, 255), -1)
        cv2.circle(depth_marked, (int(cx2), int(cy2)), 5, (0, 255, 255), -1)
        if 0 <= sample_center_x < img_w and 0 <= sample_center_y < img_h:
            cv2.circle(depth_marked, (sample_center_x, sample_center_y), 6, (0, 255, 0), -1)
            cv2.putText(depth_marked, f'Center:{depth_center:.0f}mm',
                        (sample_center_x + 10, sample_center_y + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        cv2.imwrite(os.path.join(output_dir, 'yolo_depth_depth_marked.jpg'), depth_marked)
        output_files.append('yolo_depth_depth_marked.jpg')

    return {
        'model_path': model_name,
        'image_path': image_path,
        'depth_raw_path': depth_raw_path,
        'depth_offset_px': DEPTH_OFFSET,
        'depth_shape': list(DEPTH_SHAPE),
        'image_size': {'height': img_h, 'width': img_w},
        'detection': {
            'point1': {'label': label1, 'center': [round(float(cx1), 2), round(float(cy1), 2)]},
            'point2': {'label': label2, 'center': [round(float(cx2), 2), round(float(cy2), 2)]},
        },
        'offset': {
            'line_center': [round(float(line_center_x), 2), round(float(line_center_y), 2)],
            'image_center_x': float(img_center_x),
            'horizontal_offset_px': round(float(h_offset), 2),
            'direction': direction,
        },
        'slope': {
            'slope': round(slope_val, 4),
            'angle_rad': round(angle_rad, 4),
            'angle_deg': round(float(np.degrees(angle_rad)), 1),
        },
        'depth': depth_result,
        'output_files': output_files,
    }


# ===================== 协议：\n 结尾的 JSON =====================

def recv_msg(conn: socket.socket) -> dict:
    """接收以 \n 结尾的 JSON 报文，逐块读取直到遇到换行符"""
    buf = b''
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            raise ConnectionError("连接断开")
        buf += chunk
        if buf.endswith(b'\n'):
            break
    raw = buf[:-1]  # 去掉末尾 \n
    # 保存收到的报文到 receive.json
    with open(os.path.join(WORK_DIR, 'receive.json'), 'wb') as f:
        f.write(raw)
    return json.loads(raw.decode('utf-8'))


def send_msg(conn: socket.socket, obj: dict):
    raw = json.dumps(obj, ensure_ascii=False).encode('utf-8') + b'\n'
    conn.sendall(raw)


# ===================== 处理单次请求 =====================

def handle_request(req: dict, models: dict) -> dict:
    cmd = req.get('cmd') or req.get('command')
    if cmd != 'detect':
        return {'success': False, 'error': f'未知命令: {cmd}'}

    model_name = req.get('model', 'holes.pt')
    if model_name not in models:
        return {'success': False, 'error': f'模型未加载: {model_name}'}

    rgb_b64 = req.get('rgb')
    depth_b64 = req.get('depth')

    if not rgb_b64:
        return {'success': False, 'error': '缺少 rgb 字段'}

    # 每次请求创建独立子目录，保存原图与结果图片
    output_dir = os.path.join(OUTPUT_DIR, time.strftime('%Y%m%d_%H%M%S'))
    os.makedirs(output_dir, exist_ok=True)

    # 保存 rgb.png（原图）
    rgb_path = os.path.join(output_dir, 'rgb.png')
    try:
        rgb_bytes = base64.b64decode(rgb_b64)
        with open(rgb_path, 'wb') as f:
            f.write(rgb_bytes)
    except Exception as e:
        return {'success': False, 'error': f'rgb base64 解码失败: {e}'}

    # 保存 depth.raw（原始深度数据）
    depth_raw_path = os.path.join(output_dir, 'depth.raw')
    if depth_b64:
        try:
            depth_bytes = base64.b64decode(depth_b64)
            with open(depth_raw_path, 'wb') as f:
                f.write(depth_bytes)
        except Exception as e:
            return {'success': False, 'error': f'depth base64 解码失败: {e}'}

    # 执行检测，结果图片保存到 output_dir
    model = models[model_name]
    try:
        result = yolo_detect(model, model_name, rgb_path, depth_raw_path, output_dir)
    except Exception as e:
        traceback.print_exc()
        return {'success': False, 'error': f'检测失败: {e}'}

    return result


# ===================== 主服务 =====================

def main():
    print("=" * 60)
    print("YOLO 检测服务启动")
    print("=" * 60)

    # 预加载模型
    models = {}
    for name in PRELOAD_MODELS:
        path = os.path.join(MODELS_DIR, name)
        if not os.path.exists(path):
            print(f"模型文件不存在: {path}，跳过")
            continue
        print(f"加载模型: {name} ...", end=' ', flush=True)
        t0 = time.time()
        models[name] = YOLO(path)
        print(f"耗时 {time.time() - t0:.2f}s")

    if not models:
        print("没有可用模型，退出")
        return

    print(f"已加载模型: {list(models.keys())}")
    print(f"监听 {HOST}:{PORT}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)

    print("等待客户端连接...")

    while True:
        conn, addr = server.accept()
        print(f"\n客户端连接: {addr}")
        try:
            req = recv_msg(conn)
            print(f"请求: cmd={req.get('cmd')}, model={req.get('model')}")
            resp = handle_request(req, models)
            send_msg(conn, resp)
            print(f"响应: success={resp.get('success')}")
        except ConnectionError as e:
            print(f"连接错误: {e}")
        except Exception as e:
            traceback.print_exc()
            try:
                send_msg(conn, {'success': False, 'error': str(e)})
            except:
                pass
        finally:
            conn.close()


if __name__ == '__main__':
    main()
