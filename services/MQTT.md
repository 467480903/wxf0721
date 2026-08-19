# MQTT 主题清单

本文件整理 `services/` 后端服务当前所有 MQTT 主题，包括方向、QoS、payload 格式与命令分支。

- **Broker**：`localhost:1883`（TCP，服务端内部）
- **WebSocket**：`9001`（前端 `web/js/mqtt-client.js` 使用，与 mosquitto 配置对齐）
- **客户端 ID**：`humanoid_server`（服务端）、`g2_web_xxxx`（前端）
- **主题命名规范**：`/humanoid/<模块>/<data|control>`，`data` = 服务端发布、`control` = 客户端订阅
- **状态保护**：`joints/control` 与 `commands/data` 执行期间 `common.get_state()=="busy"`，新命令被拒绝，完成后向 `/humanoid/commands/done` 发布 `{"command":"done","cmd":<原命令>}`

主题常量统一定义在 [common.py](file:///data/wxf/wxf0721/services/common.py#L44-L71)。

---

## 1. 相机 camera

| Topic | 方向 | QoS | payload |
|-------|------|-----|---------|
| `/humanoid/camera/data` | 服务端→客户端 | 0 | `{"timestamp":..,"head_color":"<b64>","head_depth":"<b64>","left_wrist":"<b64>","right_wrist":"<b64>"}` |
| `/humanoid/camera/control` | 客户端→服务端 | 0 | `{"command":"<cmd>", ...}` |

`control` 命令分支（[camera.py:handle_control](file:///data/wxf/wxf0721/services/camera.py#L587)）：

| command | 说明 | 额外字段 |
|---------|------|---------|
| `start` | 开始发布相机流 | — |
| `stop` | 停止发布相机流 | — |
| `start_continuous_capture` | 开始连拍保存到 `images/` | — |
| `stop_continuous_capture` | 停止连拍 | — |
| `save_photo` | 保存指定相机图片 | `cameras: ["kHeadColor","kHeadDepth",...]` |
| `detect` | YOLO 检测 | `yolo: "wxf.pt"`, 可选 `yolo_ip: "10.2.236.7"`（自定义服务端 IP，不传走默认） |

---

## 2. 关节 joints

| Topic | 方向 | QoS | payload |
|-------|------|-----|---------|
| `/humanoid/joints/data` | 服务端→客户端 | 0 | `{"command":"read", "joints":[...], "positions":[...]}` |
| `/humanoid/joints/control` | 客户端→服务端 | 2 | `{"command":"<cmd>", "data":...}`（busy 保护） |
| `/humanoid/joints/save` | 客户端→服务端 | 0 | `{"command":"<cmd>", ...}` |

`control` 命令分支（[joints.py:handle_control](file:///data/wxf/wxf0721/services/joints.py#L270)）：

| command | 说明 | data |
|---------|------|------|
| `WBC` | 全身关节（从 DB 加载） | `"hold"` 或内联 dict |
| `arms` | 双臂 | `{idx21..:0.1,...}` |
| `left` | 左臂 | dict |
| `right` | 右臂 | dict |
| `head` | 头部 3 关节 | dict |
| `waist` | 腰部 5 关节 | dict |
| `joint` | 单关节微调 | `{"name":"idx11_head_joint1","offset":0.01}` 或 `{"name":..,"value":0.0}` |

`save` 命令分支（[joints.py:handle_save](file:///data/wxf/wxf0721/services/joints.py#L296)）：

| command | 说明 | 字段 |
|---------|------|------|
| `save_joints` | 保存关节角 | `type,name,data` |
| `save_position` | 保存末端位姿 | `type,name,data` |
| `read` | 读取列表（发布到 `joints/data`） | — |
| `update` | 更新 | `category(joints|positions),type,name,data` |
| `delete` | 删除 | `category,type,name` |

---

## 3. 状态 status

| Topic | 方向 | QoS | payload |
|-------|------|-----|---------|
| `/humanoid/status/data` | 服务端→客户端 | 0 | `{"timestamp","joints":{..},"left_ee":{"position","orientation"},"right_ee":{..},"chassis":{"x","y","yaw","loc_state","loc_confidence"}}` |
| `/humanoid/status/cloud` | 服务端→客户端 | 0 | 点云 JSON（按需发布） |
| `/humanoid/status/control` | 客户端→服务端 | 0 | `{"command":"<cmd>"}` |

`control` 命令分支（[status.py:handle_control](file:///data/wxf/wxf0721/services/status.py#L282)）：

| command | 说明 |
|---------|------|
| `start_cloud` | 开始发布点云 |
| `stop_cloud` | 停止发布点云 |

---

## 4. 命令 commands

| Topic | 方向 | QoS | payload |
|-------|------|-----|---------|
| `/humanoid/commands/data` | 客户端→服务端 | 2 | `{"command":"<cmd>","data":...}` |
| `/humanoid/commands/done` | 服务端→客户端 | 2 | `{"command":"done","cmd":<原命令>}` |

`data` 命令分支（[commands.py:handle_control](file:///data/wxf/wxf0721/services/commands.py#L215)）：

| command | 说明 | data |
|---------|------|------|
| `tts` | 语音播报 | `"文本"` |
| `offset_move` | 末端相对移动（毫米） | `{"lx","ly","lz","rx","ry","rz"}` |
| `grab` | 夹爪 | `{"left":0.5,"right":0.5}`（负=张开，正=闭合） |
| `go` | 导航到地图点位 | `9`（点位编号/名称） |
| `go_rel` | 底盘相对运动 | `{"x","y","yaw_rad"}` |
| `cam_head` | 头部相机检测（旧接口） | 模型名字符串，默认 `shelf.pt` |

---

## 5. 地图 map

| Topic | 方向 | QoS | payload |
|-------|------|-----|---------|
| `/humanoid/map/points` | 服务端→客户端 | 0 | `{"command":"map_points","data":[{name,source,position,orientation},...]}` |
| `/humanoid/map/info` | 服务端→客户端 | 0 | `{"command":"maps","data":[...]}` 或 `{"command":"slam_state","data":{"state","is_mapping"}}` |
| `/humanoid/map/control` | 客户端→服务端 | 0 | `{"command":"<cmd>","data":...}` |

`control` 命令分支（[map.py:handle_control](file:///data/wxf/wxf0721/services/map.py#L200)）：

| command | 说明 | data |
|---------|------|------|
| `read_points` | 从 GDK 当前地图重新读取所有导航点并发布 | — |
| `start_mapping` | 开始 SLAM 建图 | — |
| `stop_mapping` | 停止建图并保存 | — |
| `read_maps` | 读取地图列表 | — |
| `switch_map` | 切换地图 | `{"map_id":"xxx"}` |

---

## 6. 程序调试 programs

| Topic | 方向 | QoS | payload |
|-------|------|-----|---------|
| `/humanoid/programs/control` | 客户端→服务端 | 0 | `{"command":"<cmd>","data":...}` |
| `/humanoid/programs/step` | 服务端→客户端 | 0 | `{"lineno":3,"code":"print(1)","filename":"main.py"}` |
| `/humanoid/programs/codes` | 服务端→客户端 | 0 | `{"code":"..."}` |
| `/humanoid/programs/files` | 服务端→客户端 | 0 | `{"files":["a.py","b.py"]}` |
| `/humanoid/programs/file_content` | 服务端→客户端 | 0 | `{"filename":"a.py","code":"...","success":true}` |
| `/humanoid/programs/upload_result` | 服务端→客户端 | 0 | `{"success":true,"filename":"xxx.py"}` 或 `{"success":false,"error":"..."}` |
| `/humanoid/programs/delete_result` | 服务端→客户端 | 0 | `{"success":true,"filename":"xxx.py"}` 或 `{"success":false,"error":"..."}` |

`control` 命令分支（[programs.py:handle_control](file:///data/wxf/wxf0721/services/programs.py)）：

| command | 说明 | data |
|---------|------|------|
| `run` | 运行 main.py | — |
| `debug` | 单步调试模式 | — |
| `next` | 执行下一行 | — |
| `stop` | 停止当前程序 | — |
| `copy` | 复制 programs/{data} → main.py | `"a.py"` |
| `codes` | 发布 main.py 内容 | — |
| `read_files` | 发布文件列表 | — |
| `read_file` | 发布指定文件内容 | `"a.py"` |
| `upload` | 上传 .py 文件 | `{"filename":"xxx.py","content":"..."}` |
| `delete` | 删除 .py 文件 | `"xxx.py"` |

---

## 7. Modbus

| Topic | 方向 | QoS | payload |
|-------|------|-----|---------|
| `/humanoid/modbus/data` | 服务端→客户端 | 0 | `{"command":"modbus_data","devices":[{ip,port,read:[{address,value}],write:[{address,value}]}]}` |
| `/humanoid/modbus/control` | 客户端→服务端 | 0 | `{"command":"<cmd>","data":...}` |

`control` 命令分支（[modbus.py:handle_control](file:///data/wxf/wxf0721/services/modbus.py#L312)）：

| command | 说明 | data |
|---------|------|------|
| `read` | 触发一次读取并发布 | — |
| `write` | 写入 holding register | `{ip,address,value}` |
| `add_device` | 增加设备 | `{ip,port?,rate?}` |
| `add_read_addrs` | 增加读取地址区间 | `{ip,start,end}` |
| `add_write_addrs` | 增加写入地址区间 | `{ip,start,end}` |
| `del_read_addr` | 删除单个读取地址 | `{ip,address}` |
| `del_write_addr` | 删除单个写入地址 | `{ip,address}` |

---

## 8. 外部/旁路主题（非 services/ 发布，仅记录）

| Topic | 来源 | 说明 |
|-------|------|------|
| `/minth/g2/camera/detect` | `yolo/detect_server.py` | YOLO 标注结果图 base64（独立 TCP 服务端发布） |
| `/runtime_debug` 等 | `runtime/run.py`（旧版） | 已由 `programs/*` 主题取代，main.py 不再使用 |

---

## 服务端订阅汇总（[main.py:on_connect](file:///data/wxf/wxf0721/services/main.py#L70-L77)）

```
/humanoid/camera/control     qos=0
/humanoid/joints/control     qos=2
/humanoid/joints/save        qos=0
/humanoid/status/control     qos=0
/humanoid/commands/data      qos=2
/humanoid/map/control        qos=0
/humanoid/programs/control    qos=0
/humanoid/modbus/control     qos=0
```

## 完成通知约定

所有耗时命令执行完毕后，服务端通过 `common.publish_done(cmd)` 向 `/humanoid/commands/done` 发布：
```json
{"command": "done", "cmd": "<原命令>"}
```
前端 `minth.py` 的 `_send_and_wait` 与 `Minth.G2` 各方法靠此机制实现同步阻塞调用。
