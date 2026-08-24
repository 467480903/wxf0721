#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务程序 - 左臂抓取放置 + PNC移动 + Modbus信号交互

使用 MQTT（minth 库）控制机械臂/夹爪/PNC底盘，使用 socket 控制 Modbus 信号。
需要 humanoid 服务（services/main.py）在运行中。

执行流程：
1.  等待信号1
2.  左臂运动到目标关节角
3.  打开左夹爪
4.  PNC 左转90° → 前进2.0m → 左转90° → 前进0.2m
5.  左臂运动×3 → 关闭夹爪 → 左臂运动
6.  PNC 后退0.2m → 左转90° → 前进2.0m → 左转90° → 前进1.0m
7.  左臂运动×3 → 打开夹爪 → 左臂运动
8.  PNC 后退1.0m
9.  发出完成信号1，等待信号2
10. PNC 前进1.0m
11. 左臂运动×3 → 关闭夹爪 → 左臂运动
12. PNC 后退1.0m → 右转90° → 前进1.0m → 右转90° → 前进0.1m
13. 左臂运动×3 → 打开夹爪 → 左臂运动
14. PNC 后退0.1m → 右转90° → 前进1.0m → 右转90°
15. 发出完成信号2
"""
import os
import sys
import math
import time
import struct
import socket

# 确保 runtime 目录在 sys.path 中（能导入 minth）
_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNTIME = os.path.dirname(_HERE)
if _RUNTIME not in sys.path:
    sys.path.insert(0, _RUNTIME)

from minth import Minth


# ═══════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════

PNC_SPEED = 0.1               # PNC 速度 (m/s 线性 / rad/s 角速度)
GRIPPER_OPEN = -0.785         # 夹爪张开
GRIPPER_CLOSE = 0.0           # 夹爪闭合

# 左臂关节键
LEFT_ARM_KEYS = [
    "idx21_arm_l_joint1", "idx22_arm_l_joint2", "idx23_arm_l_joint3",
    "idx24_arm_l_joint4", "idx25_arm_l_joint5", "idx26_arm_l_joint6",
    "idx27_arm_l_joint7",
]

# 左臂目标关节角（度）
LEFT_ARM_DEG = [110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4]

# 默认左臂关节角（度）— 各次运动可独立修改
LEFT_ARM_DEG_DEFAULT = [110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4]


def left_arm_move(robot, j1, j2, j3, j4, j5, j6, j7):
    """左臂关节运动（角度制，内部转换为弧度）

    Args:
        robot: Minth 实例
        j1..j7: 7 个关节角度（度）

    Returns:
        bool
    """
    data = {}
    for key, deg in zip(LEFT_ARM_KEYS, [j1, j2, j3, j4, j5, j6, j7]):
        data[key] = round(math.radians(deg), 4)
    return robot.LEFT(data)

# Modbus 配置
MODBUS_IP = "10.20.15.120"
MODBUS_PORT = 10502
SIGNAL1_READ_ADDR = 0        # 读取信号1
SIGNAL2_READ_ADDR = 1        # 读取信号2
SIGNAL1_WRITE_ADDR = 10      # 写入完成信号1
SIGNAL2_WRITE_ADDR = 11      # 写入完成信号2


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ═══════════════════════════════════════════════════════════
#  Modbus TCP 客户端
# ═══════════════════════════════════════════════════════════

class ModbusTcp:
    """轻量级 Modbus TCP 客户端（纯 socket，无第三方依赖）"""

    def __init__(self, ip, port=10502, unit_id=1, timeout=1.0):
        self.ip = ip
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self._tx_id = 0

    def _next_tx_id(self):
        self._tx_id = (self._tx_id + 1) & 0xFFFF
        return self._tx_id

    def _send_recv(self, pdu):
        tx_id = self._next_tx_id()
        mbap = struct.pack(">HHHB", tx_id, 0x0000, len(pdu) + 1, self.unit_id)
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.ip, self.port))
            sock.sendall(mbap + pdu)
            header = self._recv_exact(sock, 7)
            if not header:
                return None
            _, _, length, _ = struct.unpack(">HHHB", header)
            pdu_len = length - 1
            return self._recv_exact(sock, pdu_len)
        except Exception:
            return None
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    @staticmethod
    def _recv_exact(sock, n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def read_holding(self, addr, count=1):
        """读取保持寄存器，返回值列表或 None"""
        pdu = struct.pack(">BHH", 0x03, addr, count)
        resp = self._send_recv(pdu)
        if not resp or len(resp) < 2:
            return None
        if resp[0] & 0x80:
            return None
        byte_count = resp[1]
        values = []
        for i in range(0, byte_count, 2):
            val = struct.unpack(">H", resp[2 + i:4 + i])[0]
            values.append(val)
        return values

    def write_holding(self, addr, value):
        """写入保持寄存器，返回 True/False"""
        pdu = struct.pack(">BHH", 0x06, addr, value & 0xFFFF)
        resp = self._send_recv(pdu)
        if not resp or len(resp) < 5:
            return False
        if resp[0] & 0x80:
            return False
        return True


def wait_signal(modbus, addr, expected=1, poll_interval=0.2):
    """轮询读取 Modbus 保持寄存器，等待信号"""
    log(f"等待信号 (地址 {addr} == {expected})...")
    while True:
        values = modbus.read_holding(addr)
        if values is not None and len(values) > 0 and values[0] == expected:
            log(f"  收到信号 (地址 {addr} = {values[0]})")
            return True
        time.sleep(poll_interval)


def send_signal(modbus, addr, value=1):
    """发送完成信号到 Modbus 保持寄存器"""
    ok = modbus.write_holding(addr, value)
    if ok:
        log(f"  已发送信号 (地址 {addr} = {value})")
    else:
        log(f"  发送信号失败 (地址 {addr})")
    return ok


# ═══════════════════════════════════════════════════════════
#  主任务
# ═══════════════════════════════════════════════════════════

def main():
    log("═══ 初始化机器人连接 ═══")
    G2 = Minth.G2(timeout=120)
    modbus = ModbusTcp(MODBUS_IP, MODBUS_PORT)

    try:
        # ── 1. 等待信号1 ──
        log("═══ 步骤 1: 等待信号1 ═══")
        wait_signal(modbus, SIGNAL1_READ_ADDR)

        # ── 2. 左臂运动到目标关节角 ──
        log("═══ 步骤 2: 左臂运动到目标关节角 ═══")
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)

        # ── 3. 打开左夹爪 ──
        log("═══ 步骤 3: 打开左夹爪 ═══")
        G2.GRIPPER({"left": GRIPPER_OPEN})
        time.sleep(0.5)

        # ── 4. PNC 移动序列 ──
        log("═══ 步骤 4: PNC 左转90° → 前进2.0m → 左转90° → 前进0.2m ═══")
        G2.PNC_ROTATE(90, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_FORWARD(2.0, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_ROTATE(90, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_FORWARD(0.2, PNC_SPEED)
        time.sleep(0.5)

        # ── 5. 左臂运动×3 → 关闭夹爪 → 左臂运动 ──
        log("═══ 步骤 5: 左臂运动×3 → 关闭夹爪 → 左臂运动 ═══")
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        G2.GRIPPER({"left": GRIPPER_CLOSE})
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)

        # ── 6. PNC 后退0.2m → 左转90° → 前进2.0m → 左转90° → 前进1.0m ──
        log("═══ 步骤 6: PNC 后退0.2m → 左转90° → 前进2.0m → 左转90° → 前进1.0m ═══")
        G2.PNC_FORWARD(-0.2, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_ROTATE(90, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_FORWARD(2.0, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_ROTATE(90, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_FORWARD(1.0, PNC_SPEED)
        time.sleep(0.5)

        # ── 7. 左臂运动×3 → 打开夹爪 → 左臂运动 ──
        log("═══ 步骤 7: 左臂运动×3 → 打开夹爪 → 左臂运动 ═══")
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        G2.GRIPPER({"left": GRIPPER_OPEN})
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)

        # ── 8. PNC 后退1.0m ──
        log("═══ 步骤 8: PNC 后退1.0m ═══")
        G2.PNC_FORWARD(-1.0, PNC_SPEED)

        # ── 9. 发出完成信号1，等待信号2 ──
        log("═══ 步骤 9: 发出完成信号1，等待信号2 ═══")
        send_signal(modbus, SIGNAL1_WRITE_ADDR)
        wait_signal(modbus, SIGNAL2_READ_ADDR)

        # ── 10. PNC 前进1.0m ──
        log("═══ 步骤 10: PNC 前进1.0m ═══")
        G2.PNC_FORWARD(1.0, PNC_SPEED)
        time.sleep(0.5)

        # ── 11. 左臂运动×3 → 关闭夹爪 → 左臂运动 ──
        log("═══ 步骤 11: 左臂运动×3 → 关闭夹爪 → 左臂运动 ═══")
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        G2.GRIPPER({"left": GRIPPER_CLOSE})
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)

        # ── 12. PNC 后退1.0m → 右转90° → 前进1.0m → 右转90° → 前进0.1m ──
        log("═══ 步骤 12: PNC 后退1.0m → 右转90° → 前进1.0m → 右转90° → 前进0.1m ═══")
        G2.PNC_FORWARD(-1.0, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_ROTATE(-90, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_FORWARD(1.0, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_ROTATE(-90, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_FORWARD(0.1, PNC_SPEED)
        time.sleep(0.5)

        # ── 13. 左臂运动×3 → 打开夹爪 → 左臂运动 ──
        log("═══ 步骤 13: 左臂运动×3 → 打开夹爪 → 左臂运动 ═══")
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)
        G2.GRIPPER({"left": GRIPPER_OPEN})
        time.sleep(0.5)
        left_arm_move(G2, 110.0, -79.3, -94.8, -113.8, -12.0, 5.8, 0.4)
        time.sleep(0.5)

        # ── 14. PNC 后退0.1m → 右转90° → 前进1.0m → 右转90° ──
        log("═══ 步骤 14: PNC 后退0.1m → 右转90° → 前进1.0m → 右转90° ═══")
        G2.PNC_FORWARD(-0.1, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_ROTATE(-90, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_FORWARD(1.0, PNC_SPEED)
        time.sleep(0.5)
        G2.PNC_ROTATE(-90, PNC_SPEED)

        # ── 15. 发出完成信号2 ──
        log("═══ 步骤 15: 发出完成信号2 ═══")
        send_signal(modbus, SIGNAL2_WRITE_ADDR)

        log("═══ 全部任务完成 ═══")

    except Exception as e:
        log(f"任务执行异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        G2.close()


if __name__ == "__main__":
    main()
