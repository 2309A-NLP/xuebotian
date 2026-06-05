# RAG QA System

基于大模型的 PDF RAG 问答系统，后端使用 FastAPI，前端使用原生 HTML/CSS/JS，向量库支持 Milvus，本地嵌入模型支持 BGE-m3，LLM 调用兼容 OpenAI 接口的大模型 API。

## 功能概览

- PDF 上传、解析、文本与表格抽取
- 文本清洗、去重、水印去除
- 使用本地 BGE-m3 向量化并写入 Milvus
- 基于意图识别和检索增强的问答
- 文档解析结果持久化和管理
- 文字与语音输入
- 日志与异常 traceback 记录
- 前后端分离，后端提供 API，前端用原生页面调用

## 项目结构

```text
app/
  api/                 # API 路由与依赖
  core/                # 配置、日志、异常、容器
  models/              # 内部领域模型
  schemas/             # API 出入参模型
  services/            # 核心业务服务
  utils/               # 通用工具
frontend/
  assets/              # 前端样式和脚本
data/
  uploads/             # 原始上传文件
  parsed/              # 解析后的文档 JSON
  documents/           # SQLite 元数据
  logs/                # 日志
docs/
  技术文档.md
  用户手册.md
run.py
```

## 启动说明

1. 准备 Python 3.11+
2. 安装依赖
3. 复制 `.env.example` 为 `.env` 并填写配置
4. 直接运行根目录的 `run.py`

```bash
python run.py
```

如果系统已经将 `.py` 文件关联到 Python，也可以直接双击 `run.py` 启动。  
打开 `http://127.0.0.1:8000` 即可访问前端界面。

## 关键配置

- `EMBEDDING_MODEL_NAME`: 本地 BGE-m3 模型路径或模型名
- `EMBEDDING_DEVICE`: `cuda` / `cpu`
- `VECTOR_BACKEND`: `milvus` 或 `memory`
- `MILVUS_URI`: Milvus 地址
- `LLM_BASE_URL`: 在线大模型兼容 OpenAI 的接口地址
- `LLM_API_KEY`: 大模型 API Key
- `LLM_MODEL`: 调用模型名

## 说明

- 该项目优先保证结构清晰、接口可替换，方便后续接入真实环境。
- 当前代码已包含 Milvus、SentenceTransformer(BGE-m3)、OpenAI 兼容 API 的实现适配层。
- 语音输入采用前端录音、后端转写的方式实现，音频仅在请求过程中以内存字节流形式传输，不落盘保存。

## 项目文档

- 技术文档：`docs/技术文档.md`
- 用户手册：`docs/用户手册.md`
