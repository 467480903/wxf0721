from minth import Minth
import time
import cv2
from capture import capture_head_color
from tape_detect import analyze_top_workpiece
from positioning import positioning

G2 = Minth.G2()

def putA():
    G2.ARMS("a3")
    G2.WBC("W2")
    G2.GO(2)
    G2.GO(4)
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
    G2.ARMS("a4")
    G2.GO(5)
    G2.GO(10)
    G2.WBC("x2")
    G2.GO(7)
    G2.WBC("x3")
    G2.GRIPPER({"right": -0.1})
    G2.WBC("x4")    #塞入！！！！！！！！！！！！！！！！！！！！！！！！！
    G2.WBC("x5")
    G2.WBC("x6")
    G2.GRIPPER({"right": -0.2})
    G2.WBC("x7")
    G2.GRIPPER({"right": -0.5})
    G2.WBC("x8")
    G2.GRIPPER({"right": -0.7})
    G2.WBC("x9")
    G2.WBC("x10")

def car_move():
    # 拖小车
    G2.WBC("Wdown2")
    G2.GO(9)
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    positioning("/data/wxf/wxf0721/runtime/references/reference_1-2.json", G2=G2)
    G2.ARMS("car3")
    G2.ARMS("car3.1")
    G2.ARMS("car5")
    # G2.OFFSET({"ry": 15, "ly": -15})
    # G2.REL({"x": 0.03}) 
    G2.GRIPPER({"left": 0, "right": 0})
    G2.GO(0)
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    G2.ARMS("car3.1")
    G2.OFFSET({"lx": -200, "rx": -200})

def get_work():
    # 取放工件
    for i in [1,2,3,4]:
        G2.GRIPPER({"left": -0.7, "right": -0.7})
        G2.WBC("Wdown2")
        G2.GO(0)
        positioning("/data/wxf/wxf0721/runtime/references/reference_1-2.json", G2=G2)

        result = 0
        for j in range(3):
            img_path = capture_head_color(G2)
            img = cv2.imread(img_path)
            if img.shape[:2] != (400, 640):
                img = cv2.resize(img, (640, 400))
            result = analyze_top_workpiece(img,(0,230,img.shape[1],img.shape[0]-230))
            if result != 0:
                break

        if result == 0:
            G2.TTS("无工件，ワークなし")
            break
        elif result == 1:
            G2.TTS("这是大工件，これは大きな部品だ")
        elif result == 2:
            G2.TTS("这是小工件，これは小さな部品です")


        pose = f'r{i}'
        G2.ARMS(pose)
        G2.REL({"x": 0.14}) 
        G2.OFFSET({"rz": 30})
        G2.GRIPPER({"left": -0, "right": -0})
        time.sleep(0.5)
        G2.OFFSET({"rz": 5})
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
            G2.TTS("无工件，ワークなし")
            break

        G2.REL({"x": -0.5})   

def release_car():
    G2.WBC("Wdown2")
    G2.GO(0)
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    positioning("/data/wxf/wxf0721/runtime/references/reference_1-2.json", G2=G2)
    G2.ARMS("car3")
    G2.ARMS("car3.1")
    G2.ARMS("car5")
    # G2.OFFSET({"ry": 15, "ly": -15})
    # G2.REL({"x": 0.03}) 
    G2.GRIPPER({"left": 0, "right": 0})
    # G2.REL({"y": -1}) 
    G2.GO(9)
    G2.GRIPPER({"left": -0.7, "right": -0.7})
    G2.ARMS("car3.1")
    G2.OFFSET({"lx": -200, "rx": -200})
    # G2.REL({"x": -0.5}) 

def main():
    time.sleep(0.1)#姿态安全吗
    # car_move()
    # get_work()
    # release_car()
    G2.WBC("Wdown2")
    G2.GO(1)
    G2.TTS("结束，終わり")
    G2.close()

if __name__ == "__main__":
    main()
