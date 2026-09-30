"""
切分后读页码 + L/R 强制对齐 + 缺口填充 + 排序（最终版）
核心规则：
1. 双页图：左页单数，右页双数，R = L + 1
2. 不连续：按置信度高的为准，推另一个
3. 只读一页：直接互补
4. 都读不出：VL 只读一次
5. 都不行：缺口填充
6. 重复页码不覆盖，加后缀
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import base64
import json
import re
import time
import shutil
import cv2
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from rapidocr import RapidOCR
from config import client, VL_MODEL


ocr = RapidOCR()

MAX_WORKERS = 5
VL_FIXED_CONF = 0.6    # VL 读一次给固定置信度


# ============================================================
# RapidOCR（返回页码 + 置信度）
# ============================================================

def run_ocr(img_array):
    result = ocr(img_array)
    if hasattr(result, "boxes"):
        boxes, txts, scores = result.boxes, result.txts, result.scores
        if boxes is None:
            return []
        return list(zip(txts, scores))
    if isinstance(result, tuple):
        return [(item[1], item[2]) for item in (result[0] or [])]
    return []


def match_page_number(text):
    if not text:
        return None
    m = re.search(r'第\s*(\d+)\s*页', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*[/／]\s*(\d+)', text)
    if m:
        return int(m.group(1))
    return None


def preprocess_enhance(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)


def read_by_rapid(img_path):
    """OCR 读页码，返回 (页码, 置信度)"""
    img = cv2.imread(str(img_path))
    if img is None:
        return None, 0.0
    h, w = img.shape[:2]

    for region_img in [
        img[int(h * 0.80):h, :],
        preprocess_enhance(img[int(h * 0.80):h, :]),
    ]:
        results = run_ocr(np.array(region_img))
        text = " ".join(t for t, _ in results)
        n = match_page_number(text)
        if n is not None:
            # 用识别结果的平均置信度
            confs = [s for _, s in results if s > 0]
            avg_conf = float(np.mean(confs)) if confs else 0.5
            return n, avg_conf

    return None, 0.0


# ============================================================
# VL 兜底（只读一次）
# ============================================================

def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def read_by_vl_once(img_path):
    """VL 读一次，返回 (页码, 置信度)"""
    b64 = image_to_base64(img_path)
    prompt = """这是一页个人征信报告的扫描图。

请在页面的底部或角落找到页码，形如「第X页 共Y页」。

