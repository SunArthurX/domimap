"""分词：CJK 1/2/3-gram 内建（不装 jieba 也能中文检索），latin 词干切分。"""
import re

_CJK = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*|\d+")

def tokenize(text):
    """返回词袋：CJK 连续段产 1/2/3-gram，latin 产小写词与 camelCase 切分。"""
    out = []
    for m in _WORD.finditer(text):
        w = m.group(0).lower()
        out.append(w)
        # camelCase 切分（codegraph name_segment_vocab 思想的极简版）
        parts = re.findall(r"[a-z]+|[A-Z][a-z]*", m.group(0))
        if len(parts) > 1:
            out.extend(p.lower() for p in parts if len(p) > 1)
    i = 0
    n = len(text)
    while i < n:
        if _CJK.match(text[i]):
            j = i
            while j < n and _CJK.match(text[j]):
                j += 1
            seg = text[i:j]
            L = len(seg)
            for k in range(L):
                out.append(seg[k])
                if k + 1 < L:
                    out.append(seg[k:k+2])
                if k + 2 < L:
                    out.append(seg[k:k+3])
            i = j
        else:
            i += 1
    return out
