from minth import Minth
from aruco import *


G2 = Minth.G2()
# G2.GO(1)

G2.WBC("x2")
G2.WBC("x3")
G2.WBC("x4")   
G2.GRIPPER({"right": -0.1})
G2.WBC("x5") #塞入！！！！！！！！！！！！！！！！！！！！！！！！！
G2.WBC("x6")
G2.GRIPPER({"right": -0.2})
G2.WBC("x7")
G2.GRIPPER({"right": -0.4})
G2.WBC("x8")
G2.GRIPPER({"right": -0.7})
G2.WBC("x9")
G2.WBC("x10")

# G2.GRIPPER({"left": -0.7, "right": -0.4})
# positioning("/data/wxf/wxf0721/runtime/references-tag/reference_id3_id4.json",G2=G2,max_rounds=4)
# tag_correct("/data/wxf/wxf0721/runtime/tag_ref/ref_id11_20260828_152155.json", G2)

# G2.GRIPPER({"left": -0, "right": -0})
# G2.OFFSET({"rz": 20})
