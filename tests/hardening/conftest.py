"""Hardening pack: markers.

``defect`` = a test that asserts the behaviour OceanEye SHOULD have. It is red today on purpose:
each red test is a confirmed fault with a reproducible number. When you fix one it turns green.

    pytest tests/hardening -q                 # everything (red = open defects)
    pytest tests/hardening -q -m "not defect" # guards that must stay green
    pytest tests/hardening -q -m defect       # just the open faults
"""


def pytest_configure(config):
    config.addinivalue_line("markers", "defect: asserts desired behaviour; red = open fault")
