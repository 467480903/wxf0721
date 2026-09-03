from minth import Minth
import time
import cv2
from capture import capture_head_color
from aruco import *
from positioning import positioning as pt
import paho.mqtt.client as mqtt
import put 


MAP_POS_Home = 2
MAP_POS_GetCar = 1
MAP_POS_GetWorkpiece = 0
MAP_POS_PutBig = 4
MAP_POS_PutSmall = 6


G2 = Minth.G2()

def tape_detection(roi):
    while True:
        img_path = capture_head_color(G2)
        img = cv2.imread(img_path)
        if img is None:
            continue
        if img.shape[:2] != (400, 640):
            img = cv2.resize(img, (640, 400))
        result = analyze_top_workpiece(img,roi)
        if result == 0:
            break
        else:
            # playMp3("/PLACE_ENABLE.mp3")
            G2.TTS("ワークが取り除かれるのを待機；等待工件拿开")
            time.sleep(5)
    playMp3("/PLACE_ENABLE.mp3")


def playMp3(mp3):
    # 往 localhost:1883 /playMP3 发送 MP3 播放命令
    _mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bbbb_mp3")
    _mqtt.connect("localhost", 1883)
    _mqtt.loop_start()
    _mqtt.publish("/playMP3", json.dumps({"cmd": "play", "file": mp3}), qos=0)

def putA():
    G2.REL({"x": -1.7,"y": -1.7}) 
    G2.GO(MAP_POS_PutSmall)
    pt("/data/wxf/wxf0721/runtime/references-tag/ref_id5_id6_dun.json",G2=G2)
    G2.WBC("xx")

    tape_detection((0,215,440,400-215))

    G2.WBC("W2.3")
    G2.WBC("W2")
    G2.WBC("W3")
    G2.GRIPPER({"right": -0.1})
    G2.WBC("W4")
    # G2.WBC("W5")
    G2.WBC("W6")    #塞入！！！！！！！！！！！！！！！！！！！！！！！！！
    G2.GRIPPER({"right": -0.2})
    G2.WBC("W7")
    G2.GRIPPER({"right": -0.5})
    G2.WBC("W8")
    G2.GRIPPER({"right": -0.7})
    G2.WBC("W9")
    G2.WBC("W10") 

def UpPutBig():
    G2.GO(3)
    G2.WBC("xx")
    G2.GO(MAP_POS_PutBig)
    results = pt("/data/wxf/wxf0721/runtime/references-tag/ref_id3_id4_20260901_133511.json",G2=G2)
    _res = results[-1]
    offestX = -_res["dt"][0]
    offestY = -_res["dt"][1]+8
    G2.ARMS("big1")
    G2.ARMS("big2")
    G2.ARMS("big3")
    G2.MoveL("big4", {"x": offestX, "y": offestY})
    G2.MoveL("big6", {"x": offestX, "y": offestY})
    G2.GRIPPER({"right": -0.1})
    G2.MoveL("big7", {"x": offestX, "y": offestY})
    G2.GRIPPER({"right": -0.2})
    G2.MoveL("big8", {"x": offestX, "y": offestY})
    G2.GRIPPER({"right": -0.7})
    # G2.ARMS("big9")
    G2.ARMS("big10")
    G2.ARMS("big11")

    
def putBig():
    G2.GO(3)
    G2.GO(MAP_POS_PutBig)
    pt("/data/wxf/wxf0721/runtime/references-tag/ref_id3_id4_dun.json",G2=G2)
    G2.WBC("xx")

    tape_detection((305,205,640-305,400-205))

    G2.WBC("x2")
    G2.WBC("x3")
    G2.WBC("x4")    #塞入！！！！！！！！！！！！！！！！！！！！！！！！！
    G2.GRIPPER({"right": -0.1})
    G2.WBC("x5")
    G2.WBC("x6")
    G2.GRIPPER({"right": -0.2})
    G2.WBC("x7")
    G2.GRIPPER({"right": -0.4})
    G2.WBC("x8")
    G2.GRIPPER({"right": -0.7})
    G2.WBC("x9")
    G2.WBC("x10")

