import sys
import os
import time
import math

# minth.py 在上级目录 runtime/ 下，需加入搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minth import Minth

G2 = Minth.G2()
G2.TTS("从送料机上抓料，底盘运动到送料机前面")
G2.GRIPPER({"left": -0.78})#爪子张开
G2.GO(7)
G2.GO(5)
G2.WBC("SQ1")
G2.WBC("SQ2")
G2.WBC("SQ3")
G2.WBC("SQ4")
G2.WBC("SQ5")
time.sleep(1.2)
G2.GRIPPER({"left": -0.05})#爪子关闭
time.sleep(1.2)
G2.WBC("SQ6")
G2.REL({"x":-0.4}) #底盘后退0.5米
G2.REL({"yaw_rad": math.pi })
G2.TTS("向弯曲机放料，运动到设备前方")
G2.GRIPPER({"left": -0.05})
G2.GO(6)
G2.WBC("WF1")
G2.WBC("WF2")
# G2.OFFSET({"lx": 20}) 
# G2.OFFSET({"lz": -65}) 
G2.WBC("WF3")
time.sleep(1.2)
G2.GRIPPER({"left": -0.78})
time.sleep(1.2)
G2.WBC("WF4")
# G2.OFFSET({"lz": -20}) 
# G2.OFFSET({"lx": -80}) 
G2.WBC("WF5")
G2.WBC("WF6")
G2.TTS("在弯曲机上放料完成，后退")
G2.REL({"x":-0.3})
