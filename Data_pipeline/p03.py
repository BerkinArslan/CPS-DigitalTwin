"""
DOCUMENT STATUS: NOT REVIEWED AT 13.05.2026

P03 - Environmental sensing.

Two physical sensors are modelled as separate Sparkplug B devices under the
same edge node (sensor-main):
  BME280 - temperature, relative humidity, barometric pressure
  BH1750 - ambient light (lux)

Published topics (see *Topic constants below):
  cps/p03/DDATA/sensor-main/humidity-pressure-and-temperature
  cps/p03/DDATA/sensor-main/ambient-light
                                          -  ambient light
                                             (not retained, QoS 0, every 10 s)
  cps/p03/NBIRTH/sensor-main        -  on connect            (retained, QoS 1)
  cps/p03/NDEATH/sensor-main        -  LWT                   (retained, QoS 1)

Consumers: P05 (watering decisions), P06 (logging), P07 (ground-truth for weather API),
P08 (anomaly detection), P15 (digital twin), P16 (plant health)
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from .core import (
    DataType,
    MessageType,
    NodeDefinition,
    NodeTopic,
    SensorStatus,
    SparkplugNodeModel,
    SparkplugPayload,
    sparkplug_topic,
)

_NODE_ID = "p03"
_EDGE_NODE_ID = "sensor-main"


# ---------------------------------------------------------------------------
# Device models
# ---------------------------------------------------------------------------


class EnvironmentBME280(SparkplugNodeModel):
    """
    DDATA payload for the BME280 combined sensor
    (temperature, humidity, pressure).

    Published on topic: cps/p03/DDATA/sensor-main/humidity-pressure-and-temperature
    Device ID: "humidity-pressure-and-temperature"
    """

    METRIC_TEMPERATURE_C: ClassVar[str] = "temperature_c"
    METRIC_HUMIDITY_REL: ClassVar[str] = "humidity_rel"
    METRIC_PRESSURE_HPA: ClassVar[str] = "pressure_hpa"
    METRIC_STATUS: ClassVar[str] = "status"
    temperature_c: float | None = Field(
        default=None,
        ge=-40.0,
        le=85.0,
        description=(
            "Ambient air temperature in Celsius. Null when sensor error. "
            "Typical sensor range: -40..85 °C. "
            "Consumers: P05 (evapotranspiration estimate), P08 (plausibility check)."
        ),
        json_schema_extra={
            "metric_name": METRIC_TEMPERATURE_C,
            "datatype": DataType.FLOAT,
            "null_when_error": True,
        },
    )
    humidity_rel: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description=(
            "Relative humidity percentage (0–100 %). Null when sensor error. "
            "P08 uses cross-sensor sanity check: if temperature_c < 0 and "
            "humidity_rel > 100 %, flag both as implausible."
        ),
        json_schema_extra={
            "metric_name": METRIC_HUMIDITY_REL,
            "datatype": DataType.FLOAT,
            "null_when_error": True,
        },
    )
    pressure_hpa: float | None = Field(
        default=None,
        ge=300.0,
        le=1100.0,
        description=(
            "Barometric pressure in hPa (approx. altitude -500 to 9000 m). "
            "Null when sensor error. "
            "Consumers: P07 (weather API ground-truth), P08 (plausibility check)."
        ),
        json_schema_extra={
            "metric_name": METRIC_PRESSURE_HPA,
            "datatype": DataType.FLOAT,
            "null_when_error": True,
        },
    )
    status: SensorStatus = Field(
        default=SensorStatus.OK,
        description=(
            "Quality flag for this BME280 reading. Always present. "
            "Consumers MUST check this before acting on measurement fields."
        ),
        json_schema_extra={"metric_name": METRIC_STATUS, "datatype": DataType.STRING},
    )


class EnvironmentLight(SparkplugNodeModel):
    """
    DDATA payload for the BH1750 ambient light sensor.

    Published on topic: cps/p03/DDATA/sensor-main/ambient-light
    Device ID: "ambient-light"
    """

    METRIC_LIGHT_LUX: ClassVar[str] = "light_lux"
    METRIC_STATUS: ClassVar[str] = "status"
    light_lux: float | None = Field(
        default=None,
        ge=0.0,
        le=65535.0,
        description=(
            "Ambient light intensity in lux. Null when sensor error. "
            "Indicative ranges: 0 (dark) / 200 (indoor) / 1 000 (overcast) "
            "/ 100 000 (direct sunlight). "
        ),
        json_schema_extra={
            "metric_name": METRIC_LIGHT_LUX,
            "datatype": DataType.FLOAT,
            "null_when_error": True,
        },
    )
    status: SensorStatus = Field(
        default=SensorStatus.OK,
        description=(
            "Quality flag for this BH1750 reading. "
            "Consumers MUST check before acting on light_lux."
        ),
        json_schema_extra={"metric_name": METRIC_STATUS, "datatype": DataType.STRING},
    )


# ---------------------------------------------------------------------------
# Topic descriptors
#
# Two devices, one node. Import these constants in subscriber code:
#
#   import schema.p03 as P03
#   client.subscribe(P03.BME280Topic.address, qos=P03.BME280Topic.qos)
#   reading = P03.EnvironmentBME280.from_data(decoded_payload)
# ---------------------------------------------------------------------------

BME280Topic = NodeTopic(
    address=sparkplug_topic(
        MessageType.DDATA,
        _NODE_ID,
        _EDGE_NODE_ID,
        "humidity-pressure-and-temperature",
    ),
    model=EnvironmentBME280,
    publisher=_NODE_ID,
    qos=0,
    retain=False,
    interval_ms=10_000,  # 10 s
    description=(
        "BME280 combined reading: temperature, humidity, pressure."
        " Published every 10 s. "
        "Consumers check status before acting on measurement fields."
    ),
)

LightTopic = NodeTopic(
    address=sparkplug_topic(
        MessageType.DDATA, _NODE_ID, _EDGE_NODE_ID, "ambient-light"
    ),
    model=EnvironmentLight,
    publisher=_NODE_ID,
    qos=0,
    retain=False,
    interval_ms=10_000,  # 10 s
    description=(
        "BH1750 ambient light intensity in lux. Published every 10 s. "
        "Consumers check status before acting on light_lux."
    ),
)

BirthTopic = NodeTopic(
    address=sparkplug_topic(MessageType.NBIRTH, _NODE_ID, _EDGE_NODE_ID),
    model=EnvironmentBME280,
    publisher=_NODE_ID,
    qos=1,
    retain=False,
    description=(
        "P03 birth certificate. Published on connect. Subscribers: P05, P06, P08, P10."
    ),
)

DeathTopic = NodeTopic(
    address=sparkplug_topic(MessageType.NDEATH, _NODE_ID, _EDGE_NODE_ID),
    model=SparkplugPayload,
    publisher="broker",  # LWT  -  broker publishes on behalf of p03
    qos=1,
    retain=False,
    description=(
        "P03 death notice (LWT). Published by broker on unexpected disconnect. "
        "P05 and P08 MUST handle missing environmental readings gracefully."
    ),
)

# ---------------------------------------------------------------------------
# Node definition  -  auto-discovered by registry.py
# ---------------------------------------------------------------------------

NODE = NodeDefinition(
    node_id=_NODE_ID,
    label="P03  -  Environmental Sensing",
    publishes=[BME280Topic, LightTopic, BirthTopic, DeathTopic],
)