def car_move():
    # 拖小车
    G2.WBC("Wdown2")
    G2.GO(MAP_POS_GetCar)
    G2.GRIPPER({"left": -0.75, "right": -0.75})
    pt("/data/wxf/wxf0721/runtime/references-tag/reference_id1_id2.json", G2=G2)
    G2.ARMS("car3")
    G2.ARMS("car3.1")
    G2.ARMS("car5")
    # G2.OFFSET({"ry": 15, "ly": -15})
    # G2.REL({"x": 0.03}) 
    G2.GRIPPER({"left": 0, "right": 0})
    G2.JOINT("idx05_body_joint5", value=0.0)
    G2.REL({"y": -1}) 
    G2.GO(MAP_POS_GetWorkpiece)
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    G2.ARMS("car3.1")
    G2.OFFSET({"lx": -200, "rx": -200})
    return True

def get_work():
    # 取放工件
    for i in [1,2,3,4]:
        G2.GRIPPER({"left": -0.75, "right": -0.75})
        G2.WBC("Wdown2")
        G2.GO(MAP_POS_GetWorkpiece)
        positioning("/data/wxf/wxf0721/runtime/references-tag/reference_id1_id2.json", G2=G2)

        result = 0
        for j in range(3):
            img_path = capture_head_color(G2)
            img = cv2.imread(img_path)
            if img is None:
                continue
            if img.shape[:2] != (400, 640):
                img = cv2.resize(img, (640, 400))
            result = analyze_top_workpiece(img,(0,230,img.shape[1],img.shape[0]-230))
            if result != 0:
                break

        jj="ref_id11_20260828_152155.json"
        if result == 0:
            playMp3("EMPTY.mp3")
            # G2.TTS("ワークなし；无工件")
            break
        elif result == 1:
            playMp3("BIG.mp3")
            # G2.TTS("これは大きな部品だ；这是大工件")
            jj="ref_id10_20260828_152036.json"
        elif result == 2:
            playMp3("SMALL.mp3")
            # G2.TTS("これは小さな部品です；这是小工件")

        pose = f'r{i}'
        G2.ARMS(pose)
        G2.REL({"x": 0.12}) 
        G2.GRIPPER({"left": -0.7, "right": -0.4})
        # 在这里纠偏 (AprilTag 36h11, 39mm, 右手腕相机)
        tag_correct(f"/data/wxf/wxf0721/runtime/tag_ref/{jj}", G2)
        G2.OFFSET({"rz": 20})
        G2.GRIPPER({"left": -0, "right": -0})
        # time.sleep(0.5)
        G2.OFFSET({"rz": 10})
        G2.REL({"x": -1}) 
        G2.ARMS("a3")
        G2.ARMS("a5")

        if result == 1:
            put.putBig(G2)
        elif result == 2:
            put.putSmall(G2)
        else:
            playMp3("EMPTY.mp3")
            break
        
        # G2.ARMS("AWait")
        # G2.REL({"x": -0.5})   

def release_car():
    G2.WBC("Wdown2")
    G2.GO(MAP_POS_GetWorkpiece)
    G2.GRIPPER({"left": -0.75, "right": -0.75})
    pt("/data/wxf/wxf0721/runtime/references-tag/reference_id1_id2.json", G2=G2)#max_rounds:4
    G2.ARMS("car3")
    G2.ARMS("car3.1")
    G2.ARMS("car5")
    # G2.OFFSET({"ry": 15, "ly": -15})
    # G2.REL({"x": 0.03}) 
    G2.GRIPPER({"left": 0, "right": 0})
    G2.JOINT("idx05_body_joint5", value=0.0)
    G2.REL({"y": 1}) 
    # G2.GO(MAP_POS_GetCar)
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    G2.ARMS("car3.1")
    G2.OFFSET({"lx": -200, "rx": -200})
    # G2.REL({"x": -0.5}) 

def main():
    playMp3("START.mp3 ")
    G2.GO(MAP_POS_Home)
    G2.WBC("Wdown2")
    playMp3("GRAB_OUT.mp3")
    # car_move()
    get_work()
    playMp3("EMPTY.mp3")
    release_car()
    G2.WBC("Wdown2")
    G2.GO(MAP_POS_Home)
    G2.close()

if __name__ == "__main__":
    main()
