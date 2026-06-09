# RAGAS 测试设计文档

## 1. 目标

验证当前 RAG 链路在“检索是否准、答案是否贴证据、回答是否完整”三个维度上的效果，并为后续优化提供可回放、可对比的基准。

## 2. 测试范围

本次测试覆盖以下链路：

- 问题意图识别
- 问题改写与多查询扩展
- 向量检索与候选合并
- 结构化重排与最终排序
- Prompt 组装与 LLM 生成

## 3. 测试数据

数据集文件：`scripts/ragas_dataset_multi_10.json`

每条样本包含：

- `id`
- `question`
- `ground_truth`
- `doc_ids`
- `top_k`
- `history`
- `metadata`

当前样本以 PDF 问答、表格问答、图文问答为主，重点覆盖：

- 章节定位
- 数值提取
- 表格字段查询
- 图片/图表信息定位
- 多轮对话上下文补全

## 4. 评测指标

脚本使用 `ragas` 评估以下指标：

- `ContextPrecision`
- `ContextRecall`
- `Faithfulness`
- `AnswerRelevancy`
- `ContextRelevancy`（可用时启用）

Judge LLM 与 embedding 使用独立配置，避免和业务推理互相干扰。

## 5. 评测流程

1. 读取样本数据。
2. 初始化本地 RAG 运行时。
3. 对每条问题执行完整问答链路。
4. 把检索上下文、回答、参考答案组装成 `ragas` 数据集。
5. 输出总体指标和逐题明细。

## 6. 输出产物

- `scripts/ragas_eval_result.json`
- `scripts/ragas_eval_per_question.json`

## 7. 当前基线

以仓库内现有结果为准：

- `context_precision`: `0.9021`
- `context_recall`: `1.0000`
- `faithfulness`: `1.0000`
- `answer_relevancy`: `0.7016`

## 8. 复跑方式

```bash
python scripts/run_ragas_eval.py
```

