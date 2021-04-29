import logging

import pytest


log = logging.getLogger(__name__)


def _check_status_messages(ops_test):
    """ Validate that the status messages are correct. """
    expected_messages = {
        "kubernetes-master": "Kubernetes master running.",
        "kubernetes-worker": "Kubernetes worker running.",
    }
    for app, message in expected_messages.items():
        for unit in ops_test.model.applications[app].units:
            assert unit.workload_status_message == message


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test):
    bundle = ops_test.render_bundle(
        "tests/data/bundle.yaml", master_charm=await ops_test.build_charm(".")
    )
    await ops_test.model.deploy(bundle)
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)
    _check_status_messages(ops_test)


async def test_kube_api_endpoint(ops_test):
    """ Validate that adding the kube-api-endpoint relation works """
    await ops_test.model.add_relation(
        "kubernetes-master:kube-api-endpoint", "kubernetes-worker:kube-api-endpoint"
    )
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=10 * 60)
    _check_status_messages(ops_test)
