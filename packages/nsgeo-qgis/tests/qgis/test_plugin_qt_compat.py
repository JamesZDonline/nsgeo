"""Harness behaviour that differs between QGIS 3 (Qt 5) and QGIS 4 (Qt 6)."""

from __future__ import annotations

from nsgeo_qgis.log import log


def test_message_log_fixture_sees_the_plugins_own_log(message_log):
    log("m9-probe")
    assert "m9-probe" in message_log
