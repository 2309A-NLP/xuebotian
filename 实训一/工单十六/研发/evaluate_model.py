import json
import os
import re
import torch
from transformers import Qwen3VLForConditionalGeneration, Qwen3VLProcessor
from PIL import Image
from rouge_score import rouge_scorer

try:
    from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False
    print("警告: nltk未安装，BLEU分数将使用简单替代方案")
    print("安装命令: pip install nltk")


def compute_bleu(reference, hypothesis):
    """计算BLEU分数"""
    if NLTK_AVAILABLE:
        smoothing = SmoothingFunction().method1
        ref_tokens = list(reference)
        hyp_tokens = list(hypothesis)
        return sentence_bleu([ref_tokens], hyp_tokens, smoothing_function=smoothing)
    else:
        ref_words = set(reference.split())
        hyp_words = set(hypothesis.split())
        if not ref_words:
            return 0.0
        overlap = len(ref_words & hyp_words)
        return overlap / len(ref_words)


def compute_rouge(reference, hypothesis):
    """计算ROUGE分数"""
    scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
    scores = scorer.score(reference, hypothesis)
    return {
        'rouge1': scores['rouge1'].fmeasure,
        'rouge2': scores['rouge2'].fmeasure,
        'rougeL': scores['rougeL'].fmeasure
    }


def evaluate_terminology_accuracy(expected, predicted, question):
    """评估专业术语准确性"""
    score = 0.0
    details = []

    terminology_keywords = {
        'CN100342976C': [
            '配气带孔盘', '管状入口', '静电除尘器', '含尘气体',
            '圆锥形', 'P·吉特勒', 'h1', 'h2', 'X1', 'X2', 'X3'
        ],
        'CN100347506C': [
            '分配装置', '块状散料', '落料架', '驱动装置',
            '传动机构', '分配盘', '进料口', '主体框架'
        ]
    }

    patent_type = None
    if 'CN100342976C' in question or '静电' in question or '除尘' in question:
        patent_type = 'CN100342976C'
    elif 'CN100347506C' in question or '散料' in question or '分配' in question:
        patent_type = 'CN100347506C'

    if patent_type and patent_type in terminology_keywords:
        keywords = terminology_keywords[patent_type]
        matched = 0
        for kw in keywords:
            if kw in expected and kw in predicted:
                matched += 1
                details.append(f"术语'{kw}'正确识别")
            elif kw in expected and kw not in predicted:
                details.append(f"遗漏术语'{kw}'")

        if keywords:
            score = matched / len(keywords)

    return score, details


def evaluate_diagram_reasoning(expected, predicted, question):
    """评估图纸推理正确性"""
    score = 0.0
    details = []

    spatial_patterns = [
        (r'左[侧]?', '左侧'),
        (r'右[侧]?', '右侧'),
        (r'上[方]?', '上方'),
        (r'下[方]?', '下方'),
        (r'内[部]?', '内部'),
        (r'外[部]?', '外部'),
    ]

    spatial_correct = 0
    spatial_total = 0

    for pattern, name in spatial_patterns:
        if re.search(pattern, expected):
            spatial_total += 1
            if re.search(pattern, predicted):
                spatial_correct += 1
                details.append(f"空间关系'{name}'正确")
            else:
                details.append(f"遗漏空间关系'{name}'")

    if spatial_total > 0:
        score += (spatial_correct / spatial_total) * 0.5

    component_pattern = r'部件(\d+)'
    expected_components = set(re.findall(component_pattern, expected))
    predicted_components = set(re.findall(component_pattern, predicted))

    if expected_components:
        component_overlap = len(expected_components & predicted_components)
        component_score = component_overlap / len(expected_components)
        score += component_score * 0.3
        details.append(f"部件编号匹配: {component_overlap}/{len(expected_components)}")

    flow_patterns = [r'→', r'经过', r'顺序', r'路径', r'流向']
    flow_in_expected = any(p in expected for p in flow_patterns)
    if flow_in_expected:
        flow_in_predicted = any(p in predicted for p in flow_patterns)
        if flow_in_predicted:
            score += 0.2
            details.append("流程/路径推理正确")
        else:
            details.append("缺少流程/路径推理")

    return min(score, 1.0), details


