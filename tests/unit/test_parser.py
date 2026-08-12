from packages.code_intelligence.parser import detect_language, get_parser


def test_detect_language():
    assert detect_language("a/b.py") == "python"
    assert detect_language("a/b.ts") == "typescript"
    assert detect_language("a/b.jsx") == "javascript"
    assert detect_language("a/b.md") is None


def test_python_parser_extracts_class_methods_and_calls():
    src = """
import os

class UserService:
    \"\"\"Handles user auth.\"\"\"
    def login(self, user, pw):
        token = generate_token(user)
        return validate(token)

def generate_token(user):
    return hash(user)
"""
    analysis = get_parser("python").analyze("svc.py", src)
    assert analysis.imports == ["import os"]

    by_name = {s.name: s for s in analysis.symbols}
    assert by_name["UserService"].kind == "class"
    assert by_name["UserService"].docstring == "Handles user auth."
    assert by_name["login"].kind == "method"
    assert by_name["login"].parent == "UserService"
    assert "generate_token" in by_name["login"].calls
    assert "validate" in by_name["login"].calls
    assert by_name["generate_token"].kind == "function"
    assert by_name["generate_token"].line_start == 10


def test_python_parser_handles_syntax_free_of_symbols():
    analysis = get_parser("python").analyze("config.py", "X = 1\nY = 2\n")
    assert analysis.symbols == []


def test_javascript_parser_extracts_function_and_class():
    src = """
import { foo } from './foo';

class Widget {
  render() {
    return draw();
  }
}

function build() {
  return new Widget();
}
"""
    analysis = get_parser("javascript").analyze("widget.js", src)
    by_name = {s.name: s for s in analysis.symbols}
    assert by_name["Widget"].kind == "class"
    assert by_name["render"].parent == "Widget"
    assert "draw" in by_name["render"].calls
    assert by_name["build"].kind == "function"
