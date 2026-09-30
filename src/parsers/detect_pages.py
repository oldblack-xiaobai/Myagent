"""
切分：按宽高比判断单页/双页
双页用垂直投影找中缝位置（不硬切50%）
"""
import os
import sys
import json
import cv2
import numpy as np


# ============================================================
# 配置
# ============================================================
ASPECT_THRESHOLD = 1.2       # 宽高比 > 此值 = 双页
GUTTER_SEARCH_L = 0.30       # 中缝搜索范围：左边界
GUTTER_SEARCH_R = 0.70       # 中缝搜索范围：右边界


def find_gutter_x(img_bgr):
    """
    在中间区域找中缝位置
    原理：中缝处内容最稀疏（投影最小）
    """
    h, w = img_bgr.shape[:2]

    # 转灰度 + 二值化
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255,
                          cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    # 只处理中部区域（排除页边）
    y0, y1 = int(h * 0.1), int(h * 0.9)
    x0, x1 = int(w * GUTTER_SEARCH_L), int(w * GUTTER_SEARCH_R)
    center = bw[y0:y1, x0:x1]

    # 垂直投影：每列的非零像素数
    projection = np.sum(center > 0, axis=0).astype(np.float32)

    # 平滑
    kernel = np.ones(21, dtype=np.float32) / 21
    smooth = np.convolve(projection, kernel, mode='same')

    # 找最小值（最白 = 中缝）
    gutter_offset = int(np.argmin(smooth))
    gutter_x = x0 + gutter_offset

    return gutter_x


def main():
    in_dir = r"d:\MyAgent\data\images_upright"
    out_dir = r"d:\MyAgent\data\pages"
    manifest_path = r"d:\MyAgent\data\pages_manifest.json"

    os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(out_dir):
        for f in os.listdir(out_dir):
            os.remove(os.path.join(out_dir, f))

    files = sorted([f for f in os.listdir(in_dir)
                    if f.lower().endswith(('.png', '.jpg', '.jpeg'))])

    print(f"共 {len(files)} 张\n")

    manifest = []

    for i, f in enumerate(files, 1):
        img_path = os.path.join(in_dir, f)
        img = cv2.imread(img_path)
        if img is None:
            print(f"[{i}/{len(files)}] {f} ❌ 读取失败")
            continue

        h, w = img.shape[:2]
        base = os.path.splitext(f)[0]
        aspect = w / h

        print(f"[{i}/{len(files)}] {f}")
        print(f"  size={w}x{h}, 宽高比={aspect:.2f}")

        if aspect > ASPECT_THRESHOLD:
            # 双页：找中缝
            gutter_x = find_gutter_x(img)
            pct = gutter_x / w * 100

            # 留一点边（避免切到内容）
            pad = 3
            left = img[:, :gutter_x - pad]
            right = img[:, gutter_x + pad:]

            left_name = f"{base}_L.png"
            right_name = f"{base}_R.png"
            cv2.imwrite(os.path.join(out_dir, left_name), left)
            cv2.imwrite(os.path.join(out_dir, right_name), right)

            print(f"  双页 中缝x={gutter_x} ({pct:.1f}%) -> {left_name}, {right_name}")

            manifest.append({
                "file": left_name, "original": f,
                "original_index": i, "source": "double", "side": "L",
                "gutter_x": gutter_x,
            })
            manifest.append({
                "file": right_name, "original": f,
                "original_index": i, "source": "double", "side": "R",
                "gutter_x": gutter_x,
            })
        else:
            # 单页
            out_name = f"{base}.png"
            cv2.imwrite(os.path.join(out_dir, out_name), img)
            print(f"  单页 -> {out_name}")
            manifest.append({
                "file": out_name, "original": f,
                "original_index": i, "source": "single", "side": None,
            })

        print()

    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=2)

    print(f"===== done =====")
    print(f"共 {len(manifest)} 个切分片段")
    print(f"manifest -> {manifest_path}")


if __name__ == "__main__":
    main()