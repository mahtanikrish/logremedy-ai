from gha_remediator.classifier import classify_failure


def test_module_not_found():
    log = "ModuleNotFoundError: No module named 'requests'"
    assert classify_failure(log) == "environment_dependency_failure"

def test_no_matching_distribution():
    log = "ERROR: Could not find a version that satisfies the requirement numpy==99.0.0"
    assert classify_failure(log) == "environment_dependency_failure"

def test_no_matching_distribution_alt():
    log = "ERROR: No matching distribution found for pandas==99.0"
    assert classify_failure(log) == "environment_dependency_failure"

def test_pytest_failure():
    log = "FAILED tests/test_app.py::test_foo - AssertionError\n1 failed, 3 passed"
    assert classify_failure(log) == "test_failure"

def test_jest_failure():
    log = "FAIL src/app.test.js\n  ● Test suite failed to run"
    assert classify_failure(log) == "test_failure"

def test_assertion_error():
    log = "AssertionError: expected True but got False"
    assert classify_failure(log) == "test_failure"

def test_tsc_build_failure():
    log = "error TS2322: Type 'string' is not assignable to type 'number'\ntsc: Build failed"
    assert classify_failure(log) == "build_failure"

def test_npm_build_failure():
    log = "npm run build\nFailed to compile."
    assert classify_failure(log) == "build_failure"

def test_workflow_yaml_invalid():
    log = "workflow invalid yaml syntax error"
    assert classify_failure(log) == "workflow_configuration_error"

def test_permission_denied():
    log = "Error: Permission denied (publickey)"
    assert classify_failure(log) == "infrastructure_failure"

def test_unauthorized():
    log = "ERROR: unauthorized: access to the resource is denied"
    assert classify_failure(log) == "infrastructure_failure"

def test_unknown():
    log = "some completely unrelated output line with no known failure pattern"
    assert classify_failure(log) == "unknown_failure"


def test_dependabot_transitive_conflict_is_environment_dependency_failure():
    log = "\n".join(
        [
            "Starting security update job for ColorlibHQ/AdminLTE",
            "The latest possible version that can be installed is 1.29.0 because of the following conflicting dependencies:",
            "Dependabot encountered '1' error(s) during execution, please check the logs for more details.",
            "| transitive_update_not_possible |",
            "##[error]Dependabot encountered an error performing the update",
        ]
    )
    assert classify_failure(log) == "environment_dependency_failure"
