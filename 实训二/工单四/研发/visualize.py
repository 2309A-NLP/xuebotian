# 人工智能 NLP-Agent 数字人项目-基金问答智能体任务
"""
LangGraph Agent 可视化脚本

生成 Agent 工作流程图并保存为图片
"""

from pathlib import Path

from core.agent import create_sql_agent


def save_agent_graph():
    """保存 Agent 工作流图"""
    print("正在生成 Agent 工作流图...")

    agent = create_sql_agent()

    # 生成 Mermaid 图表
    mermaid_diagram = agent.get_graph().draw_mermaid()

    # 保存为 mermaid.txt
    output_path = Path(__file__).parent / "agent_graph.mmd"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(mermaid_diagram)

    print(f"Mermaid 图表已保存到: {output_path}")

    # 尝试生成 PNG（如果安装了相关依赖）
    try:
        png_path = Path(__file__).parent / "agent_graph.png"
        png_data = agent.get_graph().draw_mermaid_png()
        with open(png_path, "wb") as f:
            f.write(png_data)
        print(f"PNG 图片已保存到: {png_path}")
    except Exception as e:
        print(f"无法生成 PNG: {e}")
        print("可以使用 https://mermaid.live/ 查看 .mmd 文件")


if __name__ == "__main__":
    save_agent_graph()
