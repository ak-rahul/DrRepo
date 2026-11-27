"""Code-symbol index and the `symbols` tool family."""

import threading

import pytest

from drrepo.agents.grounding import examined_paths
from drrepo.agents.symbols import SymbolIndex, pattern_symbols, python_symbols
from drrepo.agents.tools import build_tools, make_symbol_tools
from drrepo.config import Config
from drrepo.models import ToolCallTrace

PY = '''\
import os


def authenticate(user: str, token: str = "") -> bool:
    """Check a token."""
    return check(token)


class Session:
    def login(self, user):
        return authenticate(user)

    async def refresh(self) -> None:
        def inner():
            pass


def check(token):
    return token == os.environ.get("TOKEN")
'''


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text(PY, encoding="utf-8")
    (tmp_path / "app" / "views.py").write_text(
        "from app.auth import authenticate\n\nauthenticated = authenticate('u')\n",
        encoding="utf-8",
    )
    (tmp_path / "web.ts").write_text(
        "export async function fetchUser(id: string) {}\n"
        "export const handler = async (req: Request) => fetchUser(req.id);\n"
        "export class Api {}\ninterface Options { x: number }\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.py").write_text("def ok():\n    pass\ndef broken(:\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("function vendored() {}\n", encoding="utf-8")
    return tmp_path


def _tools(root):
    return {t.name: t for t in make_symbol_tools(str(root))}


def test_python_definitions_are_exact():
    symbols = {s.name: s for s in python_symbols("app/auth.py", PY)}
    assert set(symbols) == {
        "authenticate",
        "Session",
        "Session.login",
        "Session.refresh",
        "Session.refresh.inner",
        "check",
    }
    auth = symbols["authenticate"]
    assert (auth.kind, auth.line, auth.end_line) == ("function", 4, 6)
    assert auth.signature == "def authenticate(user: str, token: str='') -> bool"
    assert symbols["Session.login"].kind == "method"
    assert symbols["Session.refresh"].signature.startswith("async def refresh(self)")
    assert symbols["Session.refresh.inner"].kind == "function"  # nested in a method body
    assert python_symbols("x.py", "def broken(:\n") is None


def test_line_patterns_cover_other_languages():
    names = {
        (s.name, s.kind)
        for s in pattern_symbols(
            "x.go",
            "func (s *Server) Handle(w http.ResponseWriter) {}\ntype Server struct {}\n",
            "go",
        )
    }
    assert names == {("Handle", "function"), ("Server", "type")}
    ruby = pattern_symbols("x.rb", "module Billing\n  def self.charge!(amount)\n", "ruby")
    assert [s.name for s in ruby] == ["Billing", "charge!"]
    rust = pattern_symbols("x.rs", "pub(crate) async fn run() {}\npub struct Config;\n", "rust")
    assert [s.name for s in rust] == ["run", "Config"]


def test_index_skips_vendored_dirs_and_falls_back_on_syntax_errors(repo):
    index = SymbolIndex(repo).build()
    assert "node_modules/dep.js" not in index.files
    assert {s.name for s in index.outline("broken.py")} == {"ok", "broken"}  # line patterns
    assert {s.name for s in index.outline("web.ts")} == {"fetchUser", "handler", "Api", "Options"}


def test_find_definition(repo):
    tools = _tools(repo)
    out = tools["find_definition"].invoke({"name": "authenticate"})
    assert (
        out
        == "app/auth.py:4-6: function authenticate: def authenticate(user: str, token: str='') -> bool"
    )
    assert "app/auth.py:10-11: method Session.login" in tools["find_definition"].invoke(
        {"name": "login"}
    )
    assert tools["find_definition"].invoke({"name": "nothing"}).startswith("No definition")
    assert tools["find_definition"].invoke({"name": "a; rm -rf /"}).startswith("ERROR")


def test_find_references_are_whole_words_without_definitions(repo):
    out = _tools(repo)["find_references"].invoke({"name": "authenticate"})
    lines = out.splitlines()
    assert "app/auth.py:11: return authenticate(user)" in lines
    assert "app/views.py:1: from app.auth import authenticate" in lines
    assert "app/views.py:3: authenticated = authenticate('u')" in lines  # one line, one hit
    assert not any(line.startswith("app/auth.py:4:") for line in lines)  # the definition
    only_views = _tools(repo)["find_references"].invoke(
        {"name": "authenticate", "glob": "app/views.py"}
    )
    assert all(line.startswith("app/views.py") for line in only_views.splitlines())
    assert _tools(repo)["find_references"].invoke({"name": "x", "glob": "../*"}).startswith("ERROR")


def test_outline_and_sandbox(repo):
    tools = _tools(repo)
    out = tools["outline"].invoke({"path": "app/auth.py"}).splitlines()
    assert out[0].startswith("app/auth.py:4-6: function authenticate")
    assert "  app/auth.py:10-11: method Session.login: def login(self, user)" in out
    assert tools["outline"].invoke({"path": "../etc/passwd"}).startswith("ERROR")
    assert "not an indexed source file" in tools["outline"].invoke({"path": "README.md"})


def test_one_index_is_built_once_and_shared(repo, monkeypatch):
    index = SymbolIndex(repo)
    calls = []
    real = SymbolIndex.build

    def counting(self):
        calls.append(self._built)
        return real(self)

    monkeypatch.setattr(SymbolIndex, "build", counting)
    threads = [threading.Thread(target=index.definitions, args=("authenticate",)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert index._built and len(index.files) == 4


def test_family_wiring_and_grounding(repo):
    index = SymbolIndex(repo)
    tools = build_tools(("symbols",), clone_root=str(repo), config=Config(), symbol_index=index)
    assert {t.name for t in tools} == {"find_definition", "find_references", "outline"}
    assert build_tools(("symbols",), clone_root=None, config=Config()) == []
    out = tools[0].invoke({"name": "check"})
    seen = examined_paths([ToolCallTrace("find_definition", {"name": "check"}, out)])
    assert "app/auth.py" in seen.files  # a definition the agent saw counts as examined
