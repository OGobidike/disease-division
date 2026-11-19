"""The ground the later phases stand on."""

import socket

import pytest

import disease_division


def test_the_package_imports_and_names_its_version():
    assert disease_division.__version__ == "0.1.0"


def test_a_test_that_reaches_for_the_network_fails():
    # Later phases call a paid model. This proves no test can do so by accident.
    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="tried to reach the network"):
            sock.connect(("example.com", 443))
