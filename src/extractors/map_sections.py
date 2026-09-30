"""
第 1 步：识别每页"章节标题"出现的位置（并发版）
输出：outputs/section_map.json + section_ranges.json
查询记录之后的页不处理（视为尾部报告说明）
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import base64
import json
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import client, VL_MODEL
from src.extractors.section_config import SECTIONS, SUBSECTIONS, TITLE_ALIASES


MAX_WORKERS = 5


# ============================================================
# 通用逻辑
# ============================================================

ALL_STD_NAMES = set(SECTIONS)
for subs in SUBSECTIONS.values():
    ALL_STD_NAMES.update(subs)

SUB_OWNER = {}
for big, subs in SUBSECTIONS.items():
    for sub in subs:
        SUB_OWNER[sub] = big


def build_section_list_text():
    lines = []
    for s in SECTIONS:
        lines.append(f"- {s}")
        for sub in SUBSECTIONS.get(s, []):
            lines.append(f"  - {sub}")
    return "\n".join(lines)


SECTION_LIST_TEXT = build_section_list_text()


def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def classify_page(img_path, page_num):
    t_start = time.time()
    b64 = image_to_base64(img_path)

    prompt = f"""这是一页个人征信报告。

征信报告的章节标题清单如下（按已知顺序排列）：
{SECTION_LIST_TEXT}

【任务】
仔细扫描这一页的**每一行文字**，找出所有印有章节标题的位置。
特别注意：**信贷交易信息明细**下有很多子章节，必须逐一核对。

如果这一页上出现了上述任何子标题文字（哪怕只出现一次），必须报告。

【关键规则】
1. 只报告**新出现的**章节标题
2. 续页（只有表格数据，没有任何新标题文字）返回 []
3. 用清单里的标准名输出，不要带"（一）"、"三 "这类编号前缀
4. **有标题文字就必须报告，不要遗漏**
5. **如果这一页是"报告说明"、"编制说明"、"声明"等尾部内容，返回 []**

