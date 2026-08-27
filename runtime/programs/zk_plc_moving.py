import sys
import os
import time
import math
import threading

# minth.py 在上级目录 runtime/ 下，需加入搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minth import Minth

G2 = Minth.G2()
# 看门狗使用独立实例 + 短超时，快速检测通信中断
G2_wd = Minth.G2(timeout=2)
# 心跳线程使用独立实例，避免与主线程 setData 竞争
G2_hb = Minth.G2(timeout=5)

# PLC 通信状态：True=正常，False=通信中断
_comm_ok = True
# 机器人运动状态：True=正在运动中，False=空闲/停止
_is_moving = False


# ---------------- 运动心跳 ----------------
def moving_heartbeat():
    """运动心跳线程：机器人运动过程中持续向 PLC 写入 G2_eanbled=1
    - _is_moving=True  → 每0.5s 写 G2_eanbled=1（运行中）
    - _is_moving=False → 写一次 G2_eanbled=0（停止），然后等待"""
    global _comm_ok
    last_state = None
    while True:
        if _comm_ok:
            try:
                if _is_moving:
                    G2_hb.setData("G2_eanbled", 1)
                    last_state = True
                else:
                    if last_state != False:
                        G2_hb.setData("G2_eanbled", 0)
                        last_state = False
            except Exception:
                pass
        time.sleep(0.5)


# ---------------- 通信监控 ----------------
def check_comm():
    """检查 PLC 通信状态，中断则立即停止"""
    global _comm_ok
    if not _comm_ok:
        try:
            G2.setData("G2_eanbled", 0)
        except Exception:
            pass
        print("[comm] PLC通信中断，机器人立即停止")
        os._exit(1)


def comm_watchdog():
    """通信看门狗线程：持续读取 PLC 心跳信号
    - readData 连续3次超时 → MQTT通信真中断 → 立即终止
      （单次超时可能是服务端忙于执行动作，不误判）
    - plc_alive=0 → PLC未发总控信号 → TTS播报后立即终止
    - plc_alive=1 → 通信正常 → 继续"""
    global _comm_ok
    timeout_count = 0          # 连续超时计数
    TIMEOUT_LIMIT = 3          # 连续3次超时才判定通信中断
    while True:
        try:
            val = G2_wd.readData("plc_alive")
            if val is None:
                # 单次超时：可能服务端正忙（长动作执行），重试不误判
                timeout_count += 1
                print(f"[watchdog] readData 超时 {timeout_count}/{TIMEOUT_LIMIT}")
                if timeout_count >= TIMEOUT_LIMIT:
                    _comm_ok = False
                    print("[watchdog] MQTT通信中断（服务无响应），机器人立即停止！")
                    try:
                        G2.setData("G2_eanbled", 0)
                    except Exception:
                        pass
                    os._exit(1)
                time.sleep(0.3)
                continue
            timeout_count = 0  # 读到值，重置计数
            if val == 0:
                # PLC 未发总控信号
                _comm_ok = False
                print("[watchdog] 未接收到总控信号(plc_alive=0)，机器人立即停止！")
                try:
                    global _is_moving
                    _is_moving = False
                    G2.TTS("未接收到总控信号，立即停止")
                    G2.setData("G2_eanbled", 0)
                except Exception:
                    pass
                os._exit(1)
            # val == 1：PLC 总控信号正常
        except Exception:
            _comm_ok = False
            print("[watchdog] 通信异常，机器人立即停止！")
            os._exit(1)
        time.sleep(0.3)


# 启动通信看门狗守护线程
threading.Thread(target=comm_watchdog, daemon=True).start()
# 启动运动心跳守护线程
threading.Thread(target=moving_heartbeat, daemon=True).start()


# ---------------- PLC 信号交互 ----------------
def wait_signal(name, value=1):
    """等待 PLC 信号变为指定值
    - PLC 发送信号（value 匹配）→ 正常执行
    - PLC 未发送信号 → 等待，不动作
    - readData 偶发超时 → 重试（由看门狗负责判定真中断）"""
    while True:
        check_comm()
        val = G2.readData(name)
        if val is None:
            # 偶发超时：服务端可能忙于执行动作，稍后重试
            time.sleep(0.2)
            continue
        if val == value:
            return
        time.sleep(0.2)


