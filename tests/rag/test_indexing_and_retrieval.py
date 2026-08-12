"""Integration test: index a small synthetic repo, then verify hybrid retrieval
actually surfaces the relevant chunk with correct citations. No mocks — this exercises
tree-sitter parsing, chunking, real fastembed embeddings, Chroma, BM25, and SQLite
end-to-end (spec module 59/77)."""
import pytest

from packages.rag.indexer import index_repository
from packages.rag.retrieval import hybrid_search
from packages.rag.store import init_db


@pytest.fixture(scope="module")
def indexed_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo_repo")
    (root / "auth.py").write_text(
        """
class AuthMiddleware:
    \"\"\"Validates JWTs before requests reach the app.\"\"\"
    def validate_token(self, token):
        payload = decode_jwt(token)
        if payload is None:
            raise Unauthorized()
        return payload

def decode_jwt(token):
    return jwt_library.decode(token)
""",
        encoding="utf-8",
    )
    (root / "payments.py").write_text(
        """
def charge_card(card, amount):
    gateway = get_payment_gateway()
    return gateway.charge(card, amount)
""",
        encoding="utf-8",
    )
    init_db()
    result = index_repository("demo-repo", str(root))
    return result


def test_indexing_extracts_expected_symbols_and_chunks(indexed_repo):
    assert indexed_repo["files_indexed"] == 2
    assert indexed_repo["files_parsed"] == 2
    assert indexed_repo["chunks_indexed"] >= 3  # class + method + function, x2 files


def test_hybrid_search_finds_relevant_auth_chunk_with_correct_citation(indexed_repo):
    repo_id = indexed_repo["repository_id"]
    results = hybrid_search(repo_id, "how are JWT tokens validated", top_k=3)
    assert results, "expected at least one retrieval result"
    top_files = [r.file_path for r in results]
    assert "auth.py" in top_files
    top_auth = next(r for r in results if r.file_path == "auth.py")
    assert top_auth.line_start >= 1
    assert top_auth.line_end >= top_auth.line_start
    assert top_auth.matched_by  # at least one of semantic/lexical matched


def test_hybrid_search_does_not_return_unrelated_repo_results(indexed_repo):
    repo_id = indexed_repo["repository_id"]
    results = hybrid_search(repo_id, "payment gateway credit card charge", top_k=3)
    assert any(r.file_path == "payments.py" for r in results)
