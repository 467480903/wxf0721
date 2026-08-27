import agibot_gdk
import time

# 初始化GDK系统
if agibot_gdk.gdk_init() != agibot_gdk.GDKRes.kSuccess:
    print("GDK初始化失败")
    exit(1)
print("GDK初始化成功")

map_manager = agibot_gdk.Map()
time.sleep(2)

# 获取当前地图ID后，获取完整地图信息
current_map = map_manager.get_curr_map()
map_info = map_manager.get_map(current_map.id)

print(f"地图名称: {map_info.name}, ID: {map_info.id}")
print(f"栅格尺寸: {map_info.grid_map.width} x {map_info.grid_map.height}")
print(f"分辨率: {map_info.grid_map.resolution}")
print(f"原点: ({map_info.grid_map.origin.position.x}, {map_info.grid_map.origin.position.y})")

# 释放GDK系统资源
if agibot_gdk.gdk_release() != agibot_gdk.GDKRes.kSuccess:
    print("GDK释放失败")
else:
    print("GDK释放成功")