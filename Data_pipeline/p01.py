"""
DOCUMENT STATUS: NOT REVIEWED AT 13.05.2026

P01 - Soil moisture sensing and calibration.

Domain model and Sparkplug B wire descriptors for the P01 group.

Published topics (see SoilReadingTopic, BirthTopic, DeathTopic below):
  cps/p01/DDATA/sensor-main/soil_moisture  -  sensor readings  (not retained, QoS 0)
  cps/p01/NBIRTH/sensor-main               -  on connect       (retained, QoS 1)
  cps/p01/NDEATH/sensor-main               -  LWT              (retained, QoS 1)

Consumers: P05 (controller), P06 (logging), P08 (anomaly detection),
P15 (digital twin), P16 (plant health)
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

_NODE_ID = "p01"  # internal  -  embedded in topic addresses below
_EDGE_NODE_ID = "sensor-main"


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


class SoilMoistureReading(SparkplugNodeModel):
    """
    Calibrated soil moisture reading from a resisitive sensor.

    Consumers check ``status`` first; act on ``calibrated`` only when
    ``status == SensorStatus.OK``. ``raw_adc`` is always present and
    is used by P08 for drift detection and error diagnosis.
    """

    # Metric name constants  -  import from this class in subscriber code:
    #   from schema.p01 import SoilMoistureReading
    #   if metric.name == SoilMoistureReading.METRIC_STATUS: ...
    METRIC_CALIBRATED: ClassVar[str] = "soil_moisture/calibrated"
    METRIC_RAW_ADC: ClassVar[str] = "soil_moisture/raw_adc"
    METRIC_STATUS: ClassVar[str] = "soil_moisture/status"
    calibrated: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Calibrated moisture fraction "
            "(0.0 = completely dry, 1.0 = fully saturated). "
            "Null on the wire when status != ok  -  consumers MUST check status first. "
            "Calibration references: air-dry soil -> ADC saturated high; "
            "submerged in water -> ADC at minimum. "
            "Consumers: P05 (threshold decisions), P08 (long-term drift detection)."
        ),
        json_schema_extra={
            "metric_name": METRIC_CALIBRATED,
            "datatype": DataType.FLOAT,
            "null_when_error": True,
        },
    )
    raw_adc: int | None = Field(
        default=None,
        ge=0,
        le=65535,
        description=(
            "Raw ADC reading before calibration (0-65535). "
            "Always published regardless of status  -  P08 uses this to detect "
            "calibration drift over time and to diagnose error causes "
            "(e.g. ADC at rail = sensor disconnected)."
        ),
        json_schema_extra={
            "metric_name": METRIC_RAW_ADC,
            "datatype": DataType.INT32,
        },
    )
    status: SensorStatus = Field(
        default=SensorStatus.OK,
        description=(
            "Quality / validity flag. Always present, even when calibrated is null. "
            "'ok' -> calibrated is valid. Any other value -> calibrated is None. "
            "Consumers MUST check this before acting on calibrated."
        ),
        json_schema_extra={"metric_name": METRIC_STATUS, "datatype": DataType.STRING},
    )


# ---------------------------------------------------------------------------
# Topics published by this node.
# Import these in subscriber code  -  never hardcode topic strings.
#
# Usage (subscriber):
#   import schema.p01 as P01
#   client.subscribe(P01.SoilReadingTopic.address, qos=P01.SoilReadingTopic.qos)
#   reading = P01.SoilMoistureReading.from_data(decoded_payload)
# ---------------------------------------------------------------------------

SoilReadingTopic = NodeTopic(
    address=sparkplug_topic(
        MessageType.DDATA, _NODE_ID, _EDGE_NODE_ID, "soil_moisture"
    ),
    model=SoilMoistureReading,
    publisher=_NODE_ID,
    qos=0,
    retain=False,
    interval_ms=5_000,  # 5 s fixed interval  -  agreed with P04
    description=(
        "Calibrated soil moisture readings. "
        "Published at a fixed interval regardless of value change. "
        "Consumers MUST check the 'status' field before acting on 'calibrated'."
    ),
)

BirthTopic = NodeTopic(
    address=sparkplug_topic(MessageType.NBIRTH, _NODE_ID, _EDGE_NODE_ID),
    model=SoilMoistureReading,
    publisher=_NODE_ID,
    qos=1,
    retain=False,
    description="P01 birth certificate. Published on connect. Declares metric schema.",
)

DeathTopic = NodeTopic(
    address=sparkplug_topic(MessageType.NDEATH, _NODE_ID, _EDGE_NODE_ID),
    model=SparkplugPayload,
    publisher="broker",  # LWT  -  broker publishes on behalf of p01
    qos=1,
    retain=False,
    description=(
        "P01 death notice (LWT). Auto-published by broker on unexpected disconnect. "
        "P05 MUST treat this as a sensor dropout and transition to"
        " 'error' or 'suppressed'."
    ),
)

# ---------------------------------------------------------------------------
# Node definition  -  auto-discovered by registry.py
# ---------------------------------------------------------------------------

NODE = NodeDefinition(
    node_id=_NODE_ID,
    label="P01  -  Soil Moisture Sensing",
    publishes=[SoilReadingTopic, BirthTopic, DeathTopic],
)
