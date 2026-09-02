#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
positions.py — 末端位姿（坐标点位）组件

职责：
  1. 坐标点位运动控制（接收 /humanoid/positions/control 命令）
     - goto    末端运动到数据库位姿（left/right 单臂，both 双臂）
     - update  用机器人当前末端位姿覆盖数据库记录

  2. 位姿数据持久化（接收 /humanoid/joints/save 命令，分流到 positions）
     - save_position：保存末端位姿到数据库
     - update / delete：更新或删除指定位姿数据（category=positions）

  数据格式（与 teach 页面保存约定一致）：
    {"x": 米, "y": 米, "z": 米,
     "rx": 四元数x, "ry": 四元数y, "rz": 四元数z}
    四元数 w 分量未存储，由 sqrt(1-x²-y²-z²) 恢复；
    四元数双重覆盖（q 与 -q 表示同一姿态），恢复结果物理等价。
    both 类型时 value = {"left": {...}, "right": {...}}

消息格式（/humanoid/positions/control，订阅）：
  {"command": "goto",   "data": {"type": "right", "name": "P1"}}
  {"command": "update", "data": {"type": "right", "name": "P1"}}

消息格式（/humanoid/joints/save，由 main.py 分流）：
  {"command": "save_position", "type": "left", "name": "pick", "data": {...}}
  {"command": "update", "category": "positions", "type": "left", "name": "P1", "data": {...}}
  {"command": "delete", "category": "positions", "type": "left", "name": "P1"}

结果发布（/humanoid/positions/data）：
  {"command": "goto_result",   "data": {"name": "P1", "success": true, "message": "已到位"}}
  {"command": "update_result", "data": {"name": "P1", "success": true, "message": "已更新"}}
