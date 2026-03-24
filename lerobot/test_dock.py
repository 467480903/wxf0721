#!/usr/bin/env python3
"""lerobot/dock.py 对接测试程序

验证三个 TCP 端口是否正常工作：
  9002: 右臂 7 关节 + 夹爪位置
  9003: 头部 RGB 相机
  9004: 右臂腕部相机

用法：
  python3 test_dock.py                      # 默认 127.0.0.1
  python3 test_dock.py --host 192.168.1.100
  python3 test_dock.py --save-dir ./test_frames
"""

import argparse
import json
import os
import socket
import struct
import sys
import time
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
DEFAULT_HOST = "127.0.0.1"
ARM_PORT = 9002
HEAD_CAM_PORT = 9003
WRIST_CAM_PORT = 9004

RECV_BUF_SIZE = 65536
RECV_TIMEOUT_S = 5.0


# ---------------------------------------------------------------------------
# TCP 通用工具
# ---------------------------------------------------------------------------
def tcp_request(host: str, port: int, request: bytes,
                timeout: float = RECV_TIMEOUT_S) -> socket.socket:
    """建立 TCP 连接并发送请求，返回已连接的 socket（供调用方继续 recv）"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    s.sendall(request)
    return s


def recv_line(s: socket.socket, max_len: int = 4096) -> str:
    """阻塞读取一行（以 \\n 结尾）"""
    buf = bytearray()
    while len(buf) < max_len:
        chunk = s.recv(1)
        if not chunk:
            break
        buf.extend(chunk)
        if chunk == b"\n":
            break
    return buf.decode("ascii", errors="replace").strip()


def recv_exact(s: socket.socket, n: int) -> Optional[bytes]:
    """精确读取 n 字节"""
    buf = bytearray()
    while len(buf) < n:
        chunk = s.recv(min(n - len(buf), RECV_BUF_SIZE))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_arm(host: str) -> bool:
    """测试 9002：右臂关节 + 夹爪"""
    print("\n" + "=" * 60)
    print(f"[TEST] arm 端口 {ARM_PORT}（右臂 7 关节 + 夹爪）")
    print("=" * 60)
    try:
        s = tcp_request(host, ARM_PORT, b"get\n")
        line = recv_line(s)
        s.close()
        if not line:
            print("  FAIL: 空响应")
            return False
        data = json.loads(line)
        if not isinstance(data, list) or len(data) != 8:
            print(f"  FAIL: 期望 8 个浮点数，实际收到: {line[:80]}")
            return False
        joints = data[:7]
        gripper = data[7]
        print(f"  右臂 7 关节 (rad):")
        for i, a in enumerate(joints, 1):
            print(f"    joint{i}: {a:+.4f}")
        print(f"  夹爪位置 (rad): {gripper:+.4f}  (范围 [-0.785, 0], 0=关, -0.785=全开)")
        print("  PASS")
        return True
    except socket.timeout:
        print("  FAIL: 超时")
        return False
    except json.JSONDecodeError as e:
        print(f"  FAIL: JSON 解析失败: {e}")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_arm_set_ack(host: str) -> bool:
    """测试 9002: set 指令 ACK"""
    print("\n" + "=" * 60)
    print(f"[TEST] arm 端口 {ARM_PORT}（set 指令 ACK）")
    print("=" * 60)
    try:
        # 用当前 get 的值回 set，确认 ACK
        s = tcp_request(host, ARM_PORT, b"get\n")
        line = recv_line(s)
        s.close()
        if not line:
            print("  SKIP: 无法获取当前值")
            return False
        payload = json.loads(line)
        # set [a1,...,a8]\n
        req = "set " + json.dumps(payload) + "\n"
        s = tcp_request(host, ARM_PORT, req.encode("ascii"))
        reply = recv_line(s)
        s.close()
        print(f"  请求: {req.strip()}")
        print(f"  响应: {reply}")
        if reply.lower() == "ok":
            print("  PASS")
            return True
        print("  FAIL: 期望 'ok'")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_camera(host: str, port: int, tag: str, save_dir: Optional[str]) -> bool:
    """测试 9003/9004：相机帧"""
    print("\n" + "=" * 60)
    print(f"[TEST] {tag} 端口 {port}")
    print("=" * 60)
    s = None
    try:
        s = tcp_request(host, port, b"get\n")
        # 先读 4 字节长度
        hdr = recv_exact(s, 4)
        if hdr is None or len(hdr) != 4:
            print("  FAIL: 未读到 4 字节长度前缀")
            return False
        n = struct.unpack(">I", hdr)[0]
        print(f"  帧长度: {n} 字节")
        if n == 0:
            print("  WARN: 0 长度（GDK 暂无帧可用，可能刚启动）")
            return False
        jpg = recv_exact(s, n)
        if jpg is None or len(jpg) != n:
            print(f"  FAIL: 期望 {n} 字节，实际读到 {len(jpg) if jpg else 0}")
            return False
        # 校验 JPEG magic
        if not jpg.startswith(b"\xff\xd8"):
            print(f"  WARN: 非 JPEG magic (前 4 字节: {jpg[:4].hex()})")
        print(f"  前 4 字节: {jpg[:4].hex()}  (JPEG 应为 ffd8)")

        # 保存
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            fname = os.path.join(save_dir, f"{tag}_{int(time.time())}.jpg")
            with open(fname, "wb") as f:
                f.write(jpg)
            print(f"  已保存: {fname}")

        # 尝试用 cv2 解码（可选）
        try:
            import cv2
            import numpy as np
            arr = np.frombuffer(jpg, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                print(f"  cv2 解码成功: shape={img.shape}, dtype={img.dtype}")
            else:
                print("  WARN: cv2.imdecode 返回 None")
        except ImportError:
            print("  (跳过 cv2 解码：未安装 opencv)")
        print("  PASS")
        return True
    except socket.timeout:
        print("  FAIL: 超时")
        return False
    except Exception as e:
        print(f"  FAIL: {e}")
        return False
    finally:
        if s:
            s.close()


# ---------------------------------------------------------------------------
# 连续采集测试（看帧率）
# ---------------------------------------------------------------------------
def test_camera_fps(host: str, port: int, tag: str,
                    count: int = 10, timeout: float = 10.0) -> bool:
    """短连接模式连续 count 次 get，统计帧率"""
    print("\n" + "=" * 60)
    print(f"[FPS ] {tag} 端口 {port}（连续 {count} 帧）")
    print("=" * 60)
    durations = []
    for i in range(count):
        t0 = time.monotonic()
        try:
            s = tcp_request(host, port, b"get\n", timeout=timeout)
            hdr = recv_exact(s, 4)
            if not hdr:
                print(f"  [{i+1}/{count}] 无响应")
                continue
            n = struct.unpack(">I", hdr)[0]
            if n == 0:
                print(f"  [{i+1}/{count}] 0 长度，跳过")
                s.close()
                continue
            jpg = recv_exact(s, n)
            s.close()
            dt = time.monotonic() - t0
            durations.append(dt)
            print(f"  [{i+1}/{count}] {n} bytes, {dt*1000:.1f} ms")
        except socket.timeout:
            print(f"  [{i+1}/{count}] 超时")
    if not durations:
        print("  FAIL: 未拿到任何帧")
        return False
    avg_ms = sum(durations) / len(durations) * 1000
    fps = 1.0 / (sum(durations) / len(durations))
    print(f"  平均: {avg_ms:.1f} ms/帧  等效 {fps:.2f} fps (短连接开销包含在内)")
    print("  PASS" if len(durations) >= count // 2 else "  WARN")
    return len(durations) >= count // 2


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="lerobot/dock.py 对接测试")
    parser.add_argument("--host", default=DEFAULT_HOST, help="dock 服务地址")
    parser.add_argument("--save-dir", default=None,
                        help="保存相机帧的目录（不指定则不保存）")
    parser.add_argument("--fps-count", type=int, default=10,
                        help="帧率测试帧数（默认 10）")
    args = parser.parse_args()

    print(f"测试目标: {args.host}")
    print(f"  arm    : {ARM_PORT}")
    print(f"  head   : {HEAD_CAM_PORT}")
    print(f"  wrist  : {WRIST_CAM_PORT}")
    if args.save_dir:
        print(f"  保存目录: {args.save_dir}")

    results = []

    # 1) arm 关节
    results.append(("arm_get", test_arm(args.host)))
    # 2) arm set ACK
    results.append(("arm_set_ack", test_arm_set_ack(args.host)))
    # 3) head cam
    results.append(("head_cam", test_camera(args.host, HEAD_CAM_PORT, "head_cam", args.save_dir)))
    # 4) wrist cam
    results.append(("wrist_cam", test_camera(args.host, WRIST_CAM_PORT, "wrist_cam", args.save_dir)))
    # 5) head cam fps
    results.append(("head_cam_fps", test_camera_fps(args.host, HEAD_CAM_PORT, "head_cam", args.fps_count)))
    # 6) wrist cam fps
    results.append(("wrist_cam_fps", test_camera_fps(args.host, WRIST_CAM_PORT, "wrist_cam", args.fps_count)))

    # 汇总
    print("\n" + "#" * 60)
    print("#  测试汇总")
    print("#" * 60)
    for name, ok in results:
        mark = "PASS" if ok else "FAIL"
        print(f"  {name:16s}  {mark}")
    n_pass = sum(1 for _, ok in results if ok)
    n_total = len(results)
    print(f"\n  {n_pass}/{n_total} 通过")
    sys.exit(0 if n_pass == n_total else 1)


if __name__ == "__main__":
    main()
