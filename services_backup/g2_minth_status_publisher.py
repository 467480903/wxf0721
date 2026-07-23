#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G2 状态读取 + 点云发布程序

合并了原 status_publisher 和 cloud_publisher 的功能。

持续发布：
  - /G2_minth_status  : 机器人关节角 + 末端坐标 + 底盘位姿
  - /G2_minth_cloud   : 激光雷达点云（仅在收到 start_cloud 后发布）

监听：
  - /minth/g2/status  : 控制指令
      {cmd: start_cloud}  → 开始读取雷达并发布点云
      {cmd: stop_cloud}   → 停止发布点云

状态消息格式：
{
  "timestamp": "2026-07-14 15:00:00",
  "joints": {"idx01_body_joint1": 0.123, ...},
  "left_ee": {"position": [x,y,z], "orientation": [x,y,z,w]},
  "right_ee": {"position": [x,y,z], "orientation": [x,y,z,w]},
  "chassis": {"x": 0.0, "y": 0.0, "yaw": 0.0, "loc_state": 2, "loc_confidence": 0.95}
}
"""

import sys
import os
import time
import json
import math

import numpy as np
import agibot_gdk
import paho.mqtt.client as mqtt

# ── 配置 ───────────────────────────────────────────────────
LEFT_NAME = "arm_l_end_link"
RIGHT_NAME = "arm_r_end_link"

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

MQTT_STATUS_TOPIC = "/G2_minth_status"
MQTT_CLOUD_TOPIC  = "/G2_minth_cloud"
MQTT_CTRL_TOPIC   = "/minth/g2/status"     # 控制指令 topic
MQTT_CLIENT_ID = "g2_status_publisher"

# 发布周期（秒）
STATUS_INTERVAL = 0.5
CLOUD_INTERVAL  = 1.0

# 点云降采样
DOWNSAMPLE_STEP = 4
MAX_DISTANCE = 30.0

LIDAR_TYPES = [
    (agibot_gdk.LidarType.kLidarFront, "前部雷达"),
    (agibot_gdk.LidarType.kLidarBack,  "后部雷达"),
]

# 全局控制标志
_cloud_enabled = False


# ═══════════════════════════════════════════════════════════
#  状态读取
# ═══════════════════════════════════════════════════════════

def read_joint_states(robot):
    """读取所有关节状态，返回 {关节名: 位置} 字典"""
    joint_states = robot.get_joint_states()
    joints = {}
    for state in joint_states['states']:
        joints[state['name']] = round(state['motor_position'], 6)
    return joints


def find_pose_by_name(status, target_name):
    """从 motion_control_status 中按名称查找末端位姿"""
    for i, frame_name in enumerate(status.frame_names):
        if frame_name == target_name:
            pose = status.frame_poses[i]
            return {
                "position": [
                    round(pose.position.x, 6),
                    round(pose.position.y, 6),
                    round(pose.position.z, 6),
                ],
                "orientation": [
                    round(pose.orientation.x, 6),
                    round(pose.orientation.y, 6),
                    round(pose.orientation.z, 6),
                    round(pose.orientation.w, 6),
                ],
            }
    return None


def read_end_effector_poses(robot):
    """读取左右手末端坐标"""
    status = robot.get_motion_control_status()
    left = find_pose_by_name(status, LEFT_NAME)
    right = find_pose_by_name(status, RIGHT_NAME)
    return left, right


def read_chassis_pose(slam):
    """读取底盘在地图中的位姿（X, Y, 旋转角）"""
    try:
        odom = slam.get_odom_info()
        pos = odom.pose.pose.position
        ori = odom.pose.pose.orientation
        # 四元数转 yaw（绕 Z 轴旋转角）
        # yaw = atan2(2(wz+xy), 1-2(y²+z²))
        w, x, y, z = ori.w, ori.x, ori.y, ori.z
        yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        return {
            "x": round(pos.x, 6),
            "y": round(pos.y, 6),
            "z": round(pos.z, 6),
            "yaw": round(yaw, 6),
            "loc_state": odom.loc_state,
            "loc_confidence": round(odom.loc_confidence, 4),
        }
    except Exception as e:
        print(f"[警告] 读取底盘位姿失败: {e}")
        return None


def build_status_message(robot, slam):
    """构建状态 JSON 消息"""
    joints = read_joint_states(robot)
    left_ee, right_ee = read_end_effector_poses(robot)
    chassis = read_chassis_pose(slam)
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "joints": joints,
        "left_ee": left_ee,
        "right_ee": right_ee,
        "chassis": chassis,
    }


# ═══════════════════════════════════════════════════════════
#  点云读取
# ═══════════════════════════════════════════════════════════

def parse_pointcloud(pointcloud):
    """解析 PointCloud 为 (N, 4) numpy 数组 [x, y, z, intensity]"""
    if not hasattr(pointcloud, 'data'):
        return None
    try:
        if isinstance(pointcloud.data, np.ndarray):
            data = pointcloud.data.astype(np.uint8)
        else:
            data = np.frombuffer(pointcloud.data, dtype=np.uint8)

        if pointcloud.point_step <= 0:
            return None

        num_points = len(data) // pointcloud.point_step
        data = data[:num_points * pointcloud.point_step]
        data = data.reshape((num_points, pointcloud.point_step))

        channels = {}
        for field in pointcloud.fields:
            if field.name in ('x', 'y', 'z', 'intensity'):
                slc = data[:, field.offset:field.offset + 4]
                channels[field.name] = np.ascontiguousarray(slc).view(np.float32)

        if 'x' in channels and 'y' in channels and 'z' in channels:
            xs, ys, zs = channels['x'], channels['y'], channels['z']
            intens = channels.get('intensity', np.zeros(num_points, dtype=np.float32))
            return np.column_stack([xs, ys, zs, intens])
        return None
    except Exception as e:
        print(f"[解析失败] {e}")
        return None


def build_cloud_message(lidar):
    """读取前后雷达点云，合并降采样后构建 MQTT 消息"""
    all_points = []
    front_count = 0
    back_count = 0
    latest_ts = 0

    for lidar_type, lidar_name in LIDAR_TYPES:
        pointcloud = lidar.get_latest_pointcloud(lidar_type, 1000.0)
        if pointcloud is None:
            continue

        pts = parse_pointcloud(pointcloud)
        if pts is None or len(pts) == 0:
            continue

        dist = np.sqrt(pts[:, 0] ** 2 + pts[:, 1] ** 2 + pts[:, 2] ** 2)
        mask = dist < MAX_DISTANCE
        pts = pts[mask]
        pts = pts[::DOWNSAMPLE_STEP]

        count = len(pts)
        if lidar_type == agibot_gdk.LidarType.kLidarFront:
            front_count = count
        else:
            back_count = count

        for i in range(count):
            all_points.append([
                round(float(pts[i, 0]), 3),
                round(float(pts[i, 1]), 3),
                round(float(pts[i, 2]), 3),
            ])

        if pointcloud.timestamp_ns > latest_ts:
            latest_ts = pointcloud.timestamp_ns

    if not all_points:
        return None

    return {
        "timestamp": latest_ts,
        "count": len(all_points),
        "front_count": front_count,
        "back_count": back_count,
        "points": all_points,
    }


# ═══════════════════════════════════════════════════════════
#  MQTT 回调
# ═══════════════════════════════════════════════════════════

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] 已连接到 {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_CTRL_TOPIC, qos=0)
        print(f"[MQTT] 已订阅控制指令: {MQTT_CTRL_TOPIC}")
        print("-" * 60)
    else:
        print(f"[MQTT] 连接失败，返回码: {rc}")


def on_message(client, userdata, msg):
    """处理控制指令"""
    global _cloud_enabled
    try:
        payload = msg.payload.decode("utf-8")
        cmd_msg = json.loads(payload)
        cmd = cmd_msg.get("cmd")
    except Exception as e:
        print(f"[解析失败] {e}")
        return

    if cmd == "start_cloud":
        _cloud_enabled = True
        print("[控制] 开始发布点云")
    elif cmd == "stop_cloud":
        _cloud_enabled = False
        print("[控制] 停止发布点云")
    else:
        print(f"[控制] 未知命令: {cmd}")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main():
    global _cloud_enabled

    print("#" * 60)
    print("#   G2 状态+点云发布程序 - 启动   #")
    print("#" * 60)
    print(f"状态 topic   : {MQTT_STATUS_TOPIC} (每 {STATUS_INTERVAL}s)")
    print(f"点云 topic   : {MQTT_CLOUD_TOPIC} (每 {CLOUD_INTERVAL}s, 按需)")
    print(f"控制 topic   : {MQTT_CTRL_TOPIC}")
    print()

    # ── 初始化 GDK ──
    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("❌ GDK 初始化失败")
        sys.exit(1)
    print("✅ GDK 初始化成功")

    robot = agibot_gdk.Robot()
    slam  = agibot_gdk.Slam()
    lidar = agibot_gdk.Lidar()
    time.sleep(2)
    print("✅ Robot/Slam/Lidar 对象创建完成")

    # ── 初始化 MQTT ──
    mqtt_client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()
    print(f"[MQTT] 已连接到 {MQTT_BROKER}:{MQTT_PORT}")

    last_cloud_time = 0.0

    try:
        while True:
            now = time.time()

            # 发布状态
            try:
                msg = build_status_message(robot, slam)
                payload = json.dumps(msg, ensure_ascii=False)
                mqtt_client.publish(MQTT_STATUS_TOPIC, payload, qos=0)
                chassis_str = ""
                if msg.get("chassis"):
                    c = msg["chassis"]
                    chassis_str = f", chassis=({c['x']:.2f},{c['y']:.2f},{c['yaw']:.2f})"
                print(f"[状态] joints={len(msg['joints'])}个{chassis_str}")
            except Exception as e:
                print(f"[错误] 状态发布失败: {e}")

            # 发布点云（仅在启用时）
            if _cloud_enabled and (now - last_cloud_time) >= CLOUD_INTERVAL:
                try:
                    cloud_msg = build_cloud_message(lidar)
                    if cloud_msg:
                        cloud_payload = json.dumps(cloud_msg, ensure_ascii=False)
                        mqtt_client.publish(MQTT_CLOUD_TOPIC, cloud_payload, qos=0)
                        print(f"[点云] 点数={cloud_msg['count']}, "
                              f"前={cloud_msg['front_count']}, 后={cloud_msg['back_count']}")
                    else:
                        print("[点云] 未获取到数据")
                except Exception as e:
                    print(f"[错误] 点云发布失败: {e}")
                last_cloud_time = now

            time.sleep(STATUS_INTERVAL)
    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
            print("⚠️ GDK 释放失败")
        else:
            print("✅ GDK 释放成功")
        print("🏁 程序结束")


if __name__ == "__main__":
    main()
