import sys
import os
import time
import math
import threading

# minth.py 在上级目录 runtime/ 下，需加入搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minth import Minth

G2 = Minth.G2()


# ---------------- PLC 信号交互 ----------------
def wait_signal(name, value=1):
    """阻塞等待 PLC 信号变为指定值
    value=1: 等待请求信号；value=0: 等待请求复位
    收不到信号就一直等待，不执行动作"""
    while G2.readData(name) != value:
        check_estop()    #---------急停-----------------------
        time.sleep(0.2)


def handshake(req, done):
    """动作完成后的标准握手：
    1. 置位完成应答，通知 PLC
    2. 等待 PLC 复位请求信号
    3. 复位完成应答，本次交互结束"""
    G2.setData(done, 1)
    wait_signal(req, 0)
    G2.setData(done, 0)


# ---------------- 急停监控 ----------------
# 急停线程使用独立的 Minth 实例，避免与主线程的 readData 竞态
G2_estop = Minth.G2()
_estop_triggered = False


def check_estop():
    """主动检查急停信号，触发后立即终止程序
    可在关键动作之间调用，实现更快的响应"""
    global _estop_triggered
    if _estop_triggered:
        G2.setData("G2_eanbled", 0)
        print("[estop] 急停已触发，程序终止")
        os._exit(1)


def estop_monitor():
    """急停监控守护线程：100ms 周期轮询 PLC 急停信号
    检测到 estop=1 立即终止整个程序进程，机器人完全静止"""
    global _estop_triggered
    while True:
        try:
            if G2_estop.readData("estop") == 1:
                _estop_triggered = True
                print("[estop] 检测到PLC急停信号，立即停止！")
                try:
                    G2.setData("G2_eanbled", 0)
                except Exception:
                    pass
                os._exit(1)
        except Exception:
            pass
        time.sleep(0.1)


# 启动急停监控守护线程（主程序退出时自动结束）
threading.Thread(target=estop_monitor, daemon=True).start()
#----------------------------------------------------------------------


# 机器人就绪，通知 PLC
G2.setData("G2_eanbled", 1)
G2.TTS("机器人已就绪，等待PLC信号")

# ================= 第一段-上料-弯曲 =================
# 等待 PLC 上料请求（pick_right=1，送料机有料）
G2.TTS("等待PLC上料信号")
wait_signal("pick_right")

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

# 第一段完成，应答 PLC（pick_right_done=1，等 PLC 复位后自动复位应答）
handshake("pick_right", "pick_right_done")

# ================= 第二段-弯曲-下料 =================
# 等待 PLC 下料请求（place_middle=1，弯曲完成/下料机就绪）
G2.TTS("等待PLC下料信号")
wait_signal("place_middle")

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

# 第二段完成，应答 PLC
handshake("place_middle", "place_middle_done")

# 全部任务完成，机器人退出就绪状态
G2.setData("G2_eanbled", 0)
G2.TTS("全部任务完成")
