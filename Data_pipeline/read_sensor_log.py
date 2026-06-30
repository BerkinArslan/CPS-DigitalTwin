import csv
import os
from datetime import datetime, timezone

# =============================================================================
# SENSOR LOG READER
# Reads sensor_log.csv and lets you retrieve data by time period and field.
# Run with: python read_sensor_log.py
# =============================================================================

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensor_log.csv")


def load_log():
    """
    Reads the entire CSV into a list of dicts.
    Each row becomes: {"timestamp_unix": float, "timestamp_utc": str, "field": str, "value": float}
    """
    if not os.path.exists(LOG_FILE):
        print("[Reader] No sensor_log.csv found. Run run_pipeline.py first.")
        return []

    rows = []
    with open(LOG_FILE, "r") as f:
        reader = csv.DictReader(f)  # DictReader uses the header row as keys automatically
        for row in reader:
            rows.append({
                "timestamp_unix": float(row["timestamp_unix"]),
                "timestamp_utc":  row["timestamp_utc"],
                "field":          row["field"],
                "value":          float(row["value"]),
            })
    return rows


def get_by_time(rows, start_utc: str, end_utc: str):
    """
    Returns all rows between start_utc and end_utc.
    Time format: "2026-06-26T17:00:00Z"

    Example:
        rows = load_log()
        window = get_by_time(rows, "2026-06-26T17:00:00Z", "2026-06-26T17:30:00Z")
    """
    # Convert the UTC strings to unix timestamps for easy comparison
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    start_ts = datetime.strptime(start_utc, fmt).replace(tzinfo=timezone.utc).timestamp()
    end_ts   = datetime.strptime(end_utc,   fmt).replace(tzinfo=timezone.utc).timestamp()

    result = []
    for row in rows:
        if start_ts <= row["timestamp_unix"] <= end_ts:
            result.append(row)

    if not result:
        print(f"[Reader] No data found between {start_utc} and {end_utc}.")
    return result


def get_field(rows, field_name: str):
    """
    Returns only the rows for one specific field.

    Example:
        temps = get_field(rows, "temperature_c")
    """
    return [row for row in rows if row["field"] == field_name]


def get_values(rows, field_name: str):
    """
    Returns just the numeric values for a field as a plain list.
    Useful for computing mean, std, min, max directly.

    Example:
        values = get_values(rows, "temperature_c")
        print(sum(values) / len(values))  # manual average
    """
    return [row["value"] for row in rows if row["field"] == field_name]


def summary(rows, field_name: str):
    """
    Prints a quick statistical summary for one field over the given rows.
    Works on any numeric field: temperature_c, humidity_rel, calibrated, etc.

    Example:
        summary(rows, "calibrated")
    """
    values = get_values(rows, field_name)
    if not values:
        print(f"[Reader] No data for field '{field_name}'.")
        return

    avg    = sum(values) / len(values)
    minval = min(values)
    maxval = max(values)

    # Standard deviation: measure of how spread out the values are.
    # A low std means readings were stable. A high std means lots of variation.
    variance = sum((v - avg) ** 2 for v in values) / len(values)
    std      = variance ** 0.5  # square root of variance

    print(f"  Field:   {field_name}")
    print(f"  Count:   {len(values)} readings")
    print(f"  Mean:    {avg:.4f}")
    print(f"  Min:     {minval:.4f}")
    print(f"  Max:     {maxval:.4f}")
    print(f"  Std dev: {std:.4f}")


# =============================================================================
# EXAMPLE USAGE -- runs when you execute this file directly
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  SENSOR LOG READER")
    print("=" * 60)

    # Step 1: load everything from the CSV
    all_rows = load_log()
    print(f"\n[Reader] Total rows loaded: {len(all_rows)}")

    if not all_rows:
        exit()

    # Show the time range available in the log
    first = all_rows[0]["timestamp_utc"]
    last  = all_rows[-1]["timestamp_utc"]
    print(f"[Reader] Data from {first} to {last}")

    # -------------------------------------------------------------------------
    # Example 1: get all data from a specific time window
    # We use the first and last timestamp from the log so this always works.
    # -------------------------------------------------------------------------
    print(f"\n--- Example 1: All data between {first} and {last} ---")
    window = get_by_time(all_rows, first, last)
    print(f"  Rows in window: {len(window)}")

    # -------------------------------------------------------------------------
    # Example 2: get only temperature readings from that window
    # -------------------------------------------------------------------------
    print("\n--- Example 2: Temperature readings from that window ---")
    temps = get_field(window, "temperature_c")
    for row in temps[:5]:  # show first 5 to avoid flooding the terminal
        print(f"  {row['timestamp_utc']}  temperature_c = {row['value']}")
    if len(temps) > 5:
        print(f"  ... and {len(temps) - 5} more")

    # -------------------------------------------------------------------------
    # Example 3: get just the numeric values for math
    # -------------------------------------------------------------------------
    print("\n--- Example 3: Raw values list for temperature_c ---")
    values = get_values(window, "temperature_c")
    print(f"  Values: {values[:10]}")  # first 10

    # -------------------------------------------------------------------------
    # Example 4: statistical summary per field
    # -------------------------------------------------------------------------
    print("\n--- Example 4: Summary for each field in the window ---")
    fields_in_window = set(row["field"] for row in window)
    for field in sorted(fields_in_window):
        summary(window, field)
        print()

    print("=" * 60 + "\n")
