"""
征信报告 AI 解析系统 - Streamlit 界面
带方向人工修正面板 + 页码待确认面板 + 启动自动加载已有结果
运行：python -m streamlit run app.py
"""
import streamlit as st
import subprocess
import os
import json
import shutil
from pathlib import Path
from PIL import Image


# ============================================================
# 配置
# ============================================================
PROJECT_ROOT = Path(__file__).parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


st.set_page_config(
    page_title="征信报告 AI 解析",
    page_icon="📊",
    layout="wide",
)


# ============================================================
# 工具函数
# ============================================================
def run_script(script_path, timeout=1800):
    full_path = PROJECT_ROOT / script_path
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(full_path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
            env=env,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"超时（>{timeout}s）"
    except Exception as e:
        return False, str(e)


def reset_workspace():
    dirs = ["data/images", "data/images_upright", "data/pages", "data/pages_final"]
    for d in dirs:
        p = PROJECT_ROOT / d
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True, exist_ok=True)

    files = [
        "outputs/section_map.json", "outputs/section_ranges.json",
        "outputs/report_extracted_raw.json", "outputs/report_extracted.json",
        "outputs/page_order.json", "outputs/report_interpretation.md",
        "outputs/need_review.json",
        "data/pages_manifest.json",
    ]
    for f in files:
        p = PROJECT_ROOT / f
        if p.exists():
            p.unlink()


def clear_raw_images():
    raw_dir = PROJECT_ROOT / "data" / "raw_images"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for f in raw_dir.glob("*"):
        if f.is_file() and not f.name.endswith(".gitkeep"):
            f.unlink()


def clear_raw_pdf():
    raw_dir = PROJECT_ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for f in raw_dir.glob("*.pdf"):
        f.unlink()


def rotate_img(path, angle):
    img = Image.open(path)
    if angle != 0:
        img = img.rotate(-angle, expand=True)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(path)


# ============================================================
# 会话状态（启动时自动检测已有结果）
# ============================================================
if "stage" not in st.session_state:
    _json = PROJECT_ROOT / "outputs" / "report_extracted.json"
    _md = PROJECT_ROOT / "outputs" / "report_interpretation.md"
    if _json.exists() and _md.exists():
        st.session_state.stage = "done"   # 有结果 → 直接进结果页
    else:
        st.session_state.stage = "idle"   # 无结果 → 上传界面
if "input_type" not in st.session_state:
    st.session_state.input_type = None
if "zoom_image" not in st.session_state:
    st.session_state.zoom_image = None


# ============================================================
# 页面标题
# ============================================================
st.title("📊 征信报告 AI 解析系统")
st.caption("上传征信报告（PDF 或图片），自动解析为结构化数据 + 人话解读报告。")


# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.header("① 选择输入类型")
    input_type = st.radio(
        "输入类型",
        ["图片（多张）", "PDF 文件"],
        horizontal=True,
    )

    st.divider()
    st.header("② 上传文件")

    uploaded_files = []
    if input_type == "图片（多张）":
        uploaded_files = st.file_uploader(
            "选择图片（可多选）",
            type=["png", "jpg", "jpeg", "bmp", "webp"],
            accept_multiple_files=True,
        )
    else:
        f = st.file_uploader("选择 PDF", type=["pdf"], accept_multiple_files=False)
        if f:
            uploaded_files = [f]

    st.divider()
    st.header("③ 开始分析")

    if st.session_state.stage == "idle":
        start_btn = st.button(
            "🚀 一键分析",
            type="primary",
            use_container_width=True,
            disabled=(not uploaded_files),
        )
    else:
        start_btn = False
        st.info(f"状态：{st.session_state.stage}")

    st.divider()
    st.caption("**流程**")
    st.caption("导入 → 矫正 → 确认 → 切分 → 排序 → 章节 → 抽取 → 过滤 → 清洗 → 解读")


# ============================================================
# 主区
# ============================================================

