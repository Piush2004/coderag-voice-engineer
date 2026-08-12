from packages.code_intelligence.parser import get_parser
from packages.rag.chunker import chunk_file


def test_chunk_file_produces_function_class_and_method_chunks():
    src = """
class Foo:
    def bar(self):
        return 1

def baz():
    return 2
"""
    analysis = get_parser("python").analyze("m.py", src)
    chunks = chunk_file(repository_id=1, analysis=analysis, source=src)
    types = sorted(c.chunk_type for c in chunks)
    assert types == ["class", "function", "method"]
    for c in chunks:
        assert c.content.startswith("# m.py")
        assert c.line_start >= 1
        assert c.line_end >= c.line_start


def test_chunk_file_falls_back_to_module_chunk_when_no_symbols():
    from packages.code_intelligence.symbols import FileAnalysis

    analysis = FileAnalysis(file_path="README.md", language="text", imports=[], symbols=[], line_count=3)
    chunks = chunk_file(repository_id=1, analysis=analysis, source="a\nb\nc")
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "module"
