from minth import Minth
import time
import cv2
from capture import capture_head_color
from aruco import *

MAP_POS_Home = 2
MAP_POS_GetCar = 1
MAP_POS_GetWorkpiece = 0
MAP_POS_PutBig = 9
MAP_POS_PutSmall = 9


G2 = Minth.G2()

def putA():
    G2.ARMS("a3")
    G2.GO(4)
    G2.GO(MAP_POS_PutSmall)


    G2.WBC("W2")
    while True:
        img_path = capture_head_color(G2)
        img = cv2.imread(img_path)
        if img.shape[:2] != (400, 640):
            img = cv2.resize(img, (640, 400))
        result = analyze_top_workpiece(img,(0,200,450,img.shape[0]-200))
        if result == 0:
            break
        else:
            G2.TTS("ワークが取り除かれるのを待機；等待工件拿开")
            time.sleep(5)

    G2.WBC("W3")
    G2.WBC("W4")
    G2.WBC("W5")
    G2.GRIPPER({"right": -0.1})
    G2.WBC("W6")    #塞入！！！！！！！！！！！！！！！！！！！！！！！！！
    G2.GRIPPER({"right": -0.2})
    G2.WBC("W7")
    G2.GRIPPER({"right": -0.5})
    G2.WBC("W8")
    G2.GRIPPER({"right": -0.7})
    G2.WBC("W9")
    G2.WBC("W10") 

def putBig():
    G2.ARMS("a3")
    # G2.ARMS("a4")
    G2.ARMS("a5")
    G2.GO(3)
    G2.GO(MAP_POS_PutBig)

    positioning("/data/wxf/wxf0721/runtime/references-tag/reference_3-4.json",G2=G2)
    
    G2.WBC("xx")

    while True:
        img_path = capture_head_color(G2)
        img = cv2.imread(img_path)
        if img.shape[:2] != (400, 640):
            img = cv2.resize(img, (640, 400))
        result = analyze_top_workpiece(img,(610,410,img.shape[1]-610,img.shape[0]-410))
        if result == 0:
            break
        else:
            G2.TTS("ワークが取り除かれるのを待機；等待工件拿开")
            time.sleep(5)

    G2.WBC("x2")
    G2.WBC("x3")
    G2.GRIPPER({"right": -0.1})
    G2.WBC("x4")    #塞入！！！！！！！！！！！！！！！！！！！！！！！！！
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
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    positioning("/data/wxf/wxf0721/runtime/references-tag/reference_id1_id2.json", G2=G2)#max_rounds:4
    G2.ARMS("car3")
    G2.ARMS("car3.1")
    G2.ARMS("car5")
    # G2.OFFSET({"ry": 15, "ly": -15})
    # G2.REL({"x": 0.03}) 
    G2.GRIPPER({"left": 0, "right": 0})
    G2.GO(MAP_POS_GetWorkpiece)
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    G2.ARMS("car3.1")
    G2.OFFSET({"lx": -200, "rx": -200})
    return True

def get_work(carmove = False):
    # 取放工件
    for i in [1,2,3,4]:
        G2.GRIPPER({"left": -0.7, "right": -0.7})
        G2.WBC("Wdown2")
        G2.GO(MAP_POS_GetWorkpiece)
        if carmove:
            carmove = False
        else:
            positioning("/data/wxf/wxf0721/runtime/references-tag/reference_id1_id2.json", G2=G2)

        result = 0
        for j in range(3):
            img_path = capture_head_color(G2)
            img = cv2.imread(img_path)
            if img.shape[:2] != (400, 640):
                img = cv2.resize(img, (640, 400))
            result = analyze_top_workpiece(img,(0,230,img.shape[1],img.shape[0]-230))
            if result != 0:
                break

        jj="ref_id11_20260828_152155.json"
        if result == 0:
            G2.TTS("ワークなし；无工件")
            break
        elif result == 1:
            G2.TTS("これは大きな部品だ；这是大工件")
            jj="ref_id10_20260828_152036.json"
        elif result == 2:
            G2.TTS("これは小さな部品です；这是小工件")

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
        
        # G2.ARMS("r1")
        # for j in range(3):
        #     img_path = capture_head_color(G2)
        #     img = cv2.imread(img_path)
        #     result = analyze_top_workpiece(img)
        #     if result != 0:
        #         break

        if result == 1:
            putBig()
        elif result == 2:
            putA()
        else:
            G2.TTS("ワークなし；无工件")
            break
        
        G2.ARMS("AWait")
        # G2.REL({"x": -0.5})   

def release_car():
    G2.WBC("Wdown2")
    G2.GO(MAP_POS_GetWorkpiece)
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    positioning("/data/wxf/wxf0721/runtime/references-tag/reference_id1_id2.json", G2=G2)#max_rounds:4
    G2.ARMS("car3")
    G2.ARMS("car3.1")
    G2.ARMS("car5")
    # G2.OFFSET({"ry": 15, "ly": -15})
    # G2.REL({"x": 0.03}) 
    G2.GRIPPER({"left": 0, "right": 0})
    # G2.REL({"y": -1}) 
    G2.GO(MAP_POS_GetCar)
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    G2.ARMS("car3.1")
    G2.OFFSET({"lx": -200, "rx": -200})
    # G2.REL({"x": -0.5}) 

def main():
    carmove = False
    G2.TTS("大家好，我将进行焊装工位的上件和更换台车演示，我将把台车拉到夹具旁边。")
    G2.GO(MAP_POS_Home)
    G2.WBC("Wdown2")
    carmove = car_move()
    get_work(carmove)
    release_car()
    G2.WBC("Wdown2")
    G2.GO(MAP_POS_Home)
    G2.TTS("整体的展示完成了，谢谢参观。ご覧いただきありがとうございました。")
    G2.close()

if __name__ == "__main__":
    main()
