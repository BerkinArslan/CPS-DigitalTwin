# HardCalibration — Usage Guide

Finds the microclimate coefficient **K_mc** by fitting observed soil moisture drops against the model's predicted drops using OLS regression (no intercept).

Formula:
```
ΔSM_actual = K_mc × (K_c × ET_0 × Δt)
```

---

## Quick Start

```python
from hard_calibration import HardCalibration

cal = HardCalibration(K_c=0.85, batch_size=10)
```

| Parameter   | Type    | Description                                              |
|-------------|---------|----------------------------------------------------------|
| `K_c`       | `float` | Crop coefficient — fixed per plant species               |
| `batch_size`| `int`   | Number of samples to collect before running calibration  |

---

## Methods

### `on_status_event(status: str)`

Call this when a status message arrives (NINFO, Group 08, web app).

**What it does:**
- Checks if `status` is a known hard calibration trigger
- If yes: clears the buffer (discards pre-event data) and arms the calibration gate

**Hard calibration triggers:**
```
"new_sensor"
"sensor_position_changed"
"flower_pot_location_changed"
"system_rebooted"
"drift_resolved"
```

**Returns:** nothing

---

### `add_sample(timestamp: float, SM: float, ET_0: float)`

Call this every time a new soil moisture reading arrives.

| Parameter   | Type    | Description                                        |
|-------------|---------|----------------------------------------------------|
| `timestamp` | `float` | Unix timestamp of the reading (seconds)            |
| `SM`        | `float` | Soil moisture value from sensor P01                |
| `ET_0`      | `float` | Reference evapotranspiration from OpenMeteo        |

**What it does:**
- Always appends the sample to the circular buffer (oldest entry dropped automatically when full)
- If the gate is armed AND buffer is full → runs OLS regression → returns `K_mc`
- Otherwise → returns `None`

**Returns:** `float` (K_mc) if calibration ran, `None` otherwise

---

### `least_square_fit()` *(called internally)*

Runs OLS regression on the buffer. You do not need to call this yourself — `add_sample` calls it automatically.

**Returns:** `float` (K_mc)

---

## What to Store

| Data         | Where      | Why                                                  |
|--------------|------------|------------------------------------------------------|
| `K_mc`       | JSON / config file | Persist across restarts                    |
| Buffer data  | RAM only   | Only post-event data matters; discard on next event  |

---

## Full Example

```python
import time
from hard_calibration import HardCalibration

cal = HardCalibration(K_c=0.85, batch_size=10)

# A new sensor was installed — arm the gate
cal.on_status_event("new_sensor")

# Sensor data arrives after the event
for i in range(10):
    K_mc = cal.add_sample(
        timestamp=time.time() + i * 3600,  # hourly samples
        SM=45.0 - i * 0.8,                 # soil moisture slowly decreasing
        ET_0=3.2                            # from OpenMeteo
    )
    if K_mc is not None:
        print(f"Calibration complete! K_mc = {K_mc:.4f}")
        # use cal.K_mc internally in your ET model from here
```

---

## Order Matters

`on_status_event` **must come before** `add_sample` data for that K_mc to be valid.

```
status event → buffer cleared → gate armed
     ↓
add_sample × N → buffer fills → OLS runs → K_mc returned
     ↓
gate disarmed → waiting for next status event
```

If data arrives before any status event, it is stored in the buffer but **calibration will not run** (gate is still closed). This is intentional — we only want K_mc from confirmed post-event data.

---


## What K_mc Is Used For

Once calibrated, plug K_mc into the ET model:

```
ET_crop = K_mc × K_c × ET_0
```

This gives the actual crop evapotranspiration on your specific balcony, correcting for local microclimate (wind, shading, humidity) that the generic ET_0 does not capture.
