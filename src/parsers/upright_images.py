"""
方向摆正：PaddleOCR 文档方向分类
- 模型：PP-LCNet_x1_0_doc_ori
- 准确率：99.06%
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import time
import cv2
import numpy as np
from PIL import Image, ImageOps
from paddleocr import DocImgOrientationClassification


# ============================================================
# 配置
# ============================================================
CLASS_ID_TO_ROTATE = {
    0: 0,
    1: 270,
    2: 180,
    3: 90,
}

OVERRIDE = {
    # "page_XX.png": 180,
}


# ============================================================
# 加载模型
# ============================================================
print("加载 PaddleOCR 方向分类模型...")
orientation_model = DocImgOrientationClassification(
    model_name="PP-LCNet_x1_0_doc_ori"
)
print("模型加载完成\n")


# ============================================================
# 工具函数
# ============================================================

def load_exif(img_path):
    pil = Image.open(img_path)
    pil = ImageOps.exif_transpose(pil)
    if pil.mode != "RGB":
        pil = pil.convert("RGB")
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def rotate_cw(img, angle):
    if angle == 0:
        return img
    elif angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    elif angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


# ============================================================
# 从 Result 对象提取 class_id / score
# ============================================================

def extract_info(res_obj):
    """从 PaddleOCR Result 里提取 (class_id, score)"""
    # 尝试 .json 属性
    if hasattr(res_obj, "json"):
        try:
            j = res_obj.json
            if isinstance(j, str):
                import json as _json
                j = _json.loads(j)
            if isinstance(j, dict):
                inner = j.get("res", j)
                if isinstance(inner, dict):
                    cid = inner.get("class_ids")
                    scr = inner.get("scores")
                    if cid is not None and len(cid) > 0:
                        # 用 .item() 避免 numpy 数组标量警告
                        class_id = int(np.asarray(cid).flatten()[0])
                        score = float(np.asarray(scr).flatten()[0]) if scr is not None else 0.0
                        return class_id, score
        except Exception:
            pass

    # 尝试 .res 属性
    if hasattr(res_obj, "res"):
        try:
            inner = res_obj.res
            if isinstance(inner, dict):
                cid = inner.get("class_ids")
                scr = inner.get("scores")
                if cid is not None and len(cid) > 0:
                    class_id = int(np.asarray(cid).flatten()[0])
                    score = float(np.asarray(scr).flatten()[0]) if scr is not None else 0.0
                    return class_id, score
        except Exception:
            pass

    # 尝试直接当 dict
    if isinstance(res_obj, dict):
        inner = res_obj.get("res", res_obj)
        if isinstance(inner, dict):
            cid = inner.get("class_ids")
            scr = inner.get("scores")
            if cid is not None and len(cid) > 0:
                class_id = int(np.asarray(cid).flatten()[0])
                score = float(np.asarray(scr).flatten()[0]) if scr is not None else 0.0
                return class_id, score

    return None, 0.0


def detect_orientation_paddle(img_path):
    """返回 (需要顺时针旋转的角度, 置信度, 详情)"""
    try:
        output = orientation_model.predict(input=img_path)
        if not output:
            return None, 0.0, "模型无输出"

        class_id, score = extract_info(output[0])

        if class_id is None:
            return None, 0.0, "无法提取 class_id"

        angle = CLASS_ID_TO_ROTATE.get(class_id)
        if angle is None:
            return None, score, f"未知 class_id={class_id}"

        detail = f"PaddleOCR class_id={class_id} → 旋转{angle}° (conf={score:.3f})"
        return angle, score, detail

    except Exception as e:
        return None, 0.0, f"异常: {e}"


# ============================================================
# 主流程
# ============================================================

def main():
    in_dir = r"d:\MyAgent\data\images"
    out_dir = r"d:\MyAgent\data\images_upright"
    os.makedirs(out_dir, exist_ok=True)

    files = sorted([f for f in os.listdir(in_dir)
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))])

    if not files:
        print(f"❌ {in_dir} 里没有图片")
        return

    print(f"共 {len(files)} 张\n")

    t_start = time.time()
    uncertain = []

    for i, f in enumerate(files, 1):
        img_path = os.path.join(in_dir, f)
        out_path = os.path.join(out_dir, f)

        # 1. OVERRIDE 优先
        if f in OVERRIDE:
            angle = OVERRIDE[f]
            print(f"[{i}/{len(files)}] {f}  [人工指定] {angle}°")
            img = load_exif(img_path)
            if img is not None:
                cv2.imwrite(out_path, rotate_cw(img, angle))
            continue

        # 2. PaddleOCR 检测
        angle, score, detail = detect_orientation_paddle(img_path)

        if angle is None:
            print(f"[{i}/{len(files)}] {f}  ⚠️ {detail}")
            uncertain.append(f)
            img = load_exif(img_path)
            if img is not None:
                cv2.imwrite(out_path, img)
            continue

        # 3. 执行旋转
        img = load_exif(img_path)
        if img is None:
            print(f"[{i}/{len(files)}] {f}  ❌ 读取失败")
            continue

        cv2.imwrite(out_path, rotate_cw(img, angle))
        print(f"[{i}/{len(files)}] {f}  {detail}  ✅")

    total_time = time.time() - t_start
    print(f"\n===== done 耗时 {total_time:.1f}s =====")

    if uncertain:
        print(f"\n⚠️ {len(uncertain)} 张检测失败：")
        for f in uncertain:
            print(f"  - {f}")


if __name__ == "__main__":
    main()