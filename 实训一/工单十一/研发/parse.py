import nltk
import os
from unstructured.partition.pdf import partition_pdf
from collections import Counter
nltk.download('punkt')
nltk.download('averaged_perceptron_tagger')
nltk.download('punkt_tab')

def process_pdfs_in_folder(folder_path):
    total_text = []  # 用于累积所有 PDF 中提取出的文本

    # 获取文件夹中所有 PDF 文件的列表
    pdf_files = [f for f in os.listdir(folder_path) if f.endswith('.pdf')]

    for pdf_file in pdf_files:
        pdf_path = os.path.join(folder_path, pdf_file)
        print(f"Processing: {pdf_path}")

        # 使用 unstructured 的 PDF 分区逻辑解析文件
        elements = partition_pdf(pdf_path, strategy="auto", languages=["chi_sim"])

        # 显示解析结果中不同元素类型的数量
        print(Counter(type(element) for element in elements))

        # 将解析出的元素拼接成文本，并加入总文本列表
        text = "\n\n".join([str(el) for el in elements])
        total_text.append(text)

    # 返回所有 PDF 文本拼接后的完整内容
    return "\n\n".join(total_text)


folder_path = "data"
all_text = process_pdfs_in_folder(folder_path)

import nltk

nltk.download('punkt')

def nltk_based_splitter(text: str, chunk_size: int, overlap: int) -> list:
    """
    将输入文本切分为指定大小的文本块，并可选择在相邻文本块之间保留重叠内容。

    参数：
    - text：需要切分的输入文本。
    - chunk_size：每个文本块的最大长度，按字符数计算。
    - overlap：相邻文本块之间重叠的字符数。

    返回：
    - 文本块列表，可以包含重叠内容，也可以不包含。
     """

    from nltk.tokenize import sent_tokenize

    # 将输入文本按句子进行切分
    sentences = sent_tokenize(text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        # 如果当前文本块加上下一个句子后不超过最大长度，就把该句子加入当前文本块
        if len(current_chunk) + len(sentence) <= chunk_size:
            current_chunk += " " + sentence
        else:
            # 否则，将当前文本块加入列表，并用当前句子开启新的文本块
            chunks.append(current_chunk.strip())  # 去除开头可能出现的空格
            current_chunk = sentence

    # 循环结束后，如果当前文本块还有剩余内容，就加入文本块列表
    if current_chunk:
        chunks.append(current_chunk.strip())

    # 如果指定了重叠字符数，则处理相邻文本块之间的重叠内容
    if overlap > 0:
        overlapping_chunks = []
        for i in range(len(chunks)):
            if i > 0:
                # 计算上一文本块中重叠内容的起始位置
                start_overlap = max(0, len(chunks[i - 1]) - overlap)
                # 将上一文本块的重叠部分与当前文本块合并
                chunk_with_overlap = chunks[i - 1][start_overlap:] + " " + chunks[i]
                # 添加合并后的文本块，并确保长度不超过 chunk_size
                overlapping_chunks.append(chunk_with_overlap[:chunk_size])
            else:
                # 第一个文本块没有上一个文本块，因此不需要重叠
                overlapping_chunks.append(chunks[i][:chunk_size])

        return overlapping_chunks  # 返回带有重叠内容的文本块列表

    # 如果 overlap 为 0，直接返回不重叠的文本块列表
    return chunks


chunks = nltk_based_splitter(text=all_text,
                             chunk_size=300,
                             overlap=45)

from openai import OpenAI
import pandas as pd
# 推荐在系统环境变量中设置 SILICONFLOW_API_KEY，避免把密钥直接写进代码
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "sk-nykszkfahiqcdahumeyznopzopgywlqqpuubjrzdsjndqjnk")
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"

# 提示词生成函数，明确要求模型按固定结构输出
def prompt(text_chunk):
    return f"""
    请根据下面的文本生成一个问题和对应答案。
    请严格按照下面的格式输出，方便程序解析：
    Question: [Your question]
    Answer: [Your answer]

    Text: {text_chunk}
    """

# 调用硅基流动 API 生成问答对的函数
def generate_with_siliconflow(text_chunk:str, temperature:float, model_name:str):
    client = OpenAI(
        api_key=SILICONFLOW_API_KEY,
        base_url=SILICONFLOW_BASE_URL,
    )

    # 根据提示词生成回复
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "user", "content": prompt(text_chunk)}
        ],
        temperature=temperature,
    )
    response_text = response.choices[0].message.content

    # 根据关键字从模型回复中提取问题和答案
    try:
        question, answer = response_text.split("Answer:", 1)
        question = question.replace("Question:", "").strip()
        answer = answer.strip()
    except ValueError:
        question, answer = "N/A", "N/A"  # 处理模型回复格式不符合预期的情况

    return question, answer

def process_text_chunks(text_chunks:list, temperature:int, model_name=str):
    """
    使用指定模型处理文本块列表，并为每个文本块生成问题和答案。

    参数：
    - text_chunks：需要处理的文本块列表。
    - temperature：采样温度，用于控制生成结果的随机性。
    - model_name：用于生成问题和答案的模型名称。

    返回：
    - 包含文本块、问题和答案的 Pandas DataFrame。
    """
    results = []

    # 遍历每个文本块
    for chunk in text_chunks:
        question, answer = generate_with_siliconflow(chunk, temperature, model_name)
        results.append({"Text Chunk": chunk, "Question": question, "Answer": answer})

    # 将结果转换为 Pandas DataFrame
    df = pd.DataFrame(results)
    return df
# 处理文本块并获取结果 DataFrame
df_results = process_text_chunks(text_chunks=chunks,
                                 temperature=0.7,
                                 model_name="deepseek-ai/DeepSeek-V3.2")
df_results.to_csv("generated_qa_pairs.csv", index=False)
