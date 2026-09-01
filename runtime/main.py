from minth import Minth
from aruco import *
from capture import capture_head_color
from positioning import positioning as pt

G2.JOINT("idx05_body_joint5", offset=-3.14/2/2/2/2)
G2 = Minth.G2()
# img_path = capture_head_color(G2)
# print(img_path)

# G2.GO(5)
# G2.GO(4)
pt("/data/wxf/wxf0721/runtime/references-tag/ref_34HorizontalPositioning_id3_id4_20260901_100202.json",G2=G2,max_rounds=4)





# G2.GRIPPER({"left": -0.7, "right": -0.4})
# positioning("/data/wxf/wxf0721/runtime/references-tag/reference_id3_id4.json",G2=G2,max_rounds=4)
# tag_correct("/data/wxf/wxf0721/runtime/tag_ref/ref_id11_20260828_152155.json", G2)

# G2.GRIPPER({"left": -0, "right": -0})
# G2.OFFSET({"rz": 20})