只输出当前页的页码数字（比如 5）。
如果找不到页码，只输出 none。
只输出数字或 none，不要任何其他文字。"""

    try:
        response = client.chat.completions.create(
            model=VL_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }],
            temperature=0
        )
        raw = response.choices[0].message.content.strip().lower()
        m = re.search(r'\d+', raw)
        if m:
            n = int(m.group(0))
            if 1 <= n <= 200:
                return n, VL_FIXED_CONF
        return None, 0.0
    except Exception:
        return None, 0.0


def read_page_number(img_path):
    """先 RapidOCR，失败用 VL（只读一次）。返回 (页码, 方法, 置信度)"""
    n, conf = read_by_rapid(img_path)
    if n is not None:
        return n, "RapidOCR", conf

    n, conf = read_by_vl_once(img_path)
    if n is not None:
        return n, "VL", conf

    return None, "failed", 0.0


def parse_filename(name):
    m = re.match(r'page_(\d+)(?:_([LR]))?', name)
    if m:
        return int(m.group(1)), m.group(2)
    return None, None


# ============================================================
# ★ 核心：L/R 强制对齐（按置信度） ★
# ============================================================

def fix_lr_relationship(records):
    """
    双页图：R = L + 1
    规则：
    - 都读到且 R = L+1 → 完美，不动
    - 都读到但不连续 → 按置信度高的为准，推另一个
    - 只有 L → R = L+1
    - 只有 R → L = R-1
    - 都没读到 → 保持 None
    """
    by_orig = {}
    for r in records:
        orig_idx, side = parse_filename(r["source"])
        r["orig_idx"] = orig_idx
        r["side"] = side
        by_orig.setdefault(orig_idx, {})[side or "single"] = r

    fixes = 0
    for orig_idx, group in by_orig.items():
        L = group.get("L")
        R = group.get("R")
        if not (L and R):
            continue

        l_num = L["page_num"]
        l_conf = L.get("confidence", 0.0)
        r_num = R["page_num"]
        r_conf = R.get("confidence", 0.0)

        if l_num is not None and r_num is not None:
            if r_num == l_num + 1:
                # ✅ 完美
                continue

            # ❌ 不连续：按置信度选
            if l_conf >= r_conf:
                # 信 L
                print(f"  [修正] page_{orig_idx:02d}: L={l_num}(conf={l_conf:.2f}), "
                      f"R读数={r_num}(conf={r_conf:.2f}) → 信 L，R={l_num+1}")
                R["page_num"] = l_num + 1
                R["method"] = f"fix_by_L(was_{r_num})"
            else:
                # 信 R
                print(f"  [修正] page_{orig_idx:02d}: L读数={l_num}(conf={l_conf:.2f}), "
                      f"R={r_num}(conf={r_conf:.2f}) → 信 R，L={r_num-1}")
                L["page_num"] = r_num - 1
                L["method"] = f"fix_by_R(was_{l_num})"
            fixes += 1

        elif l_num is not None:
            # 只有 L 读到
            R["page_num"] = l_num + 1
            R["method"] = "L+1"
            fixes += 1

        elif r_num is not None:
            # 只有 R 读到
            L["page_num"] = r_num - 1
            L["method"] = "R-1"
            fixes += 1
        # 都没读到 → 保持 None（让缺口填充处理）

    return records, fixes


# ============================================================
# 缺口填充
# ============================================================

def gap_fill(records):
    """按物理顺序，用前后已知页码填充中间缺口"""
    sorted_records = sorted(records, key=lambda x: (
        x["orig_idx"] or 9999,
        0 if x["side"] == "L" else (1 if x["side"] == "R" else 0)
    ))

    filled = 0
    for i, r in enumerate(sorted_records):
        if r["page_num"] is not None:
            continue

        before = [x for x in sorted_records[:i] if x["page_num"] is not None]
        after = [x for x in sorted_records[i+1:] if x["page_num"] is not None]

        if before and after:
            b = before[-1]
            a = after[0]
            b_pos = sorted_records.index(b)
            a_pos = sorted_records.index(a)
            gap_pos = i - b_pos
            gap_total = a_pos - b_pos
            gap_page = a["page_num"] - b["page_num"]

            if gap_total > 0 and gap_page == gap_total:
                r["page_num"] = b["page_num"] + gap_pos
                r["method"] = "gap_fill"
                filled += 1

    return records, filled


# ============================================================
# 主流程
# ============================================================

def main():
    in_dir = "data/pages"
    out_dir = "data/pages_final"
    os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(out_dir):
        for f in os.listdir(out_dir):
            os.remove(os.path.join(out_dir, f))

    files = sorted(Path(in_dir).glob("*.png"))
    print(f"共 {len(files)} 张切片")
    print(f"并发数：{MAX_WORKERS}\n")

    # ===== 第 1 步：读页码 =====
    print("--- 第 1 步：逐张读页码（并发）---")
    t_start = time.time()

    records = []
    completed = 0

    def process_one(f):
        n, method, conf = read_page_number(str(f))
        return f.name, n, method, conf

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_one, f): f for f in files}
        for future in as_completed(futures):
            try:
                name, n, method, conf = future.result()
                completed += 1
                status = f"第{n}页(conf={conf:.2f})" if n else "读不出"
                print(f"[{completed:>2}/{len(files)}] {name:>25} → {status}  [{method}]")
                records.append({
                    "source": name, "page_num": n,
                    "method": method, "confidence": conf
                })
            except Exception as e:
                completed += 1
                f = futures[future]
                print(f"[{completed:>2}/{len(files)}] {f.name:>25} → 异常 {e}")
                records.append({
                    "source": f.name, "page_num": None,
                    "method": "error", "confidence": 0.0
                })

    print(f"\n读页码耗时：{time.time()-t_start:.1f}s")

    # ===== 第 2 步：L/R 强制对齐 =====
    print("\n--- 第 2 步：L/R 强制对齐（R = L + 1）---")
    records, n_fix = fix_lr_relationship(records)
    print(f"  修正：{n_fix} 处")

    # ===== 第 3 步：缺口填充 =====
    print("\n--- 第 3 步：缺口填充 ---")
    records, n_filled = gap_fill(records)
    print(f"  填充：{n_filled} 张")

    known = [r for r in records if r["page_num"] is not None]
    unknown = [r for r in records if r["page_num"] is None]

    print(f"\n有页码：{len(known)} 张")
    print(f"无页码：{len(unknown)} 张")

    known.sort(key=lambda x: x["page_num"])

    # ===== 第 4 步：重命名（检测重复，不覆盖） =====
    final_records = []
    used_names = {}

    for r in known:
        n = r["page_num"]
        base_name = f"p{n:02d}"

        if base_name in used_names:
            # 已有同名文件，加后缀
            idx = len(used_names[base_name])
            suffix = chr(ord('a') + idx)
            new_name = f"{base_name}_{suffix}.png"
            print(f"  ⚠️ 页码 {n} 重复：{r['source']} → {new_name}")
            used_names[base_name].append(new_name)
        else:
            new_name = f"{base_name}.png"
            used_names[base_name] = [new_name]

        shutil.copy(os.path.join(in_dir, r["source"]),
                    os.path.join(out_dir, new_name))
        final_records.append({
            "file": new_name, "page_num": n,
            "source": r["source"], "method": r["method"]
        })

    for i, r in enumerate(unknown, 1):
        new_name = f"unknown_{i:02d}.png"
        shutil.copy(os.path.join(in_dir, r["source"]),
                    os.path.join(out_dir, new_name))
        final_records.append({
            "file": new_name, "page_num": None,
            "source": r["source"], "method": r["method"]
        })

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/page_order.json", "w", encoding="utf-8") as fp:
        json.dump(final_records, fp, ensure_ascii=False, indent=2)

    # ===== 连续性检查 =====
    nums = sorted([r["page_num"] for r in known])
    if nums:
        min_n, max_n = min(nums), max(nums)
        missing = sorted(set(range(min_n, max_n + 1)) - set(nums))
        dupes_nums = sorted([n for n in set(nums) if nums.count(n) > 1])

        print(f"\n--- 连续性检查 ---")
        print(f"页码范围：{min_n} ~ {max_n}")
        if missing:
            print(f"⚠️ 缺失：{missing}")
        if dupes_nums:
            print(f"⚠️ 重复：{dupes_nums}")
        if not missing and not dupes_nums:
            print(f"✅ 页码连续，无缺失无重复")

    print(f"\n输出目录：{out_dir}")
    print(f"总文件数：{len(final_records)}")


if __name__ == "__main__":
    main()