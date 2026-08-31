from minth import Minth
from positioning_tag import positioning


G2 = Minth.G2()

import tag_correct
G2.GRIPPER({"left": -0.7, "right": -0.4})
positioning("/data/wxf/wxf0721/runtime/references-tag/reference_id1_id2.json",G2=G2)
# tag_correct.tag_correct("/data/wxf/wxf0721/runtime/tag_ref/ref_id11_20260828_152155.json", G2)

# G2.GRIPPER({"left": -0, "right": -0})
# G2.OFFSET({"rz": 20})
