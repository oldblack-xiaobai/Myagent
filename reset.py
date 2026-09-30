"""
一键清理单份报告的所有中间产物
保留：data/raw/*.pdf + outputs/report_interpretation.md
删除：其他所有中间文件
"""
import os
import shutil


# 要清空的目录
CLEAN_DIRS = [
    "data/images",           # PDF 转出的原图
    "data/images_upright",   # 旋转后的图
    "data/pages",            # 切分后的单页
    "data/pages_final",      # 按页码命名后的单页
]

# 要删除的文件
CLEAN_FILES = [
    "data/pages_manifest.json",
    "outputs/section_map.json",
    "outputs/section_ranges.json",
    "outputs/report_extracted_raw.json",
    "outputs/report_extracted.json",
    "outputs/page_order.json",
    "outputs/original_page_num.json",
    "outputs/pages_original_num.json",
    "outputs/pages_extracted.json",
]


def main():
    print("开始清理...\n")

    # 清空目录（保留目录本身）
    for d in CLEAN_DIRS:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"  ✅ 已清空目录：{d}")
        os.makedirs(d, exist_ok=True)

    # 删除文件
    for f in CLEAN_FILES:
        if os.path.exists(f):
            os.remove(f)
            print(f"  ✅ 已删除文件：{f}")

    print(f"\n完成！")
    print(f"保留：")
    print(f"  - data/raw/*.pdf（原始 PDF）")
    if os.path.exists("outputs/report_interpretation.md"):
        print(f"  - outputs/report_interpretation.md（解读报告）")


if __name__ == "__main__":
    main()