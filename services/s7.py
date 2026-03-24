#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s7.py — 西门子 S7 协议读写组件（synch 同步版，基于 python-snap7）

职责：
  - 加载 datas/s7.json 配置，初始化 data.synch 中的 s7 条目
  - 后台线程按 rate 周期读取 DB 块数据
      → 更新 data.synch 中 read 条目的 value（state=1）
  - 后台线程周期扫描 synch 中 state==1 的 write 条目
      → 写入 S7 设备 → 标记 state=2

依赖：python-snap7（pip install python-snap7）

s7.json 格式：
  [
    {
      "name": "s1200",
      "ip": "10.2.250.51",
      "port": 102,
      "rack": 0,
      "slot": 1,
      "read": [
        {"name": "pick_right", "addr": "DB8.DBX2.1", "type": "bool"}
      ],
      "write": [
        {"name": "pick_right_done", "addr": "DB8.DBX0.2", "type": "bool"}
      ],
      "rate": 100
    }
  ]

  地址格式：DB{num}.DB{B|W|D|X}{offset}[.bit]
    DBB = Byte (1 字节), DBW = Word (2 字节), DBD = DWord (4 字节)
    DBX = Bit（bool，如 DB8.DBX2.1 表示 DB8 字节 2 的第 1 位）
"""

import os
import re
import json
import time
import threading

import snap7
from snap7.client import Client as Snap7Client
from snap7.util import get_bool, set_bool

import common
import data as db

# ── 配置 ───────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(common.DATAS_DIR, "s7.json")
_devices = []
_thread_running = False
_thread = None
_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════
#  S7 地址解析（"DB1.DBW0" → db=1, start=0, size=2, bit=None）
# ═══════════════════════════════════════════════════════════

# 地址前缀 → 字节数
_PREFIX_SIZE = {"B": 1, "W": 2, "D": 4}

# 匹配 "DB1.DBW0" / "DB12.DBD4" / "DB1.DBB10"
_ADDR_RE = re.compile(r"^DB(\d+)\.DB([BWD])(\d+)$", re.IGNORECASE)
# 匹配位地址 "DB8.DBX2.1"（bool）
_ADDR_BIT_RE = re.compile(r"^DB(\d+)\.DBX(\d+)\.(\d+)$", re.IGNORECASE)


def _parse_s7_addr(addr):
    """解析 S7 地址字符串 → (db_number, start_byte, size_bytes, bit)

    支持格式：
      DB1.DBW0   → (1, 0, 2, None)   Word
      DB1.DBD0   → (1, 0, 4, None)   DWord
      DB1.DBB0   → (1, 0, 1, None)   Byte
      DB8.DBX2.1 → (8, 2, 1, 1)      Bit（bool，按字节读写后取位）
    """
    m = _ADDR_BIT_RE.match(addr.strip())
    if m:
        db_num = int(m.group(1))
        start = int(m.group(2))
        bit = int(m.group(3))
        if not 0 <= bit <= 7:
            raise ValueError(f"位号超出范围 (0-7): {addr}")
        return db_num, start, 1, bit
    m = _ADDR_RE.match(addr.strip())
    if not m:
        raise ValueError(f"无法解析 S7 地址: {addr}")
    db_num = int(m.group(1))
    prefix = m.group(2).upper()
    start = int(m.group(3))
    size = _PREFIX_SIZE[prefix]
    return db_num, start, size, None


def _extract_value(raw, item):
    """从原始字节中取值：bool 取位，其他按大端整数"""
    if raw is None or len(raw) == 0:
        return None
    bit = item.get("bit")
    if bit is not None:
        return int(get_bool(raw, 0, bit))
    return int.from_bytes(raw, byteorder="big")


def _connect(dev):
    """建立 snap7 连接"""
    client = Snap7Client()
    client.connect(dev["ip"], dev["rack"], dev["slot"], dev["port"])
    return client


# ═══════════════════════════════════════════════════════════
#  数据读取与发布
# ═══════════════════════════════════════════════════════════

def _read_device(dev):
    """读取单个设备的所有 read/write items"""
    try:
        client = _connect(dev)
    except Exception as e:
        print(f"[S7] 连接 {dev['ip']}:{dev['port']} 失败: {e}")
        return [], []

    read_result = []
    write_result = []
    try:
        for item in dev.get("read_items", []):
            try:
                raw = client.db_read(item["db"], item["start"], item["size"])
            except Exception as e:
                print(f"[S7] 读取 {item['addr']} ({item['name']}) 失败: {e}")
                raw = None
            val = _extract_value(raw, item)
            read_result.append({
                "addr": item.get("addr", ""),
                "name": item["name"],
                "value": val,
            })
            if val is not None:
                db.synch_update_read(item["name"], val)

        # 读回 write 区域当前值（用于前端显示）
        for item in dev.get("write_items", []):
            try:
                raw = client.db_read(item["db"], item["start"], item["size"])
            except Exception as e:
                print(f"[S7] 读取 {item['addr']} ({item['name']}) 失败: {e}")
                raw = None
            val = _extract_value(raw, item)
            write_result.append({
                "addr": item.get("addr", ""),
                "name": item["name"],
                "value": val,
            })
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
    return read_result, write_result


def _publish_device(dev):
    """读取并发布单个设备数据"""
    try:
        read_result, write_result = _read_device(dev)
        common.publish(common.TOPIC_MODBUS_DATA, {
            "command": "s7_data",
            "devices": [{
                "name": dev.get("name", ""),
                "ip": dev["ip"],
                "read": read_result,
                "write": write_result,
            }]
        })
    except Exception as e:
        print(f"[S7] 读取 {dev['ip']} 失败: {e}")


def _process_pending_writes(dev):
    """扫描 synch 中该设备 state==1 的 write 条目，写入设备"""
    pending = db.synch_get_pending_writes("s7")
    if not pending:
        return

    write_items = dev.get("write_items", [])
    item_map = {item["name"]: item for item in write_items}

    try:
        client = _connect(dev)
    except Exception as e:
        print(f"[S7] 写入连接失败 {dev['ip']}: {e}")
        return

    try:
        for item in pending:
            name = item["name"]
            if name not in item_map:
                continue
            cfg = item_map[name]
            size = cfg["size"]
            value = item["value"]
            bit = cfg.get("bit")
            try:
                if bit is not None:
                    # bool 位写入：读-改-写（先读原字节，修改目标位后写回）
                    raw = client.db_read(cfg["db"], cfg["start"], 1)
                    set_bool(raw, 0, bit, bool(int(value)))
                    ok = client.db_write(cfg["db"], cfg["start"], raw) == 0
                else:
                    raw = bytearray(value.to_bytes(size, byteorder="big")) \
                        if isinstance(value, int) else bytearray(value)
                    ok = client.db_write(cfg["db"], cfg["start"], raw) == 0
            except Exception as e:
                print(f"[S7] synch 写入失败 {dev['ip']} {cfg.get('addr','')} ({name}): {e}")
                continue
            if ok:
                db.synch_mark_synced(name)
                print(f"[S7] synch 写入成功 {dev['ip']} {cfg.get('addr','')} ({name}) = {value}")
            else:
                print(f"[S7] synch 写入失败 {dev['ip']} {cfg.get('addr','')} ({name})")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#  配置加载 + synch 初始化
# ═══════════════════════════════════════════════════════════

def load_config():
    """加载 s7.json 配置并初始化 synch 条目

    s7.json 中 read/write 为列表，每项含 name/addr/type：
      {"name": "w1", "addr": "DB1.DBW0", "type": "int"}
    addr 格式 DB{num}.DB{B|W|D|X}{offset}[.bit] 经 _parse_s7_addr 解析。
    """
    global _devices
    _devices = []
    if not os.path.exists(_CONFIG_PATH):
        print("[S7] 配置文件不存在:", _CONFIG_PATH)
        return
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for dev in raw:
            read_raw = dev.get("read", [])
            write_raw = dev.get("write", [])
            # 兼容 {"items":[...]} 格式
            if isinstance(read_raw, dict):
                read_raw = read_raw.get("items", [])
            if isinstance(write_raw, dict):
                write_raw = write_raw.get("items", [])

            read_items = []
            for item in read_raw:
                db_num, start, size, bit = _parse_s7_addr(item["addr"])
                read_items.append({
                    "name": item["name"], "addr": item["addr"],
                    "type": item.get("type", "int"),
                    "db": db_num, "start": start, "size": size, "bit": bit,
                })

            write_items = []
            for item in write_raw:
                db_num, start, size, bit = _parse_s7_addr(item["addr"])
                write_items.append({
                    "name": item["name"], "addr": item["addr"],
                    "type": item.get("type", "int"),
                    "db": db_num, "start": start, "size": size, "bit": bit,
                })

            _devices.append({
                "name": dev.get("name", ""),
                "ip": dev.get("ip", "127.0.0.1"),
                "port": dev.get("port", 102),
                "rack": dev.get("rack", 0),
                "slot": dev.get("slot", 1),
                "read_items": read_items,
                "write_items": write_items,
                "rate": dev.get("rate", 1000),
            })

            # 初始化 synch read 条目
            for item in read_items:
                db.synch_add({
                    "type": "s7",
                    "action": "read",
                    "address": item["addr"],
                    "name": item["name"],
                    "value": 0,
                    "state": 0,
                })

            # 初始化 synch write 条目
            for item in write_items:
                db.synch_add({
                    "type": "s7",
                    "action": "write",
                    "address": item["addr"],
                    "name": item["name"],
                    "value": 0,
                    "state": 0,
                })

        print(f"[S7] 已加载 {len(_devices)} 个设备配置, synch 条目已初始化")
    except Exception as e:
        print(f"[S7] 加载配置失败: {e}")


def _save_config():
    """将 _devices 写回 s7.json（保留 addr/type 格式）"""
    try:
        raw = []
        for dev in _devices:
            read_raw = [
                {"name": it["name"], "addr": it["addr"], "type": it.get("type", "int")}
                for it in dev.get("read_items", [])
            ]
            write_raw = [
                {"name": it["name"], "addr": it["addr"], "type": it.get("type", "int")}
                for it in dev.get("write_items", [])
            ]
            raw.append({
                "name": dev.get("name", ""),
                "ip": dev["ip"],
                "port": dev["port"],
                "rack": dev["rack"],
                "slot": dev["slot"],
                "read": read_raw,
                "write": write_raw,
                "rate": dev["rate"],
            })
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        print(f"[S7] 配置已保存到 {_CONFIG_PATH}")
    except Exception as e:
        print(f"[S7] 保存配置失败: {e}")


# ═══════════════════════════════════════════════════════════
#  后台轮询线程
# ═══════════════════════════════════════════════════════════

def _polling_loop():
    """按各设备 rate 周期读取数据 + 扫描写入 synch 待同步条目"""
    global _thread_running
    print("[S7] 轮询线程已启动")
    next_times = {}
    write_scan_interval = 0.05
    last_write_scan = 0.0
    while _thread_running:
        now = time.time()
        any_due = False

        with _lock:
            devs_snapshot = list(_devices)
        for dev in devs_snapshot:
            key = dev["ip"]
            if key not in next_times:
                next_times[key] = 0.0
            if now >= next_times[key]:
                any_due = True
                try:
                    _publish_device(dev)
                except Exception as e:
                    print(f"[S7] 读取 {dev['ip']} 失败: {e}")
                next_times[key] = now + dev["rate"] / 1000.0

        if now - last_write_scan >= write_scan_interval:
            last_write_scan = now
            for dev in devs_snapshot:
                try:
                    _process_pending_writes(dev)
                except Exception as e:
                    print(f"[S7] 写入扫描 {dev['ip']} 失败: {e}")

        if not any_due:
            time.sleep(0.01)
        else:
            time.sleep(0.005)
    print("[S7] 轮询线程已停止")


def start_polling_thread():
    """启动后台轮询线程"""
    global _thread_running, _thread
    load_config()
    if not _devices:
        print("[S7] 无设备配置，不启动轮询")
        return
    _thread_running = True
    _thread = threading.Thread(target=_polling_loop, daemon=True)
    _thread.start()


def stop_polling_thread():
    """停止后台轮询线程"""
    global _thread_running
    _thread_running = False
    if _thread:
        _thread.join(timeout=2)


# ═══════════════════════════════════════════════════════════
#  命令处理
# ═══════════════════════════════════════════════════════════

def handle_control(payload):
    """处理 S7 相关命令"""
    cmd = payload.get("command")
    print(f"\n[命令] s7/control: {cmd}")

    if cmd == "read":
        with _lock:
            devs_snapshot = list(_devices)
        for dev in devs_snapshot:
            _publish_device(dev)

    elif cmd == "write":
        data = payload.get("data", {})
        name = data.get("name")
        value = data.get("value")
        if name is None or value is None:
            print("[S7] write 命令缺少参数")
            return
        if db.synch_write(name, value):
            print(f"[S7] {name} = {value} 已加入 synch 待写入队列")
        else:
            print(f"[S7] 未找到 write 条目: {name}")

    elif cmd == "add_device":
        data = payload.get("data", {})
        ip = (data.get("ip") or "").strip()
        port = int(data.get("port", 102))
        rack = int(data.get("rack", 0))
        slot = int(data.get("slot", 1))
        rate = int(data.get("rate", 100))
        if not ip:
            print("[S7] add_device 缺少 ip")
            return
        with _lock:
            for d in _devices:
                if d["ip"] == ip:
                    print(f"[S7] 设备已存在: {ip}")
                    return
            _devices.append({
                "name": data.get("name", ""),
                "ip": ip, "port": port,
                "rack": rack, "slot": slot,
                "read_items": [], "write_items": [],
                "rate": rate,
            })
        _save_config()
