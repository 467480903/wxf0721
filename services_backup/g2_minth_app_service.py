#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G2 Minth App 服务程序

监听 MQTT topic /G2_minth_app，根据收到的 JSON 命令执行对应动作：
  - WBC                     : 从 datas/joints/WBC/  读取 JSON，控制全身关节
  - arms                    : 从 datas/joints/arms/ 读取 JSON，仅控制双臂
  - left                    : 从 datas/joints/left/ 读取 JSON，仅控制左臂
  - right                   : 从 datas/joints/right/读取 JSON，仅控制右臂
  - head                    : 从 datas/joints/head/ 读取 JSON，仅控制头部
  - waist                   : 从 datas/joints/waist/读取 JSON，仅控制腰部
  - tts                     : TTS 语音播报
  - offset_move             : 末端执行器相对移动（单位：毫米）
  - grab                    : 控制左右夹爪开合
  - cam_head                : 拍摄头部相机并通过 TCP 发送给检测服务
  - go                      : 导航到指定地图点位（nav.go）
  - go_rel                  : 底盘相对运动（nav.go_rel）
  - joint                   : 单关节控制（增量微调或直接运动到角度）

注意：数据保存（save_joints / save_position）已转移到 g2_minth_data_service.py

状态管理：
  - 任意时刻只能执行一个命令，执行期间 state="busy"，新命令将被拒绝
  - 命令执行完成后，state 恢复为 "idle"
  - 每条命令执行完成后，都会向 /G2_minth_app_done 发布 {"cmd": "done"}

命令格式示例：
  {"cmd": "WBC",   "data": "hold"}          # 加载 datas/joints/WBC/hold.json
  {"cmd": "arms",  "data": "hold"}          # 加载 datas/joints/arms/hold.json
  {"cmd": "left",  "data": "hold"}          # 加载 datas/joints/left/hold.json
  {"cmd": "WBC",   "data": {"idx11_head_joint1": 0.1, ...}}  # 内联关节角（实时示教）
  {"cmd": "save_joints", "type": "WBC", "name": "hold", "data": {"idx11_head_joint1": 0.1, ...}}
  {"cmd": "tts",                     "data": "你好，我是精灵G2"}
  {"cmd": "offset_move",             "data": {"lx": 20, "ly": 0, "lz": 0, "rx": 0, "ry": 0, "rz": 0}}
  {"cmd": "grab",                    "data": {"left": 0.5, "right": 0.5}}
  {"cmd": "cam_head"}
  {"cmd": "go",                      "data": 9}
  {"cmd": "go_rel",                  "data": {"x": 1, "y": 1, "yaw_rad": 0.1}}
  {"cmd": "joint", "data": {"name": "idx11_head_joint1", "offset": 0.01}}   # 增量微调
  {"cmd": "joint", "data": {"name": "idx11_head_joint1", "value": 0.0}}     # 运动到指定角度
