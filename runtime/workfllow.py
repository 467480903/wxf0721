from minth import Minth
import time
import cv2
from capture import capture_head_color
from tape_detect import analyze_top_workpiece
from positioning import positioning

G2 = Minth.G2()

# 拖小车
# G2.WBC("Wdown2")
# G2.GO(4)
# G2.GRIPPER({"left": -0.7, "right": -0.7})
# positioning("/data/wxf/wxf0721/runtime/references/reference_1-2.json", G2=G2)
# G2.ARMS("car3")
# G2.ARMS("car3.1")
# G2.ARMS("car4")
# G2.OFFSET({"ry": 10, "ly": -10})
# G2.GRIPPER({"left": 0, "right": 0})
# G2.REL({"y": -1}) 
# G2.GRIPPER({"left": -0.7, "right": -0.7})
# G2.ARMS("car3.1")
# G2.OFFSET({"lx": -200, "rx": -200})

# 取放工件
for i in [1,2,3,4]:
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    G2.WBC("Wdown2")
    G2.GO(0)
    positioning("/data/wxf/wxf0721/runtime/references/reference_1-2.json", G2=G2)
    pose = f'r{i}'
    print(f'正在去抓取{pose}')
    G2.ARMS(pose)
    G2.REL({"x": 0.14}) 
    G2.OFFSET({"rz": 30})
    G2.GRIPPER({"left": -0, "right": -0})
    time.sleep(2)
    G2.OFFSET({"rz": 10})
    G2.REL({"x": -1}) 
    
    # for j in range(3):
    #     img_path = capture_head_color(G2)
    #     img = cv2.imread(img_path)
    #     result = analyze_top_workpiece(img)
    #     if result != 0:
    #         break
    break

    # G2.ARMS("put001")
    # G2.ARMS("emm")

    if result == 1:
        # G2.TTS("这是大工件")
        # G2.GO(1)
        # positioning("/data/cg/wxf0721/runtime/references/ref_3-4_20260808_161746.json", G2=G2)
        G2.ARMS("put002")
        G2.ARMS("put001")
        G2.OFFSET({"rz": -100})
        G2.GRIPPER({"left": -0.7, "right": -0.7})
        G2.REL({"x": -0.5})

    elif result == 0:
        G2.TTS("这是小工件")
        G2.TTS("暂未实现，程序退出")
        break
    else:
        G2.TTS("无工件，程序退出")
        break

        




G2.close()
