import sys
import os
# minth.py 在上级目录 runtime/ 下，需加入搜索路径
#sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minth import Minth

G2 = Minth.G2()
G2.REL({"X": 0.2})   
G2.GO(6)
G2.GO(3)
G2.GO(5)