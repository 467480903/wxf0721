#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G2 相机数据发布程序

持续读取 4 个相机数据，按 base64 编码后发布到 MQTT topic /minth/g2/cameras

相机：
  - 头部彩色 (kHeadColor)
  - 头部深度 (kHeadDepth)         → 转伪彩色后 JPEG 编码
  - 左手腕彩色 (kHandLeftColor)
  - 右手腕彩色 (kHandRightColor)

控制 topic：/minth/g2/camera
  - {"cmd": "start"}                                开始发布
  - {"cmd": "stop"}                                 停止发布（线程仍以 0.5s 周期运行）
  - {"cmd": "save", "cameras": ["kHeadColor", ...]} 保存图片到 ../images/
  - {"cmd": "detect", "yolo": "wxf.pt"}             拍摄头部彩深图 → TCP 发给 YOLO 服务

发布格式（/minth/g2/cameras）：
{
  "timestamp": 1782975716895377276,
  "head_color": "<base64 jpeg>",
  "head_depth": "<base64 jpeg>",
  "left_wrist": "<base64 jpeg>",
  "right_wrist": "<base64 jpeg>"
}

任务完成后向 /G2_minth_app_done 发布 {"cmd": "done"}
"""

import sys
import os
import time
import json
import base64
import socket
import threading

import agibot_gdk
import paho.mqtt.client as mqtt

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# ── 配置 ───────────────────────────────────────────────────
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

CAMERAS_TOPIC   = "/minth/g2/cameras"   # 发布相机数据
CONTROL_TOPIC   = "/minth/g2/camera"    # 接收控制命令
DONE_TOPIC      = "/G2_minth_app_done"  # 任务完成通知
MQTT_CLIENT_ID  = "g2_camera_publisher"

# 采集周期（秒）— 线程始终按此周期运行
LOOP_INTERVAL = 0.5

# 4 个相机
CAMERA_LIST = [
    ("head_color", agibot_gdk.CameraType.kHeadColor,     "头部彩色"),
    ("head_depth", agibot_gdk.CameraType.kHeadDepth,     "头部深度"),
    ("left_wrist", agibot_gdk.CameraType.kHandLeftColor, "左手腕"),
    ("right_wrist",agibot_gdk.CameraType.kHandRightColor,"右手腕"),
]

# 相机名称字符串 → CameraType 枚举（用于 save/detect 命令的 cameras 字段）
CAMERA_NAME_MAP = {
    "kHeadColor":      agibot_gdk.CameraType.kHeadColor,
    "kHeadDepth":      agibot_gdk.CameraType.kHeadDepth,
    "kHandLeftColor":  agibot_gdk.CameraType.kHandLeftColor,
    "kHandRightColor": agibot_gdk.CameraType.kHandRightColor,
}

# 图片保存目录（mqtt/../images/）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_SAVE_DIR = os.path.join(SCRIPT_DIR, "..", "images")
# 检测结果保存目录（mqtt/../detect/）
DETECT_SAVE_DIR = os.path.join(SCRIPT_DIR, "..", "detect")

# JPEG 编码质量
JPEG_QUALITY = 60

# YOLO TCP 服务配置
YOLO_TCP_HOST = "10.2.236.7"
YOLO_TCP_PORT = 9998
YOLO_RECV_TIMEOUT = 60.0


# ═══════════════════════════════════════════════════════════
#  图像编码
# ═══════════════════════════════════════════════════════════

def encode_image(image, key):
    """把 GDK Image 编码为 base64 字符串"""
    if image is None or not hasattr(image, 'data') or image.data is None:
        return None

    raw = image.data
    # 判断是否已经是压缩格式（JPEG/PNG），可直接 base64
    encoding = getattr(image, 'encoding', None)
    if encoding == agibot_gdk.Encoding.JPEG:
        return base64.b64encode(bytes(raw)).decode("ascii")
    if encoding == agibot_gdk.Encoding.PNG:
        return base64.b64encode(bytes(raw)).decode("ascii")

    # 未压缩数据，需要用 cv2 重新编码为 JPEG
    if not HAS_CV2:
        return base64.b64encode(bytes(raw)).decode("ascii")

    try:
        color_format = getattr(image, 'color_format', None)

        if key == "head_depth":
            if len(raw) == image.width * image.height * 2:
                depth = np.frombuffer(raw, dtype=np.uint16).reshape((image.height, image.width))
            elif len(raw) == image.width * image.height:
                depth = np.frombuffer(raw, dtype=np.uint8).reshape((image.height, image.width))
            else:
                depth = np.frombuffer(raw, dtype=np.uint16)
                if depth.size == image.width * image.height:
                    depth = depth.reshape((image.height, image.width))
                else:
                    print(f"  [深度] 数据大小 {len(raw)} 无法匹配 {image.width}x{image.height}")
                    return None

            valid = depth > 0
            if np.any(valid):
                mn, mx = depth[valid].min(), depth[valid].max()
                if mx > mn:
                    norm = ((depth.astype(np.float32) - mn) / (mx - mn) * 255).astype(np.uint8)
                else:
                    norm = np.zeros_like(depth, dtype=np.uint8)
            else:
                norm = np.zeros_like(depth, dtype=np.uint8)
            colored = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
        else:
            nparr = np.frombuffer(raw, dtype=np.uint8)
            if color_format == agibot_gdk.ColorFormat.RGB:
                img = nparr.reshape((image.height, image.width, 3))
                colored = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            elif color_format == agibot_gdk.ColorFormat.BGR:
                colored = nparr.reshape((image.height, image.width, 3))
            elif color_format == agibot_gdk.ColorFormat.GRAY8:
                gray = nparr.reshape((image.height, image.width))
                colored = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            else:
                colored = nparr.reshape((image.height, image.width, 3))

        ok, buf = cv2.imencode('.jpg', colored, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if ok:
            return base64.b64encode(buf).decode("ascii")
    except Exception as e:
        print(f"[编码失败] {key}: {e}")

    return None


# ═══════════════════════════════════════════════════════════
#  图片保存
# ═══════════════════════════════════════════════════════════

def save_camera_images(camera, camera_names):
    """保存指定相机的图片到 ../images/ 目录

    Parameters
    ----------
    camera : agibot_gdk.Camera
    camera_names : list[str]
        相机名称列表，如 ["kHeadColor", "kHeadDepth"]
    """
    os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    saved_files = []

    for name in camera_names:
        cam_type = CAMERA_NAME_MAP.get(name)
        if cam_type is None:
            print(f"  [保存] 未知相机名: {name}")
            continue

        try:
            img = camera.get_latest_image(cam_type, 1000.0)
        except Exception as e:
            print(f"  [保存] {name} 读取异常: {e}")
            continue

        if img is None or img.data is None:
            print(f"  [保存] {name} 无数据")
            continue

        if name == "kHeadDepth":
            # 深度图：保存原始 uint16 + 伪彩色 jpg
            raw_name = f"{name}_raw_{timestamp}.raw"
            raw_path = os.path.join(IMAGE_SAVE_DIR, raw_name)
            with open(raw_path, "wb") as f:
                f.write(img.data)
            saved_files.append(raw_name)
            print(f"  [保存] {raw_name}")

            if HAS_CV2:
                try:
                    depth_array = np.frombuffer(img.data, dtype=np.uint16)
                    depth_array = depth_array.reshape((img.height, img.width))
                    valid_mask = depth_array > 0
                    if np.any(valid_mask):
                        mn, mx = depth_array[valid_mask].min(), depth_array[valid_mask].max()
                    else:
                        mn, mx = 0, 1
                    if mx > mn:
                        normalized = ((depth_array - mn) / (mx - mn) * 255).astype(np.uint8)
                    else:
                        normalized = np.zeros_like(depth_array, dtype=np.uint8)
                    depth_colored = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)
                    cv2.putText(depth_colored, f"Depth: {mn}-{mx}mm", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    jpg_name = f"{name}_{timestamp}.jpg"
                    jpg_path = os.path.join(IMAGE_SAVE_DIR, jpg_name)
                    cv2.imwrite(jpg_path, depth_colored)
                    saved_files.append(jpg_name)
                    print(f"  [保存] {jpg_name}")
                except Exception as e:
                    print(f"  [保存] 深度伪彩色失败: {e}")
        else:
            # 彩色图：直接写原始数据，再尝试 jpg
            # 判断编码
            encoding = getattr(img, 'encoding', None)
            if encoding == agibot_gdk.Encoding.JPEG:
                jpg_name = f"{name}_{timestamp}.jpg"
                jpg_path = os.path.join(IMAGE_SAVE_DIR, jpg_name)
                with open(jpg_path, "wb") as f:
                    f.write(img.data)
                saved_files.append(jpg_name)
                print(f"  [保存] {jpg_name}")
            elif HAS_CV2:
                try:
                    nparr = np.frombuffer(img.data, dtype=np.uint8)
                    color_format = getattr(img, 'color_format', None)
                    if color_format == agibot_gdk.ColorFormat.RGB:
                        bgr = cv2.cvtColor(nparr.reshape((img.height, img.width, 3)), cv2.COLOR_RGB2BGR)
                    elif color_format == agibot_gdk.ColorFormat.BGR:
                        bgr = nparr.reshape((img.height, img.width, 3))
                    else:
                        bgr = nparr.reshape((img.height, img.width, 3))
                    jpg_name = f"{name}_{timestamp}.jpg"
                    jpg_path = os.path.join(IMAGE_SAVE_DIR, jpg_name)
                    cv2.imwrite(jpg_path, bgr)
                    saved_files.append(jpg_name)
                    print(f"  [保存] {jpg_name}")
                except Exception as e:
                    print(f"  [保存] {name} 编码失败: {e}")
            else:
                raw_name = f"{name}_{timestamp}.raw"
                raw_path = os.path.join(IMAGE_SAVE_DIR, raw_name)
                with open(raw_path, "wb") as f:
                    f.write(img.data)
                saved_files.append(raw_name)
                print(f"  [保存] {raw_name}")

    print(f"[保存] 完成，共 {len(saved_files)} 个文件 → {IMAGE_SAVE_DIR}")
    return saved_files


# ═══════════════════════════════════════════════════════════
#  YOLO 检测
# ═══════════════════════════════════════════════════════════

def run_yolo_detect(camera, model_name):
    """拍摄头部彩深图 → 保存图片 → TCP 发给 YOLO 服务 → 保存检测结果

    参考 yolo/cam_get_head_send.py

    Parameters
    ----------
    camera : agibot_gdk.Camera
    model_name : str
        YOLO 模型文件名，如 "wxf.pt"
    """
    # 1. 拍摄头部彩色 + 深度
    color_img = None
    depth_img = None
    color_bytes = None
    depth_bytes = None

    try:
        color_img = camera.get_latest_image(agibot_gdk.CameraType.kHeadColor, 1000.0)
        if color_img is not None and color_img.data is not None:
            color_bytes = color_img.data
            print(f"[YOLO] 彩色图: {color_img.width}x{color_img.height}")
        else:
            print("[YOLO] 未获取到彩色图像")
    except Exception as e:
        print(f"[YOLO] 彩色图读取异常: {e}")

    try:
        depth_img = camera.get_latest_image(agibot_gdk.CameraType.kHeadDepth, 1000.0)
        if depth_img is not None and depth_img.data is not None:
            depth_bytes = depth_img.data
            print(f"[YOLO] 深度图: {depth_img.width}x{depth_img.height}")
        else:
            print("[YOLO] 未获取到深度图像")
    except Exception as e:
        print(f"[YOLO] 深度图读取异常: {e}")

    if color_bytes is None or depth_bytes is None:
        print("[YOLO] ⚠ 彩色或深度图未获取到，跳过检测")
        return None

    # 2. 保存图片到 ../images/
    os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    rgb_name = f"P{ts}_RGB.jpg"
    depth_name = f"P{ts}_DEPTH.jpg"

    # 保存彩色图
    try:
        encoding = getattr(color_img, 'encoding', None)
        if encoding == agibot_gdk.Encoding.JPEG:
            with open(os.path.join(IMAGE_SAVE_DIR, rgb_name), "wb") as f:
                f.write(color_bytes)
        elif HAS_CV2:
            nparr = np.frombuffer(color_bytes, dtype=np.uint8)
            color_format = getattr(color_img, 'color_format', None)
            if color_format == agibot_gdk.ColorFormat.RGB:
                bgr = cv2.cvtColor(nparr.reshape((color_img.height, color_img.width, 3)), cv2.COLOR_RGB2BGR)
            else:
                bgr = nparr.reshape((color_img.height, color_img.width, 3))
            cv2.imwrite(os.path.join(IMAGE_SAVE_DIR, rgb_name), bgr)
        else:
            with open(os.path.join(IMAGE_SAVE_DIR, rgb_name), "wb") as f:
                f.write(color_bytes)
        print(f"[YOLO] 彩色图已保存: {rgb_name}")
    except Exception as e:
        print(f"[YOLO] 彩色图保存失败: {e}")

    # 保存深度伪彩色图
    try:
        if HAS_CV2:
            depth_array = np.frombuffer(depth_bytes, dtype=np.uint16)
            depth_array = depth_array.reshape((depth_img.height, depth_img.width))
            valid_mask = depth_array > 0
            if np.any(valid_mask):
                mn, mx = depth_array[valid_mask].min(), depth_array[valid_mask].max()
            else:
                mn, mx = 0, 1
            if mx > mn:
                normalized = ((depth_array - mn) / (mx - mn) * 255).astype(np.uint8)
            else:
                normalized = np.zeros_like(depth_array, dtype=np.uint8)
            depth_colored = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)
            cv2.putText(depth_colored, f"Depth: {mn}-{mx}mm", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imwrite(os.path.join(IMAGE_SAVE_DIR, depth_name), depth_colored)
            print(f"[YOLO] 深度图已保存: {depth_name}")
        else:
            # 没有 cv2，保存原始数据
            with open(os.path.join(IMAGE_SAVE_DIR, depth_name), "wb") as f:
                f.write(depth_bytes)
            print(f"[YOLO] 深度图(原始)已保存: {depth_name}")
    except Exception as e:
        print(f"[YOLO] 深度图保存失败: {e}")

    # 3. base64 编码 + 构造请求
    rgb_b64 = base64.b64encode(color_bytes).decode("ascii")
    depth_b64 = base64.b64encode(depth_bytes).decode("ascii")

    payload = {
        "cmd": "detect",
        "rgb": rgb_b64,
        "depth": depth_b64,
        "model": model_name,
    }
    message = json.dumps(payload, ensure_ascii=False) + "\n"
    print(f"[YOLO] 请求: rgb={len(rgb_b64)}, depth={len(depth_b64)}, model={model_name}")

    # 4. TCP 发送并接收回复
    sock = None
    try:
        print(f"[YOLO] 连接 {YOLO_TCP_HOST}:{YOLO_TCP_PORT} ...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(YOLO_RECV_TIMEOUT)
        sock.connect((YOLO_TCP_HOST, YOLO_TCP_PORT))
        print("[YOLO] 已连接，发送报文...")

        sock.sendall(message.encode("utf-8"))
        print("[YOLO] 报文已发送，等待回复...")

        received = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                print("[YOLO] ⚠ 接收超时")
                break
            if not chunk:
                break
            received += chunk
            if b"\n" in chunk:
                break

        if not received:
            print("[YOLO] ⚠ 未收到回复")
            return None

        print(f"[YOLO] 收到回复，长度={len(received)} 字节")

        # 5. 保存检测结果到 ../detect/
        os.makedirs(DETECT_SAVE_DIR, exist_ok=True)
        result = None
        try:
            response_json = json.loads(received.decode("utf-8"))
            result = response_json
            print(f"[YOLO] 检测结果: {json.dumps(response_json, ensure_ascii=False)[:200]}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[YOLO] ⚠ 回复非合法 JSON: {e}")
            result = {"raw": received.decode("utf-8", errors="replace")}

        # 保存 D{时间戳}.json 和覆盖 detect.json
        detect_ts_name = f"D{ts}.json"
        detect_latest_name = "detect.json"
        detect_ts_path = os.path.join(DETECT_SAVE_DIR, detect_ts_name)
        detect_latest_path = os.path.join(DETECT_SAVE_DIR, detect_latest_name)

        with open(detect_ts_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[YOLO] 检测结果已保存: {detect_ts_name}")

        with open(detect_latest_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[YOLO] 最新结果已覆盖: {detect_latest_name}")

        return result

    except Exception as e:
        print(f"[YOLO] ❌ TCP 通信失败: {e}")
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════
#  主程序
# ═══════════════════════════════════════════════════════════

def main():
    print("#" * 60)
    print("#   G2 相机数据发布程序 - 启动   #")
    print("#" * 60)
    print(f"发布 topic : {CAMERAS_TOPIC}")
    print(f"控制 topic : {CONTROL_TOPIC}")
    print(f"完成通知   : {DONE_TOPIC}")
    print(f"图片保存   : {IMAGE_SAVE_DIR}")
    print(f"采集周期   : {LOOP_INTERVAL}s")
    print(f"OpenCV     : {'已加载' if HAS_CV2 else '未加载'}")
    print()

    # ── 初始化 GDK ──
    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("❌ GDK 初始化失败")
        sys.exit(1)
    print("✅ GDK 初始化成功")

    camera = agibot_gdk.Camera()
    print("✅ Camera 对象创建完成，等待 DDS 连接...")
    time.sleep(3)

    # 发布开关
    publishing = [False]

    # ── 初始化 MQTT ──
    mqtt_client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    def publish_done():
        """向 /G2_minth_app_done 发送完成通知"""
        mqtt_client.publish(DONE_TOPIC, json.dumps({"cmd": "done"}), qos=0)
        print(f"[完成] 已发送 done → {DONE_TOPIC}")

    def handle_save(camera_names):
        """在子线程中执行保存图片"""
        try:
            save_camera_images(camera, camera_names)
        except Exception as e:
            print(f"[保存] ❌ 异常: {e}")
        finally:
            publish_done()

    def handle_detect(model_name):
        """在子线程中执行 YOLO 检测"""
        try:
            run_yolo_detect(camera, model_name)
        except Exception as e:
            print(f"[YOLO] ❌ 异常: {e}")
        finally:
            publish_done()

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            cmd = payload.get("cmd", "").lower()

            if cmd == "start":
                publishing[0] = True
                print("[控制] ▶️ 开始发布")
            elif cmd == "stop":
                publishing[0] = False
                print("[控制] ⏸️ 停止发布")
            elif cmd == "save":
                cameras = payload.get("cameras", [])
                if not cameras:
                    print("[控制] save 命令缺少 cameras 字段")
                    return
                print(f"[控制] 💾 保存图片: {cameras}")
                t = threading.Thread(target=handle_save, args=(cameras,), daemon=True)
                t.start()
            elif cmd == "detect":
                yolo_model = payload.get("yolo", "")
                if not yolo_model:
                    print("[控制] detect 命令缺少 yolo 字段")
                    return
                print(f"[控制] 🔍 YOLO 检测: model={yolo_model}")
                t = threading.Thread(target=handle_detect, args=(yolo_model,), daemon=True)
                t.start()
            else:
                print(f"[控制] 未知命令: {cmd}")
        except Exception as e:
            print(f"[控制] 解析失败: {e}")

    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.subscribe(CONTROL_TOPIC, qos=0)
    mqtt_client.loop_start()
    print(f"[MQTT] 已连接到 {MQTT_BROKER}:{MQTT_PORT}")
    print("[提示] 默认不发布，等待 start 命令")

    try:
        while True:
            t0 = time.time()
            if publishing[0]:
                try:
                    msg = {"timestamp": int(time.time() * 1e9)}
                    for key, cam_type, cam_name in CAMERA_LIST:
                        try:
                            img = camera.get_latest_image(cam_type, 1000.0)
                            b64 = encode_image(img, key) if img is not None else None
                        except Exception as e:
                            b64 = None
                            print(f"  [{cam_name}] 读取异常: {e}")
                        if b64:
                            msg[key] = b64
                            print(f"  [{cam_name}] OK len={len(b64)}")
                        else:
                            print(f"  [{cam_name}] 无数据")

                    payload = json.dumps(msg, ensure_ascii=False)
                    mqtt_client.publish(CAMERAS_TOPIC, payload, qos=0)
                    print(f"[发布] payload={len(payload)} 字节")
                except Exception as e:
                    print(f"[错误] {e}")

            elapsed = time.time() - t0
            if elapsed < LOOP_INTERVAL:
                time.sleep(LOOP_INTERVAL - elapsed)
    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        try:
            camera.close_camera()
        except Exception:
            pass
        if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
            print("⚠️ GDK 释放失败")
        else:
            print("✅ GDK 释放成功")
        print("🏁 程序结束")


if __name__ == "__main__":
    main()
