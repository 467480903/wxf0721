import requests
import time

PNC_URL = "http://10.42.10.11:53176/rpc/aimdk.protocol.PncService"


def move_forward(distance=0.3, angle=0, map_id=1):
    """PNC 直线前进"""
    # 下发前进任务
    resp = requests.post(
        f"{PNC_URL}/MoveForward",
        json={"task_id": 0, "map_id": map_id, "angle": angle, "distance": distance},
        timeout=10,
    )
    result = resp.json()
    print(f"任务下发: {result}")

    if result.get("state") != "CommonState_SUCCESS":
        print("下发失败")
        return False

    # 轮询任务状态
    for _ in range(120):
        time.sleep(0.5)
        state = requests.post(
            f"{PNC_URL}/ActionGetState",
            json={"task_id": 0},
            timeout=5,
        ).json()
        s = str(state.get("state", ""))
        print(f"状态: {s}")
        if "SUCCESS" in s.upper():
            print(f"完成: 前进 {distance} 米")
            return True
        if "FAIL" in s.upper():
            print("失败")
            return False

    print("超时")
    return False


if __name__ == "__main__":
    move_forward(0.3)
