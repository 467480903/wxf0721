import time
import math
import agibot_gdk

# 导航任务状态码
_S = {0: "空闲", 1: "启动中", 2: "运行中", 3: "暂停中",
      4: "已暂停", 5: "恢复中", 6: "取消中", 7: "已取消",
      8: "失败", 9: "成功"}
_DONE = {7, 8, 9}
GDK_INIT_WAIT_S = 2.0


def main():
    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("GDK初始化失败")
        return
    print("GDK初始化成功")

    pnc = None
    try:
        pnc = agibot_gdk.Pnc()
        time.sleep(GDK_INIT_WAIT_S)

        # 目标：pnc 后退 0.5m
        dx = -0.2
        dy = 0.0
        dz = 0.0
        yaw_rad = 0.0

        # 取消旧任务
        ts = pnc.get_task_state()
        if ts.state not in _DONE and ts.state != 0:
            print(f"取消旧任务 (state={_S.get(ts.state, ts.state)})")
            pnc.cancel_task(ts.id)
            time.sleep(0.3)

        # yaw 转四元数
        half = yaw_rad / 2.0
        qz = math.sin(half)
        qw = math.cos(half)

        # 构建相对移动请求
        req = agibot_gdk.NaviReq()
        req.target.position.x = dx
        req.target.position.y = dy
        req.target.position.z = dz
        req.target.orientation.x = 0.0
        req.target.orientation.y = 0.0
        req.target.orientation.z = qz
        req.target.orientation.w = qw

        print(f"相对运动: dx={dx:+.2f}m  dy={dy:+.2f}m  yaw={math.degrees(yaw_rad):+.1f}°")

        pnc.relative_move(req)
        print("相对移动请求发送成功")

        # 等待启动
        started = False
        for _ in range(20):
            time.sleep(0.5)
            ts = pnc.get_task_state()
            if ts.state == 2:
                started = True
                print("已启动")
                break
            if ts.state in _DONE:
                break

        if not started:
            ts = pnc.get_task_state()
            if ts.state == 9:
                print("相对运动已完成（已在目标点附近）")
                return
            print(f"任务未能启动: {_S.get(ts.state, ts.state)}  {ts.message}")
            return

        # 等待完成
        start = time.time()
        timeout = 60.0
        while time.time() - start < timeout:
            time.sleep(0.5)
            ts = pnc.get_task_state()
            elapsed = time.time() - start
            print(f"\r{_S.get(ts.state, ts.state)}... {elapsed:.0f}s/{timeout:.0f}s",
                  end="", flush=True)

            if ts.state == 9:
                print(f"\n相对运动完成！耗时 {elapsed:.1f}s")
                return
            if ts.state in {7, 8}:
                print(f"\n相对运动失败: {_S.get(ts.state, ts.state)}  {ts.message}")
                return

        print(f"\n超时，取消任务")
        try:
            ts = pnc.get_task_state()
            if ts.state not in _DONE:
                pnc.cancel_task(ts.id)
        except Exception:
            pass
    except Exception as e:
        print(f"运动控制失败: {e}")
    finally:
        if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
            print("GDK释放失败")
        else:
            print("GDK释放成功")


if __name__ == "__main__":
    main()