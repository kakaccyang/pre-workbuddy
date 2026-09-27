"""Okapi BM25 文本检索算法实现（零第三方依赖）。
用bm25实现简易搜索算法，完成rag操作
评分公式：

    score(D, Q) = Σ_i  idf(q_i) · f(q_i, D) · (k1 + 1)
                  ─────────────────────────────────────────────
                  f(q_i, D) + k1 · (1 - b + b · |D| / avgdl)

    idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

其中：
    N       文档总数
    df(t)   包含词项 t 的文档数
    f(t,D)  词项 t 在文档 D 中的词频
    |D|     文档长度（词项数）
    avgdl   平均文档长度
    k1      词频饱和参数，常用 1.2 ~ 2.0
    b       文档长度归一化参数，0 表示不归一化，1 表示完全按长度归一化
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Callable, Sequence

Tokenizer = Callable[[str], list[str]]

# 英文/数字按词切分并转小写；中日韩统一表意文字按单字切分
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*|[一-鿿]")


def default_tokenize(text: str) -> list[str]:
    """默认分词器：英文按词、中文按单字。

    如需中文分词，可在构造 BM25 时传入自定义 tokenizer
    （例如 ``tokenizer=lambda s: jieba.lcut(s)``）。
    """
    return _TOKEN_RE.findall(text.lower())


class BM25:
    """基于 BM25 算法的简易检索器。"""

    def __init__(
        self,
        corpus: Sequence[str],
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Tokenizer | None = None,
    ) -> None:
        """对语料库建立索引。

        Args:
            corpus: 文档集合（字符串序列）。
            k1: 词频饱和调节参数，通常取 1.2 ~ 2.0。
            b: 文档长度惩罚强度，取值范围 [0, 1]，常用 0.75。
            tokenizer: 自定义分词函数，输入文本，输出词项列表。
        """
        if not corpus:
            raise ValueError("corpus 不能为空")
        if k1 < 0:
            raise ValueError("k1 必须 >= 0")
        if not 0.0 <= b <= 1.0:
            raise ValueError("b 必须在 [0, 1] 范围内")

        self.k1 = float(k1)
        self.b = float(b)
        self.tokenize: Tokenizer = tokenizer or default_tokenize
        self.corpus: list[str] = list(corpus)

        # 每篇文档的词频表、长度，以及词项的文档频率
        self.doc_terms: list[Counter[str]] = []
        self.doc_len: list[int] = []
        doc_freq: Counter[str] = Counter()

        for doc in self.corpus:
            term_freq = Counter(self.tokenize(doc))
            self.doc_terms.append(term_freq)
            self.doc_len.append(sum(term_freq.values()))
            doc_freq.update(term_freq.keys())

        self.n_docs = len(self.corpus)
        self.avgdl: float = sum(self.doc_len) / self.n_docs

        # idf 表；+1 形式保证 idf 非负（Lucene 采用的变体）
        self.idf: dict[str, float] = {
            term: math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))
            for term, df in doc_freq.items()
        }

        # 倒排索引：term -> [(文档下标, 词频), ...]
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for doc_idx, term_freq in enumerate(self.doc_terms):
            for term, freq in term_freq.items():
                self.postings.setdefault(term, []).append((doc_idx, freq))

    def _query_terms(self, query: str | Sequence[str]) -> list[str]:
        if isinstance(query, str):
            return self.tokenize(query)
        return list(query)

    def get_scores(self, query: str | Sequence[str]) -> list[float]:
        """返回查询对每篇文档的 BM25 得分（下标与语料库一致）。"""
        scores = [0.0] * self.n_docs
        avgdl = self.avgdl if self.avgdl > 0 else 1.0

        for term in self._query_terms(query):
            idf = self.idf.get(term)
            if idf is None:
                # 未登录词：语料库中没有任何文档包含它，贡献为 0
                continue
            for doc_idx, freq in self.postings[term]:
                length_norm = 1.0 - self.b + self.b * self.doc_len[doc_idx] / avgdl
                denominator = freq + self.k1 * length_norm
                scores[doc_idx] += idf * freq * (self.k1 + 1.0) / denominator

        return scores

    def search(
        self,
        query: str | Sequence[str],
        top_k: int | None = None,
    ) -> list[tuple[int, float, str]]:
        """检索并按相关性降序返回结果。

        Args:
            query: 查询字符串（会被分词）或已分好词的词项序列。
            top_k: 只返回得分最高的前 k 篇；None 表示返回全部匹配文档。

        Returns:
            ``(文档下标, BM25 得分, 文档原文)`` 列表，不含零分文档。
        """
        scores = self.get_scores(query)
        ranked = sorted(
            ((i, s) for i, s in enumerate(scores) if s > 0.0),
            key=lambda item: item[1],
            reverse=True,
        )
        if top_k is not None:
            ranked = ranked[:top_k]
        return [(i, s, self.corpus[i]) for i, s in ranked]


if __name__ == "__main__":
    # ---------- 英文示例 ----------
    english_docs = [
        "The quick brown fox jumps over the lazy dog",
        "A fast brown dog outruns a quick fox in the park",
        "BM25 is a ranking function used by search engines",
        "Search engines rank documents by relevance to a query",
        "The lazy cat sleeps on the warm sofa all day",
    ]
    bm25_en = BM25(english_docs)

    print("=== English demo: query = 'quick fox' ===")
    for idx, score, doc in bm25_en.search("quick fox", top_k=3):
        print(f"  [{idx}] score={score:.4f}  {doc}")

    # ---------- 中文示例（默认按单字切分） ----------
    chinese_docs = [
        "BM25是一种常用的文本检索相关性打分算法",
        "搜索引擎使用倒排索引快速查找包含查询词的文档",
        "今天天气很好，适合去公园散步和遛狗",
        "检索算法会根据词频和文档长度计算相关性得分",
        "机器学习模型也可以用于信息检索任务",
    ]
    bm25_zh = BM25(chinese_docs)

    print("\n=== 中文示例：查询 = '检索 算法' ===")
    for idx, score, doc in bm25_zh.search("算法工程师", top_k=3):
        print(f"  [{idx}] score={score:.4f}  {doc}")
