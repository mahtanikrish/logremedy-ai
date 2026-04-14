from gha_remediator.verification.static_checks import basic_static_validation, file_exists


def test_non_supported_file_skipped(tmp_path):
    """Unsupported file extensions produce no static checks."""
    result = basic_static_validation(str(tmp_path), ["foo.txt"])
    assert result["checks"] == []


def test_non_yaml_extension_skipped(tmp_path):
    """A .txt file under .github/workflows/ is not YAML-checked."""
    result = basic_static_validation(str(tmp_path), [".github/workflows/ci.txt"])
    assert result["checks"] == []


def test_missing_workflow_yaml_fails(tmp_path):
    """A .yml path that doesn't exist on disk results in a failed yaml_parse check."""
    result = basic_static_validation(str(tmp_path), [".github/workflows/ci.yml"])
    checks = result["checks"]
    assert len(checks) == 1
    assert checks[0]["type"] == "yaml_parse"
    assert checks[0]["ok"] is False


def test_valid_workflow_yaml_passes(tmp_path):
    """A syntactically valid YAML workflow file passes static validation."""
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    wf_file = wf_dir / "ci.yml"
    wf_file.write_text("on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n")

    result = basic_static_validation(str(tmp_path), [".github/workflows/ci.yml"])
    checks = result["checks"]
    assert len(checks) == 1
    assert checks[0]["ok"] is True


def test_valid_python_file_passes(tmp_path):
    py_file = tmp_path / "conf.py"
    py_file.write_text("value = 1\n", encoding="utf-8")

    result = basic_static_validation(str(tmp_path), ["conf.py"])
    checks = result["checks"]

    assert len(checks) == 1
    assert checks[0]["type"] == "python_compile"
    assert checks[0]["ok"] is True


def test_invalid_python_file_fails(tmp_path):
    py_file = tmp_path / "conf.py"
    py_file.write_text("if True print('broken')\n", encoding="utf-8")

    result = basic_static_validation(str(tmp_path), ["conf.py"])
    checks = result["checks"]

    assert len(checks) == 1
    assert checks[0]["type"] == "python_compile"
    assert checks[0]["ok"] is False


def test_valid_json_file_passes(tmp_path):
    json_file = tmp_path / "package.json"
    json_file.write_text('{"name": "demo"}\n', encoding="utf-8")

    result = basic_static_validation(str(tmp_path), ["package.json"])
    checks = result["checks"]

    assert len(checks) == 1
    assert checks[0]["type"] == "json_parse"
    assert checks[0]["ok"] is True


def test_file_exists_true(tmp_path):
    f = tmp_path / "requirements.txt"
    f.write_text("requests\n")
    assert file_exists(str(tmp_path), "requirements.txt")


def test_file_exists_false(tmp_path):
    assert not file_exists(str(tmp_path), "requirements.txt")
