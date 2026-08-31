import os
import sys

# 让 runtime/ 目录在 sys.path 中，命令行直接运行也能 import minth
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minth import Minth
import time

G2 = Minth.G2()
# G2.GO(9)
# G2.YOLO("wxf.pt")
# G2.CHASSIS_CORRECT(px_to_meter=-130/50/1000)
# G2.WAIST_CORRECT()
# G2.YOLO("holes.pt","192.168.0.8")
# G2.YOLO("shelf.pt","192.168.0.8")

# G2.GRIPPER({"right": -0.01})
# G2.GO(1)
G2.ARMS("a2")
G2.WBC("W2")
G2.GO(5)
G2.GO(8)
G2.GO(7)
G2.WBC("x1")
G2.WBC("x2")
G2.WBC("x3")
G2.WBC("x4")
G2.WBC("x5")
G2.WBC("x6")
G2.GRIPPER({"right": -0.2})
G2.WBC("x7")
G2.GRIPPER({"right": -0.4})
G2.WBC("x8")
G2.GRIPPER({"right": -0.6})
G2.WBC("x9")
G2.GRIPPER({"right": -0.7})
G2.WBC("x10")