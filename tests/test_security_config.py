from tests.conftest import make_test_settings


def test_deployment_mode_defaults_to_dev():
    s = make_test_settings()
    assert s.deployment.mode == "dev"


def test_sandbox_requires_isolation_by_default():
    s = make_test_settings()
    assert s.sandbox.require_isolation is True


def test_sso_auto_provision_defaults_false():
    s = make_test_settings()
    assert s.sso_auto_provision is False


def test_hosted_mode_is_accepted():
    s = make_test_settings(deployment={"mode": "hosted"})
    assert s.deployment.mode == "hosted"
