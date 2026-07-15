"""
DOCUMENT STATUS: NOT REVIEWED AT 13.05.2026

P15 - Digital twin.

Domain model and Sparkplug B wire descriptors for the model node.

Published topics (see PredictionTopic, BirthTopic, DeathTopic below):
  cps/p15/NDATA/digital-twin-main   -  ET model output  (not retained, QoS 0)
  cps/p15/NBIRTH/digital-twin-main  -  on connect  (not retained, QoS 1)
  cps/p15/NDEATH/digital-twin-main  -  LWT         (not retained, QoS 1)

Subscribes to:
  cps/p01/DDATA/sensor-main/soil_moisture
  cps/p02/DDATA/actuator-main/pump
  cps/p03/DDATA/sensor-main/temperature
  cps/p03/DDATA/sensor-main/humidity
  cps/p03/DDATA/sensor-main/light
  cps/p05/DDATA/controller-main/controller

Consumers: P08 (Anomaly Detection), P06 (logging), P13 (web app)
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from . import p01, p02, p03, p05
from .core import (
    DataType,
    MessageType,
    NodeDefinition,
    NodeTopic,
    SparkplugNodeModel,
    SparkplugPayload,
    sparkplug_topic,
)

_NODE_ID = "p15"  # internal  -  embedded in topic addresses below
_EDGE_NODE_ID = "digital-twin-main"


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


class SoilWaterBalanceBucketModel(SparkplugNodeModel):
    """
    Evapotranspiration output: Penman-Monteith model inputs and computed ET.

    Published by P15 (Digital Twin) via the NDATA/digital-twin-main topic.
    Consumers: P08 (Anomaly Detection), P06 (logging), P13 (web app).
    """

    # Metric name constants  -  import from this class in subscriber code:
    #   from schema.p15 import SoilWaterBalanceBucketModel
    #   if metric.name == SoilWaterBalanceBucketModel.METRIC_CROP_COEFFICIENT: ...
    METRIC_CROP_COEFFICIENT: ClassVar[str] = "crop_coefficient"
    METRIC_DELTA: ClassVar[str] = "delta"
    METRIC_R_N: ClassVar[str] = "R_n"
    METRIC_G: ClassVar[str] = "G"
    METRIC_GAMMA: ClassVar[str] = "gamma"
    METRIC_T: ClassVar[str] = "T"
    METRIC_U_2: ClassVar[str] = "u_2"
    METRIC_E_S: ClassVar[str] = "e_s"
    METRIC_E_A: ClassVar[str] = "e_a"
    METRIC_REFERENCE_EVAPOTRANSPIRATION: ClassVar[str] = "reference_evapotranspiration"
    crop_coefficient: float = Field(
        ge=0.0,
        le=1.5,
        description=(
            "Crop coefficient (unitless). Dependent on plant type and growth stage."
        ),
        json_schema_extra={
            "metric_name": "crop_coefficient",
            "datatype": DataType.FLOAT,
        },
    )
    delta: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Slope of the saturation vapor pressure curve at air temperature "
            "(kPa/\u00b0C). Represents sensitivity of vapor pressure to temperature."
        ),
        json_schema_extra={
            "metric_name": "delta",
            "datatype": DataType.FLOAT,
        },
    )
    R_n: float = Field(
        ge=0.0,
        le=40.0,
        description=(
            "Net radiation at the crop surface (MJ/m\u00b2/day). "
            "Available energy for evapotranspiration."
        ),
        json_schema_extra={
            "metric_name": "R_n",
            "datatype": DataType.FLOAT,
        },
    )
    G: float = Field(
        ge=-5.0,
        le=5.0,
        description=(
            "Soil heat flux density (MJ/m\u00b2/day). "
            "Energy exchanged with the soil; often near zero on a daily scale."
        ),
        json_schema_extra={
            "metric_name": "G",
            "datatype": DataType.FLOAT,
        },
    )
    gamma: float = Field(
        ge=0.04,
        le=0.1,
        description=(
            "Psychrometric constant (kPa/\u00b0C). "
            "Relates air temperature and humidity to evaporation processes."
        ),
        json_schema_extra={
            "metric_name": "gamma",
            "datatype": DataType.FLOAT,
        },
    )
    T: float = Field(
        ge=-30.0,
        le=60.0,
        description=(
            "Air temperature at 2 m height (\u00b0C). Influences evaporation rate."
        ),
        json_schema_extra={
            "metric_name": "T",
            "datatype": DataType.FLOAT,
        },
    )
    u_2: float = Field(
        ge=0.0,
        le=20.0,
        description=(
            "Wind speed at 2 m above ground (m/s). "
            "Affects vapor transport away from the surface."
        ),
        json_schema_extra={
            "metric_name": "u_2",
            "datatype": DataType.FLOAT,
        },
    )
    e_s: float = Field(
        ge=0.0,
        le=10.0,
        description=(
            "Saturation vapor pressure (kPa). "
            "Maximum moisture content of air at a given temperature."
        ),
        json_schema_extra={
            "metric_name": "e_s",
            "datatype": DataType.FLOAT,
        },
    )
    e_a: float = Field(
        ge=0.0,
        le=10.0,
        description="Actual vapor pressure (kPa). Current moisture content of the air.",
        json_schema_extra={
            "metric_name": "e_a",
            "datatype": DataType.FLOAT,
        },
    )
    reference_evapotranspiration: float = Field(
        ge=0.0,
        le=25.0,
        description=(
            "Reference evapotranspiration (mm/day). "
            "Computed via the Penman-Monteith equation."
        ),
        json_schema_extra={
            "metric_name": "reference_evapotranspiration",
            "datatype": DataType.FLOAT,
        },
    )


# ---------------------------------------------------------------------------
# Topics published by this node.
# Import these in subscriber code  -  never hardcode topic strings.
#
# Usage (subscriber):
#   import schema.p15 as P15
#   client.subscribe(P15.PredictionTopic.address, qos=P15.PredictionTopic.qos)
#   reading = P15.SoilWaterBalanceBucketModel.from_ndata(decoded_payload)
# ---------------------------------------------------------------------------

PredictionTopic = NodeTopic(
    address=sparkplug_topic(MessageType.NDATA, _NODE_ID, _EDGE_NODE_ID),
    model=SoilWaterBalanceBucketModel,
    publisher=_NODE_ID,
    qos=0,
    retain=False,
    description=(
        "P15 Digital Twin ET output: Penman-Monteith model inputs and computed "
        "reference evapotranspiration. "
        "Consumers: P08 (Anomaly Detection), P06 (logging), P13 (web app)."
    ),
)

BirthTopic = NodeTopic(
    address=sparkplug_topic(MessageType.NBIRTH, _NODE_ID, _EDGE_NODE_ID),
    model=SoilWaterBalanceBucketModel,
    publisher=_NODE_ID,
    qos=1,
    retain=False,
    description="P15 birth certificate. Published on connect. Declares metric schema.",
)

DeathTopic = NodeTopic(
    address=sparkplug_topic(MessageType.NDEATH, _NODE_ID, _EDGE_NODE_ID),
    model=SparkplugPayload,
    publisher="broker",
    qos=1,
    retain=False,
    description=(
        "P15 death notice (LWT). Auto-published by broker on unexpected disconnect. "
        "P08 should treat this as twin dropout and fall back to statistical "
        "methods only."
    ),
)

# ---------------------------------------------------------------------------
# Node definition  -  auto-discovered by registry.py
# ---------------------------------------------------------------------------

NODE = NodeDefinition(
    node_id=_NODE_ID,
    label="P15  -  Digital Twin",
    publishes=[PredictionTopic, BirthTopic, DeathTopic],
    subscribes_to=[
        p01.SoilReadingTopic,
        p02.PumpStateTopic,
        p03.BME280Topic,
        p03.LightTopic,
        p05.ControllerStateTopic,
        p01.DeathTopic,
        p02.DeathTopic,
    ],
)
