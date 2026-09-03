from re import X

from minth import Minth
import time

import json
import paho.mqtt.client as mqtt

# 往 localhost:1883 /playMP3 发送 MP3 播放命令
_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bbbb_mp3")
_mqtt.connect("localhost", 1883)
_mqtt.loop_start()
_mqtt.publish("/playMP3", json.dumps({"cmd": "play", "file": "JPCH1.mp3"}), qos=0)
print("[MP3] 已发送播放命令: JPCH1.mp3")

G2 = Minth.G2()
G2.YOLO("shelf.pt", "192.168.0.8")

if 2>3 :

    # G2.GO_NOWAIT(0)
    G2.REL_NOWAIT({"x": -1.5})
    
    G2.TTS("跑到位置0")
    # G2.WBC("xx")
    G2.GO(0)
    time.sleep(2)
    # G2.GO_NOWAIT(2)
    G2.REL_NOWAIT({"x": 0.5})
    G2.TTS("跑到位置2")
    G2.WBC("A3")

if 2>3 :
    G2.WBC("xx")
    G2.GO(8)
    G2.GRIPPER({"right": -0.7})
    time.sleep(5)
    G2.GRIPPER({"right": -0.0})    
    time.sleep(2)
    
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
    # G2.OFFSET({"ry": -13})
    G2.OFFSET({"rz": -80})
    # G2.OFFSET({"rx": 12})
    # G2.OFFSET({"ry": -15})
    # G2.OFFSET({"rz": -20})
    # G2.OFFSET({"ry": -15})
    G2.GRIPPER({"right": -0.2})
    G2.OFFSET({"rz": -25})
    
    G2.OFFSET({"rx": -45})

    G2.OFFSET({"ry": +40})   #左右扯
    G2.OFFSET({"ry": -40}) 
    G2.GRIPPER({"right": -0.74})
    G2.OFFSET({"rz": -50})
    # G2.OFFSET({"rz": -20})    




    
    G2.OFFSET({"rx": -120})
    G2.ARMS("big11")
    G2.GO(8)
    G2.GO(2)

if 2>1 :

    # G2.GO(2)
    # G2.WBC("A3")
    # G2.GRIPPER({"right": -0.7})
    # time.sleep(5)
    # G2.GRIPPER({"right": -0.0})
    # time.sleep(2)
    G2.GO_NOWAIT(10)
    G2.WBC("xx")    
    # G2.GO(9)
    # G2.ARMS("big1")
    # G2.ARMS("big2")
    # G2.ARMS("big3")
    # G2.ARMS("big4")
    # G2.OFFSET({"rx": 31+20+10+10})
    # G2.OFFSET({"rz": -20})
    # G2.OFFSET({"rz": -20})    
    # G2.OFFSET({"rz": -40})   
    # G2.OFFSET({"rx": -55}) #推出后再拉回
    # G2.GRIPPER({"right": -0.1})
    # G2.OFFSET({"rz": -20})    
    # G2.OFFSET({"rz": -30})     
    # G2.GRIPPER({"right": -0.3})
    # G2.OFFSET({"rz": -8})     
    # G2.OFFSET({"ry": +40})   #左右扯
    # G2.OFFSET({"ry": -40})     
  

    # G2.GRIPPER({"right": -0.5})  
    # G2.OFFSET({"rz": -5})  
    # G2.GRIPPER({"right": -0.7})
    # G2.OFFSET({"rx": -180})
    # G2.WBC("xx")

    
    G2.GO_NOWAIT(2)
    G2.WBC("A3")    

if 2>3 :
    G2.GO_NOWAIT(10)
    G2.OFFSET({"ry": -15})
    G2.GO_NOWAIT(9)
    G2.OFFSET({"ry": 15})
    G2.TTS("小盒子")    
# G2.GRIPPER({"right": -0.5})
# G2.JOINT("idx05_body_joint5", offset=-3.14/2/2/2/2)
# G2.REL({"x": -2.1+0.4, "y": -1.7, "yaw_rad": 0})
# G2.REL({"x": -0.1})
# G2.REL({"x": 0.095})