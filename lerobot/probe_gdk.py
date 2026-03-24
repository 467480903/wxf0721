#!/usr/bin/env python3
"""快速诊断 GDK 接口返回结构"""

import json
import time
import agibot_gdk


def main():
    print("=== GDK 初始化 ===")
    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("GDK 初始化失败")
        return
    print("GDK 初始化成功")

    robot = agibot_gdk.Robot()
    camera = agibot_gdk.Camera()
    time.sleep(2)

    print("\n=== get_joint_states 返回 ===")
    try:
        js = robot.get_joint_states()
        print(f"nums: {js.get('nums')}")
        print(f"timestamp: {js.get('timestamp')}")
        states = js.get("states", [])
        print(f"states 数量: {len(states)}")
        if states:
            print("所有关节名:")
            for i, s in enumerate(states):
                name = s.get("name", "?")
                pos = s.get("position", 0)
                motor_pos = s.get("motor_position", 0)
                print(f"  [{i}] {name:30s}  pos={pos:+.4f}  motor={motor_pos:+.4f}")
            # 过滤 arm_r
            arm_r = [s for s in states if "arm_r" in s.get("name", "")]
            print(f"\n含 'arm_r' 的关节数: {len(arm_r)}")
            for s in arm_r:
                print(f"  {s['name']:30s}  pos={s['position']:+.4f}")
    except Exception as e:
        print(f"get_joint_states 失败: {type(e).__name__}: {e}")

    print("\n=== get_end_state 返回 ===")
    try:
        es = robot.get_end_state()
        # 序列化时只保留可序列化字段
        def safe(o):
            if isinstance(o, dict):
                return {k: safe(v) for k, v in o.items()}
            if isinstance(o, list):
                return [safe(x) for x in o]
            if isinstance(o, (str, int, float, bool)) or o is None:
                return o
            return str(o)
        print(json.dumps(safe(es), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"get_end_state 失败: {type(e).__name__}: {e}")

    print("\n=== get_latest_image (kHeadColor) ===")
    try:
        img = camera.get_latest_image(agibot_gdk.CameraType.kHeadColor, 2000.0)
        if img is None:
            print("image is None  <-- 90% 是相机服务未启动")
        else:
            print(f"width={img.width}  height={img.height}")
            print(f"encoding={img.encoding}")
            print(f"color_format={img.color_format}")
            print(f"timestamp_ns={img.timestamp_ns}")
            data = getattr(img, "data", None)
            print(f"data type={type(data).__name__}  len={len(data) if data is not None else 0}")
    except Exception as e:
        print(f"get_latest_image(kHeadColor) 失败: {type(e).__name__}: {e}")

    print("\n=== get_latest_image (kHandRightColor) ===")
    try:
        img = camera.get_latest_image(agibot_gdk.CameraType.kHandRightColor, 2000.0)
        if img is None:
            print("image is None  <-- 腕部相机可能未启用")
        else:
            print(f"width={img.width}  height={img.height}")
            print(f"encoding={img.encoding}")
            print(f"data len={len(img.data) if img.data is not None else 0}")
    except Exception as e:
        print(f"get_latest_image(kHandRightColor) 失败: {type(e).__name__}: {e}")

    print("\n=== 释放 ===")
    agibot_gdk.gdk_release()


if __name__ == "__main__":
    main()
