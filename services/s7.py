#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s7.py — 西门子 S7 协议读写组件（synch 同步版）

职责：
  - 加载 datas/s7.json 配置，初始化 data.synch 中的 s7 条目
  - 后台线程按 rate 周期读取 DB 块数据
      → 更新 data.synch 中 read 条目的 value（state=1）
  - 后台线程周期扫描 synch 中 state==1 的 write 条目
      → 写入 S7 设备 → 标记 state=2
  - 纯 Python 实现，无第三方依赖

s7.json 格式：
  [
    {
      "name": "s1200",
      "ip": "10.2.250.27",
      "port": 102,
      "rack": 0,
      "slot": 1,
      "read": [
        {"name": "w1", "addr": "DB1.DBW0", "type": "int"},
        {"name": "w2", "addr": "DB1.DBW2", "type": "int"}
      ],
      "write": [
        {"name": "w1_", "addr": "DB1.DBW10", "type": "int"}
      ],
      "rate": 100
    }
  ]

  地址格式：DB{num}.DB{B|W|D}{offset}
    DBW = Word (2 字节), DBD = DWord (4 字节), DBB = Byte (1 字节)
"""

import os
import re
import json
import time
import socket
import struct
import threading

import common
import data as db

# ── 配置 ───────────────────────────────────────────────────
_CONFIG_PATH = os.path.join(common.DATAS_DIR, "s7.json")
_devices = []
_thread_running = False
_thread = None
_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════
#  S7 地址解析（"DB1.DBW0" → db=1, start=0, size=2）
# ═══════════════════════════════════════════════════════════

# 地址前缀 → 字节数
_PREFIX_SIZE = {"B": 1, "W": 2, "D": 4}

# 匹配 "DB1.DBW0" / "DB12.DBD4" / "DB1.DBB10"
_ADDR_RE = re.compile(r"^DB(\d+)\.DB([BWD])(\d+)$", re.IGNORECASE)


def _parse_s7_addr(addr):
    """解析 S7 地址字符串 → (db_number, start_byte, size_bytes)

    支持格式：
      DB1.DBW0   → (1, 0, 2)   Word
      DB1.DBD0   → (1, 0, 4)   DWord
      DB1.DBB0   → (1, 0, 1)   Byte
    """
    m = _ADDR_RE.match(addr.strip())
    if not m:
        raise ValueError(f"无法解析 S7 地址: {addr}")
    db_num = int(m.group(1))
    prefix = m.group(2).upper()
    start = int(m.group(3))
    size = _PREFIX_SIZE[prefix]
    return db_num, start, size


# ═══════════════════════════════════════════════════════════
#  纯 Python S7 协议客户端
# ═══════════════════════════════════════════════════════════

# S7 区域代码
S7_AREA_DB = 0x84   # DB 块

# S7 传输类型
TS_BYTE = 0x02      # BYTE
TS_WORD = 0x04      # WORD (2 bytes)
TS_DWORD = 0x06     # DWORD (4 bytes)


class S7Client:
    """纯 Python S7 通信客户端（ISO over TCP）"""

    def __init__(self, ip, port=102, rack=0, slot=1, timeout=1.0):
        self.ip = ip
        self.port = port
        self.rack = rack
        self.slot = slot
        self.timeout = timeout
        self._sock = None
        self._pdu_ref = 0

    # ── 连接管理 ──────────────────────────────────────────

    def connect(self):
        """建立 ISO COTP 连接"""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.ip, self.port))
        except Exception as e:
            self._sock = None
            raise ConnectionError(f"S7 连接 {self.ip}:{self.port} 失败: {e}")

        # 发送 COTP CR（连接请求）
        cr = self._build_cr()
        self._sock.sendall(cr)

        # 接收 COTP CC（连接确认）
        resp = self._recv_tpkt()
        if not resp:
            self.disconnect()
            raise ConnectionError("S7 CR 无响应")

        # 检查是否为 CC（Connection Confirm）
        if len(resp) < 6 or (resp[5] & 0xF0) != 0xD0:
            self.disconnect()
            raise ConnectionError(f"S7 连接被拒绝: {resp.hex()}")

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # ── 读写操作 ──────────────────────────────────────────

    def read(self, db_number, start, size):
        """读取 DB 块数据
        Args:
            db_number: DB 编号
            start: 字节偏移
            size: 读取字节数
        Returns:
            bytes 数据或 None
        """
        if not self._sock:
            return None
        req = self._build_read_req(db_number, start, size)
        try:
            self._sock.sendall(req)
            resp = self._recv_tpkt()
            if not resp:
                return None
            return self._parse_read_resp(resp, size)
        except Exception:
            return None

    def write(self, db_number, start, data):
        """写入 DB 块数据
        Args:
            db_number: DB 编号
            start: 字节偏移
            data: bytes 数据
        Returns:
            bool: True=成功
        """
        if not self._sock:
            return False
        req = self._build_write_req(db_number, start, data)
        try:
            self._sock.sendall(req)
            resp = self._recv_tpkt()
            if not resp:
                return False
            return self._parse_write_resp(resp)
        except Exception:
            return False

    # ── 协议构建 ──────────────────────────────────────────

    def _build_cr(self):
        """构建 ISO COTP 连接请求"""
        # TPKT header: version=3, reserved=0, length=22
        # COTP CR: LI=17, type=0xE0, DST=0x0000, SRC=0x0001, class=0x00
        # Params: TPDU size(0x0A=1024), src TSAP, dst TSAP
        local_tsap = 0x0100
        remote_tsap = 0x0100 | (self.rack << 5) | self.slot
        cr = bytearray([
            0x03, 0x00, 0x00, 0x16,      # TPKT (length=22)
            0x11,                          # COTP LI (17 bytes follow)
            0xE0,                          # PDU type = CR
            0x00, 0x00,                    # DST ref
            0x00, 0x01,                    # SRC ref
            0x00,                          # Class
            0xC0, 0x01, 0x0A,             # TPDU size = 1024
            0xC1, 0x02,
            (local_tsap >> 8) & 0xFF, local_tsap & 0xFF,   # Src TSAP
            0xC2, 0x02,
            (remote_tsap >> 8) & 0xFF, remote_tsap & 0xFF,  # Dst TSAP
        ])
        return bytes(cr)

    def _next_pdu_ref(self):
        self._pdu_ref = (self._pdu_ref + 1) & 0xFFFF
        return self._pdu_ref

    def _build_read_req(self, db_number, start, size):
        """构建 S7 读请求"""
        ref = self._next_pdu_ref()
        bit_addr = start * 8

        # S7 参数区
        param = bytearray([
            0x04,                           # Function = Read
            0x01,                           # Item count = 1
            0x12,                           # Variable spec = S7ANY
            0x0A,                           # Spec length = 10
            TS_BYTE,                        # Transport size = BYTE
            (size >> 8) & 0xFF, size & 0xFF,    # Number of elements
            (db_number >> 8) & 0xFF, db_number & 0xFF,  # DB number
            S7_AREA_DB,                     # Area = DB
            (bit_addr >> 16) & 0xFF,
            (bit_addr >> 8) & 0xFF,
            bit_addr & 0xFF,                # Byte address (3 bytes)
        ])

        par_len = len(param)
        # TPKT + COTP DT + S7 Header
        header = bytearray([
            0x03, 0x00, 0x00, 0x00,         # TPKT (length filled below)
            0x02, 0xF0, 0x80,               # COTP DT
            0x32,                           # S7 Protocol ID
            0x01,                           # ROSCTR = Job
            0x00, 0x00,                     # Reserved
            (ref >> 8) & 0xFF, ref & 0xFF,  # PDU ref
            (par_len >> 8) & 0xFF, par_len & 0xFF,  # Param length
            0x00, 0x00,                     # Data length = 0
        ])
        header += param

        total_len = len(header)
        header[2] = (total_len >> 8) & 0xFF
        header[3] = total_len & 0xFF
        return bytes(header)

    def _build_write_req(self, db_number, start, data):
        """构建 S7 写请求"""
        ref = self._next_pdu_ref()
        bit_addr = start * 8
        data_len = len(data)

        # S7 参数区
        param = bytearray([
            0x05,                           # Function = Write
            0x01,                           # Item count = 1
            0x12,                           # Variable spec = S7ANY
            0x0A,                           # Spec length = 10
            TS_BYTE,                        # Transport size = BYTE
            (data_len >> 8) & 0xFF, data_len & 0xFF,  # Number of elements
            (db_number >> 8) & 0xFF, db_number & 0xFF,  # DB number
            S7_AREA_DB,                     # Area = DB
            (bit_addr >> 16) & 0xFF,
            (bit_addr >> 8) & 0xFF,
            bit_addr & 0xFF,                # Byte address
        ])

        # S7 数据区
        data_field = bytearray([
            0x00,                               # Return code (reserved)
            TS_BYTE,                            # Transport size
            (data_len >> 8) & 0xFF, data_len & 0xFF,  # Data length
        ]) + bytearray(data)

        par_len = len(param)
        dat_len = len(data_field)
        header = bytearray([
            0x03, 0x00, 0x00, 0x00,         # TPKT
            0x02, 0xF0, 0x80,               # COTP DT
            0x32,                           # S7 Protocol ID
            0x01,                           # ROSCTR = Job
            0x00, 0x00,                     # Reserved
            (ref >> 8) & 0xFF, ref & 0xFF,  # PDU ref
            (par_len >> 8) & 0xFF, par_len & 0xFF,
            (dat_len >> 8) & 0xFF, dat_len & 0xFF,
        ])
        header += param + data_field

        total_len = len(header)
        header[2] = (total_len >> 8) & 0xFF
        header[3] = total_len & 0xFF
        return bytes(header)

    def _parse_read_resp(self, resp, expected_size):
        """解析 S7 读响应"""
        # resp 包含: TPKT(4) + COTP(3) + S7 header(10) + param(2) + data(4+data)
        offset = 4 + 3  # 跳过 TPKT + COTP
        if len(resp) < offset + 10:
            return None
        # S7 header
        if resp[offset] != 0x32:
            return None
        rosctr = resp[offset + 1]
        if rosctr != 0x03:  # Ack-Data
            return None
        par_len = struct.unpack(">H", resp[offset+6:offset+8])[0]
        dat_len = struct.unpack(">H", resp[offset+8:offset+10])[0]
        offset += 10 + par_len  # 跳过 header + param
        if dat_len < 4:
            return None
        ret_code = resp[offset]
        if ret_code != 0xFF:
            return None
        ts = resp[offset + 1]
        dlen = struct.unpack(">H", resp[offset+2:offset+4])[0]
        raw = resp[offset+4:offset+4+dlen]
        return bytes(raw)

    def _parse_write_resp(self, resp):
        """解析 S7 写响应"""
        offset = 4 + 3  # TPKT + COTP
        if len(resp) < offset + 10:
            return False
        if resp[offset] != 0x32:
            return False
        rosctr = resp[offset + 1]
        if rosctr != 0x03:
            return False
        par_len = struct.unpack(">H", resp[offset+6:offset+8])[0]
        dat_len = struct.unpack(">H", resp[offset+8:offset+10])[0]
        offset += 10 + par_len  # 跳过 header + param
        if dat_len < 1:
            return False
        ret_code = resp[offset]
        return ret_code == 0xFF

    # ── 网络工具 ──────────────────────────────────────────

    def _recv_tpkt(self):
        """接收完整 TPKT 报文"""
        try:
            header = self._recv_exact(4)
            if not header:
                return None
            # TPKT: version(1) + reserved(1) + length(2)
            length = struct.unpack(">H", header[2:4])[0]
            remaining = length - 4
            if remaining <= 0:
                return None
            data = self._recv_exact(remaining)
            if data is None:
                return None
            return header + data
        except Exception:
            return None

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf


# ═══════════════════════════════════════════════════════════
#  数据读取与发布
# ═══════════════════════════════════════════════════════════

def _read_device(dev):
    """读取单个设备的所有 read/write items"""
    client = S7Client(dev["ip"], dev["port"], dev["rack"], dev["slot"])
    try:
        client.connect()
    except Exception as e:
        print(f"[S7] 连接 {dev['ip']}:{dev['port']} 失败: {e}")
        return [], []
    read_result = []
    write_result = []

    for item in dev.get("read_items", []):
        raw = client.read(item["db"], item["start"], item["size"])
        val = int.from_bytes(raw, byteorder="big") if raw else None
        read_result.append({
            "addr": item.get("addr", ""),
            "name": item["name"],
            "value": val,
        })
        if val is not None:
            db.synch_update_read(item["name"], val)

    # 读回 write 区域当前值（用于前端显示）
    for item in dev.get("write_items", []):
        raw = client.read(item["db"], item["start"], item["size"])
        val = int.from_bytes(raw, byteorder="big") if raw else None
        write_result.append({
            "addr": item.get("addr", ""),
            "name": item["name"],
            "value": val,
        })

    client.disconnect()
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

    client = S7Client(dev["ip"], dev["port"], dev["rack"], dev["slot"])
    try:
        client.connect()
    except Exception as e:
        print(f"[S7] 写入连接失败 {dev['ip']}: {e}")
        return

    for item in pending:
        name = item["name"]
        if name not in item_map:
            continue
        cfg = item_map[name]
        size = cfg["size"]
        value = item["value"]
        raw = value.to_bytes(size, byteorder="big") if isinstance(value, int) else bytes(value)
        ok = client.write(cfg["db"], cfg["start"], raw)
        if ok:
            db.synch_mark_synced(name)
            print(f"[S7] synch 写入成功 {dev['ip']} {cfg.get('addr','')} ({name}) = {value}")
        else:
            print(f"[S7] synch 写入失败 {dev['ip']} {cfg.get('addr','')} ({name})")

    client.disconnect()


# ═══════════════════════════════════════════════════════════
#  配置加载 + synch 初始化
# ═══════════════════════════════════════════════════════════

def load_config():
    """加载 s7.json 配置并初始化 synch 条目

    s7.json 中 read/write 为列表，每项含 name/addr/type：
      {"name": "w1", "addr": "DB1.DBW0", "type": "int"}
    addr 格式 DB{num}.DB{B|W|D}{offset} 经 _parse_s7_addr 解析为 db/start/size。
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
                db_num, start, size = _parse_s7_addr(item["addr"])
                read_items.append({
                    "name": item["name"], "addr": item["addr"],
                    "type": item.get("type", "int"),
                    "db": db_num, "start": start, "size": size,
                })

            write_items = []
            for item in write_raw:
                db_num, start, size = _parse_s7_addr(item["addr"])
                write_items.append({
                    "name": item["name"], "addr": item["addr"],
                    "type": item.get("type", "int"),
                    "db": db_num, "start": start, "size": size,
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
                "rack": dev.get("rack", 0),
                "slot": dev.get("slot", 1),
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