"""

import sys
import os
import time
import json
import socket
import base64
import threading

import agibot_gdk
import paho.mqtt.client as mqtt

# ── 路径配置 ───────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
POSITIONS_DIR = os.path.join(PROJECT_DIR, "positions")
JOINTS_DIR = os.path.join(PROJECT_DIR, "datas", "joints")

BOX_DIR = os.path.join(PROJECT_DIR, "BOX_528_1")
sys.path.append(BOX_DIR)
sys.path.append(SCRIPT_DIR)

from chassis_controller import RobotController
from offset_move_common import EndEffectorController

# ── MQTT 配置 ─────────────────────────────────────────────
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "/G2_minth_app"
MQTT_DONE_TOPIC = "/G2_minth_app_done"
MQTT_MAP_POINTS_TOPIC = "/minth/g2/map/points"
MQTT_CLIENT_ID = "g2_minth_app_service"

# ── TCP 配置（cam_head 用）────────────────────────────────
TCP_HOST = "10.2.236.7"
TCP_PORT = 9998
DEFAULT_MODEL = "shelf.pt"
RESPONSE_FILE = os.path.join(SCRIPT_DIR, "yolo_depth_result.json")

# ── 全局对象（在 GDK 初始化后创建）────────────────────────
robot = None
interaction = None
camera = None
ee_controller = None
nav = None

# MQTT 客户端全局引用（供发布 done 消息使用）
mqtt_client = None

# ── 状态管理 ───────────────────────────────────────────────
# state: "idle" = 空闲可接收命令，"busy" = 正在执行命令
_state = "idle"
_state_lock = threading.Lock()


def get_state():
    with _state_lock:
        return _state


def set_state(new_state):
    global _state
    with _state_lock:
        _state = new_state


def publish_done():
    """命令执行完成后向 done topic 发布完成消息"""
    if mqtt_client is None:
        return
    try:
        done_msg = json.dumps({"cmd": "done"}, ensure_ascii=False)
        mqtt_client.publish(MQTT_DONE_TOPIC, done_msg, qos=2)
        print(f"[完成] 已发布到 {MQTT_DONE_TOPIC}: {done_msg}")
    except Exception as e:
        print(f"[警告] 发布完成消息失败: {e}")


# ═══════════════════════════════════════════════════════════
#  GDK 初始化 / 释放
# ═══════════════════════════════════════════════════════════

def init_gdk():
    """初始化 GDK 并创建全局对象"""
    global robot, interaction, camera, ee_controller, nav

    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("❌ GDK 初始化失败")
        sys.exit(1)
    print("✅ GDK 初始化成功")

    robot = agibot_gdk.Robot()
    interaction = agibot_gdk.Interaction()
    camera = agibot_gdk.Camera()
    time.sleep(2)  # 等待机器人就绪

    ee_controller = EndEffectorController(robot)

    # 导航控制器
    nav = RobotController()
    nav.list_waypoints()
    print("✅ 全局对象创建完成")


def release_gdk():
    """释放 GDK"""
    if camera is not None:
        try:
            camera.close_camera()
        except Exception:
            pass
    if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
        print("⚠️ GDK 释放失败")
    else:
        print("✅ GDK 释放成功")


# ═══════════════════════════════════════════════════════════
#  命令处理器
# ═══════════════════════════════════════════════════════════

# ── 全身关节运动 ──────────────────────────────────────────
HEAD_JOINT_KEYS = [
    "idx11_head_joint1", "idx12_head_joint2", "idx13_head_joint3",
]
WAIST_JOINT_KEYS = [
    "idx01_body_joint1", "idx02_body_joint2", "idx03_body_joint3",
    "idx04_body_joint4", "idx05_body_joint5",
]
LEFT_ARM_JOINT_KEYS = [
    "idx21_arm_l_joint1", "idx22_arm_l_joint2", "idx23_arm_l_joint3",
    "idx24_arm_l_joint4", "idx25_arm_l_joint5", "idx26_arm_l_joint6",
    "idx27_arm_l_joint7",
]
RIGHT_ARM_JOINT_KEYS = [
    "idx61_arm_r_joint1", "idx62_arm_r_joint2", "idx63_arm_r_joint3",
    "idx64_arm_r_joint4", "idx65_arm_r_joint5", "idx66_arm_r_joint6",
    "idx67_arm_r_joint7",
]

HEAD_SPEED = 0.3
WAIST_SPEED = 0.3
ARM_SPEED = 0.2


def _extract_positions(data, keys):
    return [data.get(key, 0.0) for key in keys]


def _load_joints_data(cmd_type, data):
    """加载关节角数据
    data 可以是：
      - 字符串：从 datas/joints/{cmd_type}/{data}.json 加载
      - 字典：内联关节角，直接使用
    返回 (pos_data, desc) 或 (None, error_msg)
    """
    if isinstance(data, dict):
        return data, f"内联关节角 ({len(data)} 个关节)"

    json_name = data if data.endswith('.json') else data + '.json'
    json_path = os.path.join(JOINTS_DIR, cmd_type, json_name)
    if not os.path.exists(json_path):
        return None, f"找不到 {json_path}"
    with open(json_path, "r", encoding="utf-8") as f:
        pos_data = json.load(f)
    return pos_data, f"已加载 datas/joints/{cmd_type}/{json_name}"


def _move_head(pos_data):
    pos = _extract_positions(pos_data, HEAD_JOINT_KEYS)
    vel = [HEAD_SPEED] * len(pos)
    print(f"  头部 → {[f'{p:.3f}' for p in pos]}")
    robot.move_head_joint(pos, vel)


def _move_waist(pos_data):
    pos = _extract_positions(pos_data, WAIST_JOINT_KEYS)
    vel = [WAIST_SPEED] * len(pos)
    print(f"  腰部 → {[f'{p:.3f}' for p in pos]}")
    robot.move_waist_joint(pos, vel)


def _move_both_arms(pos_data):
    left = _extract_positions(pos_data, LEFT_ARM_JOINT_KEYS)
    right = _extract_positions(pos_data, RIGHT_ARM_JOINT_KEYS)
    positions = left + right
    velocities = [ARM_SPEED] * len(positions)
    print(f"  左臂 → {[f'{p:.3f}' for p in left]}")
    print(f"  右臂 → {[f'{p:.3f}' for p in right]}")
    robot.move_arm_joint(positions, velocities, 2)


def _move_left_arm(pos_data):
    left = _extract_positions(pos_data, LEFT_ARM_JOINT_KEYS)
    right = [0.0] * len(RIGHT_ARM_JOINT_KEYS)
    positions = left + right
    velocities = [ARM_SPEED] * len(positions)
    print(f"  左臂 → {[f'{p:.3f}' for p in left]}")
    robot.move_arm_joint(positions, velocities, 2)


def _move_right_arm(pos_data):
    left = [0.0] * len(LEFT_ARM_JOINT_KEYS)
    right = _extract_positions(pos_data, RIGHT_ARM_JOINT_KEYS)
    positions = left + right
    velocities = [ARM_SPEED] * len(positions)
    print(f"  右臂 → {[f'{p:.3f}' for p in right]}")
    robot.move_arm_joint(positions, velocities, 2)


# 各身体部位的执行函数
BODY_PART_MOVERS = {
    "head":      _move_head,
    "waist":     _move_waist,
    "arms":      _move_both_arms,
    "left_arm":  _move_left_arm,
    "right_arm": _move_right_arm,
}


def make_joint_handler(cmd_type, body_parts):
    """创建关节运动处理器
    cmd_type   : 命令类型，对应 datas/joints/ 下的子目录名
    body_parts : 要执行的身体部位列表，如 ["head", "waist", "arms"]
    """
    def handler(data, msg=None):
        pos_data, desc = _load_joints_data(cmd_type, data)
        if pos_data is None:
            print(f"❌ {desc}")
            return
        print(f"📄 {desc}")

        for part in body_parts:
            mover = BODY_PART_MOVERS.get(part)
            if mover is None:
                continue
            try:
                mover(pos_data)
                print(f"  ✅ {part} 控制成功")
            except Exception as e:
                print(f"  ❌ {part} 控制失败: {e}")
            time.sleep(0.2)

    return handler


def handle_tts(data, msg=None):
    """TTS 语音播报"""
    text = data
    print(f"🔊 TTS: {text}")
    try:
        interaction.play_tts(text)
        print("  ✅ TTS 播放成功")
        time.sleep(1)
    except Exception as e:
        print(f"  ❌ TTS 播放失败: {e}")


def handle_offset_move(data, msg=None):
    """
    末端相对移动
    data 格式: {"lx": 20, "ly": 0, "lz": 0, "rx": 0, "ry": 0, "rz": 0}
    数值单位：毫米，内部转换为米
    """
    # 毫米 → 米
    offset_l = (
        data.get("lx", 0.0) / 1000.0,
        data.get("ly", 0.0) / 1000.0,
        data.get("lz", 0.0) / 1000.0,
    )
    offset_r = (
        data.get("rx", 0.0) / 1000.0,
        data.get("ry", 0.0) / 1000.0,
        data.get("rz", 0.0) / 1000.0,
    )
    print(f"  左臂偏移 (mm): lx={data.get('lx', 0)}, ly={data.get('ly', 0)}, lz={data.get('lz', 0)}")
    print(f"  右臂偏移 (mm): rx={data.get('rx', 0)}, ry={data.get('ry', 0)}, rz={data.get('rz', 0)}")
    print(f"  换算 (m): L={offset_l}, R={offset_r}")
    try:
        ee_controller.adjust_arms_relative(offset_l=offset_l, offset_r=offset_r)
        print("  ✅ 末端移动完成")
    except Exception as e:
        print(f"  ❌ 末端移动失败: {e}")


def handle_grab(data, msg=None):
    """
    控制夹爪开合
    data 格式: {"left": -0.7, "right": -0.0}
    只操作传入的手，未传入的不操作
    """
    has_left = "left" in data
    has_right = "right" in data
    left_pos = data.get("left", 0.0)
    right_pos = data.get("right", 0.0)

    if has_left:
        print(f"  左夹爪 position={left_pos}")
    if has_right:
        print(f"  右夹爪 position={right_pos}")

    # 右夹爪
    if has_right:
        joint_states_r = agibot_gdk.JointStates()
        joint_states_r.group = "right_tool"
        joint_states_r.target_type = "omnipicker"
        joint_state_r = agibot_gdk.JointState()
        joint_state_r.position = right_pos
        joint_states_r.states = [joint_state_r]
        joint_states_r.nums = 1
        try:
            robot.move_ee_pos(joint_states_r)
            print("  ✅ 右夹爪控制成功")
            time.sleep(0.02)
        except Exception as e:
            print(f"  ❌ 右夹爪控制失败: {e}")

    # 左夹爪
    if has_left:
        joint_states_l = agibot_gdk.JointStates()
        joint_states_l.group = "left_tool"
        joint_states_l.target_type = "omnipicker"
        joint_state_l = agibot_gdk.JointState()
        joint_state_l.position = left_pos
        joint_states_l.states = [joint_state_l]
        joint_states_l.nums = 1
        try:
            robot.move_ee_pos(joint_states_l)
            print("  ✅ 左夹爪控制成功")
        except Exception as e:
            print(f"  ❌ 左夹爪控制失败: {e}")


def handle_cam_head(data, msg=None):
    """
    拍摄头部彩色+深度相机，通过 TCP 发送给检测服务
    data 可选指定 model 名称
    """
    model_name = data if isinstance(data, str) else DEFAULT_MODEL

    color_bytes = None
    depth_bytes = None

    # 拍摄彩色图
    try:
        color_img = camera.get_latest_image(agibot_gdk.CameraType.kHeadColor, 1000.0)
        if color_img is not None:
            print(f"  彩色相机：{color_img.width}x{color_img.height}")
            color_bytes = color_img.data
        else:
            print("  ⚠️ 未获取到彩色图像")
    except Exception as e:
        print(f"  ❌ 彩色相机异常: {e}")

    # 拍摄深度图
    try:
        depth_img = camera.get_latest_image(agibot_gdk.CameraType.kHeadDepth, 1000.0)
        if depth_img is not None:
            print(f"  深度相机：{depth_img.width}x{depth_img.height}")
            depth_bytes = depth_img.data
        else:
            print("  ⚠️ 未获取到深度图像")
    except Exception as e:
        print(f"  ❌ 深度相机异常: {e}")

    if color_bytes is None or depth_bytes is None:
        print("  ⚠️ 彩色图或深度图未获取到，跳过 TCP 发送")
        return

    # base64 编码
    rgb_b64 = base64.b64encode(color_bytes).decode("ascii")
    depth_b64 = base64.b64encode(depth_bytes).decode("ascii")

    payload = {
        "cmd": "detect",
        "rgb": rgb_b64,
        "depth": depth_b64,
        "model": model_name,
    }
    message = json.dumps(payload, ensure_ascii=False) + "\n"
    print(f"  📦 发送报文 model={model_name}, rgb_len={len(rgb_b64)}, depth_len={len(depth_b64)}")

    # TCP 发送并接收回复
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(60.0)
        sock.connect((TCP_HOST, TCP_PORT))
        sock.sendall(message.encode("utf-8"))
        print("  📨 报文已发送，等待回复...")

        received = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                print("  ⚠️ 接收超时")
                break
            if not chunk:
                break
            received += chunk
            if b"\n" in chunk:
                break

        if not received:
            print("  ⚠️ 未收到任何回复")
        else:
            print(f"  📨 收到回复，长度={len(received)} 字节")
            try:
                response_json = json.loads(received.decode("utf-8"))
                with open(RESPONSE_FILE, "w", encoding="utf-8") as f:
                    json.dump(response_json, f, ensure_ascii=False, indent=2)
                print(f"  ✅ 回复已保存为 {os.path.basename(RESPONSE_FILE)}")
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                with open(RESPONSE_FILE, "wb") as f:
                    f.write(received)
                print(f"  ⚠️ 回复非合法 JSON（{e}），原样保存")
    except Exception as e:
        print(f"  ❌ TCP 通信失败: {e}")
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def handle_go(data, msg=None):
    """
    导航到指定地图点位
    data 格式：整数导航点索引，如 9
    """
    try:
        waypoint = int(data)
    except (TypeError, ValueError):
        print(f"  ❌ 无效的导航点: {data}")
        return
    print(f"  导航到点位 {waypoint}")
    try:
        if not nav.go(waypoint):
            print(f"  ❌ 导航到点位 {waypoint} 失败")
        else:
            print(f"  ✅ 已到达点位 {waypoint}")
    except Exception as e:
        print(f"  ❌ 导航异常: {e}")


def handle_go_rel(data, msg=None):
    """
    底盘相对运动
    data 格式: {"x": 0, "y": 0, "yaw_rad": 0}
      x       : 前进位移（米），正=前进，负=后退
      y       : 左右位移（米），正=左，负=右
      yaw_rad : 旋转角度（弧度），正=左转，负=右转
    """
    dx = data.get("x", 0.0)
    dy = data.get("y", 0.0)
    yaw_rad = data.get("yaw_rad", 0.0)
    print(f"  底盘相对运动 dx={dx}m, dy={dy}m, yaw_rad={yaw_rad}rad")
    try:
        if not nav.go_rel(dx=dx, dy=dy, yaw_rad=yaw_rad):
            print("  ❌ 底盘相对运动失败")
        else:
            print("  ✅ 底盘相对运动完成")
    except Exception as e:
        print(f"  ❌ 底盘相对运动异常: {e}")


# ── 单关节控制 ────────────────────────────────────────────

# 关节名 → 所属部位 + 对应的关节键列表
JOINT_NAME_MAP = {}
for _keys in HEAD_JOINT_KEYS:
    JOINT_NAME_MAP[_keys] = ("head", HEAD_JOINT_KEYS, HEAD_SPEED)
for _keys in WAIST_JOINT_KEYS:
    JOINT_NAME_MAP[_keys] = ("waist", WAIST_JOINT_KEYS, WAIST_SPEED)
for _keys in LEFT_ARM_JOINT_KEYS + RIGHT_ARM_JOINT_KEYS:
    JOINT_NAME_MAP[_keys] = ("arms", LEFT_ARM_JOINT_KEYS + RIGHT_ARM_JOINT_KEYS, ARM_SPEED)


def _get_current_joints():
    """读取当前所有关节角度，返回 {关节名: 弧度} 字典"""
    try:
        joint_states = robot.get_joint_states()
        joints = {}
        for state in joint_states['states']:
            joints[state['name']] = state['motor_position']
        return joints
    except Exception as e:
        print(f"  ⚠ 读取关节状态失败: {e}")
        return {}


def handle_joint(data, msg=None):
    """单关节控制
    msg 格式:
      {"cmd": "joint", "name": "idx11_head_joint1", "offset": 0.01}  # 增量微调
      {"cmd": "joint", "name": "idx11_head_joint1", "value": 0.0}    # 直接运动到角度
    """
    if not isinstance(data, dict):
        print(f"❌ joint 命令 data 不是字典: {data}")
        return

    joint_name = data.get("name")
    if not joint_name:
        print("❌ joint 命令缺少 name 字段")
        return

    info = JOINT_NAME_MAP.get(joint_name)
    if info is None:
        print(f"❌ 未知关节名: {joint_name}")
        return

    part, keys, speed = info

    # 确定目标角度
    if "value" in data:
        target_value = float(data["value"])
    elif "offset" in data:
        # 增量微调：需要读取当前关节角度
        current = _get_current_joints()
        cur_val = current.get(joint_name, 0.0)
        target_value = cur_val + float(data["offset"])
        print(f"  {joint_name}: 当前={cur_val:.4f}, 偏移={data['offset']}, 目标={target_value:.4f}")
    else:
        print("❌ joint 命令需要 value 或 offset 字段")
        return

    # 以当前关节角度为基底，只修改目标关节，其余保持不变
    current = _get_current_joints()
    pos_data = {}
    for k in (HEAD_JOINT_KEYS + WAIST_JOINT_KEYS + LEFT_ARM_JOINT_KEYS + RIGHT_ARM_JOINT_KEYS):
        pos_data[k] = current.get(k, 0.0)
    pos_data[joint_name] = target_value

    if part == "head":
        pos = _extract_positions(pos_data, HEAD_JOINT_KEYS)
        vel = [speed] * len(pos)
        print(f"  头部关节 → {[f'{p:.4f}' for p in pos]}")
        robot.move_head_joint(pos, vel)
    elif part == "waist":
        pos = _extract_positions(pos_data, WAIST_JOINT_KEYS)
        vel = [speed] * len(pos)
        print(f"  腰部关节 → {[f'{p:.4f}' for p in pos]}")
        robot.move_waist_joint(pos, vel)
    elif part == "arms":
        left = _extract_positions(pos_data, LEFT_ARM_JOINT_KEYS)
        right = _extract_positions(pos_data, RIGHT_ARM_JOINT_KEYS)
        positions = left + right
        velocities = [speed] * len(positions)
        print(f"  手臂关节 → {[f'{p:.4f}' for p in positions]}")
        robot.move_arm_joint(positions, velocities, 2)


# ── 地图点位管理 ──────────────────────────────────────────

MAP_POINTS_DIR = os.path.join(PROJECT_DIR, "datas", "map_points")

def handle_read_map_points(data=None, msg=None):
    """读取所有地图点位（地图引导点 + 本地保存的点位），发布到 /minth/g2/map/points"""
    points = []

    # 1. 从地图读取引导点
    try:
        for name, wp in nav.waypoints.items():
            pos = wp.get("position", [0, 0, 0])
            ori = wp.get("orientation", [0, 0, 0, 1])
            points.append({
                "name": name,
                "source": wp.get("source", "map"),
                "position": pos,
                "orientation": ori,
            })
    except Exception as e:
        print(f"  ⚠ 读取地图引导点失败: {e}")

    # 2. 从本地文件读取保存的点位
    os.makedirs(MAP_POINTS_DIR, exist_ok=True)
    for fname in sorted(os.listdir(MAP_POINTS_DIR)):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(MAP_POINTS_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                pt = json.load(f)
            pt["source"] = "local"
            points.append(pt)
        except Exception as e:
            print(f"  ⚠ 跳过 {fpath}: {e}")

    resp = json.dumps({"cmd": "map_points", "data": points}, ensure_ascii=False)
    if mqtt_client:
        mqtt_client.publish(MQTT_MAP_POINTS_TOPIC, resp, qos=0)
    print(f"  ✅ 已发布 {len(points)} 个地图点位到 {MQTT_MAP_POINTS_TOPIC}")


def handle_save_map_point(data, msg=None):
    """保存当前底盘位姿为地图点位
    data: {"name": "point_name"}
    """
    save_name = data.get("name", "unnamed") if isinstance(data, dict) else "unnamed"
    os.makedirs(MAP_POINTS_DIR, exist_ok=True)

    # 获取当前位姿
    pose = nav.get_current_pose()
    pos = pose.get("position", [0, 0, 0])
    ori = pose.get("orientation", [0, 0, 0, 1])

    pt_data = {
        "name": save_name,
        "position": [round(pos[0], 6), round(pos[1], 6), round(pos[2], 6)],
        "orientation": [round(ori[0], 6), round(ori[1], 6), round(ori[2], 6), round(ori[3], 6)],
    }

    json_name = save_name if save_name.endswith('.json') else save_name + '.json'
    json_path = os.path.join(MAP_POINTS_DIR, json_name)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pt_data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 地图点位已保存: {json_path}")


# ═══════════════════════════════════════════════════════════
#  命令分发表
# ═══════════════════════════════════════════════════════════

CMD_HANDLERS = {
    "WBC":         make_joint_handler("WBC",   ["head", "waist", "arms"]),
    "arms":        make_joint_handler("arms",  ["arms"]),
    "left":        make_joint_handler("left",  ["left_arm"]),
    "right":       make_joint_handler("right", ["right_arm"]),
    "head":        make_joint_handler("head",  ["head"]),
    "waist":       make_joint_handler("waist", ["waist"]),
    "tts":         handle_tts,
    "offset_move": handle_offset_move,
    "grab":        handle_grab,
    "cam_head":    handle_cam_head,
    "go":             handle_go,
    "go_rel":         handle_go_rel,
    "joint":          handle_joint,
    "read_map_points": handle_read_map_points,
    "save_map_point":  handle_save_map_point,
}


# ═══════════════════════════════════════════════════════════
#  MQTT 回调
# ═══════════════════════════════════════════════════════════

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] 已连接到 {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC, qos=2)
        print(f"[MQTT] 已订阅: {MQTT_TOPIC}")
        print("-" * 60)
    else:
        print(f"[MQTT] 连接失败，返回码: {rc}")


def on_message(client, userdata, msg):
    """收到 MQTT 消息时分发命令"""
    try:
        payload = msg.payload.decode("utf-8")
        cmd_msg = json.loads(payload)
        cmd = cmd_msg.get("cmd")
        data = cmd_msg.get("data")
    except Exception as e:
        print(f"[解析失败] {e}，原始: {msg.payload}")
        return

    print(f"\n{'=' * 60}")
    print(f"[收到命令] cmd={cmd}, data={data}  (当前 state={get_state()})")
    print(f"{'=' * 60}")

    # 状态检查：busy 时拒绝新命令
    if get_state() == "busy":
        print("⚠️ 有命令正在执行，拒绝本次命令")
        return

    handler = CMD_HANDLERS.get(cmd)
    if handler is None:
        print(f"⚠️ 未知命令: {cmd}，支持的命令: {list(CMD_HANDLERS.keys())}")
        return

    # 标记为忙碌并执行
    set_state("busy")
    try:
        handler(data, cmd_msg)
    except Exception as e:
        print(f"❌ 命令执行异常: {e}")
    finally:
        set_state("idle")
        publish_done()
    print(f"{'─' * 60}\n")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main():
    global mqtt_client

    print("#" * 60)
    print("#   G2 Minth App 服务程序 - 启动   #")
    print("#" * 60)
    print(f"positions 目录: {POSITIONS_DIR}")
    print(f"joints 目录  : {JOINTS_DIR}")
    print(f"命令 topic : {MQTT_TOPIC}")
    print(f"完成 topic : {MQTT_DONE_TOPIC}")
    print(f"支持命令: {list(CMD_HANDLERS.keys())}")
    print()

    # 初始化 GDK
    init_gdk()

    # 启动 MQTT 监听
    mqtt_client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        print(f"[MQTT] 正在连接 {MQTT_BROKER}:{MQTT_PORT} ...")
        mqtt_client.loop_forever()
    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
    except Exception as e:
        print(f"[错误] {e}")
    finally:
        try:
            mqtt_client.disconnect()
        except Exception:
            pass
        release_gdk()
        print("🏁 服务已停止")


if __name__ == "__main__":
    main()
