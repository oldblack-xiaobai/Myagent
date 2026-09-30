"""
B. LLM 解读：结构化 JSON → 人话解读报告
输入：outputs/report_extracted.json
输出：outputs/report_interpretation.md
模型：qwen-plus
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import json
import re
from datetime import datetime
from config import client, TEXT_MODEL


INTERPRETATION_PROMPT = """你是一位资深信贷风控分析师。以下是一份个人征信报告的结构化数据和预计算的关键指标。

请生成一份**专业、客观、易懂**的解读报告。

【重要说明——数据口径】

1. **查询次数的口径**：
   - "近1个月查询次数"和"近2年查询次数"**只用关键指标（代码预计算）里的数字**
   - **忽略"查询记录概要"字段**（那是报告出具时的历史统计，不代表当前）
   - **不要把两者对比**，直接用关键指标里的数字

2. **"授信协议信息"单独一节展示**：
   - 授信协议是银行授予的**循环额度**
   - **不要**与贷款账户、信用卡账户做交叉分析
   - **不要**对比"授信额度 vs 余额"
   - **不要**描述为"矛盾"或"账实不符"
   - 只客观列出：机构、授信额度、已用额度、生效日期、到期日期

3. **"信息概要声明的账户数" vs "实际列出的账户数"**：
   - "信息概要"里"账户数"是**历史累计**（含已结清、已销户）
   - "信贷交易明细"里列出的是**筛选后的账户**（已删除结清/销户的）
   - 两者不一致是**正常的过滤结果**，不要强行解释

【解读要求】

## 一、基本信息概览
- 当前活跃信贷账户数（贷款 + 信用卡）
- 整体信用状况一句话总结

## 二、负债结构分析
- 贷款 vs 信用卡的负债占比
- 总负债规模及构成
- 信用卡授信使用率是否过高（>70% 需提示）
- 主要负债来源（按机构）

## 三、逾期风险
- 当前逾期（如有）
- 历史逾期情况
- 最长逾期月数
- 逾期对信用的影响评估

## 四、查询行为
- 近 1 个月查询次数（用关键指标里的数字）
- 近 2 年查询次数（用关键指标里的数字）
- 是否存在多头借贷倾向
- 查询原因分布

## 五、授信协议信息
- **单独列出**所有授信协议（机构、授信额度、已用额度、生效日期、到期日期）
- 只客观陈述事实，**不做与其他账户的关联分析**

## 六、重点关注项
- 呆账/代偿/担保等严重不良
- 异常账户

## 七、综合风险提示
给出 **3-5 条**具体的行动建议。

【关键规则】
1. 所有结论**必须有数据支撑**，引用具体数字
2. **不要编造**数据中不存在的信息
3. 使用专业但平实的语言，避免过度术语
4. 用 Markdown 格式输出，包含小标题和要点列表
5. 每个小节的结尾用一句话总结
6. **遇到数据不一致时，按上面的口径说明处理，不要强行解释矛盾**

【数据】

### 关键指标（代码预计算）
{metrics}

