#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_map_points.py — 从 G2 机器人当前地图导出点位到 SQLite

功能：
  1. 读取当前 G2 机器人当前 map 里的所有导航点（GDK Map guide_pts）
  2. 打开 datas/robot_data.db，将点位插入 map_points 表
  3. 命名规则：年月日-点位序号，如 20260821-1、20260821-2 ...

环境：
  GDK 需要 LD_LIBRARY_PATH 等环境变量，本脚本会自动检测：
  若 agibot_gdk 不可用，自动 source /home/agi/app/env.sh 后重新执行自身。
  也可手动先 source 再运行，效果相同：
    source /home/agi/app/env.sh
    python3 convert_map_points.py

说明：
  - source 固定为 "map"，与 chassis_controller 的点位来源标记一致
  - 同名点位（同年月日-序号）重复运行时按"更新"处理（幂等）
  - 若 humanoid 服务（services/main.py）正在运行，其内存数据库
    在下次写操作时会整体回写覆盖 robot_data.db；本脚本跑完后
    建议重启服务，或先停服务再跑本脚本。

用法：
  cd /data/wxf/wxf0721/datas
  python3 convert_map_points.py
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime

# ── 常量 ─────────────────────────────────────────────────
ENV_SH    = "/home/agi/app/env.sh"
GDK_LIB   = "/home/agi/app/gdk/lib"
DATA_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(DATA_DIR, "robot_data.db")
SOURCE    = "map"

# 延迟持有，避免 import 本模块（如测试）就要求 GDK 就绪
_GDK = None


def _ensure_gdk_env():
    """确保 agibot_gdk 可用；若环境缺失则 source env.sh 后重 exec 自身

    LD_LIBRARY_PATH 只在进程启动时被动态链接器读取，Python 进程内
    修改无效，因此必须通过 bash source 后重新拉起进程。
    """
    global _GDK
    # PYTHONPATH 兜底（GDK 的 python 包路径）
    if GDK_LIB not in sys.path and os.path.isdir(GDK_LIB):
        sys.path.insert(0, GDK_LIB)

    try:
        import agibot_gdk
        _GDK = agibot_gdk
        return
    except ImportError:
        pass

    # 走到这说明缺 LD_LIBRARY_PATH / APP_CONF_PATH，需重 exec
    if not os.path.isfile(ENV_SH):
        print(f"[错误] agibot_gdk 不可用，且 {ENV_SH} 不存在")
        sys.exit(1)

    print("[提示] GDK 环境未加载，正在 source env.sh 后重新执行...")
    sys.stdout.flush()  # execvp 前必须刷新，否则缓冲中的提示会丢失
    cmd = (
        f'source "{ENV_SH}" >/dev/null 2>&1 && '
        f'exec "{sys.executable}" "{os.path.abspath(__file__)}"'
    )
    os.execvp("bash", ["bash", "-c", cmd])
    # execvp 成功则不会返回


def load_map_points():
    """从 GDK 读取当前地图所有导航点

    Returns
    -------
    tuple : (map_id, list[dict])
        每个点位 dict: {"index", "guide_id", "position", "orientation", "type"}
    """
    _ensure_gdk_env()

    print("[1/3] 正在从 GDK 读取当前地图...")
    m = _GDK.Map()
    time.sleep(1.0)
    curr = m.get_curr_map()
    result = m.get_map(curr.id)

    points = []
    for i, pt in enumerate(result.guide_pts, start=1):
        points.append({
            "index":       i,
            "guide_id":    str(pt.id),
            "position":    [pt.pt.position.x,    pt.pt.position.y,    pt.pt.position.z],
            "orientation": [pt.pt.orientation.x, pt.pt.orientation.y,
                            pt.pt.orientation.z, pt.pt.orientation.w],
            "type":        pt.type,
        })
    print(f"  当前地图 id={curr.id}，共读到 {len(points)} 个导航点")
    return curr.id, points


def insert_to_db(points):
    """将点位插入 robot_data.db 的 map_points 表

    命名规则：年月日-点位序号（如 20260821-1）
    """
    print(f"[2/3] 正在写入数据库: {DB_PATH}")
    date_tag = datetime.now().strftime("%Y%m%d")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # 兼容库文件尚不存在的情况（与 services/data.py 的建表语句一致）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS map_points (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            source       TEXT NOT NULL DEFAULT 'local',
            position     TEXT NOT NULL DEFAULT '[]',
            orientation  TEXT NOT NULL DEFAULT '[0,0,0,1]',
            UNIQUE(name, source)
        )
    """)

    inserted, updated = 0, 0
    for p in points:
        name = f"{date_tag}-{p['index']}"
        pos_json = json.dumps(p["position"], ensure_ascii=False)
        ori_json = json.dumps(p["orientation"], ensure_ascii=False)

        cur.execute(
            "SELECT 1 FROM map_points WHERE name=? AND source=?", (name, SOURCE)
        )
        exists = cur.fetchone() is not None

        cur.execute(
            "INSERT INTO map_points (name, source, position, orientation) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name, source) DO UPDATE SET "
            "position=excluded.position, orientation=excluded.orientation",
            (name, SOURCE, pos_json, ori_json)
        )
        if exists:
            updated += 1
        else:
            inserted += 1

    conn.commit()
    conn.close()
    print(f"  新增 {inserted} 条，更新 {updated} 条")
    return inserted, updated


def main():
    print("=" * 60)
    print("  G2 地图点位 → robot_data.db 转换")
    print("=" * 60)

    map_id, points = load_map_points()
    if not points:
        print("[提示] 当前地图没有导航点，结束")
        return

    inserted, updated = insert_to_db(points)

    date_tag = datetime.now().strftime("%Y%m%d")
    print("[3/3] 结果预览：")
    for p in points:
        name = f"{date_tag}-{p['index']}"
        pos = ", ".join(f"{v:.3f}" for v in p["position"])
        print(f"  {name:<14} guide_id={p['guide_id']:<4} "
              f"type={p['type']}  pos=({pos})")

    print()
    print(f"完成：地图 id={map_id}，{len(points)} 个点位 "
          f"（新增 {inserted}，更新 {updated}）")
    print("注意：若 humanoid 服务正在运行，请重启服务以加载新数据"
          "（服务内存库会整体回写覆盖本文件）")


if __name__ == "__main__":
    main()
