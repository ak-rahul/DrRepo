import json

from drrepo.collectors.manifests import (
    discover,
    parse_package_json,
    parse_package_lock_json,
    parse_poetry_lock,
    parse_pyproject_toml,
    parse_requirements_txt,
    parse_uv_lock,
)


def test_requirements_exact_pins_extras_markers_and_ranges():
    deps = parse_requirements_txt(
        "uvicorn[standard]==0.49.0\n"
        "Django==4.2.1 ; python_version >= '3.8'\n"
        "requests>=2.6  # range, not auditable\n"
        "-r other.txt\n"
        "git+https://github.com/x/y.git\n"
        "# comment\n"
        "Flask_Login===0.6.3\n"
    )
    assert deps.packages == [
        ("PyPI", "uvicorn", "0.49.0"),
        ("PyPI", "django", "4.2.1"),
        ("PyPI", "flask-login", "0.6.3"),
    ]
    assert deps.unpinned == ["requests"]
    assert not deps.dev


def test_pyproject_project_groups_and_poetry():
    deps = parse_pyproject_toml(
        """
[project]
dependencies = ["httpx==0.28.1", "pydantic>=2"]
[project.optional-dependencies]
cli = ["click==8.1.7"]
[dependency-groups]
dev = ["pytest==8.0.0", {include-group = "lint"}]
[tool.poetry.dependencies]
python = "^3.11"
rich = "13.7.1"
typer = "^0.9"
[tool.poetry.group.test.dependencies]
coverage = {version = "7.4.0"}
"""
    )
    assert ("PyPI", "httpx", "0.28.1") in deps.packages
    assert ("PyPI", "click", "8.1.7") in deps.packages
    assert ("PyPI", "rich", "13.7.1") in deps.packages
    assert deps.dev == {("PyPI", "pytest", "8.0.0"), ("PyPI", "coverage", "7.4.0")}
    assert set(deps.unpinned) == {"pydantic", "typer"}


def test_invalid_toml_and_json_are_empty():
    assert parse_pyproject_toml("not = [valid").packages == []
    assert parse_package_json("{nope").packages == []


def test_package_json_exact_vs_ranges():
    deps = parse_package_json(
        json.dumps(
            {
                "dependencies": {"lodash": "4.17.20", "react": "^18.0.0"},
                "devDependencies": {"jest": "=29.0.0"},
            }
        )
    )
    assert deps.packages == [("npm", "lodash", "4.17.20"), ("npm", "jest", "29.0.0")]
    assert deps.dev == {("npm", "jest", "29.0.0")}
    assert deps.unpinned == ["react"]


UV_LOCK = """
version = 1
[[package]]
name = "demo"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "httpx" }]
[package.optional-dependencies]
cli = [{ name = "click" }]
[package.dev-dependencies]
dev = [{ name = "pytest" }]

[[package]]
name = "httpx"
version = "0.28.1"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "idna" }]

[[package]]
name = "idna"
version = "3.10"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "click"
version = "8.1.7"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pytest"
version = "8.3.5"
source = { registry = "https://pypi.org/simple" }
"""


def test_uv_lock_runtime_closure():
    deps = parse_uv_lock(UV_LOCK)
    names = {name for _, name, _ in deps.packages}
    assert names == {"httpx", "idna", "click", "pytest"}  # the editable project itself is excluded
    assert deps.dev == {("PyPI", "pytest", "8.3.5")}  # idna is a transitive runtime dep


def test_poetry_lock_legacy_category():
    deps = parse_poetry_lock('[[package]]\nname = "Black"\nversion = "24.1.0"\ncategory = "dev"\n')
    assert deps.dev == {("PyPI", "black", "24.1.0")}


def test_package_lock_v3_and_v1():
    v3 = parse_package_lock_json(
        json.dumps(
            {
                "packages": {
                    "": {"name": "app"},
                    "node_modules/lodash": {"version": "4.17.20"},
                    "node_modules/jest": {"version": "29.0.0", "dev": True},
                    "node_modules/linked": {"link": True},
                }
            }
        )
    )
    assert set(v3.packages) == {("npm", "lodash", "4.17.20"), ("npm", "jest", "29.0.0")}
    assert v3.dev == {("npm", "jest", "29.0.0")}
    v1 = parse_package_lock_json(json.dumps({"dependencies": {"a": {"version": "1.0.0"}}}))
    assert v1.packages == [("npm", "a", "1.0.0")]


def test_discover_lockfile_wins_and_dedupes(make_repo):
    root = make_repo(
        {
            "uv.lock": UV_LOCK,
            "pyproject.toml": '[project]\ndependencies = ["httpx==0.1.0"]\n',  # ignored: lockfile present
            "services/api/requirements.txt": "httpx==0.28.1\nrequests>=2\n",
            "node_modules/x/package.json": json.dumps(
                {"dependencies": {"evil": "1.0.0"}}
            ),  # vendored, skipped
        }
    )
    deps, used = discover(root)
    assert set(used) == {"uv.lock", "services/api/requirements.txt"}
    assert deps.packages.count(("PyPI", "httpx", "0.28.1")) == 1
    assert ("PyPI", "httpx", "0.1.0") not in deps.packages
    assert deps.unpinned == ["requests"]


def test_discover_package_runtime_anywhere_is_not_dev(make_repo):
    root = make_repo(
        {
            "a/requirements-dev.txt": "pytest==8.0.0\n",
            "b/requirements.txt": "pytest==8.0.0\n",
        }
    )
    deps, _ = discover(root)
    assert deps.dev == set()
