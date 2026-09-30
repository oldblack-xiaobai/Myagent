"""
输出清洗
1. 修复"信贷交易违约信息概要"结构（字符串 → 对象）
2. 删除"信贷交易信息提示"的空行
3. 统一字段名
4. 还款记录里的金额去逗号（"1,000" → "1000"）
输入：outputs/report_extracted.json
输出：覆盖原文件
"""
import os
import json
import re


IN_PATH = "outputs/report_extracted.json"


# 字段名标准化（旧名 → 新名）
FIELD_RENAME = {
    "最近6个月内平均应还款": "最近6个月平均应还款",
    "最近6个月内平均使用额度": "最近6个月平均使用额度",
}


def fix_credit_summary(data):
    """修复"信贷交易违约信息概要"结构"""
    v = data.get("信贷交易违约信息概要")
    if isinstance(v, str):
        data["信贷交易违约信息概要"] = {"逾期信息汇总": v}
    elif v is None:
        data["信贷交易违约信息概要"] = {"逾期信息汇总": "无逾期记录"}
    return data


def remove_garbage_rows(data):
    """删除"信贷交易信息提示"里的空行"""
    items = data.get("信贷交易信息提示", [])
    if not isinstance(items, list):
        return data

    cleaned = []
    for row in items:
        if not isinstance(row, dict):
            continue
        values = [str(v).strip() for v in row.values()]
        if all(v in ("--", "", "-") for v in values):
            continue
        cleaned.append(row)

    data["信贷交易信息提示"] = cleaned
    return data


def rename_fields(data):
    """递归重命名字段"""
    if isinstance(data, dict):
        new = {}
        for k, v in data.items():
            new_k = FIELD_RENAME.get(k, k)
            new[new_k] = rename_fields(v)
        return new
    elif isinstance(data, list):
        return [rename_fields(item) for item in data]
    else:
        return data


def normalize_amounts(obj):
    """
    递归处理所有字符串：
    - 把纯数字带逗号的字符串去掉逗号（如 "400,000" → "400000"）
    - 只处理看起来像金额的（含数字和逗号，其他字符不超过 2 个）
    """
    if isinstance(obj, dict):
        return {k: normalize_amounts(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [normalize_amounts(item) for item in obj]
    elif isinstance(obj, str):
        s = obj.strip()
        # 匹配 "400,000" 这种
        if re.match(r'^\d{1,3}(,\d{3})+(\.\d+)?$', s):
            return s.replace(",", "")
        return obj
    else:
        return obj


def main():
    with open(IN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("清洗前：")
    print(f"  信贷交易违约信息概要：{type(data.get('信贷交易违约信息概要')).__name__}")
    print(f"  信贷交易信息提示：{len(data.get('信贷交易信息提示', []))} 行")

    # 1. 修复结构
    data = fix_credit_summary(data)

    # 2. 删空行
    data = remove_garbage_rows(data)

    # 3. 统一字段名
    data = rename_fields(data)

    # 4. 金额去逗号
    data = normalize_amounts(data)

    print("\n清洗后：")
    print(f"  信贷交易违约信息概要：{type(data.get('信贷交易违约信息概要')).__name__}")
    print(f"  信贷交易信息提示：{len(data.get('信贷交易信息提示', []))} 行")

    with open(IN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n输出：{IN_PATH}")


if __name__ == "__main__":
    main()