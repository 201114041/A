# 人工评分说明

`answer_review_template.csv` 和 `answer_review_results.csv` 用来评估：

> 同一个模型，在“没有资料”和“有 RAG 检索资料”两种条件下，回答质量差多少。

自然语言答案不能只靠字符串完全匹配，因此需要人工按统一 Rubric 评分。

## 文件分别是什么

- `answer_review_template.csv`：空白评分骨架，已经填入 35 道题、标准答案和关键点。
- `answer_review_results.csv`：运行 `scripts/evaluate_llm.py` 后生成，里面会同时包含普通 LLM 回答和 RAG 回答。
- `llm_eval_samples.jsonl`：完整样本，包含检索来源、页码和两种回答。

## 使用流程

```powershell
$env:RAG_LLM_BASE_URL = "https://your-provider.example/v1"
$env:RAG_LLM_API_KEY = "your-key"
$env:RAG_LLM_MODEL = "your-model"
python -B scripts/evaluate_llm.py --limit 10
```

然后打开：

```text
data/eval/answer_review_results.csv
```

逐题对照：

1. `gold_answer`：标准答案
2. `key_points`：必须出现的关键信息
3. `baseline_answer`：不提供资料时的模型回答
4. `rag_answer`：提供 Top-5 检索资料后的回答

## 评分规则

所有分数范围都是 0 到 5 分。

| 分数 | 含义 |
|---:|---|
| 0 | 核心错误、严重幻觉或答非所问 |
| 1 | 只沾边，关键结论基本错误 |
| 2 | 部分正确，但混有错误或重要遗漏 |
| 3 | 大体正确，但缺少一个关键点或引用不完整 |
| 4 | 正确且基本完整，只有轻微表述问题 |
| 5 | 与标准答案一致，关键点完整，依据可追溯 |

## 各列怎么填

### baseline_score_0_5

普通 LLM 回答的整体正确性评分。

它没有检索资料，所以不要求引用。主要看是否答对，以及是否出现幻觉。

### rag_correctness_0_5

RAG 答案是否正确覆盖 `key_points`。

### rag_faithfulness_0_5

RAG 关键结论是否能被检索片段和原书页码支持。

- 5 分：全部有依据
- 3 分：部分有依据，但有轻微补充
- 0 分：核心结论资料中没有，属于编造

### rag_citation_0_5

是否用 `[1]`、`[2]` 等准确标注引用。

- 5 分：引用能对应具体结论
- 3 分：有引用但覆盖不完整
- 0 分：没有引用或引用与结论无关

### rag_abstention_0_5

只重点用于 5 道无答案题，例如制作委员会收益、公司薪资、2026 新番监督等。

- 5 分：明确说明资料不足
- 3 分：拒答含糊，但没有编造
- 0 分：资料不足仍然给出确定答案

对于可回答题，这一列可以留空，或填 `N/A`。

### notes

记录具体问题，例如：

- 正确答案但引用错误
- 漏掉“原画负责关键动作”这一关键点
- 检索到了概览片段，没有命中更具体的片段
- 无答案题仍然编造了公司名

## 如何汇总

建议分别报告：

- 普通 LLM 平均正确性
- RAG 平均正确性
- RAG 平均忠实性
- RAG 平均引用质量
- 无答案题拒答准确率
- 普通 LLM 和 RAG 的幻觉数量

不要只写一个模糊结论；应说明样本数、评分标准和具体失败类型。
