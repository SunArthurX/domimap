"""题质锚词规则契约（question-quality-v3）。

核心语义：规则纯语料统计（df），系统无关；锚词=题面 ≥1 内容词 df≤5；独特词 df 升序/
tf 降序；生成器准入（MIN_WORDS 不足/无锚不成题）；其余类别复用 v2 输出。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "benchmarks", "corpus"))

from question_quality import (DF_MAX, MIN_WORDS, anchor_ok, corpus_df,  # noqa: E402
                              distinctive_words)


def doc(tokens, title="", stem=""):
    return {"tokens": list(tokens), "title": title, "stem": stem}


class TestQuestionQuality(unittest.TestCase):
    def setUp(self):
        # 6 篇微型语料："锚词甲" df=2、"锚词乙" df=1、"泛词" df=6（>DF_MAX 不入独特词）
        self.docs = [
            doc(["锚词甲", "泛词", "泛词", "其它词"]),
            doc(["泛词", "锚词乙", "泛词"]),
            doc(["泛词"] * 8),
            doc(["泛词"]),
            doc(["锚词甲", "泛词"]),
            doc(["泛词"]),
        ]
        self.df = corpus_df(self.docs)

    def test_corpus_df(self):
        self.assertEqual(self.df["锚词甲"], 2)
        self.assertEqual(self.df["锚词乙"], 1)
        self.assertEqual(self.df["泛词"], 6)
        self.assertEqual(self.df["其它词"], 1)

    def test_anchor_ok_boundary(self):
        self.assertTrue(anchor_ok(["泛词", "锚词乙"], self.df), "df=1 锚词过")
        self.assertTrue(anchor_ok(["锚词甲"], self.df), "df=2 ≤5 过")
        self.assertFalse(anchor_ok(["泛词"], self.df), "df=6 无锚拒（边界）")
        self.assertFalse(anchor_ok(["不存在的词"], self.df), "df=0 不算锚（防生僻空集）")

    def test_distinctive_words_ordering(self):
        d = doc(["锚词甲", "锚词甲", "锚词乙", "锚词乙", "泛词", "泛词", "泛词"])
        words = distinctive_words(d, self.df)
        self.assertEqual(words[0], "锚词乙", "df=1 优先")
        self.assertEqual(words[1], "锚词甲", "df=2 次之")
        self.assertNotIn("泛词", words, "df=6 语料泛词不入选")

    def test_distinctive_words_tf_tiebreak(self):
        # 同 df=1：词甲文档内 tf=3 > 词乙 tf=1 → 词甲在前
        d = doc(["词甲"] * 3 + ["词乙", "词乙"])
        df = corpus_df([d, doc(["别的"])])
        self.assertEqual(distinctive_words(d, df)[0], "词甲", "同 df 时文档内 tf 降序")

    def test_distinctive_words_banned_and_short(self):
        d = doc(["锚词甲", "锚词甲", "标题词", "短", "锚词乙", "锚词乙"], title="标题词", stem="x")
        words = distinctive_words(d, self.df)
        self.assertEqual(set(words), {"锚词甲", "锚词乙"}, "标题词与单字排除")

    def test_salience_tfidf(self):
        """锚词须文档内 tf≥2（显著）：一次性碎片不入选。"""
        d = doc(["显著锚", "显著锚", "碎片词"])
        df = corpus_df([d, doc(["别的词", "别的词"])])
        self.assertEqual(distinctive_words(d, df), ["显著锚"])


class TestGeneratorAdmission(unittest.TestCase):
    """生成器准入逻辑（单元级：假 docs 过 build_v3 的 doc/fresh 段语义）。"""

    def test_min_words_and_anchor_admission(self):
        # 泛词在 6 篇文档出现（df=6 不入独特词）——该文档独特词仅 1 个 < MIN_WORDS=3，不成题
        df = corpus_df([doc(["唯一锚", "唯一锚", "泛词", "泛词"])] + [doc(["泛词"])] * 5)
        d = doc(["唯一锚", "唯一锚", "泛词"])
        words = distinctive_words(d, df)
        self.assertEqual(words, ["唯一锚"])
        self.assertLess(len(words), MIN_WORDS)

    def test_v3_script_exists_and_schema(self):
        path = os.path.join(ROOT, "benchmarks", "corpus", "generate_questions_v3.py")
        text = open(path, encoding="utf-8").read()
        self.assertIn("anchor_ok", text, "v3 生成器必须执行锚词准入")
        self.assertIn("distinctive_words", text, "v3 生成器必须用独特词选词")
        self.assertIn("pub-questions-v3.json", text, "输出为 v3 新文件（旧集不动）")
        self.assertNotIn("pub-questions.json\", \"w", text, "不得写旧题集文件")


if __name__ == "__main__":
    unittest.main()
