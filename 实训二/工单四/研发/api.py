# 人工智能 NLP-Agent 数字人项目-基金问答智能体任务
"""
API 服务模块 - 提供 RESTful API 接口

基于 Flask 实现，方便集成和部署
"""

import argparse
from flask import Flask, jsonify, request

from core.agent import FundQAAgent

app = Flask(__name__)

# 全局 Agent 实例
agent = None


def init_agent():
    """初始化 Agent"""
    global agent
    if agent is None:
        agent = FundQAAgent()


@app.route("/health", methods=["GET"])
def health_check():
    """健康检查接口"""
    return jsonify({
        "status": "ok",
        "service": "fund-qa-agent"
    })


@app.route("/api/ask", methods=["POST"])
def ask_question():
    """
    问答接口

    请求格式:
    {
        "question": "问题内容"
    }

    返回格式:
    {
        "code": 0,
        "message": "success",
        "data": {
            "question": "...",
            "answer": "...",
            "sql": "...",
            "query_result": "..."
        }
    }
    """
    try:
        data = request.get_json()

        if not data or "question" not in data:
            return jsonify({
                "code": 400,
                "message": "缺少 question 参数",
                "data": None
            }), 400

        question = data["question"]

        if not question or not isinstance(question, str):
            return jsonify({
                "code": 400,
                "message": "question 参数无效",
                "data": None
            }), 400

        result = agent.ask(question)

        return jsonify({
            "code": 0,
            "message": "success",
            "data": {
                "question": result.get("question"),
                "answer": result.get("answer"),
                "sql": result.get("sql"),
                "query_result": result.get("query_result"),
                "retry_count": result.get("retry_count", 0),
                "error": result.get("error")
            }
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }), 500


@app.route("/api/batch", methods=["POST"])
def batch_ask():
    """
    批量问答接口

    请求格式:
    {
        "questions": ["问题1", "问题2", ...]
    }

    返回格式:
    {
        "code": 0,
        "message": "success",
        "data": [
            {"question": "...", "answer": "...", ...},
            ...
        ]
    }
    """
    try:
        data = request.get_json()

        if not data or "questions" not in data:
            return jsonify({
                "code": 400,
                "message": "缺少 questions 参数",
                "data": None
            }), 400

        questions = data["questions"]

        if not isinstance(questions, list):
            return jsonify({
                "code": 400,
                "message": "questions 参数必须是数组",
                "data": None
            }), 400

        results = []
        for question in questions:
            try:
                result = agent.ask(question)
                results.append({
                    "question": result.get("question"),
                    "answer": result.get("answer"),
                    "sql": result.get("sql"),
                    "query_result": result.get("query_result"),
                    "retry_count": result.get("retry_count", 0),
                    "error": result.get("error")
                })
            except Exception as e:
                results.append({
                    "question": question,
                    "answer": None,
                    "sql": None,
                    "query_result": None,
                    "retry_count": 0,
                    "error": str(e)
                })

        return jsonify({
            "code": 0,
            "message": "success",
            "data": results
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"服务器错误: {str(e)}",
            "data": None
        }), 500


def run_server(host="0.0.0.0", port=5000, debug=False):
    """
    启动 API 服务器

    Args:
        host: 主机地址
        port: 端口号
        debug: 调试模式
    """
    init_agent()
    print(f"启动 API 服务: http://{host}:{port}")
    print(f"健康检查: http://{host}:{port}/health")
    print(f"问答接口: POST http://{host}:{port}/api/ask")
    print(f"批量问答: POST http://{host}:{port}/api/batch")

    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="基金问答智能体 API 服务")
    parser.add_argument("-h", "--host", default="0.0.0.0", help="主机地址")
    parser.add_argument("-p", "--port", type=int, default=5000, help="端口号")
    parser.add_argument("-d", "--debug", action="store_true", help="调试模式")

    args = parser.parse_args()
    run_server(args.host, args.port, args.debug)
