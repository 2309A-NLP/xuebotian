# RAG 多角色扮演

## 项目结构

```text
.
├─ app/
│  ├─ api/            # FastAPI 路由、鉴权、请求模型、应用状态
│  ├─ core/           # 配置
│  ├─ repositories/   # 数据访问层
│  ├─ services/       # RAG、向量库、模型与知识管理
│  └─ main.py         # FastAPI 应用入口
├─ data/              # 知识库原始数据
├─ static/            # 前端静态页面
├─ app.py             # 项目启动入口
└─ requirements.txt
```

## 启动方式

```bash
python app.py
```

或：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
