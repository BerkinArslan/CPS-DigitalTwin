"""
P07 - Weather API integration and predictive demand.

Domain model and Sparkplug B wire descriptors for the weather pipeline node.

Published topics (see ForecastTopic, BirthTopic, DeathTopic below):
  cps/p07/DDATA/weather-pipeline   -  weather forecast   (not retained, QoS 1)
  cps/p07/NBIRTH/weather-pipeline  -  on connect         (retained, QoS 1)
  cps/p07/NDEATH/weather-pipeline  -  LWT                (retained, QoS 1)

Note: ``generated_at`` (Q3 required field) is carried by the Sparkplug B payload
envelope timestamp (``SparkplugNodeModel.timestamp``) and is therefore not
repeated as a named metric.

Consumers: P05 (watering controller  -  ET0 / rainfall-suppression logic),
           P06 (logging)
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field

from .core import (
    DataType,
    MessageType,
    NodeDefinition,
    NodeTopic,
    SparkplugNodeModel,
    SparkplugPayload,
    sparkplug_topic,
)

_NODE_ID = "p07"
_EDGE_NODE_ID = "weather-pipeline"


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class WeatherForecastStatus(StrEnum):
    LIVE = "live"
    CACHED = "cached"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Nested sub-models  —  plain BaseModel, NOT SparkplugNodeModel.
# Each field that holds one of these is serialised to a JSON string inside
# a STRING metric by to_ndata() and reconstructed by from_ndata().
# ---------------------------------------------------------------------------


class StalenessReason(StrEnum):
    NO_CACHE = "no_cache"
    CORRUPT_CACHE = "corrupt_cache"
    MISSING_TIMESTAMP = "missing_timestamp"
    CACHE_TOO_OLD = "cache_too_old"


class StalenessInfo(BaseModel):
    """Cache-state metadata. Always present in every payload."""

    is_cached: bool
    fetched_at: str | None = None
    hours_old: float | None = Field(default=None, ge=0)
    reason: StalenessReason | None = None


class LocationData(BaseModel):
    """Geographic location of the forecast."""

    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class HourlyForecast(BaseModel):
    """One hour of weather forecast data."""

    time: str
    temperature_c: float = Field(ge=-60, le=60)
    precipitation_mm: float = Field(ge=0, le=200)
    solar_radiation_wm2: float = Field(ge=0, le=1400)


class DailyETSummary(BaseModel):
    """Daily evapotranspiration summary — one entry per forecast day."""

    date: str
    hours_of_data: int = Field(ge=1, le=24)
    temp_max_c: float = Field(ge=-60, le=60)
    temp_min_c: float = Field(ge=-60, le=60)
    temp_mean_c: float = Field(ge=-60, le=60)
    total_precipitation_mm: float = Field(ge=0)
    total_solar_mj_m2: float = Field(ge=0, le=100)
    ra_mj_m2: float = Field(ge=0, le=50)
    et0_mm: float = Field(ge=0, le=20)


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


class WeatherForecastData(SparkplugNodeModel):
    """
    Weather forecast payload published by the weather API integration node.

    Consumers MUST check ``status`` first:
    - ``live``        — freshly fetched this cycle; all fields are valid.
    - ``cached``      — API unreachable; data served from local file;
                        check ``staleness.hours_old`` for age.
    - ``unavailable`` — cache missing or older than 24 h;
                        ``forecast_hours`` and ``daily_et_summary`` are empty;
                        ``message`` describes why.
                        Consumers MUST activate a safe fallback and MUST NOT
                        treat this state as "no rain expected".

    Nested sub-models (``location``, ``forecast_hours``, ``daily_et_summary``,
    ``staleness``) are JSON-encoded as STRING metrics on the wire.
    """

    METRIC_DATA_SOURCE: ClassVar[str] = "weather/data_source"
    METRIC_LOCATION: ClassVar[str] = "weather/location"
    METRIC_FORECAST_HOURS: ClassVar[str] = "weather/forecast_hours"
    METRIC_DAILY_ET_SUMMARY: ClassVar[str] = "weather/daily_et_summary"
    METRIC_STALENESS: ClassVar[str] = "weather/staleness"
    METRIC_STATUS: ClassVar[str] = "weather/status"
    METRIC_MESSAGE: ClassVar[str] = "weather/message"
    data_source: str = Field(
        default="open-meteo",
        description=(
            "Data provider identifier. Currently always 'open-meteo'. "
            "Consumers: P05, P06."
        ),
        json_schema_extra={
            "metric_name": METRIC_DATA_SOURCE,
            "datatype": DataType.STRING,
        },
    )
    location: LocationData = Field(
        description=(
            "Geographic location of the forecast (name, latitude, longitude). "
            "Encoded as a JSON object in a STRING metric. "
            "Consumers: P05, P06."
        ),
        json_schema_extra={
            "metric_name": METRIC_LOCATION,
            "datatype": DataType.STRING,
        },
    )
    forecast_hours: list[HourlyForecast] = Field(
        default_factory=list,
        description=(
            "Hourly forecast array (up to 48 items). Empty when status is "
            "'unavailable'. Each item contains time, temperature_c, "
            "precipitation_mm, solar_radiation_wm2. "
            "Encoded as a JSON array in a STRING metric. "
            "Consumers: P05 (rainfall suppression), P06."
        ),
        json_schema_extra={
            "metric_name": METRIC_FORECAST_HOURS,
            "datatype": DataType.STRING,
        },
    )
    daily_et_summary: list[DailyETSummary] = Field(
        default_factory=list,
        description=(
            "Per-day ET0 summary array. Empty when status is 'unavailable'. "
            "Each item: date, et0_mm, ra_mj_m2, and weather aggregates. "
            "Encoded as a JSON array in a STRING metric. "
            "Consumers: P05 (feed-forward demand estimation), P06."
        ),
        json_schema_extra={
            "metric_name": METRIC_DAILY_ET_SUMMARY,
            "datatype": DataType.STRING,
        },
    )
    staleness: StalenessInfo = Field(
        description=(
            "Cache-state metadata. Always present. 'is_cached' flags whether "
            "data is served from the local cache file. 'hours_old' is the age "
            "of the cached data in hours; present when is_cached=true. "
            "'reason' is present only when status='unavailable'. "
            "Encoded as a JSON object in a STRING metric. "
            "Consumers: P05, P06."
        ),
        json_schema_extra={
            "metric_name": METRIC_STALENESS,
            "datatype": DataType.STRING,
        },
    )
    status: WeatherForecastStatus = Field(
        default=WeatherForecastStatus.UNAVAILABLE,
        description=(
            "Forecast availability state. Always present. Consumers MUST check "
            "this before acting on any other field. "
            "Consumers: P05 (controller), P06."
        ),
        json_schema_extra={
            "metric_name": METRIC_STATUS,
            "datatype": DataType.STRING,
        },
    )
    message: str | None = Field(
        default=None,
        description=(
            "Human-readable explanation of the unavailable state. "
            "Present only when status='unavailable'. "
            "Consumers: P06 (logging)."
        ),
        json_schema_extra={
            "metric_name": METRIC_MESSAGE,
            "datatype": DataType.STRING,
            "skip_when_none": True,
        },
    )


# ---------------------------------------------------------------------------
# Topics published by this node.
# Import these in subscriber code  -  never hardcode topic strings.
#
# Usage (subscriber):
#   import schema.p07 as P07
#   client.subscribe(P07.ForecastTopic.address, qos=P07.ForecastTopic.qos)
#   forecast = P07.WeatherForecastData.from_ndata(decoded_payload)
# ---------------------------------------------------------------------------

ForecastTopic = NodeTopic(
    address=sparkplug_topic(MessageType.DDATA, _NODE_ID, _EDGE_NODE_ID),
    model=WeatherForecastData,
    publisher=_NODE_ID,
    qos=1,
    retain=False,
    interval_ms=7_200_000,  # 2 h fetch cycle  -  agreed with P04 and P05
    description=(
        "Weather forecast payload. Published after each API fetch cycle (2 h) "
        "and immediately on startup. "
        "Retained so late subscribers (e.g. P05 on reconnect) immediately "
        "receive the most recent forecast without waiting up to 2 hours. "
        "Consumers MUST check the 'status' field before acting on any data. "
        "'unavailable' MUST NOT be treated as 'no rain expected'."
    ),
)

BirthTopic = NodeTopic(
    address=sparkplug_topic(MessageType.NBIRTH, _NODE_ID, _EDGE_NODE_ID),
    model=WeatherForecastData,
    publisher=_NODE_ID,
    qos=1,
    retain=False,
    description="P07 birth certificate. Published on connect. Declares metric schema.",
)

DeathTopic = NodeTopic(
    address=sparkplug_topic(MessageType.NDEATH, _NODE_ID, _EDGE_NODE_ID),
    model=SparkplugPayload,
    publisher="broker",
    qos=1,
    retain=False,
    description="P07 death notice (LWT).",
)

# ---------------------------------------------------------------------------
# Node definition  -  auto-discovered by registry.py
# ---------------------------------------------------------------------------

NODE = NodeDefinition(
    node_id=_NODE_ID,
    label="P07  -  Weather API Integration",
    publishes=[ForecastTopic, BirthTopic, DeathTopic],
)
