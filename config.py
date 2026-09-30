import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 视觉模型：用于章节识别、内容抽取、页码兜底
VL_MODEL = "qwen3.8-flash"

# 文本模型：用于生成解读报告
TEXT_MODEL = "qwen-plus"