# ========== 阶段 1：开始 ==========
if start_btn and uploaded_files and st.session_state.stage == "idle":
    reset_workspace()

    if input_type == "图片（多张）":
        clear_raw_images()
        raw_dir = PROJECT_ROOT / "data" / "raw_images"
        for uf in uploaded_files:
            (raw_dir / uf.name).write_bytes(uf.getbuffer())
        st.session_state.input_type = "image"
    else:
        clear_raw_pdf()
        raw_dir = PROJECT_ROOT / "data" / "raw"
        (raw_dir / "report.pdf").write_bytes(uploaded_files[0].getbuffer())
        st.session_state.input_type = "pdf"

    st.subheader("⏳ 步骤 1-2：导入 + 自动方向矫正")

    with st.status("**① 导入文件**", expanded=False) as status:
        if st.session_state.input_type == "image":
            ok, out = run_script("src/parsers/import_images.py")
        else:
            ok, out = run_script("src/parsers/pdf_to_images.py")
        if ok:
            st.success("✅ 完成")
            status.update(label="**① 导入文件** ✅", state="complete")
        else:
            st.error("❌ 失败")
            st.code(out)
            status.update(label="**① 导入文件** ❌", state="error")
            st.stop()

    with st.status("**② 自动方向矫正**", expanded=False) as status:
        ok, out = run_script("src/parsers/upright_images.py")
        if ok:
            st.success("✅ 完成")
            tail = out[-1200:] if len(out) > 1200 else out
            st.code(tail, language="text")
            status.update(label="**② 自动方向矫正** ✅", state="complete")
        else:
            st.error("❌ 失败")
            st.code(out)
            status.update(label="**② 自动方向矫正** ❌", state="error")
            st.stop()

    st.session_state.stage = "direction_check"
    st.rerun()


