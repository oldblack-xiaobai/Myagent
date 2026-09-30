"""
把 PDF 每页转成 PNG 图片
适用于扫描件 PDF（全能扫描王、拍照等生成的）
"""
import fitz  # PyMuPDF
import os


def pdf_to_images(pdf_path: str, output_dir: str, dpi: int = 300):
    """
    把 PDF 每页渲染成 PNG 图片

    参数：
        pdf_path: PDF 文件路径
        output_dir: 图片输出目录
        dpi: 渲染分辨率，300 更清晰，推荐用于征信报告
    """
    os.makedirs(output_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"PDF 共 {total_pages} 页")

    image_paths = []
    for page_num in range(total_pages):
        page = doc[page_num]

        # 按 DPI 渲染成图片
        zoom = dpi / 72  # PDF 默认 72 DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        output_path = os.path.join(output_dir, f"page_{page_num + 1:02d}.png")
        pix.save(output_path)
        image_paths.append(output_path)
        print(f"  第 {page_num + 1} 页 → {output_path}")

    doc.close()
    print(f"\n共生成 {len(image_paths)} 张图片")
    return image_paths


if __name__ == "__main__":
    # ===== 修改这里 =====
    pdf_path = "data/raw/report.pdf"          # 你的 PDF 路径
    output_dir = "data/images"                # 图片输出目录
    # =====================

    pdf_to_images(pdf_path, output_dir, dpi=300)