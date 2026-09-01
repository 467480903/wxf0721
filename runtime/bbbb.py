from re import X

from minth import Minth
import time

G2 = Minth.G2()
# G2.YOLO("shelf.pt", "192.168.0.8")
G2.JOINT("idx05_body_joint5", offset=-3.14/2/2/2/2)
# G2.REL({"x": -2.1+0.4, "y": -1.7, "yaw_rad": 0})
# G2.REL({"x": -0.1})
# G2.REL({"x": 0.095})