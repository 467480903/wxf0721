import os

import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ANNOTATED_PATH = os.path.join(BASE_DIR, "tape_annotated.jpg")


def _save_annotation(img, valid_tapes, top_tapes, result):
    vis = img.copy()
    top_ids = {id(t) for t in top_tapes}
    for t in valid_tapes:
        x, y, w, h = t['bbox']
        if id(t) in top_ids:
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)
        else:
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 1)
    label = {0: "no tape", 1: "1 tape", 2: ">=2 tapes"}.get(result, "?")
    cv2.putText(vis, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.imwrite(ANNOTATED_PATH, vis)
    print(f"[胶带检测] 标记图已保存: {ANNOTATED_PATH}")


def analyze_top_workpiece(img, roi=None):
    if img is None:
        return None

    h, w = img.shape[:2]

    if roi is not None:
        rx, ry, rw, rh = roi
        x1 = max(0, int(rx))
        y1 = max(0, int(ry))
        x2 = min(w, x1 + int(rw))
        y2 = min(h, y1 + int(rh))
        if x2 <= x1 or y2 <= y1:
            print(f"[胶带检测] ROI 无效: {roi}, 返回 0")
            return 0
        img = img[y1:y2, x1:x2]
        print(f"[胶带检测] ROI: x=[{x1},{x2}), y=[{y1},{y2})")

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    mask1 = cv2.inRange(hsv, np.array([0, 70, 70]), np.array([10, 255, 255]))
    mask2 = cv2.inRange(hsv, np.array([170, 70, 70]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(mask1, mask2)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    valid_tapes = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 100:
            x, y, bw, bh = cv2.boundingRect(cnt)
            fill_ratio = area / (bw * bh) if bw * bh > 0 else 0
            roi_hsv = hsv[y:y+bh, x:x+bw]
            mean_s = np.mean(roi_hsv[:, :, 1])
            if fill_ratio > 0.25 and mean_s > 60:
                valid_tapes.append({
                    'bbox': (x, y, bw, bh),
                    'y_bottom': y + bh
                })

    valid_tapes.sort(key=lambda t: t['y_bottom'])

    if not valid_tapes:
        _save_annotation(img, [], [], 0)
        return 0

    min_y = valid_tapes[0]['y_bottom']
    top_tapes = [t for t in valid_tapes if t['y_bottom'] - min_y < 10]

    if len(top_tapes) == 0:
        result = 0
    elif len(top_tapes) == 1:
        result = 1
    else:
        result = 2

    _save_annotation(img, valid_tapes, top_tapes, result)

    return result


if __name__ == "__main__":
    import sys
    from capture import capture_head_color
    from minth import Minth

    G2 = Minth.G2()
    try:
        img_path = capture_head_color(G2)
        if img_path is None:
            print("拍照失败")
            sys.exit(1)

        print(f"[拍照] 图片: {img_path}")
        img = cv2.imread(img_path)

        result = analyze_top_workpiece(img)
        print(result)
    finally:
        G2.close()
