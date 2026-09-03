from minth import Minth
from positioning import positioning as pt
import paho.mqtt.client as mqtt
import time

def putBig(G2):
    G2.GO(8)
    # time.sleep(1)
    G2.WBC("xx")
    time.sleep(1)
 
    G2.GO(8)
    G2.WBC("xx")
    # pt("/data/wxf/wxf0721/runtime/references-tag/ref_id3_id4_20260901_133511.json",G2=G2,max_rounds=9)
    G2.GO(7)

    G2.ARMS("big1")
    G2.ARMS("big2")
    G2.ARMS("big3")
    G2.ARMS("big4")
    G2.OFFSET({"rz": -20})
    G2.GRIPPER({"right": -0.1})
    G2.OFFSET({"rz": -80})
    G2.GRIPPER({"right": -0.15})
    G2.OFFSET({"rz": -25})
    G2.OFFSET({"rx": -45})
    G2.OFFSET({"ry": +45})   #左右扯
    G2.OFFSET({"ry": -45}) 

    G2.GRIPPER({"right": -0.74})
    G2.OFFSET({"rz": -49})
    G2.OFFSET({"rx": -120})

    G2.ARMS("big11")
    G2.GO(8)
    G2.GO(2)


def putSmall(G2):
    G2.WBC("xx")    
    time.sleep(1)
    G2.GO(10)
    time.sleep(1)
    G2.WBC("xx")    
    G2.GO(9)
    G2.ARMS("big1")
    G2.ARMS("big2")
    G2.ARMS("big3")
    G2.ARMS("big4")
    G2.OFFSET({"rx": 31+20+10+10})
    G2.OFFSET({"rz": -20})
    G2.OFFSET({"rz": -20})    
    G2.OFFSET({"rz": -40})   
    G2.OFFSET({"rx": -55}) #推出后再拉回
    G2.GRIPPER({"right": -0.1})
    G2.OFFSET({"rz": -20})    
    G2.OFFSET({"rz": -30})     
    G2.GRIPPER({"right": -0.3})
    G2.OFFSET({"ry": +40})   #左右扯
    G2.OFFSET({"ry": -40})     
  
    # G2.OFFSET({"rz": -20})  
    
    # G2.OFFSET({"rx": -10})  
    G2.GRIPPER({"right": -0.5})  
    G2.OFFSET({"rz": -5})  
    G2.GRIPPER({"right": -0.7})
    G2.OFFSET({"rx": -180})
    G2.WBC("xx")
    G2.GO(10)