只输出 JSON 数组，不要任何其他文字。
示例：["信息概要"] 或 ["信贷交易信息明细", "非循环贷账户"] 或 []"""

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

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        try:
            titles = json.loads(raw)
        except Exception:
            titles = []

        normalized = []
        for t in titles:
            std = TITLE_ALIASES.get(t.strip(), t.strip())
            if std in ALL_STD_NAMES:
                normalized.append(std)

        return page_num, normalized, time.time() - t_start

    except Exception as e:
        print(f"    ❌ 第{page_num}页 异常：{e}")
        return page_num, [], time.time() - t_start


# ============================================================
# 顺序过滤 + 尾部处理
# ============================================================

def order_filter(section_map):
    seen_sections = set()
    seen_subs = {big: set() for big in SECTIONS}

    for page in section_map:
        new_titles = []
        for t in page["sections"]:
            if t in SECTIONS:
                if t in seen_sections:
                    continue
                idx = SECTIONS.index(t)
                prev = [SECTIONS.index(s) for s in seen_sections if s in SECTIONS]
                if prev and max(prev) >= idx:
                    continue
                new_titles.append(t)
                seen_sections.add(t)
            else:
                owner = SUB_OWNER.get(t)
                if owner is None:
                    continue
                if owner not in seen_sections:
                    continue
                if t in seen_subs[owner]:
                    continue
                subs = SUBSECTIONS[owner]
                idx = subs.index(t)
                prev = [subs.index(s) for s in seen_subs[owner] if s in subs]
                if prev and max(prev) >= idx:
                    continue
                new_titles.append(t)
                seen_subs[owner].add(t)
        page["sections"] = new_titles
    return section_map


def stop_after_query(section_map):
    """
    查询记录是报告最后一个大章节
    从"查询记录"首次出现后，所有后续页的 sections 清空
    """
    # 找"查询记录"首次出现的页码
    query_start = None
    for page in section_map:
        if "查询记录" in page["sections"]:
            query_start = page["page_num"]
            break

    if query_start is None:
        print("  [尾部处理] 未找到查询记录，跳过")
        return section_map

    # 清空查询记录之后的所有页
    cleared = 0
    for page in section_map:
        if page["page_num"] > query_start:
            if page["sections"]:
                print(f"    [清空] 第{page['page_num']}页（原内容：{page['sections']}）")
                cleared += 1
            page["sections"] = []

    print(f"  [尾部处理] 查询记录起始于第{query_start}页，清空后续 {cleared} 页")
    return section_map


def build_section_ranges(section_map):
    max_page = max(p["page_num"] for p in section_map)

    big_first = {}
    sub_first = {big: {} for big in SECTIONS}

    for page in section_map:
        pn = page["page_num"]
        for t in page["sections"]:
            if t in SECTIONS:
                if t not in big_first:
                    big_first[t] = pn
            else:
                owner = SUB_OWNER.get(t)
                if owner and t not in sub_first[owner]:
                    sub_first[owner][t] = pn

    big_list = [(s, big_first[s]) for s in SECTIONS if s in big_first]
    big_list.sort(key=lambda x: x[1])

    big_ranges = {}
    for i, (big, start) in enumerate(big_list):
        if i + 1 < len(big_list):
            end = big_list[i + 1][1]
        else:
            end = max_page
        big_ranges[big] = (start, end)

    ranges = []
    for big, (b_start, b_end) in big_ranges.items():
        ranges.append({
            "section": big,
            "level": "big",
            "start_page": b_start,
            "end_page": b_end,
        })

        subs_order = SUBSECTIONS.get(big, [])
        present_subs = [(s, sub_first[big][s]) for s in subs_order if s in sub_first[big]]

        for j, (sub, sub_start) in enumerate(present_subs):
            if j + 1 < len(present_subs):
                sub_end = max(present_subs[j + 1][1] - 1, sub_start)
            else:
                sub_end = b_end

            ranges.append({
                "section": sub,
                "level": "sub",
                "parent": big,
                "start_page": sub_start,
                "end_page": sub_end,
            })

    return ranges


# ============================================================
# 主流程
# ============================================================

if __name__ == "__main__":
    pages_dir = "data/pages_final"
    files = sorted(Path(pages_dir).glob("*.png"))

    print(f"共 {len(files)} 页")
    print(f"并发数：{MAX_WORKERS}")
    print(f"模型：{VL_MODEL}\n")

    tasks = []
    for f in files:
        page_num = int(re.search(r'\d+', f.stem).group())
        tasks.append((str(f), page_num))

    t_start = time.time()
    page_sections = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(classify_page, img_path, pn): pn
            for img_path, pn in tasks
        }

        for future in as_completed(futures):
            pn, sections, elapsed = future.result()
            page_sections[pn] = sections
            completed += 1
            display = sections if sections else "（续页）"
            print(f"[{completed}/{len(tasks)}] 第{pn}页: {display} | {elapsed:.1f}s")

    results = [
        {"file": f"p{pn:02d}.png", "page_num": pn, "sections": page_sections[pn]}
        for pn in sorted(page_sections.keys())
    ]

    print("\n--- 顺序过滤后 ---")
    results = order_filter(results)
    for page in results:
        if page["sections"]:
            print(f"  第{page['page_num']}页: {page['sections']}")

    # ★ 尾部处理：查询记录之后清空
    print("\n--- 尾部处理 ---")
    results = stop_after_query(results)

    # 打印尾部处理后结果
    print("\n--- 尾部处理后 ---")
    for page in results:
        if page["sections"]:
            print(f"  第{page['page_num']}页: {page['sections']}")

    os.makedirs("outputs", exist_ok=True)

    out1 = "outputs/section_map.json"
    with open(out1, "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=2)

    ranges = build_section_ranges(results)
    out2 = "outputs/section_ranges.json"
    with open(out2, "w", encoding="utf-8") as fp:
        json.dump(ranges, fp, ensure_ascii=False, indent=2)

    print("\n--- 章节页码范围 ---")
    for r in ranges:
        span = f"p{r['start_page']}" if r["start_page"] == r["end_page"] \
               else f"p{r['start_page']}~p{r['end_page']}"
        indent = "" if r["level"] == "big" else "    "
        print(f"{indent}  {r['section']}: {span}")

    total_time = time.time() - t_start
    print(f"\n总耗时：{total_time:.1f}s")
    print(f"保存：{out1}")
    print(f"保存：{out2}")