# ========== 阶段 2：人工确认方向 ==========
elif st.session_state.stage == "direction_check":
    st.subheader("👁️ 步骤 3：确认方向")
    st.info("自动矫正已完成。请检查每张图，不对的点击按钮旋转。")

    upright_dir = PROJECT_ROOT / "data" / "images_upright"
    images = sorted(upright_dir.glob("*.png"))

    if not images:
        st.error("找不到矫正后的图片")
        st.stop()

    st.markdown(f"**共 {len(images)} 张图**")

    ctrl1, ctrl2 = st.columns([3, 1])
    with ctrl1:
        layout = st.radio(
            "每行显示",
            ["1 张（大图）", "2 张", "3 张", "4 张"],
            horizontal=True,
            index=0,
        )
    with ctrl2:
        show_filenames = st.checkbox("显示文件名", value=True)

    cols_per_row = int(layout[0])

    # 放大预览
    if st.session_state.zoom_image:
        zoom_path = Path(st.session_state.zoom_image)
        if zoom_path.exists():
            st.markdown("---")
            st.markdown(f"### 🔍 放大查看：`{zoom_path.name}`")
            zc1, zc2, zc3, zc4, zc5 = st.columns([1, 1, 1, 1, 1])
            if zc1.button("↺ 90°", key="zoom_ccw", use_container_width=True):
                rotate_img(str(zoom_path), -90)
                st.rerun()
            if zc2.button("↻ 90°", key="zoom_cw", use_container_width=True):
                rotate_img(str(zoom_path), 90)
                st.rerun()
            if zc3.button("180°", key="zoom_180", use_container_width=True):
                rotate_img(str(zoom_path), 180)
                st.rerun()
            if zc4.button("🔄 刷新", key="zoom_refresh", use_container_width=True):
                st.rerun()
            if zc5.button("✖ 关闭放大", key="zoom_close", use_container_width=True):
                st.session_state.zoom_image = None
                st.rerun()

            st.image(str(zoom_path), use_container_width=True)
            st.markdown("---")

    for i in range(0, len(images), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, col in enumerate(cols):
            idx = i + j
            if idx >= len(images):
                break
            img_path = images[idx]
            with col:
                if show_filenames:
                    st.markdown(f"**{idx+1}. {img_path.name}**")
                st.image(str(img_path), use_container_width=True)

                b1, b2, b3, b4 = st.columns(4)
                if b1.button("↺90", key=f"ccw_{img_path.name}",
                             use_container_width=True):
                    rotate_img(str(img_path), -90)
                    st.rerun()
                if b2.button("↻90", key=f"cw_{img_path.name}",
                             use_container_width=True):
                    rotate_img(str(img_path), 90)
                    st.rerun()
                if b3.button("180", key=f"r180_{img_path.name}",
                             use_container_width=True):
                    rotate_img(str(img_path), 180)
                    st.rerun()
                if b4.button("🔍", key=f"zoom_{img_path.name}",
                             use_container_width=True,
                             help="放大查看"):
                    st.session_state.zoom_image = str(img_path)
                    st.rerun()

    st.divider()
    if st.button("✅ 确认继续", type="primary", use_container_width=True):
        st.session_state.zoom_image = None
        st.session_state.stage = "running"
        st.rerun()


# ========== 阶段 3：跑后续步骤 ==========
elif st.session_state.stage == "running":
    st.subheader("⏳ 步骤 4-10：分析中")

    steps = [
        ("④ 切分单页", "src/parsers/detect_pages.py"),
        ("⑤ 读页码排序", "src/parsers/read_and_sort.py"),
        ("⑥ 章节树重建", "src/extractors/map_sections.py"),
        ("⑦ 按章节抽取", "src/extractors/extract_sections.py"),
        ("⑧ 账户过滤", "src/extractors/filter_accounts.py"),
        ("⑨ 输出清洗", "src/extractors/clean_output.py"),
        ("⑩ 生成解读报告", "src/interpretation/generate_interpretation.py"),
    ]

    progress = st.progress(0)
    status_container = st.container()
    all_ok = True

    for i, (name, script) in enumerate(steps):
        with status_container:
            with st.status(f"**{name}**", expanded=False) as status:
                ok, output = run_script(script)
                if ok:
                    st.success("✅ 完成")
                    tail = output[-800:] if len(output) > 800 else output
                    if tail.strip():
                        st.code(tail, language="text")
                    status.update(label=f"**{name}** ✅", state="complete")
                else:
                    st.error("❌ 失败")
                    st.code(output)
                    status.update(label=f"**{name}** ❌", state="error", expanded=True)
                    all_ok = False
                    break

        progress.progress((i + 1) / len(steps))

    if all_ok:
        st.success("🎉 全流程完成！")
        st.session_state.stage = "done"
        st.rerun()


# ========== 阶段 4：展示结果 ==========
elif st.session_state.stage == "done":
    st.success("🎉 分析完成！")
    st.divider()

    json_path = PROJECT_ROOT / "outputs" / "report_extracted.json"
    md_path = PROJECT_ROOT / "outputs" / "report_interpretation.md"
    review_path = PROJECT_ROOT / "outputs" / "need_review.json"

    # 检查是否有待确认
    has_review = False
    review_data = []
    if review_path.exists():
        try:
            review_data = json.loads(review_path.read_text(encoding="utf-8"))
            has_review = len(review_data) >= 3
        except Exception:
            has_review = False

    # 有需确认的，加 Tab
    if has_review:
        tabs = st.tabs([
            "⚠️ 待确认", "📋 概览", "📊 结构化数据",
            "📝 解读报告", "🔍 原始 JSON"
        ])
        tab_review, tab1, tab2, tab3, tab4 = tabs
    else:
        tabs = st.tabs([
            "📋 概览", "📊 结构化数据", "📝 解读报告", "🔍 原始 JSON"
        ])
        tab_review = None
        tab1, tab2, tab3, tab4 = tabs

    # ===== Tab 待确认 =====
    if tab_review is not None:
        with tab_review:
            st.warning(f"⚠️ 有 **{len(review_data)}** 张页码是'顺序推断'得到的，请人工核对")
            st.info(
                "**推断逻辑**：前后页页码已知，中间页通过顺序推算。\n\n"
                "**如何核对**：看下方大图，确认页码是否和'推断为第 X 页'一致。\n\n"
                "**如果不对**：在 `data/pages_final/` 里手工重命名对应文件。"
            )

            st.divider()
            for idx, item in enumerate(review_data, 1):
                st.markdown(
                    f"### {idx}. 📄 `{item['source']}` → 推断为第 **{item['inferred_page']}** 页"
                )
                st.caption(f"最终文件名：`{item['final_file']}`")

                img_path = PROJECT_ROOT / "data" / "pages_final" / item["final_file"]
                if img_path.exists():
                    st.image(str(img_path), use_container_width=True)
                else:
                    st.error(f"找不到图片：{img_path}")
                st.divider()

    # ===== Tab 1：概览 =====
    with tab1:
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            detail = data.get("信贷交易信息明细", {})

            loan_count = 0
            card_count = 0
            total_balance = 0.0
            for sec in ["非循环贷账户", "循环贷账户一", "循环贷账户二"]:
                accounts = detail.get(sec, [])
                if isinstance(accounts, list):
                    loan_count += len(accounts)
                    for acc in accounts:
                        try:
                            total_balance += float(
                                str(acc.get("余额", "0")).replace(",", "") or 0
                            )
                        except Exception:
                            pass

            cards = detail.get("贷记卡账户", [])
            if isinstance(cards, list):
                card_count = len(cards)

            queries = data.get("查询记录", [])
            query_count = len(queries) if isinstance(queries, list) else 0

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("未结清贷款", f"{loan_count} 笔")
            col2.metric("贷记卡", f"{card_count} 张")
            col3.metric("贷款余额", f"¥{total_balance:,.0f}")
            col4.metric("贷款审批查询", f"{query_count} 次")

            st.divider()
            overdue = data.get("信贷交易违约信息概要", {})
            if isinstance(overdue, dict):
                overdue_info = overdue.get("逾期信息汇总", "无")
            else:
                overdue_info = str(overdue)
            st.info(f"**逾期信息**：{overdue_info}")

            st.markdown("**公共信息**")
            for k in ["欠税记录", "民事判决记录", "强制执行记录", "行政处罚记录"]:
                v = data.get(k, [])
                if v and isinstance(v, list) and len(v) > 0:
                    st.warning(f"{k}：{len(v)} 条")
                else:
                    st.caption(f"{k}：无")

    # ===== Tab 2：结构化数据 =====
    with tab2:
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            for section, content in data.items():
                if isinstance(content, (list, dict)):
                    size = len(content)
                    with st.expander(f"**{section}**（{size} 项）", expanded=False):
                        st.json(content)
                else:
                    st.markdown(f"**{section}**：{content}")

    # ===== Tab 3：解读报告 =====
    with tab3:
        if md_path.exists():
            md_content = md_path.read_text(encoding="utf-8")
            st.markdown(md_content)
            st.divider()
            st.download_button(
                "📥 下载解读报告（Markdown）",
                md_content,
                "report_interpretation.md",
                "text/markdown",
            )

    # ===== Tab 4：原始 JSON =====
    with tab4:
        if json_path.exists():
            content = json_path.read_text(encoding="utf-8")
            st.download_button(
                "📥 下载结构化数据（JSON）",
                content,
                "report_extracted.json",
                "application/json",
            )
            st.code(content, language="json")


# ============================================================
# 底部：重新加载 / 重新开始
# ============================================================
if st.session_state.stage == "done":
    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 重新加载结果（不重新跑）", use_container_width=True):
            st.rerun()
    with col_b:
        if st.button("🔄 重新开始（清空所有数据）", use_container_width=True):
            st.session_state.stage = "idle"
            st.session_state.zoom_image = None
            reset_workspace()
            st.rerun()

elif st.session_state.stage != "idle":
    st.divider()
    if st.button("🔄 重新开始（清空所有数据）", use_container_width=True):
        st.session_state.stage = "idle"
        st.session_state.zoom_image = None
        reset_workspace()
        st.rerun()