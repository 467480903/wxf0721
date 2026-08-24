import time
import json
import requests
import agibot_gdk

# PNC 规控导航服务地址
PNC_RPC_BASE = "http://10.2.250.25:8002/rpc/aimdk.protocol.PncService"


def pnc_move_forward(distance=0.3, angle=0, map_id=1):
    """
    通过 PNC 下发直线前进任务
    参数:
        distance: 前进距离（米），正值前进
        angle:    旋转角度（弧度），0 表示不旋转
        map_id:   当前地图 ID，需与重定位地图一致
    """
    # 1. 初始化 GDK
    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("GDK 初始化失败")
        return False
    print("GDK 初始化成功")

    robot = agibot_gdk.Robot()
    time.sleep(2)  # 等待 Robot 初始化完成

    # 2. 下发 MoveForward 直线平移任务
    url = f"{PNC_RPC_BASE}/MoveForward"
    payload = {
        "task_id": 0,       # 0 表示由 PNC 自动生成
        "map_id": map_id,
        "angle": angle,
        "distance": distance
    }

    print(f"下发前进任务: 距离 {distance} 米, 角度 {angle} rad")
    try:
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
    except Exception as e:
        print(f"RPC 请求失败: {e}")
        return False

    task_id = result.get("task_id", "")
    state = result.get("state", "")

    print(f"任务已下发 → task_id: {task_id}, state: {state}")
    if state != "CommonState_SUCCESS":
        print("任务下发失败，请检查重定位状态和 MC 模式")
        return False

    # 3. 轮询任务状态直到完成
    state_url = f"{PNC_RPC_BASE}/ActionGetState"
    timeout_s = 60  # 最大等待时间
    t0 = time.time()

    while time.time() - t0 < timeout_s:
        time.sleep(0.5)
        try:
            state_resp = requests.post(state_url, json={"task_id": 0}, timeout=5)
            state_result = state_resp.json()
        except Exception as e:
            print(f"状态查询异常: {e}")
            continue

        task_state = state_result.get("state", "")
        print(f"  任务状态: {task_state}")

        # 成功
        if "SUCCESS" in str(task_state).upper():
            print(f"✓ 前进 {distance} 米任务完成！")
            return True
        # 失败
        if "FAIL" in str(task_state).upper():
            print(f"✗ 任务执行失败: {task_state}")
            return False

    print("任务超时")
    return False


def main():
    # PNC 前进 0.3 米
    success = pnc_move_forward(distance=0.3, angle=0, map_id=1)
    if not success:
        print("前进任务未成功完成")


if __name__ == "__main__":
    main()
