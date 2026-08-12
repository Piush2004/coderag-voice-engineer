"""LanguageParser abstraction over tree-sitter grammars.

Adding a language means adding one entry to _LANGUAGES plus query strings —
no redesign of the pipeline required (spec module 16/17).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from tree_sitter import Language, Node, Parser

from packages.code_intelligence.symbols import FileAnalysis, Symbol

EXT_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
}


def _load_language(name: str) -> Language:
    if name == "python":
        import tree_sitter_python as tsp

        return Language(tsp.language())
    if name == "javascript":
        import tree_sitter_javascript as tsjs

        return Language(tsjs.language())
    if name == "typescript":
        import tree_sitter_typescript as tsts

        return Language(tsts.language_typescript())
    if name == "go":
        import tree_sitter_go as tsgo

        return Language(tsgo.language())
    raise ValueError(f"Unsupported language: {name}")


class LanguageParser(ABC):
    language: str

    @abstractmethod
    def analyze(self, file_path: str, source: str) -> FileAnalysis: ...


class TreeSitterPythonParser(LanguageParser):
    language = "python"

    def __init__(self) -> None:
        self._parser = Parser(_load_language("python"))

    def analyze(self, file_path: str, source: str) -> FileAnalysis:
        tree = self._parser.parse(source.encode("utf-8"))
        root = tree.root_node
        src_bytes = source.encode("utf-8")

        imports: list[str] = []
        symbols: list[Symbol] = []

        def text(node: Node) -> str:
            return src_bytes[node.start_byte : node.end_byte].decode("utf-8")

        def collect_calls(node: Node) -> list[str]:
            calls = []
            for child in node.children:
                if child.type == "call":
                    fn = child.child_by_field_name("function")
                    if fn is not None:
                        calls.append(text(fn).split(".")[-1])
                calls.extend(collect_calls(child))
            return calls

        def docstring_of(body_node: Node) -> str | None:
            if body_node.child_count == 0:
                return None
            first = body_node.children[0]
            if first.type == "expression_statement" and first.child_count:
                s = first.children[0]
                if s.type == "string":
                    return text(s).strip("\"'")
            return None

        def walk(node: Node, parent_name: str | None) -> None:
            for child in node.children:
                if child.type in ("import_statement", "import_from_statement"):
                    imports.append(text(child).strip())
                elif child.type in ("function_definition", "class_definition"):
                    name_node = child.child_by_field_name("name")
                    body_node = child.child_by_field_name("body")
                    name = text(name_node) if name_node else "<anon>"
                    kind = (
                        "class"
                        if child.type == "class_definition"
                        else ("method" if parent_name else "function")
                    )
                    symbols.append(
                        Symbol(
                            name=name,
                            kind=kind,
                            file_path=file_path,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            source=text(child),
                            parent=parent_name,
                            docstring=docstring_of(body_node) if body_node else None,
                            calls=collect_calls(body_node) if body_node else [],
                        )
                    )
                    if body_node is not None:
                        walk(body_node, name if kind == "class" else parent_name)
                else:
                    walk(child, parent_name)

        walk(root, None)
        return FileAnalysis(
            file_path=file_path,
            language=self.language,
            imports=imports,
            symbols=symbols,
            line_count=source.count("\n") + 1,
        )


class TreeSitterJSParser(LanguageParser):
    """Shared implementation for JavaScript and TypeScript grammars."""

    def __init__(self, language: str) -> None:
        self.language = language
        self._parser = Parser(_load_language(language))

    def analyze(self, file_path: str, source: str) -> FileAnalysis:
        tree = self._parser.parse(source.encode("utf-8"))
        root = tree.root_node
        src_bytes = source.encode("utf-8")

        imports: list[str] = []
        symbols: list[Symbol] = []

        def text(node: Node) -> str:
            return src_bytes[node.start_byte : node.end_byte].decode("utf-8")

        def collect_calls(node: Node) -> list[str]:
            calls = []
            for child in node.children:
                if child.type == "call_expression":
                    fn = child.child_by_field_name("function")
                    if fn is not None:
                        calls.append(text(fn).split(".")[-1])
                calls.extend(collect_calls(child))
            return calls

        FUNC_TYPES = ("function_declaration", "method_definition", "function")
        CLASS_TYPES = ("class_declaration",)

        def walk(node: Node, parent_name: str | None) -> None:
            for child in node.children:
                if child.type == "import_statement":
                    imports.append(text(child).strip())
                elif child.type in CLASS_TYPES:
                    name_node = child.child_by_field_name("name")
                    name = text(name_node) if name_node else "<anon>"
                    symbols.append(
                        Symbol(
                            name=name,
                            kind="class",
                            file_path=file_path,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            source=text(child),
                            parent=parent_name,
                            calls=[],
                        )
                    )
                    walk(child, name)
                elif child.type in FUNC_TYPES:
                    name_node = child.child_by_field_name("name")
                    name = text(name_node) if name_node else "<anonymous>"
                    body = child.child_by_field_name("body")
                    symbols.append(
                        Symbol(
                            name=name,
                            kind="method" if parent_name else "function",
                            file_path=file_path,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            source=text(child),
                            parent=parent_name,
                            calls=collect_calls(body) if body else [],
                        )
                    )
                else:
                    walk(child, parent_name)

        walk(root, None)
        return FileAnalysis(
            file_path=file_path,
            language=self.language,
            imports=imports,
            symbols=symbols,
            line_count=source.count("\n") + 1,
        )


class TreeSitterGoParser(LanguageParser):
    language = "go"

    def __init__(self) -> None:
        self._parser = Parser(_load_language("go"))

    def analyze(self, file_path: str, source: str) -> FileAnalysis:
        tree = self._parser.parse(source.encode("utf-8"))
        root = tree.root_node
        src_bytes = source.encode("utf-8")

        imports: list[str] = []
        symbols: list[Symbol] = []

        def text(node: Node) -> str:
            return src_bytes[node.start_byte : node.end_byte].decode("utf-8")

        def collect_calls(node: Node) -> list[str]:
            calls = []
            for child in node.children:
                if child.type == "call_expression":
                    fn = child.child_by_field_name("function")
                    if fn is not None:
                        calls.append(text(fn).split(".")[-1])
                calls.extend(collect_calls(child))
            return calls

        for node in root.children:
            if node.type == "import_declaration":
                imports.append(text(node).strip())
            elif node.type == "type_declaration":
                for spec in node.children:
                    if spec.type == "type_spec":
                        name_node = spec.child_by_field_name("name")
                        struct_node = spec.child_by_field_name("type")
                        if name_node is not None and struct_node is not None and struct_node.type == "struct_type":
                            symbols.append(
                                Symbol(
                                    name=text(name_node),
                                    kind="class",
                                    file_path=file_path,
                                    line_start=node.start_point[0] + 1,
                                    line_end=node.end_point[0] + 1,
                                    source=text(node),
                                    calls=[],
                                )
                            )
            elif node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                body_node = node.child_by_field_name("body")
                name = text(name_node) if name_node else "<anon>"
                symbols.append(
                    Symbol(
                        name=name,
                        kind="function",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        source=text(node),
                        calls=collect_calls(body_node) if body_node else [],
                    )
                )
            elif node.type == "method_declaration":
                name_node = node.child_by_field_name("name")
                body_node = node.child_by_field_name("body")
                receiver_node = node.child_by_field_name("receiver")
                # receiver looks like "(s *Server)" — pull the type name out.
                parent = None
                if receiver_node is not None:
                    receiver_text = text(receiver_node)
                    parent = receiver_text.strip("()").split()[-1].lstrip("*") if receiver_text.strip("()") else None
                name = text(name_node) if name_node else "<anon>"
                symbols.append(
                    Symbol(
                        name=name,
                        kind="method",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        source=text(node),
                        parent=parent,
                        calls=collect_calls(body_node) if body_node else [],
                    )
                )

        return FileAnalysis(
            file_path=file_path,
            language=self.language,
            imports=imports,
            symbols=symbols,
            line_count=source.count("\n") + 1,
        )


_PARSER_CACHE: dict[str, LanguageParser] = {}


def get_parser(language: str) -> LanguageParser:
    if language not in _PARSER_CACHE:
        if language == "python":
            _PARSER_CACHE[language] = TreeSitterPythonParser()
        elif language in ("javascript", "typescript"):
            _PARSER_CACHE[language] = TreeSitterJSParser(language)
        elif language == "go":
            _PARSER_CACHE[language] = TreeSitterGoParser()
        else:
            raise ValueError(f"Unsupported language: {language}")
    return _PARSER_CACHE[language]


def detect_language(file_path: str) -> str | None:
    for ext, lang in EXT_TO_LANGUAGE.items():
        if file_path.endswith(ext):
            return lang
    return None
