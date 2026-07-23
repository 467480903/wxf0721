#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
map.py — 地图点位组件

职责：
  - 读取所有地图点位（地图引导点 + 本地保存的点位），发布到 /humanoid/map/points
  - 接收 /humanoid/map/control 命令：
      read_points    读取并发布所有地图点位
      save_point     保存当前底盘位姿为地图点位

消息格式（/humanoid/map/points，发布）：
  {"command": "map_points", "data": [{"name": "A", "source": "map", "position": [...], "orientation": [...]}]}

消息格式（/humanoid/map/control，订阅）：
  {"command": "read_points"}
  {"command": "save_point", "data": {"name": "point_name"}}
"""

import os
import json

import common
import data as db


# ═══════════════════════════════════════════════════════════
#  地图点位读取
# ═══════════════════════════════════════════════════════════

def read_all_map_points():
    """读取所有地图点位（地图引导点 + 数据库中的本地点位）

    Returns
    -------
    list[dict]
        点位列表，每项包含 name / source / position / orientation
    """
    points = []

    # 1. 从地图读取引导点
    try:
        for name, wp in common.nav.waypoints.items():
            pos = wp.get("position", [0, 0, 0])
            ori = wp.get("orientation", [0, 0, 0, 1])
            points.append({
                "name": name,
                "source": wp.get("source", "map"),
                "position": pos,
                "orientation": ori,
            })
    except Exception as e:
        print(f"  [地图] 读取地图引导点失败: {e}")

    # 2. 从数据库读取本地保存的点位
    for pt in db.get_map_points(source="local"):
        points.append(pt)

    return points


def handle_read_points():
    """读取所有地图点位并发布到 /humanoid/map/points"""
    points = read_all_map_points()
    resp = {"command": "map_points", "data": points}
    common.publish(common.TOPIC_MAP_POINTS, resp, qos=0)
    print(f"  [地图] 已发布 {len(points)} 个地图点位到 {common.TOPIC_MAP_POINTS}")


# ═══════════════════════════════════════════════════════════
#  地图点位保存
# ═══════════════════════════════════════════════════════════

def handle_save_point(data):
    """保存当前底盘位姿为地图点位到数据库

    data: {"name": "point_name"}
    """
    save_name = data.get("name", "unnamed") if isinstance(data, dict) else "unnamed"

    # 获取当前底盘位姿
    pose = common.nav.get_current_pose()
    pos = pose.get("position", [0, 0, 0])
    ori = pose.get("orientation", [0, 0, 0, 1])

    position = [round(pos[0], 6), round(pos[1], 6), round(pos[2], 6)]
    orientation = [round(ori[0], 6), round(ori[1], 6), round(ori[2], 6), round(ori[3], 6)]

    db.save_map_point(save_name, position, orientation, source="local")
    print(f"  [地图] 地图点位已保存到数据库: {save_name}")


# ═══════════════════════════════════════════════════════════
#  命令处理
# ═══════════════════════════════════════════════════════════

def handle_control(payload):
    """处理 /humanoid/map/control 命令

    Parameters
    ----------
    payload : dict
        命令消息，如 {"command": "read_points"}
    """
    cmd = payload.get("command")
    data = payload.get("data")

    if cmd == "read_points":
        handle_read_points()
    elif cmd == "save_point":
        handle_save_point(data)
    else:
        print(f"[地图] 未知命令: {cmd}")