"""

import math

import common
import data as db

# 末端 link 名（与 status.py / EndEffectorController.py 一致）
LEFT_NAME = "arm_l_end_link"
RIGHT_NAME = "arm_r_end_link"

SUPPORTED_TYPES = ("left", "right", "both")


# ═══════════════════════════════════════════════════════════
#  数据格式转换
# ═══════════════════════════════════════════════════════════

def _value_to_pose(value):
    """存储格式 {x,y,z,rx,ry,rz} → {"position": [...], "orientation": [qx,qy,qz,qw]}"""
    def f(key, default=0.0):
        try:
            return float(value.get(key, default))
        except (TypeError, ValueError):
            return default

    qx, qy, qz = f("rx"), f("ry"), f("rz")
    w2 = 1.0 - (qx * qx + qy * qy + qz * qz)
    qw = math.sqrt(w2) if w2 > 0.0 else 0.0
    return {
        "position": [f("x"), f("y"), f("z")],
        "orientation": [qx, qy, qz, qw],
    }


def _pose_to_value(position, orientation):
    """当前末端位姿 → 存储格式（丢 w，与 teach 页面保存约定一致）"""
    return {
        "x":  round(float(position[0]), 6),
        "y":  round(float(position[1]), 6),
        "z":  round(float(position[2]), 6),
        "rx": round(float(orientation[0]), 6),
        "ry": round(float(orientation[1]), 6),
        "rz": round(float(orientation[2]), 6),
    }


def _find_position(ptype, name):
    """按 type+name 在 positions 表中查一条记录，找不到返回 None"""
    for row in db.get_positions():
        if row["type"] == ptype and row["name"] == name:
            return row
    return None


def _read_end_pose(side):
    """读取指定侧末端当前位姿，返回 {"position": [...], "orientation": [...]} 或 None"""
    link = LEFT_NAME if side == "left" else RIGHT_NAME
    status = common.robot.get_motion_control_status()
    for i, frame_name in enumerate(status.frame_names):
        if frame_name == link:
            p = status.frame_poses[i]
            return {
                "position": [p.position.x, p.position.y, p.position.z],
                "orientation": [p.orientation.x, p.orientation.y,
                                p.orientation.z, p.orientation.w],
            }
    return None


def _publish_result(cmd, name, success, message):
    """发布执行结果到 /humanoid/positions/data"""
    common.publish(common.TOPIC_POSITIONS_DATA,
                   {"command": cmd,
                    "data": {"name": name, "success": bool(success),
                             "message": message}}, qos=0)


# ═══════════════════════════════════════════════════════════
#  命令实现
# ═══════════════════════════════════════════════════════════

def _apply_offset(value, offset):
    """对存储格式的位姿值应用偏移，返回新的 value 字典

    offset 只支持 x/y/z 平移偏移，单位毫米
    value 中 x/y/z 为米，rx/ry/rz 为四元数 x/y/z 分量
    """
    result = dict(value)
    # 平移偏移：毫米 → 米，直接加
    for k in ("x", "y", "z"):
        if k in offset:
            try:
                result[k] = float(result.get(k, 0.0)) + float(offset[k]) / 1000.0
            except (TypeError, ValueError):
                pass
    return result


def handle_goto(ptype, name, offset=None):
    """末端运动到位：按 positions 表中的位姿执行绝对运动，可附加偏移"""
    row = _find_position(ptype, name)
    if row is None:
        print(f"  [坐标] 找不到 positions/{ptype}/{name}")
        _publish_result("goto_result", name, False, f"找不到 positions/{ptype}/{name}")
        return
    value = row["value"]

    # 应用偏移
    if offset:
        if ptype == "both":
            value = {"left": _apply_offset(value.get("left", {}), offset),
                     "right": _apply_offset(value.get("right", {}), offset)}
        else:
            value = _apply_offset(value, offset)
        print(f"  [坐标] 已应用偏移: {offset}")

    if ptype == "both":
        target_l = _value_to_pose(value.get("left", {}))
        target_r = _value_to_pose(value.get("right", {}))
        ok = common.ee_controller.move_arms_to(target_l=target_l, target_r=target_r)
    elif ptype == "left":
        ok = common.ee_controller.move_arms_to(target_l=_value_to_pose(value))
    else:  # right
        ok = common.ee_controller.move_arms_to(target_r=_value_to_pose(value))

    _publish_result("goto_result", name, ok, "已到位" if ok else "运动失败")


def handle_update(ptype, name):
    """更新：用当前末端位姿覆盖数据库记录"""
    if ptype == "both":
        pose_l = _read_end_pose("left")
        pose_r = _read_end_pose("right")
        if pose_l is None or pose_r is None:
            _publish_result("update_result", name, False, "读取末端位姿失败")
            return
        value = {"left": _pose_to_value(pose_l["position"], pose_l["orientation"]),
                 "right": _pose_to_value(pose_r["position"], pose_r["orientation"])}
    else:
        pose = _read_end_pose(ptype)
        if pose is None:
            _publish_result("update_result", name, False, "读取末端位姿失败")
            return
        value = _pose_to_value(pose["position"], pose["orientation"])

    db.save_positions(ptype, name, value)
    print(f"  [坐标] 已用当前位姿更新: {ptype}/{name}")
    _publish_result("update_result", name, True, "已更新")


# ═══════════════════════════════════════════════════════════
#  数据持久化（save_position / update / delete）
# ═══════════════════════════════════════════════════════════

def handle_save(payload):
    """处理 /humanoid/joints/save 中与位姿相关的命令

    payload : dict
        {"command": "save_position", "type": "left", "name": "pick", "data": {...}}
        {"command": "update", "category": "positions", "type": "left", "name": "P1", "data": {...}}
        {"command": "delete", "category": "positions", "type": "left", "name": "P1"}
    """
    cmd = payload.get("command")

    if cmd == "save_position":
        _save_position(payload)
    elif cmd == "update":
        _handle_update(payload)
    elif cmd == "delete":
        _handle_delete(payload)
    else:
        print(f"[坐标] 未知 save 命令: {cmd}")


def _save_position(msg):
    """保存末端位姿到数据库

    msg: {"type": "left"/"right"/"both", "name": "pick",
          "data": {"x":0.1, "y":0.2, "z":0.3, "rx":0, "ry":0, "rz":0}}
    both 时 data = {"left": {...}, "right": {...}}
    """
    save_type = msg.get("type", "both")
    save_name = msg.get("name", "unnamed")
    pos_data = msg.get("data", {})
    if not isinstance(pos_data, dict):
        print(f"  [保存] data 不是字典: {type(pos_data)}")
        return

    db.save_positions(save_type, save_name, pos_data)
    print(f"  [保存] 末端位姿已保存到数据库: {save_type}/{save_name}")


def _handle_update(msg):
    """更新数据库中的位姿数据

    msg: {category: positions, type: left, name: P1, data: {...}}
    """
    category = msg.get("category", "positions")
    if category != "positions":
        return  # 非 positions 类由 joints.py 处理
    update_type = msg.get("type", "both")
    update_name = msg.get("name", "unnamed")
    data = msg.get("data", {})

    db.update_data("positions", update_type, update_name, data)
    print(f"  [更新] 已更新 positions/{update_type}/{update_name}")


def _handle_delete(msg):
    """删除数据库中的位姿数据

    msg: {category: positions, type: left, name: P1}
    """
    category = msg.get("category", "positions")
    if category != "positions":
        return  # 非 positions 类由 joints.py 处理
    del_type = msg.get("type", "both")
    del_name = msg.get("name", "")

    db.delete_data("positions", del_type, del_name)
    print(f"  [删除] 已删除 positions/{del_type}/{del_name}")


# ═══════════════════════════════════════════════════════════
#  命令分发（goto / update 运动控制）
# ═══════════════════════════════════════════════════════════

def handle_control(payload):
    """处理 /humanoid/positions/control 命令

    payload : dict
        {"command": "goto",   "data": {"type": "right", "name": "P1"}}
        {"command": "update", "data": {"type": "right", "name": "P1"}}
    """
    cmd = payload.get("command")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    ptype = data.get("type")
    name = data.get("name")

    if ptype not in SUPPORTED_TYPES or not name:
        print(f"  [坐标] 参数无效: type={ptype}, name={name}")
        _publish_result(f"{cmd}_result" if cmd else "error", name,
                        False, "缺少有效的 type/name")
        return

    try:
        if cmd == "goto":
            offset = data.get("offset")
            if offset:
                print(f"[坐标] 到位: {ptype}/{name} +偏移 {offset}")
            else:
                print(f"[坐标] 到位: {ptype}/{name}")
            handle_goto(ptype, name, offset)
        elif cmd == "update":
            print(f"[坐标] 更新: {ptype}/{name}")
            handle_update(ptype, name)
        else:
            print(f"[坐标] 未知命令: {cmd}")
    except Exception as e:
        print(f"[坐标] 命令执行异常: {e}")
        _publish_result(f"{cmd}_result" if cmd else "error", name, False, str(e))