### 原始数据
{raw_data}"""


def load_report(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_amount(s):
    """把 '400000' 或 '400,000' 转成 float"""
    if not s:
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).replace(",", "").replace(" ", "").strip()
    t = t.rstrip("元")
    try:
        return float(t)
    except ValueError:
        return 0.0


def month_diff(y1, m1, y2, m2):
    """两个年月差几个月（y1,m1 是较晚的）"""
    return (y1 - y2) * 12 + (m1 - m2)


def parse_year_month(date_str):
    """从 '2023.05.09' 解析出 (2023, 5)，失败返回 None"""
    try:
        parts = date_str.split(".")
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None


def compute_metrics(data):
    """从结构化数据计算关键指标"""
    metrics = {
        "报告生成时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # ===== 信贷交易明细 =====
    detail = data.get("信贷交易信息明细", {})
    if not isinstance(detail, dict):
        detail = {}

    # 未结清贷款统计
    loan_sections = ["非循环贷账户", "循环贷账户一", "循环贷账户二"]
    total_loan_balance = 0.0
    loan_count = 0
    loan_details = []
    for sec in loan_sections:
        for acc in detail.get(sec, []):
            if not isinstance(acc, dict):
                continue
            balance = parse_amount(acc.get("余额", ""))
            total_loan_balance += balance
            if balance > 0:
                loan_count += 1
                loan_details.append({
                    "机构": acc.get("管理机构", ""),
                    "类型": sec,
                    "余额": balance,
                    "开立日期": acc.get("开立日期", ""),
                })

    metrics["未结清贷款笔数"] = loan_count
    metrics["未结清贷款总余额"] = total_loan_balance
    metrics["未结清贷款明细"] = loan_details

    # 贷记卡统计
    credit_cards = detail.get("贷记卡账户", [])
    total_credit_limit = 0.0
    total_credit_used = 0.0
    card_count = 0
    card_details = []
    for card in credit_cards:
        if not isinstance(card, dict):
            continue
        limit = parse_amount(card.get("借款金额", ""))
        used = parse_amount(card.get("余额", ""))
        total_credit_limit += limit
        total_credit_used += used
        if limit > 0:
            card_count += 1
        card_details.append({
            "机构": card.get("管理机构", ""),
            "授信额度": limit,
            "已用额度": used,
            "使用率": f"{used/limit*100:.1f}%" if limit > 0 else "N/A",
        })

    metrics["贷记卡张数"] = card_count
    metrics["贷记卡总授信"] = total_credit_limit
    metrics["贷记卡已用额度"] = total_credit_used
    metrics["贷记卡使用率"] = (
        f"{total_credit_used/total_credit_limit*100:.1f}%"
        if total_credit_limit > 0 else "N/A"
    )
    metrics["贷记卡明细"] = card_details

    # 总负债
    metrics["总负债"] = total_loan_balance + total_credit_used

    # ===== 信息概要 =====
    summary = data.get("信息概要", {})
    if isinstance(summary, dict):
        overdue = summary.get("信贷交易违约信息概要", {})
        if isinstance(overdue, dict):
            metrics["逾期信息"] = overdue.get("逾期信息汇总", "无")
        else:
            metrics["逾期信息"] = overdue

    # ===== 查询记录（按当前时间算） =====
    queries = data.get("查询记录", [])
    loan_queries = [q for q in queries if isinstance(q, dict)]

    now = datetime.now()
    recent_1m = 0
    recent_2y = 0

    for q in loan_queries:
        ym = parse_year_month(q.get("查询日期", ""))
        if not ym:
            continue
        diff = month_diff(now.year, now.month, ym[0], ym[1])
        if 0 <= diff <= 1:
            recent_1m += 1
        if 0 <= diff <= 24:
            recent_2y += 1

    metrics["贷款审批查询总数"] = len(loan_queries)
    metrics["近1个月贷款审批查询"] = recent_1m
    metrics["近2年贷款审批查询"] = recent_2y

    # ===== 授信协议信息（单独提取） =====
    credit_agreements = detail.get("授信协议信息", [])
    if credit_agreements and isinstance(credit_agreements, list):
        metrics["授信协议数量"] = len(credit_agreements)
        metrics["授信协议明细"] = [
            {
                "机构": a.get("管理机构", ""),
                "授信额度": a.get("授信额度", ""),
                "已用额度": a.get("已用额度", ""),
                "生效日期": a.get("生效日期", ""),
                "到期日期": a.get("到期日期", ""),
            }
            for a in credit_agreements if isinstance(a, dict)
        ]

    # ===== 公共信息 =====
    public_keys = ["欠税记录", "民事判决记录", "强制执行记录", "行政处罚记录"]
    public_issues = []
    for k in public_keys:
        v = data.get(k, [])
        if v and isinstance(v, list) and len(v) > 0:
            public_issues.append(f"{k}: {len(v)} 条")
    metrics["公共信息"] = public_issues if public_issues else "无异常"

    return metrics


def generate_interpretation(metrics, raw_data):
    prompt = INTERPRETATION_PROMPT.format(
        metrics=json.dumps(metrics, ensure_ascii=False, indent=2),
        raw_data=json.dumps(raw_data, ensure_ascii=False, indent=2)[:8000]
    )

    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4000,
    )
    return response.choices[0].message.content.strip()


def main():
    in_path = "outputs/report_extracted.json"
    out_path = "outputs/report_interpretation.md"

    if not os.path.exists(in_path):
        print(f"❌ 找不到 {in_path}")
        return

    print(f"读取：{in_path}")
    data = load_report(in_path)

    print("计算关键指标...")
    metrics = compute_metrics(data)

    print(f"\n关键指标：")
    for k, v in metrics.items():
        if isinstance(v, (int, float, str)):
            print(f"  {k}: {v}")
        elif isinstance(v, list):
            print(f"  {k}: {len(v)} 条")

    print(f"\n调用 {TEXT_MODEL} 生成解读...")
    interpretation = generate_interpretation(metrics, data)

    os.makedirs("outputs", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(interpretation)

    print(f"\n✅ 解读报告：{out_path}")
    print(f"字数：{len(interpretation)} 字")


if __name__ == "__main__":
    main()