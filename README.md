# 征信报告 AI 解析系统

从扫描版征信报告（PDF 或手机照片），自动解析为结构化 JSON + 人话解读报告。

**项目定位**：多模态 AI 应用学习项目 / 技术选型 demo
**核心亮点**：完整工程链路 + 多方案对比 + 自动/人工平衡

---

## 目录

- [项目简介](#项目简介)
- [完整流程](#完整流程)
- [技术选型](#技术选型) ★
- [各模块详解](#各模块详解)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [时间与成本](#时间与成本)
- [学习收获](#学习收获)

---

## 项目简介

**输入**：一份征信报告（PDF / 多张手机照片）
**输出**：
- `outputs/report_extracted.json` — 结构化数据
- `outputs/report_interpretation.md` — 人话解读报告

**技术栈**：
- 图像处理：PyMuPDF、OpenCV、Pillow
- 方向矫正：PaddleOCR（飞桨）
- OCR：RapidOCR（本地）+ Qwen-VL（云端兜底）
- 多模态理解：Qwen-VL-Max / Qwen3.8-Max
- 界面：Streamlit
- 并发：ThreadPoolExecutor

---

## 完整流程

```
输入（PDF 或手机照片）
   ↓ ① 导入
data/images/page_01.png ~ page_XX.png
   ↓ ② 方向矫正（自动 + 人工兜底）
data/images_upright/
   ↓ ③ 切分单页（投影找中缝）
data/pages/
   ↓ ④ 读页码 + L/R 互补 + 排序
data/pages_final/p01.png ~ pXX.png
   ↓ ⑤ 章节树重建（VL + 顺序约束）
outputs/section_ranges.json
   ↓ ⑥ 按章节抽取（VL + JSON修复 + 失败拆页）
outputs/report_extracted.json
   ↓ ⑦ 账户过滤（结清/销户跳过）
   ↓ ⑧ 输出清洗（字段统一、金额去逗号）
   ↓ ⑨ LLM 解读（Qwen 生成 Markdown）
outputs/report_interpretation.md
```

---

## 技术选型

> **这是本项目最有价值的部分——展示了 AI 应用中"选对工具"的思考过程。**

### 选型原则

1. **有成熟工具且效果够** → 直接用，不造轮子
2. **有成熟工具但效果差** → 换替代品，或自己写
3. **完全没工具** → 用 AI 辅助从零实现
4. **自动做不了 100%** → 自动 + 人工兜底

### 方向矫正：对比 3 个方案

**任务**：判断图片被旋转了多少度（0/90/180/270）

| 方案 | 准确率 | 成本 | 结论 |
|---|---|---|---|
| Tesseract OSD | 极低（全判 0°） | 免费 | ❌ 淘汰 |
| RapidOrientation（13票投票） | 75% | 免费 | ⚠️ 不稳定 |
| **PaddleOCR PP-LCNet_x1_0_doc_ori** | **75-80%** | **免费** | ✅ **选它** |
| + Streamlit 人工修正 | **100%** | 免费 | ✅ **最终方案** |

**为什么最终方案是"自动 + 人工"**：

- 手机拍照存在**透视畸变**，超出 4 方向分类模型的表达能力
- 无论用哪个模型，准确率天花板都是 75-80%
- **人工修正 5 分钟，比调模型 5 小时更划算**
- 工业级 AI 应用的真实形态：**自动 90% + 人工 10%**

### OCR：本地优先 + 云端兜底

| 任务 | 方案 | 原因 |
|---|---|---|
| 页码识别 | **RapidOCR（本地）** | 快、免费、够用 |
| 页码兜底 | **Qwen-VL（云端）** | OCR 失败时用大模型补 |
| 印章识别 | 未做 | 不是核心需求 |

**降级链**：
```
RapidOCR 失败 → Qwen-VL 兜底
    ↓ 也失败
L/R 互补（同页左右推断）
    ↓ 也失败
缺口填充（前后页码推断）
    ↓ 也失败
标记 unknown，人工补
```

### 多模态模型：从 Max 到 Flash 的实测

| 模型 | 价格 | 效果 | 适用 |
|---|---|---|---|
| Qwen-VL-Max | ¥0.02/千tokens | ⭐⭐⭐⭐⭐ | 生产级 |
| Qwen3.8-Max | ¥12/百万tokens | ⭐⭐⭐⭐⭐ | 最新旗舰 |
| Qwen-VL-Plus | ¥0.0015/千tokens | ⭐⭐⭐ | 学习用 |
| GLM-4V-Flash（智谱） | 免费 | ⭐⭐ | 学习用，能力不足 |
| 千问 App（网页版） | 免费 | ⭐⭐⭐ | 单份报告够用 |

**实测教训**：
- **免费模型就是免费水平**——不要期待免费模型能做好复杂任务
- **单份报告用千问 App 更快**——我们的流程价值在批量/集成场景
- **但流程的优势**：结构化输出 + 特定 Prompt + 规则过滤

### 从"用工具"到"造工具"

**项目里"没有现成工具、自己写"的环节**：

| 环节 | 市面有现成方案吗 | 我们的实现 |
|---|---|---|
| 双页切分 | ❌ 没有 | OpenCV **投影找中缝** |
| 页码排序 | ⚠️ 有 OCR 但没有完整方案 | **RapidOCR + VL + 逻辑组合** |
| 章节树重建 | ❌ 没有 | **VL + 顺序约束过滤** |
| 账户过滤 | ❌ 没有 | **业务规则引擎** |
| 输出清洗 | ❌ 没有 | **字段名统一 + 金额处理** |

**这些都不是"用现成工具"，是"用 AI 辅助从零实现"——这正是 AI 应用工程师的核心工作。**

---

## 各模块详解

### ① 导入

| 脚本 | 用途 |
|---|---|
| `pdf_to_images.py` | PDF → PNG，DPI=300 |
| `import_images.py` | 图片格式统一 → PNG |

### ② 方向矫正

- **PaddleOCR** 自动判方向
- **Streamlit 界面**人工修正
- 最终 100% 正确

### ③ 切分单页

- **宽高比 > 1.2** → 双页，**投影找中缝**切分
- 中缝 = 中间区域垂直投影最低点

### ④ 页码识别排序

- RapidOCR 读页码（底部 15%）
- Qwen-VL 兜底 + 投票
- L/R 互补 + 缺口填充
- 读不出的排最后

### ⑤ 章节树重建

- 并发 5 调 Qwen-VL
- 每页识别"哪些章节标题出现在本页"
- 顺序约束过滤（用已知章节顺序纠错）

### ⑥ 按章节抽取

- 并发 5 调 Qwen-VL
- 按章节类型用不同 Prompt
- **3 层 JSON 修复**：直接解析 → 修复 → 报错
- **失败自动拆页重试**

### ⑦ 账户过滤

- **跳过**：状态"结清/提前结清/销户"且五级分类"正常"或空
- **保留还款记录**：符号行有 1-7/D/G/Z/# 或金额行非 0
- **删除还款记录**：只有 N/C/A/* 且金额都是 0

### ⑧ 输出清洗

- 结构修复（字符串 → 对象）
- 删除空行
- 字段名统一
- 金额去逗号

### ⑨ LLM 解读

- Qwen 生成 Markdown 报告
- 6 大维度：负债/逾期/查询/授信/关注/建议

---

## 目录结构

```
项目根目录\
├── .env                          # API Key（不上传）
├── .gitignore                    # Git 忽略规则
├── config.py                     # 全局配置
├── reset.py                      # 一键清理
├── app.py                        # Streamlit 界面
├── README.md
├── data/
│   ├── raw/                      # 原始 PDF（不上传）
│   ├── raw_images/               # 原始图片（不上传）
│   ├── images/                   # 标准化图片
│   ├── images_upright/           # 方向矫正后
│   ├── pages/                    # 切分后
│   └── pages_final/              # 按页码命名
├── outputs/                      # 所有输出 JSON/MD（不上传）
└── src/
    ├── parsers/
    │   ├── pdf_to_images.py
    │   ├── import_images.py
    │   ├── upright_images.py
    │   ├── detect_pages.py
    │   └── read_and_sort.py
    ├── extractors/
    │   ├── section_config.py     # ★ 唯一需要改的配置
    │   ├── map_sections.py
    │   ├── extract_sections.py
    │   ├── filter_accounts.py
    │   └── clean_output.py
    └── interpretation/
        └── generate_interpretation.py
```

---

## 快速开始

### 环境准备

```powershell
# Python 3.10+
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**安装依赖**（分步装，避免命令行过长）：

```powershell
python -m pip install opencv-python pillow pymupdf -i https://mirrors.aliyun.com/pypi/simple/
python -m pip install rapidocr paddleocr paddlepaddle onnxruntime -i https://mirrors.aliyun.com/pypi/simple/
python -m pip install numpy openai python-dotenv pydantic pandas -i https://mirrors.aliyun.com/pypi/simple/
python -m pip install streamlit -i https://mirrors.aliyun.com/pypi/simple/
```

### 配置

**`.env`**：

```
DASHSCOPE_API_KEY=sk-你的百炼key
```

**`config.py`**：

```python
VL_MODEL = "qwen-vl-max"     # 或 qwen3.8-max（有额度的话）
TEXT_MODEL = "qwen-plus"     # 解读用便宜的就行
```

### 运行

**方式 1：命令行**

```powershell
python reset.py
python src\parsers\import_images.py
python src\parsers\upright_images.py
python src\parsers\detect_pages.py
python src\parsers\read_and_sort.py
python src\extractors\map_sections.py
python src\extractors\extract_sections.py
python src\extractors\filter_accounts.py
python src\extractors\clean_output.py
python src\interpretation\generate_interpretation.py
```

**方式 2：Streamlit 界面（推荐）**

```powershell
python -m streamlit run app.py
```

界面提供：
- 一键跑全流程
- 方向人工修正面板
- 4 个 Tab 查看结果
- 下载 JSON / Markdown

**方式 3：后台启动（可选）**

```powershell
# 不弹终端，后台跑
Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" -ArgumentList "-m","streamlit","run","app.py","--server.headless","true" -WindowStyle Hidden
```

---

## 时间与成本

### 40 页报告（估算）

| 步骤 | 耗时 | 成本 |
|---|---|---|
| 图像处理（本地） | 1 分钟 | 0 |
| 方向矫正（PaddleOCR） | 10 秒 | 0 |
| 切分 + 页码（本地 + VL 兜底） | 2 分钟 | ¥0.05 |
| 章节树（并发 VL） | 30 秒 | ¥0.05 |
| 抽取（并发 VL） | 2 分钟 | ¥0.1-0.3 |
| 过滤 + 清洗（纯 Python） | 5 秒 | 0 |
| 解读（VL 或文本模型） | 30 秒 | ¥0.05 |
| **合计** | **约 5-8 分钟** | **约 ¥0.2-0.5** |

---

## 学习收获

### 技术能力

- ✅ 图像处理全链路（PDF → 切分 → 矫正）
- ✅ 云端多模态模型调用与 Prompt 工程
- ✅ 结构化 Schema 设计（Pydantic）
- ✅ 并发优化（ThreadPoolExecutor 提速 3 倍）
- ✅ 多级降级机制设计
- ✅ Streamlit 界面开发
- ✅ 完整工程化流程

### 核心思维

**1. 工具选型思维**
> 不是"有什么用什么"，而是"知道为什么用这个"

**2. 自动/人工平衡思维**
> 不是"追求全自动"，而是"自动 90% + 人工 10%"

**3. 降级容错思维**
> 每一环节都要有兜底：OCR 失败 → VL；VL 失败 → 拆页；都失败 → 人工

**4. 造工具思维**
> 没有现成工具就用 AI 辅助从零写

### 项目定位

| 场景 | 是否适合 |
|---|---|
| 单份报告随手看 | ❌ 千问 App 更快 |
| **批量 100 份** | ✅ 本系统 |
| **接入自己的系统** | ✅ 本系统 |
| **特定输出格式** | ✅ 本系统 |
| **学习 AI 应用** | ✅ 本系统 |

---

## 项目状态

| 阶段 | 状态 |
|---|---|
| A. 文档处理 + 结构化抽取 | ✅ 完成 |
| B. LLM 解读 | ✅ 完成 |
| C. Streamlit 界面 | ✅ 完成 |
| D. Agent 化 | ⏳ 可选 |

---

## 更新日志

- **2026-09-30**：README 重写，加入技术选型章节；config 示例改为通用模型
- **2026-09-29**：完整流程贯通，Streamlit 界面完成
- **2026-09-28**：章节树 + 抽取 + 过滤 + 清洗
- **2026-09-27**：PaddleOCR 方向检测
- **2026-09-26**：PDF 处理 + 切分 + 页码排序

---

## License

MIT