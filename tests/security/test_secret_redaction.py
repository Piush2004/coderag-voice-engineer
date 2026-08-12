from packages.rag.secrets import redact


def test_redacts_aws_access_key():
    text = 'AWS_ACCESS_KEY_ID = "AKIAABCDEFGHIJKLMNOP"'
    out, found = redact(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in out
    assert "aws_access_key" in found


def test_redacts_github_token():
    text = "token = ghp_1234567890abcdefghijklmnopqrstuvwxYZ"
    out, found = redact(text)
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxYZ" not in out
    assert "github_token" in found


def test_redacts_private_key_block():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    out, found = redact(text)
    assert "MIIEpAIBAAKCAQEA" not in out
    assert "private_key_block" in found


def test_redacts_db_connection_string_with_credentials():
    text = "DATABASE_URL=postgresql://admin:sup3rSecret@db.internal:5432/prod"
    out, found = redact(text)
    assert "sup3rSecret" not in out
    assert "db_connection_string" in found


def test_redacts_generic_api_key_assignment():
    text = 'STRIPE_API_KEY = "sk_live_51H8x9zJXsomeLongSecretValue123456"'
    out, found = redact(text)
    assert "sk_live_51H8x9zJXsomeLongSecretValue123456" not in out
    assert found


def test_does_not_touch_normal_code():
    text = "def add(a, b):\n    return a + b\n"
    out, found = redact(text)
    assert out == text
    assert found == []


def test_chunker_redacts_secrets_in_indexed_content():
    from packages.code_intelligence.symbols import FileAnalysis
    from packages.rag.chunker import chunk_file

    source = 'API_KEY = "AKIAABCDEFGHIJKLMNOP"\nVALUE = 1\n'
    analysis = FileAnalysis(file_path="config.py", language="python", imports=[], symbols=[], line_count=2)
    chunks = chunk_file(repository_id=1, analysis=analysis, source=source)
    assert len(chunks) == 1
    assert "AKIAABCDEFGHIJKLMNOP" not in chunks[0].content
    assert "REDACTED" in chunks[0].content
