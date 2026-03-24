import sys
import os
import time
import math
# minth.py 在上级目录 runtime/ 下，需加入搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minth import Minth

G2 = Minth.G2()




G2.setData("G2_eanbled", 1) 

pick_right = G2.readData("pick_right")
if pick_right == 0 :
    G2.setData("pick_right_done", 0) 
while pick_right == 1 :

    #
    G2.setData("pick_right_done", 1) 
    time.sleep(1)
    break;

pick_middle = G2.readData("pick_middle")
if pick_middle == 0 :
    G2.setData("pick_middle_done", 0) 
while pick_middle == 1 :
    #
    G2.setData("pick_middle_done", 1) 
    time.sleep(1)
    break;