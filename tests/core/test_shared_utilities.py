"""Tests for shared geographic and time utilities."""
from datetime import UTC, datetime

import pytest

from umich_transit.core.geo import haversine_m
from umich_transit.core.time import AGENCY_TIMEZONE, to_agency_time


def test_haversine_distance_is_symmetric():
    mason_hall = (42.2769, -83.7382)
    pierpont_commons = (42.2914, -83.7178)

    forward = haversine_m(*mason_hall, *pierpont_commons)
    reverse = haversine_m(*pierpont_commons, *mason_hall)

    assert forward == pytest.approx(reverse)
    assert forward > 0


def test_to_agency_time_converts_utc():
    local = to_agency_time(datetime(2026, 5, 1, 14, 30, tzinfo=UTC))

    assert local.tzinfo == AGENCY_TIMEZONE
    assert local.hour == 10


def test_to_agency_time_treats_naive_values_as_utc():
    local = to_agency_time(datetime(2026, 5, 1, 14, 30))

    assert local.hour == 10
