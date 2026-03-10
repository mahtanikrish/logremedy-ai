import pytest
from gha_remediator.verification.venv_verifier import verify_python_dependency


def test_known_good_package():
    """An installable package should verify unless the environment blocks network."""
    status, ev = verify_python_dependency("pip")
    assert status in ("verified", "inconclusive"), f"Unexpected status: {status}, evidence: {ev}"


def test_nonexistent_package_fails():
    """A non-existent package should fail installation."""
    status, ev = verify_python_dependency("this-package-definitely-does-not-exist-xyz123abc")
    assert status == "failed", f"Expected 'failed', got: {status}, evidence: {ev}"
    assert "package" in ev
    assert ev["package"] == "this-package-definitely-does-not-exist-xyz123abc"


def test_evidence_contains_expected_keys_on_failure():
    """Failure evidence should include return code and output tails."""
    status, ev = verify_python_dependency("no-such-package-xyz9999")
    if status == "failed":
        assert "returncode" in ev
        assert "stdout_tail" in ev
        assert "stderr_tail" in ev
        assert ev["returncode"] != 0


def test_venv_cleanup_does_not_raise():
    """The verifier should clean up temp venv directories."""
    import tempfile, os
    before = set(
        d for d in os.listdir(tempfile.gettempdir()) if d.startswith("gha_venv_")
    )
    verify_python_dependency("no-such-package-xyz9999")
    after = set(
        d for d in os.listdir(tempfile.gettempdir()) if d.startswith("gha_venv_")
    )
    assert after == before