def evaluate_model(model_path, test_data_path, output_dir):
    """评估模型在测试集上的表现"""

    print(f"\n{'='*70}")
    print(f"加载模型: {model_path}")
    print(f"{'='*70}")

    model = Qwen3VLForConditionalGeneration.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True
    )
    processor = Qwen3VLProcessor.from_pretrained(
        model_path,
        trust_remote_code=True
    )

    with open(test_data_path, 'r', encoding='utf-8') as f:
        test_data = [json.loads(line) for line in f]

    test_data_dir = os.path.dirname(os.path.abspath(test_data_path))

    results = []
    total_bleu = 0.0
    total_rouge1 = 0.0
    total_rouge2 = 0.0
    total_rougeL = 0.0
    total_terminology = 0.0
    total_diagram = 0.0
    correct_count = 0

    for i, item in enumerate(test_data):
        print(f"\n{'='*70}")
        print(f"问题 {i+1}/{len(test_data)}: {item['id']}")
        print(f"{'='*70}")

        # 准备图像
        images = []
        if item.get("images") and len(item["images"]) > 0:
            img_path = item["images"][0]
            if not img_path.startswith("/"):
                img_path = os.path.join(test_data_dir, img_path)

            if os.path.exists(img_path):
                images.append(Image.open(img_path).convert("RGB"))
                print(f"加载图像: {os.path.basename(img_path)}")
            else:
                print(f"图像不存在: {img_path}")

        # 构建消息 - 使用Qwen3-VL的图像标记格式
        messages = []
        question_text = ""

        # for msg in item["messages"]:
        for msg in item["conversations"]:
            if msg["from"] == "system":
                messages.append({"role": "system", "content": msg["value"]})
            elif msg["from"] == "human":
                content = msg["value"].strip()
                question_text = content

                # 如果有图像，使用Qwen3-VL的图像标记格式
                if images:
                    # 替换 <image> 为 <|vision_start|><|image_pad|><|vision_end|>
                    # 或者直接在content中保留图像占位符，processor会自动处理
                    if "<image>" in content:
                        # Qwen3-VL格式：使用特殊token标记图像位置
                        content = content.replace("<image>", "<|vision_start|><|image_pad|><|vision_end|>")
                    else:
                        # 如果没有<image>标记，在开头添加图像
                        content = "<|vision_start|><|image_pad|><|vision_end|>\n" + content

                messages.append({"role": "user", "content": content})

        try:
            if images:
                # 有图像的情况 - 使用processor处理图像和文本
                text_input = processor.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True
                )

                # 使用processor处理图像和文本
                inputs = processor(
                    text=[text_input],
                    images=images,
                    return_tensors="pt",
                    padding=True
                ).to(model.device)
            else:
                # 纯文本情况
                text_input = processor.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True
                )
                inputs = processor(
                    text=[text_input],
                    return_tensors="pt",
                    padding=True
                ).to(model.device)

            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=512,
                    do_sample=False
                )

            predicted = processor.batch_decode(outputs, skip_special_tokens=True)[0]

            # 提取assistant的回答
            if "assistant" in predicted:
                parts = predicted.split("assistant")
                if len(parts) > 1:
                    predicted = parts[-1].strip()

            print(f"\n预测答案:\n{predicted[:400]}...")

        except Exception as e:
            print(f"推理错误: {e}")
            import traceback
            traceback.print_exc()
            predicted = f"ERROR: {str(e)}"

        # 获取正确答案
        # answer_msg = [m for m in item["messages"] if m["from"] == "gpt"][0]
        answer_msg = [m for m in item["conversations"] if m["from"] == "gpt"][0]
        expected = answer_msg["value"]

        print(f"\n标准答案:\n{expected[:400]}...")

        # 计算BLEU
        bleu = compute_bleu(expected, predicted)
        total_bleu += bleu

        # 计算ROUGE
        rouge = compute_rouge(expected, predicted)
        total_rouge1 += rouge['rouge1']
        total_rouge2 += rouge['rouge2']
        total_rougeL += rouge['rougeL']

        # 计算工业准确性
        term_score, term_details = evaluate_terminology_accuracy(expected, predicted, question_text)
        total_terminology += term_score

        diag_score, diag_details = evaluate_diagram_reasoning(expected, predicted, question_text)
        total_diagram += diag_score

        # 综合正确性判断
        is_correct = bleu > 0.3 or term_score > 0.5 or diag_score > 0.5
        if is_correct:
            correct_count += 1

        print(f"\n评估指标:")
        print(f"  BLEU: {bleu:.4f}")
        print(f"  ROUGE-1: {rouge['rouge1']:.4f}")
        print(f"  ROUGE-2: {rouge['rouge2']:.4f}")
        print(f"  ROUGE-L: {rouge['rougeL']:.4f}")
        print(f"  术语准确性: {term_score:.4f}")
        print(f"  图纸推理: {diag_score:.4f}")

        if term_details:
            print(f"\n术语详情:")
            for d in term_details[:5]:
                print(f"    {d}")

        if diag_details:
            print(f"\n推理详情:")
            for d in diag_details[:5]:
                print(f"    {d}")

        status = "正确" if is_correct else "错误"
        print(f"\n{status}")

        results.append({
            "id": item["id"],
            "has_image": len(images) > 0,
            "predicted": predicted,
            "expected": expected,
            "bleu": bleu,
            "rouge1": rouge['rouge1'],
            "rouge2": rouge['rouge2'],
            "rougeL": rouge['rougeL'],
            "terminology_accuracy": term_score,
            "diagram_reasoning": diag_score,
            "correct": is_correct
        })

    n = len(test_data)
    avg_bleu = total_bleu / n
    avg_rouge1 = total_rouge1 / n
    avg_rouge2 = total_rouge2 / n
    avg_rougeL = total_rougeL / n
    avg_terminology = total_terminology / n
    avg_diagram = total_diagram / n
    accuracy = correct_count / n * 100

    industrial_score = (avg_terminology * 0.4 + avg_diagram * 0.4 + avg_bleu * 0.2) * 100

    print(f"\n{'='*70}")
    print(f"评估报告")
    print(f"{'='*70}")
    print(f"模型: {model_path}")
    print(f"测试集: {test_data_path}")
    print(f"总问题数: {n}")
    print(f"")
    print(f"【通用指标】")
    print(f"  BLEU: {avg_bleu:.4f}")
    print(f"  ROUGE-1: {avg_rouge1:.4f}")
    print(f"  ROUGE-2: {avg_rouge2:.4f}")
    print(f"  ROUGE-L: {avg_rougeL:.4f}")
    print(f"")
    print(f"【工业准确性指标】")
    print(f"  专业术语准确性: {avg_terminology:.4f} ({avg_terminology*100:.1f}%)")
    print(f"  图纸推理正确性: {avg_diagram:.4f} ({avg_diagram*100:.1f}%)")
    print(f"  综合工业评分: {industrial_score:.1f}%")
    print(f"")
    print(f"【综合结果】")
    print(f"  正确数: {correct_count}/{n}")
    print(f"  准确率: {accuracy:.1f}%")
    print(f"{'='*70}")

    os.makedirs(output_dir, exist_ok=True)
    report = {
        "model": model_path,
        "test_data": test_data_path,
        "total_questions": n,
        "metrics": {
            "bleu": avg_bleu,
            "rouge1": avg_rouge1,
            "rouge2": avg_rouge2,
            "rougeL": avg_rougeL,
            "terminology_accuracy": avg_terminology,
            "diagram_reasoning": avg_diagram,
            "industrial_score": industrial_score,
            "accuracy": accuracy
        },
        "correct_count": correct_count,
        "details": results
    }

    with open(os.path.join(output_dir, "evaluation_report.json"), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    with open(os.path.join(output_dir, "detailed_results.jsonl"), 'w', encoding='utf-8') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    print(f"\n评估报告已保存到: {output_dir}/")
    print(f"   - evaluation_report.json (汇总报告)")
    print(f"   - detailed_results.jsonl (逐条详情)")

    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("="*70)
        print("工业VLM评估脚本 - 包含BLEU/ROUGE和工业准确性评估")
        print("="*70)
        print("")
        print("用法: python3 evaluate_industrial_vlm.py <model_path> <test_data> <output_dir>")
        print("")
        print("示例:")
        print("  # 评估微调模型")
        print("  python3 evaluate_industrial_vlm.py \\")
        print("    models/Qwen3-VL-Industrial-Finetuned \\")
        print("    data/test_set_10_sharegpt.jsonl \\")
        print("    eval_finetuned")
        print("")
        print("  # 评估基线模型（对比）")
        print("  python3 evaluate_industrial_vlm.py \\")
        print("    /home/ztt/models/Qwen3-VL-2B-Instruct \\")
        print("    data/test_set_10_sharegpt.jsonl \\")
        print("    eval_baseline")
        print("")
        print("依赖安装:")
        print("  pip install rouge-score nltk")
        print("="*70)
        sys.exit(1)

    model_path = sys.argv[1]
    test_data = sys.argv[2]
    output_dir = sys.argv[3]

    evaluate_model(model_path, test_data, output_dir)