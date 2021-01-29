import json
from ipaddress import ip_interface
from unittest import mock
from reactive import kubernetes_master
from charms.layer import kubernetes_common
from charms.layer.kubernetes_common import get_version, kubectl
from charms.reactive import endpoint_from_flag, set_flag, is_flag_set, clear_flag
from charmhelpers.core import hookenv, unitdata


kubernetes_common.get_networks = lambda cidrs: [ip_interface(cidr.strip()).network
                                                for cidr in cidrs.split(',')]


def test_send_default_cni():
    hookenv.config.return_value = 'test-default-cni'
    kubernetes_master.send_default_cni()
    kube_control = endpoint_from_flag('kube-control.connected')
    kube_control.set_default_cni.assert_called_once_with('test-default-cni')


def test_default_cni_changed():
    set_flag('kubernetes-master.components.started')
    kubernetes_master.default_cni_changed()
    assert not is_flag_set('kubernetes-master.components.started')


def test_series_upgrade():
    assert kubernetes_master.service_pause.call_count == 0
    assert kubernetes_master.service_resume.call_count == 0
    kubernetes_master.pre_series_upgrade()
    assert kubernetes_master.service_pause.call_count == 4
    assert kubernetes_master.service_resume.call_count == 0
    kubernetes_master.post_series_upgrade()
    assert kubernetes_master.service_pause.call_count == 4
    assert kubernetes_master.service_resume.call_count == 4


@mock.patch('builtins.open', mock.mock_open())
@mock.patch('os.makedirs', mock.Mock(return_value=0))
def configure_apiserver(service_cidr_from_db, service_cidr_from_config):
    set_flag('leadership.is_leader')
    db = unitdata.kv()
    db.get.return_value = service_cidr_from_db
    hookenv.config.return_value = service_cidr_from_config
    get_version.return_value = (1, 18)
    kubernetes_master.configure_apiserver()


def update_for_service_cidr_expansion():
    def _svc(clusterIP):
        return json.dumps({
            "items": [
                {
                    "metadata": {"name": "kubernetes"},
                    "spec": {"clusterIP": clusterIP},
                }
            ]
        }).encode('utf8')

    kubectl.side_effect = [
        _svc('10.152.183.1'),
        None,
        _svc('10.152.0.1'),
        b'{"items":[]}',
    ]
    assert kubectl.call_count == 0
    kubernetes_master.update_for_service_cidr_expansion()


def test_service_cidr_greenfield_deploy():
    configure_apiserver(None, '10.152.183.0/24')
    assert not is_flag_set('kubernetes-master.had-service-cidr-expanded')
    configure_apiserver(None, '10.152.183.0/24,fe80::/120')
    assert not is_flag_set('kubernetes-master.had-service-cidr-expanded')


def test_service_cidr_no_change():
    configure_apiserver('10.152.183.0/24', '10.152.183.0/24')
    assert not is_flag_set('kubernetes-master.had-service-cidr-expanded')
    configure_apiserver('10.152.183.0/24,fe80::/120', '10.152.183.0/24,fe80::/120')
    assert not is_flag_set('kubernetes-master.had-service-cidr-expanded')


def test_service_cidr_non_expansion():
    configure_apiserver('10.152.183.0/24', '10.154.183.0/24')
    assert not is_flag_set('kubernetes-master.had-service-cidr-expanded')
    configure_apiserver('10.152.183.0/24,fe80::/120', '10.152.183.0/24,fe81::/120')
    assert not is_flag_set('kubernetes-master.had-service-cidr-expanded')


def test_service_cidr_expansion():
    configure_apiserver('10.152.183.0/24', '10.152.0.0/16')
    assert is_flag_set('kubernetes-master.had-service-cidr-expanded')
    clear_flag('kubernetes-master.had-service-cidr-expanded')
    configure_apiserver('10.152.183.0/24,fe80::/120', '10.152.183.0/24,fe80::/112')
    assert is_flag_set('kubernetes-master.had-service-cidr-expanded')
    unitdata.kv().get.return_value = '10.152.0.0/16'
    update_for_service_cidr_expansion()
    assert kubectl.call_count == 4


def test_get_unset_flags():
    set_flag("test.available")

    missing_flags = kubernetes_master.get_unset_flags("test.available",
                                                      "not-set-flag.available")
    assert missing_flags == ["not-set-flag.available"]


@mock.patch("reactive.kubernetes_master.send_data")
def test_update_certificates_with_missing_relations(mock_send_data):
    # NOTE (rgildein): This test only tests whether the send_data function
    # has been called, if required relations are missing.
    set_flag('test_available')

    kubernetes_master.update_certificates()
    hookenv.log.assert_any_call("Missing relations: 'certificates.available, "
                                "kube-api-endpoint.available'", hookenv.ERROR)
    mock_send_data.assert_not_called()


def test_status_set_on_missing_ca():
    """Test that set_final_status() will set blocked state if CA is missing"""
    set_flag("certificates.available")
    set_flag("kubernetes-master.secure-storage.failed")
    kubernetes_master.set_final_status()
    hookenv.status_set.assert_called_with('blocked',
                                          'Failed to configure encryption; '
                                          'secrets are unencrypted or inaccessible')
    clear_flag("certificates.available")
    kubernetes_master.set_final_status()
    hookenv.status_set.assert_called_with('blocked',
                                          'Missing relation to certificate '
                                          'authority.')
