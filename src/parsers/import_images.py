"""
把任意格式的图片导入到 data/images/，自动重命名 page_01.png ~
用法：把图片放到 data/raw_images/ 后运行
"""
import os
import shutil
from pathlib import Path


IN_DIR = "data/raw_images"
OUT_DIR = "data/images"


def main():
    # 清空输出
    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)

    # 找所有图片
    exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp')
    files = sorted([f for f in Path(IN_DIR).glob("*")
                    if f.suffix.lower() in exts])

    if not files:
        print(f"❌ {IN_DIR} 里没有图片")
        print(f"请把图片放进去，支持格式：{exts}")
        return

    print(f"共找到 {len(files)} 张图片\n")

    for i, f in enumerate(files, 1):
        new_name = f"page_{i:02d}.png"
        dst = os.path.join(OUT_DIR, new_name)

        # 转成 PNG（统一格式）
        try:
            from PIL import Image
            img = Image.open(f)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(dst, "PNG")
            print(f"  {f.name} → {new_name}")
        except Exception as e:
            # 转换失败就直接复制
            shutil.copy(f, dst)
            print(f"  {f.name} → {new_name}（直接复制）")

    print(f"\n完成！输出：{OUT_DIR}")


if __name__ == "__main__":
    main()