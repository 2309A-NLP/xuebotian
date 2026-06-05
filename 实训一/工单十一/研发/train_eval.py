# -*- coding: utf-8 -*-
import torch
from datasets import DatasetDict, load_dataset
from sentence_transformers import (
    SentenceTransformer,
    SentenceTransformerTrainer,
    SentenceTransformerTrainingArguments,
)
from sentence_transformers.evaluation import (
    InformationRetrievalEvaluator,
    SequentialEvaluator,
)
from sentence_transformers.losses import MatryoshkaLoss, MultipleNegativesRankingLoss
from sentence_transformers.training_args import BatchSamplers
from sentence_transformers.util import cos_sim


model_id = "/root/autodl-tmp/model/bge-base-zh-v1.5"
output_dir = "bge-finetuned"
matryoshka_dimensions = [768, 512, 256, 128, 64]


def is_valid_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip() != "N/A"


def load_and_split_dataset(csv_path: str) -> tuple[DatasetDict, object]:
    """Load CSV data, filter invalid rows, then split into train/eval/test sets."""
    raw_dataset = load_dataset("csv", data_files=csv_path)["train"]

    def is_valid_example(example):
        return is_valid_text(example.get("Question")) and is_valid_text(example.get("Text Chunk"))

    raw_dataset = raw_dataset.filter(is_valid_example)

    def process_example(example, idx):
        return {
            "id": idx,
            "anchor": example["Question"].strip(),
            "positive": example["Text Chunk"].strip(),
        }

    processed_dataset = raw_dataset.map(
        process_example,
        with_indices=True,
        remove_columns=["Text Chunk", "Question", "Answer"],
    )

    n = len(processed_dataset)
    train_end = int(n * 0.8)
    eval_end = int(n * 0.9)

    gap = 1 if n >= 30 else 0
    train_indices = list(range(0, train_end))
    eval_indices = list(range(min(train_end + gap, n), eval_end))
    test_indices = list(range(min(eval_end + gap, n), n))

    split_dataset = DatasetDict(
        {
            "train": processed_dataset.select(train_indices),
            "eval": processed_dataset.select(eval_indices),
            "test": processed_dataset.select(test_indices),
        }
    )

    return split_dataset, processed_dataset


def create_ir_evaluator(query_dataset, corpus_dataset, name_prefix: str):
    """Build an IR evaluator: query questions retrieve relevant text chunks."""
    corpus = dict(zip(corpus_dataset["id"], corpus_dataset["positive"]))
    queries = dict(zip(query_dataset["id"], query_dataset["anchor"]))
    relevant_docs = {query_id: [query_id] for query_id in queries}

    evaluators = []
    for dim in matryoshka_dimensions:
        evaluators.append(
            InformationRetrievalEvaluator(
                queries=queries,
                corpus=corpus,
                relevant_docs=relevant_docs,
                name=f"{name_prefix}_dim_{dim}",
                truncate_dim=dim,
                score_functions={"cosine": cos_sim},
            )
        )

    return SequentialEvaluator(evaluators)


def print_ndcg_at_10(results, name_prefix: str):
    for dim in matryoshka_dimensions:
        key = f"{name_prefix}_dim_{dim}_cosine_ndcg@10"
        print(f"{key}: {results[key]}")


dataset, full_corpus_dataset = load_and_split_dataset("generated_qa_pairs.csv")
print(dataset)

model = SentenceTransformer(
    model_id,
    device="cuda" if torch.cuda.is_available() else "cpu",
)

inner_train_loss = MultipleNegativesRankingLoss(model)
train_loss = MatryoshkaLoss(
    model,
    inner_train_loss,
    matryoshka_dims=matryoshka_dimensions,
)

eval_evaluator = create_ir_evaluator(
    query_dataset=dataset["eval"],
    corpus_dataset=full_corpus_dataset,
    name_prefix="eval",
)
test_evaluator = create_ir_evaluator(
    query_dataset=dataset["test"],
    corpus_dataset=full_corpus_dataset,
    name_prefix="test",
)

args = SentenceTransformerTrainingArguments(
    output_dir=output_dir,
    num_train_epochs=1,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=16,
    per_device_eval_batch_size=16,
    warmup_ratio=0.1,
    learning_rate=2e-5,
    lr_scheduler_type="cosine",
    optim="adamw_torch_fused",
    tf32=True,
    bf16=True,
    batch_sampler=BatchSamplers.NO_DUPLICATES,
    eval_strategy="epoch",
    save_strategy="epoch",
    logging_steps=10,
    save_total_limit=3,
    load_best_model_at_end=True,
    metric_for_best_model="eval_dim_128_cosine_ndcg@10",
)

print("Before training eval results:")
eval_results = eval_evaluator(model)
print_ndcg_at_10(eval_results, "eval")

trainer = SentenceTransformerTrainer(
    model=model,
    args=args,
    train_dataset=dataset["train"].select_columns(["anchor", "positive"]),
    loss=train_loss,
    evaluator=eval_evaluator,
)

trainer.train()
trainer.save_model()

fine_tuned_model = SentenceTransformer(
    args.output_dir,
    device="cuda" if torch.cuda.is_available() else "cpu",
)

print("After training eval results:")
eval_results = eval_evaluator(fine_tuned_model)
print_ndcg_at_10(eval_results, "eval")

print("Final test results:")
test_results = test_evaluator(fine_tuned_model)
print_ndcg_at_10(test_results, "test")
