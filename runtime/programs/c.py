import os
import sys
import time

# 确保能找到 agibot_gdk 模块
_GDK_LIB = "/home/agi/app/gdk/lib"
if _GDK_LIB not in sys.path:
    sys.path.insert(0, _GDK_LIB)
# 确保能找到 GDK 动态库
_HOME_LIB = "/home/agi/app/lib"
if os.path.isdir(_HOME_LIB):
    os.environ["LD_LIBRARY_PATH"] = _HOME_LIB + ":" + os.environ.get("LD_LIBRARY_PATH", "")

import agibot_gdk

GDK_INIT_WAIT_S = 2.0


def main():
    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("GDK初始化失败")
        return
    print("GDK初始化成功")

    try:
        robot = agibot_gdk.Robot()
        time.sleep(GDK_INIT_WAIT_S)

        # 打开左夹爪（position=-0.785 为完全张开）
        joint_states = agibot_gdk.JointStates()
        joint_states.group = "left_tool"
        joint_states.target_type = "omnipicker"

        joint_state = agibot_gdk.JointState()
        joint_state.position = -0.785
        joint_states.states = [joint_state]
        joint_states.nums = 1

        print("正在打开左夹爪...")
        robot.move_ee_pos(joint_states)
        print("左夹爪打开完成")

        time.sleep(2)
    except Exception as e:
        print(f"夹爪控制失败: {e}")
    finally:
        if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
            print("GDK释放失败")
        else:
            print("GDK释放成功")


if __name__ == "__main__":
    main()