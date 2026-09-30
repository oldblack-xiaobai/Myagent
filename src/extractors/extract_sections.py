"""
第 2 步：按章节抽取（并发版 + 失败自动拆分）
============================================================
所有抽取规则从 section_config.py 读，本文件不写死任何章节名。
============================================================
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import client, VL_MODEL
from src.extractors.section_config import SECTION_EXTRACTION


MAX_WORKERS = 5
MAX_RETRY = 2


def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def call_vl(prompt, img_paths):
    content = [{"type": "text", "text": prompt}]
    for p in img_paths:
        b64 = image_to_base64(p)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}
        })

    response = client.chat.completions.create(
        model=VL_MODEL,
        messages=[{"role": "user", "content": content}],
        temperature=0,
        max_tokens=16000,
    )
    return response.choices[0].message.content.strip()


def _extract_json_block(text):
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start:end + 1]
    return text


def _fix_common_json_issues(text):
    text = re.sub(r"(\w+)\s*:\s*'([^']*)'", r'\1: "\2"', text)
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    text = text.replace('"', '"').replace('"', '"')
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    return text


def parse_json_response(text):
    block = _extract_json_block(text)
    try:
        return json.loads(block)
    except Exception:
        pass
    try:
        fixed = _fix_common_json_issues(block)
        return json.loads(fixed)
    except Exception:
        return {"_error": "JSON 解析失败", "_raw": block[:1000]}


def get_pages(start, end):
    paths = []
    for pn in range(start, end + 1):
        f = f"data/pages_final/p{pn:02d}.png"
        if os.path.exists(f):
            paths.append(f)
    return paths


def build_tasks(ranges):
    tasks = []
    for r in ranges:
        section = r["section"]
        level = r["level"]
        parent = r.get("parent")

        if level == "big":
            config = SECTION_EXTRACTION.get(section)
            if config is None:
                continue
            mode = config.get("mode", "skip")
            if mode == "by_big":
                tasks.append({
                    "type": "big",
                    "key": section,
                    "prompt": config["prompt"],
                    "start": r["start_page"],
                    "end": r["end_page"],
                    "container": None,
                })
        elif level == "sub":
            if parent is None:
                continue
            parent_config = SECTION_EXTRACTION.get(parent)
            if parent_config is None:
                continue
            if parent_config.get("mode") != "by_sub":
                continue
            prompts = parent_config.get("sub_prompts", {})
            prompt = prompts.get(section)
            if prompt is None:
                continue
            tasks.append({
                "type": "sub",
                "key": section,
                "prompt": prompt,
                "start": r["start_page"],
                "end": r["end_page"],
                "container": parent,
            })
    return tasks


# ============================================================
# 【单次抽取，带重试】
# ============================================================

def _try_extract(prompt, pages):
    """单次抽取，失败返回 None"""
    for attempt in range(MAX_RETRY + 1):
        try:
            raw = call_vl(prompt, pages)
        except Exception:
            if attempt < MAX_RETRY:
                time.sleep(2 ** attempt)
                continue
            return None

        data = parse_json_response(raw)
        if "_error" not in data:
            return data

        if attempt < MAX_RETRY:
            time.sleep(2 ** attempt)

    return None


# ============================================================
# 【抽取单个任务：失败自动拆分】
# ============================================================

def extract_one_task(task):
    """
    抽取单个任务
    第 1 轮：整段多页一起抽
    第 2 轮：失败时拆成单页分别抽，合并结果
    """
    t_start = time.time()
    pages = get_pages(task["start"], task["end"])
    if not pages:
        return task, None, "failed", time.time() - t_start

    # ===== 第 1 轮：整段抽取 =====
    data = _try_extract(task["prompt"], pages)
    if data is not None:
        return task, data, "ok", time.time() - t_start

    # ===== 第 2 轮：拆页重试 =====
    if len(pages) == 1:
        return task, None, "failed", time.time() - t_start

    print(f"    ⚠️ {task['key']} 整段失败，拆 {len(pages)} 页重试...")

    merged = {}
    success = 0
    for single_page in pages:
        data = _try_extract(task["prompt"], [single_page])
        if data is None:
            continue
        success += 1
        for k, v in data.items():
            if k.startswith("_"):
                continue
            if k in merged and isinstance(merged[k], list) and isinstance(v, list):
                merged[k].extend(v)
            else:
                merged[k] = v

    if success > 0:
        return task, merged, "retry_ok", time.time() - t_start

    return task, None, "failed", time.time() - t_start


# ============================================================
# 【主流程】
# ============================================================

def main():
    ranges_path = "outputs/section_ranges.json"
    out_path = "outputs/report_extracted.json"

    with open(ranges_path, "r", encoding="utf-8") as f:
        ranges = json.load(f)

    tasks = build_tasks(ranges)
    total = len(tasks)
    print(f"共 {total} 个抽取任务")
    print(f"并发数：{MAX_WORKERS}\n")

    t_start = time.time()
    results = []
    stats = {"ok": 0, "retry_ok": 0, "failed": 0}
    failed_sections = []
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(extract_one_task, t): t for t in tasks}

        for future in as_completed(futures):
            try:
                task, data, status, elapsed = future.result()
            except Exception as e:
                task = futures[future]
                data, status, elapsed = None, "failed", 0
                print(f"  ❌ {task['key']} 异常：{e}")

            completed += 1
            stats[status] += 1

            if status == "failed":
                failed_sections.append(task["key"])
                print(f"[{completed}/{total}] {task['key']} ❌ 失败 | {elapsed:.1f}s")
            else:
                mark = "✅" if status == "ok" else "🔄"
                print(f"[{completed}/{total}] {task['key']} {mark} {status} | {elapsed:.1f}s")

            results.append((task, data, status))

    # 按起始页排序合并
    results_sorted = sorted(
        results,
        key=lambda x: (x[0]["start"], 0 if x[0]["type"] == "big" else 1)
    )

    result = {}
    for task, data, status in results_sorted:
        if status == "failed" or data is None:
            continue

        if task["type"] == "big":
            for k, v in data.items():
                if k.startswith("_"):
                    continue
                result[k] = v
        else:
            container = task["container"]
            result.setdefault(container, {})
            for k, v in data.items():
                if k.startswith("_"):
                    continue
                result[container][k] = v

    os.makedirs("outputs", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total_time = time.time() - t_start
    print(f"\n{'='*50}")
    print(f"成功：{stats['ok']}")
    print(f"重试成功：{stats['retry_ok']}")
    print(f"失败：{stats['failed']}")
    if failed_sections:
        print(f"失败章节：{failed_sections}")
    print(f"总耗时：{total_time:.1f}s")
    print(f"\n结果保存：{out_path}")


if __name__ == "__main__":
    main()