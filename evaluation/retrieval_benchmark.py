"""Minimal retrieval evaluation harness (spec module 36/37).

Indexes a small synthetic repo with known ground-truth file locations, runs a set of
natural-language queries through hybrid_search, and reports Recall@K and MRR — actual
measured numbers, not fabricated (spec module 94). Extend `BENCHMARK` as the real
demo repositories are added.

Run: apps/backend/.venv/Scripts/python.exe evaluation/retrieval_benchmark.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.rag.indexer import index_repository
from packages.rag.retrieval import hybrid_search
from packages.rag.store import init_db

FIXTURE_FILES = {
    "auth.py": '''
class AuthMiddleware:
    """Validates JWTs before requests reach downstream services."""
    def validate_token(self, token):
        payload = decode_jwt(token)
        if payload is None:
            raise Unauthorized()
        return payload

def decode_jwt(token):
    return jwt_library.decode(token)
''',
    "payments.py": '''
def charge_card(card, amount):
    gateway = get_payment_gateway()
    return gateway.charge(card, amount)

def refund(charge_id):
    gateway = get_payment_gateway()
    return gateway.refund(charge_id)
''',
    "users.py": '''
class UserRepository:
    def find_by_email(self, email):
        return db.query(User).filter_by(email=email).first()

    def create(self, email, password):
        hashed = hash_password(password)
        return db.insert(User(email=email, password=hashed))
''',
    "tests/test_auth.py": '''
def test_validate_token_rejects_expired():
    middleware = AuthMiddleware()
    with pytest.raises(Unauthorized):
        middleware.validate_token(EXPIRED_TOKEN)
''',
}

# (query, expected_file) — expected_file must appear in top-K results.
BENCHMARK = [
    ("how are JWT tokens validated", "auth.py"),
    ("where is credit card charging handled", "payments.py"),
    ("how do I refund a payment", "payments.py"),
    ("where are users looked up by email", "users.py"),
    ("how is a password hashed before storing a user", "users.py"),
    ("what test covers token validation", "tests/test_auth.py"),
]


def run(k: int = 5) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="coderag_eval_"))
    try:
        for rel, content in FIXTURE_FILES.items():
            path = tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        init_db()
        result = index_repository("eval-fixture", str(tmp))
        repo_id = result["repository_id"]

        hits, reciprocal_ranks = 0, []
        print(f"{'query':<55} {'expected':<22} {'found@':<8} {'top-1'}")
        for query, expected in BENCHMARK:
            results = hybrid_search(repo_id, query, top_k=k)
            files = [r.file_path for r in results]
            rank = files.index(expected) + 1 if expected in files else None
            if rank:
                hits += 1
                reciprocal_ranks.append(1.0 / rank)
            else:
                reciprocal_ranks.append(0.0)
            print(f"{query:<55} {expected:<22} {str(rank):<8} {files[0] if files else '-'}")

        recall_at_k = hits / len(BENCHMARK)
        mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
        print(f"\nRecall@{k}: {recall_at_k:.2f}  MRR: {mrr:.2f}  (n={len(BENCHMARK)} queries)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    run()
