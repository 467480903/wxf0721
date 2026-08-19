import cv2
import numpy as np


def analyze_top_workpiece(img):
    """识别最上面工件的胶带类型"""
    if img is None:
        return None

    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 检测黄色胶带
    lower_yellow = np.array([12, 70, 70])
    upper_yellow = np.array([35, 255, 255])
    yellow_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    yellow_mask = cv2.morphologyEx(yellow_mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    valid_tapes = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 100:
            x, y, bw, bh = cv2.boundingRect(cnt)
            fill_ratio = area / (bw * bh) if bw * bh > 0 else 0
            roi = hsv[y:y+bh, x:x+bw]
            mean_s = np.mean(roi[:, :, 1])
            if fill_ratio > 0.25 and mean_s > 60:
                valid_tapes.append({
                    'bbox': (x, y, bw, bh),
                    'y_bottom': y + bh
                })

    valid_tapes.sort(key=lambda t: t['y_bottom'])

    if not valid_tapes:
        return 0   # 无胶带

    min_y = valid_tapes[0]['y_bottom']
    top_tapes = [t for t in valid_tapes if t['y_bottom'] - min_y < 10]

    if len(top_tapes) == 0:
        return 0   # 无胶带
    elif len(top_tapes) == 1:
        return 1   # 单胶带
    else:
        return 2   # 双胶带或更多


if __name__ == "__main__":
    import sys
    from capture import capture_head_color
    from minth import Minth

    G2 = Minth.G2()
    try:
        # 拍照
        img_path = capture_head_color(G2)
        if img_path is None:
            print("拍照失败")
            sys.exit(1)

        print(f"[拍照] 图片: {img_path}")
        img = cv2.imread(img_path)

        # 识别
        result = analyze_top_workpiece(img)
        print(result)
    finally:
        G2.close()

