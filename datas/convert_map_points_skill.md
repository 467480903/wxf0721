新建一个文件  datas/convert_map_points.py 
它的功能是
1 读取当前 G2 机器人里， 当前 map 里的所有点位
2 打开 robot_data.db 这个 sqlite 数据库， 然后， 将 map 中读取到的所有点位， 新增插入到 map_points 表中， 命名规则为， 年月日-点位序号
