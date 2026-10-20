"""M4.3 R09-01：PDF/DOCX 摄入五态区分。"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.lite_scan import extract_document  # noqa: E402

try:
    import docx  # noqa: F401
    import pypdf  # noqa: F401
    HAVE_DOC_DEPS = True
except ImportError:
    HAVE_DOC_DEPS = False


def make_pdf(path, encrypted=False, blank=False, text=False):
    if text:
        # 完整 xref/%%EOF 的最小文本 PDF（pypdf writer 不支持写文本）
        stream = b"BT /F1 12 Tf 10 50 Td (hello pdf marker-p4) Tj ET"
        objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
                b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R"
                b"/Resources<</Font<</F1 5 0 R>>>>>>",
                b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream),
                b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
        out = b"%PDF-1.4\n"
        offs = []
        for i, o in enumerate(objs, 1):
            offs.append(len(out))
            out += b"%d 0 obj" % i + o + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
        for off in offs:
            out += b"%010d 00000 n \n" % off
        out += (b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" %
                (len(objs) + 1, xref))
        open(path, "wb").write(out)
        return
    from pypdf import PdfWriter
    w = PdfWriter()
    if not blank:
        w.add_blank_page(width=200, height=200)
    if encrypted:
        w.encrypt("secret")
    with open(path, "wb") as f:
        w.write(f)


def make_docx(path, empty=False):
    import docx
    d = docx.Document()
    if not empty:
        d.add_paragraph("hello docx marker-d4")
    d.save(path)


@unittest.skipUnless(HAVE_DOC_DEPS, "可选依赖 pypdf/python-docx 未安装（pip install pypdf python-docx）；五态契约需真实解析器")
class TestDocStates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dm-fmt-")

    def test_ok_and_pages(self):
        p = os.path.join(self.tmp, "a.pdf")
        make_pdf(p, text=True)
        r = extract_document(p)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["pages"], 1, "PDF 定位须含页数")
        self.assertIn("marker-p4", r["text"])

    def test_corrupt(self):
        for name, mk in (("b.pdf", lambda p: open(p, "wb").write(b"%PDF-junk-not-real")),
                         ("b.docx", lambda p: open(p, "wb").write(b"PK\x03\x04junk"))):
            p = os.path.join(self.tmp, name)
            mk(p)
            r = extract_document(p)
            self.assertEqual(r["status"], "corrupt", name)

    def test_encrypted(self):
        p = os.path.join(self.tmp, "c.pdf")
        make_pdf(p, encrypted=True)
        r = extract_document(p)
        self.assertEqual(r["status"], "encrypted")

    def test_no_text(self):
        p1 = os.path.join(self.tmp, "d.docx")
        make_docx(p1, empty=True)
        p2 = os.path.join(self.tmp, "e.pdf")
        make_pdf(p2)  # 空白页：无文本
        self.assertEqual(extract_document(p1)["status"], "no-text")
        self.assertEqual(extract_document(p2)["status"], "no-text")

    def test_no_dep_simulated(self):
        import domimap.lite_scan as ls
        real = ls._import_optional
        ls._import_optional = lambda mod: (_ for _ in ()).throw(ImportError(mod))
        try:
            p = os.path.join(self.tmp, "f.docx")
            make_docx(p)
            self.assertEqual(extract_document(p)["status"], "no-dep")
        finally:
            ls._import_optional = real

    def test_coverage_records_states(self):
        import domimap.lite_scan as ls
        ws = os.path.join(self.tmp, "ws")
        os.makedirs(ws)
        open(os.path.join(ws, "pom.xml"), "w").write("<project/>")
        open(os.path.join(ws, "bad.docx"), "wb").write(b"PK junk")
        make_pdf(os.path.join(ws, "enc.pdf"), encrypted=True)
        R = ls.scan_repo(ws, repo_label="f")
        reasons = [s["reason"] for s in R["coverage"]["skipped"]]
        self.assertTrue(any("损坏" in r for r in reasons), reasons)
        self.assertTrue(any("加密" in r for r in reasons), reasons)
        self.assertFalse(any("未安装" in r for r in reasons), "已装依赖时不得误标未安装")

if __name__ == "__main__":
    unittest.main()
