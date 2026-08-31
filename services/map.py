#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
map.py — 地图管理与SLAM建图组件

职责：
  - 读取所有地图点位（地图引导点 + 本地保存的点位），发布到 /humanoid/map/points
  - 接收 /humanoid/map/control 命令：
      read_points      读取并发布所有地图点位
      save_point       保存当前底盘位姿为地图点位
      start_mapping    开始SLAM建图
      stop_mapping     结束建图（保存地图）
      read_maps        读取并发布地图列表
      switch_map       切换到指定地图

消息格式（/humanoid/map/points，发布）：
  {"command": "map_points", "data": [{"name": "A", "source": "map", "position": [...], "orientation": [...]}]}

消息格式（/humanoid/map/info，发布）：
  {"command": "maps", "data": [{"id": "xxx", "name": "xxx", "is_current": true}]}
  {"command": "slam_state", "data": {"state": "mapping/idle", "is_mapping": true/false}}

消息格式（/humanoid/map/control，订阅）：
  {"command": "read_points"}
  {"command": "save_point", "data": {"name": "point_name"}}
  {"command": "start_mapping"}
  {"command": "stop_mapping"}
  {"command": "read_maps"}
  {"command": "switch_map", "data": {"map_id": "xxx"}}
"""

import os
import json
import base64
import struct

import common
import data as db

# 本地跟踪建图状态（GDK接口没有直接暴露is_mapping布尔值）
_is_mapping = False


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
    for pt in db.get_map_points():
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
#  SLAM 建图控制
# ═══════════════════════════════════════════════════════════

def handle_start_mapping():
    """开始SLAM建图"""
    global _is_mapping
    try:
        common.slam.start_mapping()
        _is_mapping = True
        print("  [SLAM] 开始建图")
        publish_slam_state()
    except Exception as e:
        print(f"  [SLAM] 开始建图失败: {e}")


def handle_stop_mapping():
    """结束SLAM建图（保存地图）"""
    global _is_mapping
    try:
        common.slam.stop_mapping()
        _is_mapping = False
        print("  [SLAM] 结束建图，地图已保存")
        publish_slam_state()
        publish_maps_list()
    except Exception as e:
        print(f"  [SLAM] 结束建图失败: {e}")


def handle_save_map():
    """保存当前地图（调用 stop_mapping 完成保存）"""
    global _is_mapping
    try:
        common.slam.stop_mapping()
        _is_mapping = False
        print("  [SLAM] 地图已保存")
        publish_slam_state()
        publish_maps_list()
    except Exception as e:
        print(f"  [SLAM] 保存地图失败: {e}")


def publish_slam_state():
    """发布当前SLAM状态到 /humanoid/map/info"""
    resp = {"command": "slam_state", "data": {"is_mapping": _is_mapping}}
    common.publish(common.TOPIC_MAP_INFO, resp, qos=0)


# ═══════════════════════════════════════════════════════════
#  地图列表管理
# ═══════════════════════════════════════════════════════════

def publish_maps_list():
    """读取并发布所有地图列表到 /humanoid/map/info"""
    try:
        all_maps = common.gmap.get_all_map()
        maps_data = []
        for m in all_maps:
            mid = m.id
            mname = m.name
            is_curr = m.is_curr_map
            maps_data.append({"id": mid, "name": mname, "is_current": is_curr})
        resp = {"command": "maps", "data": maps_data}
        common.publish(common.TOPIC_MAP_INFO, resp, qos=0)
        print(f"  [地图] 已发布 {len(maps_data)} 个地图")
    except Exception as e:
        print(f"  [地图] 读取地图列表失败: {e}")


def publish_occupancy_grid(map_id=None):
    """获取并发布当前地图的 OccupancyGrid 栅格数据到 /humanoid/map/grid

    Parameters
    ----------
    map_id : int or None
        地图 ID，为 None 时使用当前地图
    """
    try:
        if map_id is not None:
            map_info = common.gmap.get_map(int(map_id))
        else:
            curr_map = common.gmap.get_curr_map()
            map_info = common.gmap.get_map(curr_map.id)

        grid = map_info.grid_map

        origin_pos = grid.origin.position
        origin_ori = grid.origin.orientation

        data_bytes = struct.pack(f'{len(grid.data)}b', *grid.data)
        data_b64 = base64.b64encode(data_bytes).decode('ascii')

        payload = {
            "command": "occupancy_grid",
            "data": {
                "map_id": map_info.id,
                "map_name": map_info.name,
                "width": grid.width,
                "height": grid.height,
                "resolution": grid.resolution,
                "origin": {
                    "position": [origin_pos.x, origin_pos.y, origin_pos.z],
                    "orientation": [origin_ori.x, origin_ori.y, origin_ori.z, origin_ori.w],
                },
                "data_b64": data_b64,
            },
        }
        common.publish(common.TOPIC_MAP_GRID, payload, qos=0)
        print(f"  [地图] 已发布栅格地图: {map_info.name} "
              f"({grid.width}x{grid.height}, resolution={grid.resolution}, "
              f"data={len(grid.data)} bytes)")
    except Exception as e:
        print(f"  [地图] 发布栅格地图失败: {e}")


def handle_read_maps():
    """处理读取地图列表命令"""
    publish_maps_list()
    publish_slam_state()
    publish_occupancy_grid()


def handle_switch_map(map_id):
    """切换到指定地图"""
    try:
        mid = int(map_id)
        common.gmap.switch_map(mid)
        print(f"  [地图] 已切换到地图: {mid}")
        common.nav.list_waypoints()
        publish_maps_list()
        publish_occupancy_grid(mid)
    except Exception as e:
        print(f"  [地图] 切换地图失败: {e}")


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

    if cmd in ("read_points", "read_map_points"):
        handle_read_points()
    elif cmd in ("save_point", "save_map_point"):
        handle_save_point(data)
    elif cmd == "start_mapping":
        handle_start_mapping()
    elif cmd == "stop_mapping":
        handle_stop_mapping()
    elif cmd == "save_map":
        handle_save_map()
    elif cmd == "read_maps":
        handle_read_maps()
    elif cmd == "load_grid":
        grid_map_id = data.get("map_id") if isinstance(data, dict) else None
        publish_occupancy_grid(grid_map_id)
    elif cmd == "switch_map":
        map_id = data.get("map_id") if isinstance(data, dict) else data
        if map_id:
            handle_switch_map(map_id)
    else:
        print(f"[地图] 未知命令: {cmd}")


# ═══════════════════════════════════════════════════════════
#  DB 地图点位管理（只操作 robot_data.db，不读写 G2 地图）
# ═══════════════════════════════════════════════════════════

def _publish_db_points():
    """读取 map_points 全表并发布到 /humanoid/map/db_data"""
    points = db.get_map_points()
    resp = {"command": "db_points", "data": points}
    common.publish(common.TOPIC_MAP_DB_DATA, resp, qos=0)
    print(f"  [地图DB] 已发布 {len(points)} 条点位到 {common.TOPIC_MAP_DB_DATA}")
    return points


def _find_db_point(name, source):
    """按 name(+source) 在 map_points 表中查一条点位，找不到返回 None"""
    for pt in db.get_map_points():
        if pt["name"] == name and (source is None or pt["source"] == source):
            return pt
    return None


def handle_db_control(payload):
    """处理 /humanoid/map/db_control 命令（纯数据库操作，不触碰 G2 地图）

    payload : dict
        {"command": "read"}
        {"command": "update", "data": {"name": "A", "source": "local",
         "position": [x,y,z], "orientation": [x,y,z,w]}}
        {"command": "delete", "data": {"name": "A", "source": "local"}}
        {"command": "goto",   "data": {"name": "A", "source": "local"}}
    """
    cmd = payload.get("command")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    name = data.get("name")
    source = data.get("source")

    if cmd == "read":
        _publish_db_points()

    elif cmd == "update":
        position = data.get("position")
        orientation = data.get("orientation")
        if not name or not isinstance(position, (list, tuple)) or len(position) < 2:
            print(f"  [地图DB] update 参数无效: name={name}, position={position}")
            return
        if not isinstance(orientation, (list, tuple)) or len(orientation) < 4:
            orientation = [0, 0, 0, 1]
        db.save_map_point(name, list(position), list(orientation),
                          source=source or "local")
        print(f"  [地图DB] 已更新点位: {name} ({source or 'local'})")
        _publish_db_points()

    elif cmd == "delete":
        if not name:
            print(f"  [地图DB] delete 缺少 name")
            return
        db.delete_map_point(name)
        print(f"  [地图DB] 已删除点位: {name} ({source or 'local'})")
        _publish_db_points()

    elif cmd == "goto":
        # 「到位」：按 DB 坐标直接导航（只运动，不修改 G2 地图数据）
        if not name:
            print(f"  [地图DB] goto 缺少 name")
            return
        pt = _find_db_point(name, source)
        if pt is None:
            print(f"  [地图DB] 找不到点位: {name}")
            common.publish(common.TOPIC_MAP_DB_DATA,
                           {"command": "goto_result",
                            "data": {"name": name, "success": False,
                                     "message": "点位不存在"}}, qos=0)
            return
        print(f"  [地图DB] 到位: {name} → {pt['position']}")
        ok = common.nav.go_by_pose(pt["position"], pt["orientation"], name=name)
        common.publish(common.TOPIC_MAP_DB_DATA,
                       {"command": "goto_result",
                        "data": {"name": name, "success": bool(ok),
                                 "message": "已到达" if ok else "导航失败"}}, qos=0)

    else:
        print(f"[地图DB] 未知命令: {cmd}")
