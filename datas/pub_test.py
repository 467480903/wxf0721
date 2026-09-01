#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pub_test.py — 坐标点位控制通道安全验证脚本

用法:
    python3 pub_test.py

验证内容:
    发送一条缺 name 参数的 goto 命令（机器人不会运动），
    等待后端 /humanoid/positions/data 回传 goto_result，
    确认 positions.py 路由、参数校验、结果发布链路正常。
"""

import json
import sys
import time

import paho.mqtt.client as mqtt

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883

TOPIC_CTRL = "/humanoid/positions/control"   # 发送（客户端 → 服务端）
TOPIC_DATA = "/humanoid/positions/data"     # 接收（服务端 → 客户端)

got_result = {"done": False}


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[pub_test] 已连接 MQTT broker")
        client.subscribe(TOPIC_DATA)
        print(f"[pub_test] 已订阅 {TOPIC_DATA}")
    else:
        print(f"[pub_test] 连接失败 rc={rc}")
        sys.exit(1)


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
    except Exception as e:
        print(f"[pub_test] 解析消息失败: {e}")
        return
    print(f"[pub_test] ← {msg.topic}: {json.dumps(data, ensure_ascii=False)}")
    if data.get("command") in ("goto_result", "update_result", "error"):
        got_result["done"] = True


def main():
    client = mqtt.Client(client_id="pub_test_positions", clean_session=True)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()

    # 等待连接建立
    time.sleep(0.8)

    # 发送缺 name 的 goto 命令（安全：不会触发实际运动）
    payload = {"command": "goto", "data": {"type": "right"}}
    print(f"[pub_test] → {TOPIC_CTRL}: {json.dumps(payload, ensure_ascii=False)}")
    client.publish(TOPIC_CTRL, json.dumps(payload), qos=0)

    # 等待结果（最多 5 秒）
    for _ in range(50):
        if got_result["done"]:
            break
        time.sleep(0.1)

    if got_result["done"]:
        print("[pub_test] ✓ 验证通过：后端已正确响应坐标控制命令")
    else:
        print("[pub_test] ✗ 超时未收到响应，请检查后端服务是否运行")

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
