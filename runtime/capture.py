import os
import time
import json

from minth import Minth

IMAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images")


def capture_head_color(G2, timeout=10.0, poll_interval=0.1, settle_time=0.2):
    if settle_time > 0:
        time.sleep(settle_time)

    before = set(os.listdir(IMAGE_DIR)) if os.path.exists(IMAGE_DIR) else set()

    G2._done_event.clear()
    payload = {"command": "save_photo", "cameras": ["kHeadColor"]}
    G2._client.publish("/humanoid/camera/control", json.dumps(payload, ensure_ascii=False), qos=2)
    print("[拍照] 已发送 save_photo 命令")

    done = G2._done_event.wait(timeout=15)
    if not done:
        print("[拍照] MQTT 回执超时")
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        after = set(os.listdir(IMAGE_DIR)) if os.path.exists(IMAGE_DIR) else set()
        new_files = [f for f in (after - before) if f.endswith(".jpg")]
        if new_files:
            return os.path.join(IMAGE_DIR, sorted(new_files)[-1])
        time.sleep(poll_interval)

    print(f"[拍照] 超时 {timeout}s 未检测到新图片, 拒绝返回旧照片")
    return None


if __name__ == "__main__":
    G2 = Minth.G2()
    try:
        img_path = capture_head_color(G2)
        if img_path is None:
            print("拍照失败")
        else:
            print(f"[拍照] 图片: {img_path}")
    finally:
        G2.close()
