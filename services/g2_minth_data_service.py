#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G2 数据读写服务程序

专门处理数据持久化操作，与 app_service 解耦。

监听 topic：
  - /G2_minth_save_joints    : 保存关节角到 datas/joints/{type}/{name}.json
  - /G2_minth_save_position  : 保存末端位姿到 datas/positions/{type}/{name}.json

消息格式：
  保存关节角：
    {"cmd": "save_joints", "type": "WBC", "name": "hold",
     "data": {"idx11_head_joint1": 0.1, ...}}

  保存末端位姿：
    {"cmd": "save_position", "type": "left", "name": "pick",
     "data": {"x": 0.1, "y": 0.2, "z": 0.3, "rx": 0, "ry": 0, "rz": 0}}
    type 可选: left / right / both
      - both 时 data 包含 left 和 right 两个子对象
"""

import os
import sys
import json
import time

import paho.mqtt.client as mqtt

# ── 路径配置 ───────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
JOINTS_DIR = os.path.join(PROJECT_DIR, "datas", "joints")
POSITIONS_DIR = os.path.join(PROJECT_DIR, "datas", "positions")

# ── MQTT 配置 ─────────────────────────────────────────────
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "g2_data_service"

TOPIC_SAVE_JOINTS = "/G2_minth_save_joints"
TOPIC_SAVE_POSITION = "/G2_minth_save_position"
TOPIC_DATA_REQ = "/minth/g2/data"
TOPIC_DATA_RESP = "/minth/g2/data/response"

# 关节类型目录（datas/joints/ 下的子目录名）
JOINT_TYPES = ["WBC", "arms", "left", "right", "head", "waist"]
# 位姿类型目录（datas/positions/ 下的子目录名）
POSITION_TYPES = ["left", "right", "both"]


# ═══════════════════════════════════════════════════════════
#  保存接口
# ═══════════════════════════════════════════════════════════

def save_joints(msg):
    """保存关节角
    msg: {"type": "WBC", "name": "hold", "data": {关节名: 弧度}}
    """
    save_type = msg.get("type", "WBC")
    save_name = msg.get("name", "unnamed")
    joints = msg.get("data", {})
    if not isinstance(joints, dict):
        print(f"  ❌ data 不是字典: {type(joints)}")
        return

    save_dir = os.path.join(JOINTS_DIR, save_type)
    os.makedirs(save_dir, exist_ok=True)

    json_name = save_name if save_name.endswith('.json') else save_name + '.json'
    json_path = os.path.join(save_dir, json_name)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(joints, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 关节角已保存: {json_path} ({len(joints)} 个关节)")


def save_position(msg):
    """保存末端位姿
    msg: {"type": "left"/"right"/"both", "name": "pick",
          "data": {"x":0.1, "y":0.2, "z":0.3, "rx":0, "ry":0, "rz":0}}
    both 时 data = {"left": {...}, "right": {...}}
    """
    save_type = msg.get("type", "both")
    save_name = msg.get("name", "unnamed")
    pos_data = msg.get("data", {})
    if not isinstance(pos_data, dict):
        print(f"  ❌ data 不是字典: {type(pos_data)}")
        return

    save_dir = os.path.join(POSITIONS_DIR, save_type)
    os.makedirs(save_dir, exist_ok=True)

    json_name = save_name if save_name.endswith('.json') else save_name + '.json'
    json_path = os.path.join(save_dir, json_name)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pos_data, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 末端位姿已保存: {json_path}")


# ═══════════════════════════════════════════════════════════
#  数据读写接口
# ═══════════════════════════════════════════════════════════

def read_all_data():
    """扫描 joints 和 positions 目录，返回所有数据条目"""
    items = []

    # 扫描关节数据
    if os.path.exists(JOINTS_DIR):
        for jtype in JOINT_TYPES:
            type_dir = os.path.join(JOINTS_DIR, jtype)
            if not os.path.isdir(type_dir):
                continue
            for fname in sorted(os.listdir(type_dir)):
                if not fname.endswith('.json'):
                    continue
                fpath = os.path.join(type_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        value = json.load(f)
                    items.append({
                        "category": "joints",
                        "type": jtype,
                        "name": fname[:-5],   # 去掉 .json
                        "value": value
                    })
                except Exception as e:
                    print(f"  ⚠ 跳过 {fpath}: {e}")

    # 扫描位姿数据
    if os.path.exists(POSITIONS_DIR):
        for ptype in POSITION_TYPES:
            type_dir = os.path.join(POSITIONS_DIR, ptype)
            if not os.path.isdir(type_dir):
                continue
            for fname in sorted(os.listdir(type_dir)):
                if not fname.endswith('.json'):
                    continue
                fpath = os.path.join(type_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        value = json.load(f)
                    items.append({
                        "category": "positions",
                        "type": ptype,
                        "name": fname[:-5],
                        "value": value
                    })
                except Exception as e:
                    print(f"  ⚠ 跳过 {fpath}: {e}")

    print(f"  📋 读取到 {len(items)} 条数据")
    return items


def handle_read(client):
    """处理 read 命令：扫描目录并发布数据列表"""
    items = read_all_data()
    resp = json.dumps({"cmd": "response", "data": items}, ensure_ascii=False)
    client.publish(TOPIC_DATA_RESP, resp, qos=0)
    print(f"  ✅ 已发布 {len(items)} 条数据到 {TOPIC_DATA_RESP}")


def handle_update(msg):
    """处理 update 命令：更新指定数据文件
    msg: {category: joints/positions, type: WBC, name: hold, data: {...}}
    """
    category = msg.get("category", "joints")
    update_type = msg.get("type", "WBC")
    update_name = msg.get("name", "unnamed")
    data = msg.get("data", {})

    base_dir = JOINTS_DIR if category == "joints" else POSITIONS_DIR
    save_dir = os.path.join(base_dir, update_type)
    os.makedirs(save_dir, exist_ok=True)

    json_name = update_name if update_name.endswith('.json') else update_name + '.json'
    json_path = os.path.join(save_dir, json_name)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 已更新 {json_path}")


def handle_delete(msg):
    """处理 delete 命令：删除指定数据文件
    msg: {category: joints/positions, type: WBC, name: hold}
    """
    category = msg.get("category", "joints")
    del_type = msg.get("type", "WBC")
    del_name = msg.get("name", "")

    base_dir = JOINTS_DIR if category == "joints" else POSITIONS_DIR
    json_name = del_name if del_name.endswith('.json') else del_name + '.json'
    json_path = os.path.join(base_dir, del_type, json_name)

    if os.path.exists(json_path):
        os.remove(json_path)
        print(f"  🗑 已删除 {json_path}")
    else:
        print(f"  ⚠ 文件不存在: {json_path}")


# ═══════════════════════════════════════════════════════════
#  MQTT
# ═══════════════════════════════════════════════════════════

# 命令分发表
CMD_HANDLERS = {
    "save_joints":   save_joints,
    "save_position": save_position,
}


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] 已连接到 {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(TOPIC_SAVE_JOINTS, qos=0)
        client.subscribe(TOPIC_SAVE_POSITION, qos=0)
        client.subscribe(TOPIC_DATA_REQ, qos=0)
        print(f"[MQTT] 已订阅: {TOPIC_SAVE_JOINTS}, {TOPIC_SAVE_POSITION}, {TOPIC_DATA_REQ}")
        print("-" * 60)
    else:
        print(f"[MQTT] 连接失败，返回码: {rc}")


def on_message(client, userdata, msg):
    """收到 MQTT 消息时分发命令"""
    try:
        payload = msg.payload.decode("utf-8")
        cmd_msg = json.loads(payload)
        cmd = cmd_msg.get("cmd")
    except Exception as e:
        print(f"[解析失败] {e}，原始: {msg.payload}")
        return

    print(f"\n{'=' * 60}")
    print(f"[收到命令] topic={msg.topic}, cmd={cmd}")
    print(f"{'=' * 60}")

    # 数据读写命令（需要 client 参数来发布响应）
    if cmd == "read":
        handle_read(client)
        return
    if cmd == "update":
        handle_update(cmd_msg)
        return
    if cmd == "delete":
        handle_delete(cmd_msg)
        return

    # 保存命令
    handler = CMD_HANDLERS.get(cmd)
    if handler is None:
        print(f"⚠️ 未知命令: {cmd}，支持的命令: {list(CMD_HANDLERS.keys())} + read/update/delete")
        return

    try:
        handler(cmd_msg)
    except Exception as e:
        print(f"❌ 命令执行异常: {e}")
    print(f"{'─' * 60}\n")


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main():
    print("#" * 60)
    print("#   G2 数据读写服务 - 启动   #")
    print("#" * 60)
    print(f"joints 目录    : {JOINTS_DIR}")
    print(f"positions 目录 : {POSITIONS_DIR}")
    print(f"save_joints topic   : {TOPIC_SAVE_JOINTS}")
    print(f"save_position topic : {TOPIC_SAVE_POSITION}")
    print(f"data req topic      : {TOPIC_DATA_REQ}")
    print(f"data resp topic     : {TOPIC_DATA_RESP}")
    print(f"支持命令: save_joints, save_position, read, update, delete")
    print()

    # 确保目录存在
    os.makedirs(JOINTS_DIR, exist_ok=True)
    os.makedirs(POSITIONS_DIR, exist_ok=True)

    client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        print(f"[MQTT] 正在连接 {MQTT_BROKER}:{MQTT_PORT} ...")
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
    except Exception as e:
        print(f"[错误] {e}")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        print("🏁 程序结束")


if __name__ == "__main__":
    main()
