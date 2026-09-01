#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts.py — 直接使用 agibot_gdk 的独立 TTS 测试脚本

不依赖 minth.py，也不依赖 services 里的程序。

功能：
  TTS 语音播报："你好你好"

环境：
  GDK 需要 LD_LIBRARY_PATH 等环境变量，本脚本会自动检测：
  若 agibot_gdk 不可用，自动 source /home/agi/app/env.sh 后重新执行自身。
  也可手动先 source 再运行，效果相同：
    source /home/agi/app/env.sh
    python3 tts.py
"""

import os
import sys
import time

# ── 常量 ─────────────────────────────────────────────────
ENV_SH  = "/home/agi/app/env.sh"
GDK_LIB = "/home/agi/app/gdk/lib"

TTS_TEXT = "你好你好"


def _ensure_gdk_env():
    """确保 agibot_gdk 可用；若环境缺失则 source env.sh 后重 exec 自身"""
    if GDK_LIB not in sys.path and os.path.isdir(GDK_LIB):
        sys.path.insert(0, GDK_LIB)
    try:
        import agibot_gdk  # noqa: F401
        return
    except ImportError:
        pass

    if not os.path.isfile(ENV_SH):
        print(f"[错误] agibot_gdk 不可用，且 {ENV_SH} 不存在")
        sys.exit(1)

    print("[提示] GDK 环境未加载，正在 source env.sh 后重新执行...")
    sys.stdout.flush()
    cmd = (
        f'source "{ENV_SH}" >/dev/null 2>&1 && '
        f'exec "{sys.executable}" "{os.path.abspath(__file__)}"'
    )
    os.execvp("bash", ["bash", "-c", cmd])


def main():
    _ensure_gdk_env()
    import agibot_gdk

    print("=" * 60)
    print("  tts: GDK 独立测试 — TTS 播报")
    print("=" * 60)

    if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
        print("[错误] gdk_init 失败")
        sys.exit(1)

    try:
        interaction = agibot_gdk.Interaction()
        time.sleep(1.0)

        print(f"\n🔊 TTS: {TTS_TEXT}")
        try:
            interaction.play_tts(TTS_TEXT)
            print("   播放命令已发送")
        except Exception as e:
            print(f"   播放失败: {e}")

        print("\n完成: TTS 已下发")

    finally:
        if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
            print("[警告] gdk_release 失败")


if __name__ == "__main__":
    main()
