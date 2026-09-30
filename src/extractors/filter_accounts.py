"""
账户过滤（后处理）
从 section_config.py 读哪些章节是账户类
"""
import os
import json
import shutil
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.extractors.section_config import SECTION_EXTRACTION


RAW_PATH = "outputs/report_extracted_raw.json"
OUT_PATH = "outputs/report_extracted.json"

SKIP_STATUSES = {"结清", "提前结清", "销户"}
NORMAL_CLASSES = {"正常", ""}
ABNORMAL_SYMBOLS = {"1", "2", "3", "4", "5", "6", "7", "D", "G", "Z", "#"}


def get_account_containers():
    """从配置读账户容器"""
    result = {}
    for section, config in SECTION_EXTRACTION.items():
        if config.get("mode") == "by_sub":
            subs = list(config.get("sub_prompts", {}).keys())
            if subs:
                result[section] = subs
    return result

def normalize(s):
    if s is None:
        return ""
    return str(s).strip().upper()


def should_skip_account(acc):
    status = normalize(acc.get("账户状态", ""))
    five = normalize(acc.get("五级分类", ""))
    return status in SKIP_STATUSES and five in NORMAL_CLASSES


def _parse_amount(s):
    """
    尝试把字符串解析为金额（数字）
    返回 float 或 None
    """
    if not s:
        return None
    # 去逗号、空格
    t = str(s).replace(",", "").replace(" ", "").strip()
    # 去掉末尾可能的非数字字符
    t = t.rstrip("元")
    try:
        return float(t)
    except ValueError:
        return None


def has_abnormal_record(records):
    """
    检查还款记录有没有异常
    兼容两种格式：

    格式 1：二维数组（符号行 + 金额行交替）
      表头是 1-12 月份
      第 1 行：状态符号 N/C/A/1-7/D/G/Z/*/#
      第 2 行：该月逾期金额（0=无逾期，非0=有逾期）
      第 3 行：状态符号
      第 4 行：金额
      ...
      偶数索引（0,2,4...）= 符号行
      奇数索引（1,3,5...）= 金额行

    格式 2：嵌套字典 {"2021": {"1":"N", ...}, "2022": {...}}
      只检查值（符号），月份/年份是 key 不看

    判断规则：
      符号行出现 N/C/A/* 之外的符号 → 异常
      金额行出现非 0 数字 → 异常
    """
    if not records:
        return False

    # ===== 格式 1：二维数组 =====
    if isinstance(records, list):
        for idx, row in enumerate(records):
            if not isinstance(row, (list, tuple)):
                continue

            is_symbol_row = (idx % 2 == 0)

            for c in row:
                s = normalize(c)
                if not s:
                    continue

                if is_symbol_row:
                    # 符号行：N/C/A/* 之外算异常
                    if s in ABNORMAL_SYMBOLS:
                        return True
                else:
                    # 金额行：非 0 数字算异常
                    amount = _parse_amount(c)
                    if amount is not None and amount > 0:
                        return True
        return False

    # ===== 格式 2：嵌套字典 =====
    if isinstance(records, dict):
        for year, months in records.items():
            if isinstance(months, dict):
                for month, sym in months.items():
                    if normalize(sym) in ABNORMAL_SYMBOLS:
                        return True
            elif isinstance(months, list):
                for sym in months:
                    if normalize(sym) in ABNORMAL_SYMBOLS:
                        return True
        return False

    return False


def filter_account(acc):
    result = dict(acc)
    if "还款记录" in result:
        if not has_abnormal_record(result["还款记录"]):
            del result["还款记录"]
    return result


def main():
    if not os.path.exists(RAW_PATH):
        if not os.path.exists(OUT_PATH):
            print(f"❌ 找不到 {OUT_PATH}")
            return
        shutil.copy(OUT_PATH, RAW_PATH)
        print(f"备份原始：{RAW_PATH}")

    with open(RAW_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    containers = get_account_containers()
    print(f"账户容器：{list(containers.keys())}\n")

    total_skip = 0
    total_keep = 0

    for container, sections in containers.items():
        container_data = data.get(container, {})
        if not isinstance(container_data, dict):
            continue

        for section in sections:
            accounts = container_data.get(section, [])
            if not isinstance(accounts, list):
                continue

            print(f"【{container} → {section}】共 {len(accounts)} 条")
            new_list = []
            for acc in accounts:
                if not isinstance(acc, dict):
                    new_list.append(acc)
                    continue
                mgr = acc.get("管理机构", "?")
                if should_skip_account(acc):
                    print(f"  [跳过] {mgr}")
                    total_skip += 1
                    continue
                print(f"  [保留] {mgr}")
                new_list.append(filter_account(acc))
                total_keep += 1
            container_data[section] = new_list

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n跳过：{total_skip}，保留：{total_keep}")
    print(f"输出：{OUT_PATH}")


if __name__ == "__main__":
    main()