def handshake(req, done):
    """动作完成后的标准握手：
    1. 置位完成应答，通知 PLC
    2. 等待 PLC 复位请求信号
    3. 复位完成应答"""
    G2.setData(done, 1)
    wait_signal(req, 0)
    G2.setData(done, 0)


# ---------------- 运动控制包装 ----------------
def start_moving():
    """标记机器人进入运动状态，心跳线程开始持续发送 G2_eanbled=1"""
    global _is_moving
    _is_moving = True
    G2.setData("G2_eanbled", 1)


def stop_moving():
    """标记机器人退出运动状态，心跳线程发送 G2_eanbled=0"""
    global _is_moving
    _is_moving = False
    G2.setData("G2_eanbled", 0)


# 机器人就绪，通知 PLC
G2.setData("G2_eanbled", 1)
G2.TTS("机器人已就绪，等待PLC信号")

# ================= 第一段-上料-弯曲 =================
# 等待 PLC 上料请求（pick_right=1，送料机有料）
G2.TTS("等待PLC上料信号")
wait_signal("pick_right")

# 进入运动状态，持续向 PLC 发送运动中信号
start_moving()

G2.TTS("从送料机上抓料，底盘运动到送料机前面")
G2.GRIPPER({"left": -0.78})#爪子张开
G2.GO(7)
G2.GO(5)
G2.WBC("SQ1")
G2.WBC("SQ2")
G2.WBC("SQ3")
G2.WBC("SQ4")
G2.WBC("SQ5")
time.sleep(1.2)
G2.GRIPPER({"left": -0.05})#爪子关闭
time.sleep(1.2)
G2.WBC("SQ6")
G2.REL({"x":-0.4}) #底盘后退0.5米
G2.REL({"yaw_rad": math.pi })
G2.TTS("向弯曲机放料，运动到设备前方")
G2.GRIPPER({"left": -0.05})
G2.GO(6)
G2.WBC("WF1")
G2.WBC("WF2")
# G2.OFFSET({"lx": 20})
# G2.OFFSET({"lz": -65})
G2.WBC("WF3")
time.sleep(1.2)
G2.GRIPPER({"left": -0.78})
time.sleep(1.2)
G2.WBC("WF4")
# G2.OFFSET({"lz": -20})
# G2.OFFSET({"lx": -80})
G2.WBC("WF5")
G2.WBC("WF6")
G2.TTS("在弯曲机上放料完成，后退")
G2.REL({"x":-0.3})

# 第一段完成，暂停运动信号，应答 PLC
stop_moving()
handshake("pick_right", "pick_right_done")

# ================= 第二段-弯曲-下料 =================
# 等待 PLC 下料请求（place_middle=1，弯曲完成/下料机就绪）
G2.TTS("等待PLC下料信号")
wait_signal("place_middle")

# 进入运动状态，持续向 PLC 发送运动中信号
start_moving()

G2.TTS("从弯曲机上取料，运动到设备前方")
G2.GRIPPER({"left": -0.78})
G2.GO(6)
G2.WBC("GD1")
G2.WBC("GD2")
G2.WBC("GD3")
G2.WBC("GD4")
G2.WBC("GD5")
G2.WBC("GD6")
time.sleep(1.2)
G2.GRIPPER({"left": -0.05})
time.sleep(1.2)
G2.WBC("GD7")
G2.TTS("从弯曲机上取料完成，后退至下料机")
G2.REL({"x":-0.3})
G2.WBC("XF1")
time.sleep(1.2)
# 原地向左转90度（直接输入角度值，正数左转/负数右转）
TURN_DEG = 180
# G2.TTS("原地向左转90度")
G2.REL({"x": 0, "y": 0, "yaw_rad": math.radians(TURN_DEG)})
time.sleep(1.2)
G2.GO(3)
G2.WBC("XF2")
G2.WBC("XF3")
time.sleep(1.2)
G2.GRIPPER({"left": -0.78})
time.sleep(1.2)
G2.WBC("XF4")
G2.WBC("XF5")
G2.WBC("XF6")
G2.TTS("下料完成，后退")
G2.REL({"x":-0.3})
G2.GO(1)

# 第二段完成，暂停运动信号，应答 PLC
stop_moving()
handshake("place_middle", "place_middle_done")

# 全部任务完成，机器人退出就绪状态
G2.setData("G2_eanbled", 0)
G2.TTS("全部任务完成")
