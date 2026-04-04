"""
MPU-9250 Dual IMU Data Receiver — Flask Server
================================================
Receives HTTP POST JSON from two ESP32 nodes at /imu
Each sensor is identified by sensor_id in the payload.
Saves separate CSV files per sensor + combined CSV.

Install:
    pip install flask

Run:
    python imu_server.py
"""

from flask import Flask, request, jsonify
import csv
import os
from datetime import datetime

app = Flask(__name__)

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────
HOST            = "0.0.0.0"
COMBINED_CSV    = "imu_data_all.csv"
MAX_RECORDS     = 10000

# ─────────────────────────────────────────────
#  CSV Headers
# ─────────────────────────────────────────────
CSV_HEADERS = [
    "server_time", "sensor_id", "label", "device_timestamp_ms",
    "accel_x", "accel_y", "accel_z",
    "gyro_x",  "gyro_y",  "gyro_z",
    "mag_x",   "mag_y",   "mag_z",
    "temp_c"
]

# ─────────────────────────────────────────────
#  In-memory store — per sensor + combined
# ─────────────────────────────────────────────
records = {
    "all": []
}

# ─────────────────────────────────────────────
#  CSV Helpers
# ─────────────────────────────────────────────
def init_csv(filepath):
    if not os.path.exists(filepath):
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
        print(f"[CSV] Created {filepath}")
    else:
        print(f"[CSV] Appending to existing {filepath}")

def append_csv(filepath, row):
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow(row)

def get_sensor_csv(sensor_id):
    return f"imu_data_{sensor_id}.csv"

# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────

@app.route("/imu", methods=["POST"])
def receive_imu():
    """Main endpoint — receives JSON from any ESP32 sensor."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    sensor_id = data.get("sensor_id", "unknown")
    label     = data.get("label", "")
    accel     = data.get("accel", {})
    gyro      = data.get("gyro",  {})
    mag       = data.get("mag",   {})

    row = {
        "server_time":          datetime.now().isoformat(timespec="milliseconds"),
        "sensor_id":            sensor_id,
        "label":                label,
        "device_timestamp_ms":  data.get("timestamp", ""),
        "accel_x":              accel.get("x", ""),
        "accel_y":              accel.get("y", ""),
        "accel_z":              accel.get("z", ""),
        "gyro_x":               gyro.get("x",  ""),
        "gyro_y":               gyro.get("y",  ""),
        "gyro_z":               gyro.get("z",  ""),
        "mag_x":                mag.get("x",   ""),
        "mag_y":                mag.get("y",   ""),
        "mag_z":                mag.get("z",   ""),
        "temp_c":               data.get("temp", ""),
    }

    # Save to per-sensor CSV
    sensor_csv = get_sensor_csv(sensor_id)
    if not os.path.exists(sensor_csv):
        init_csv(sensor_csv)
    append_csv(sensor_csv, row)

    # Save to combined CSV
    append_csv(COMBINED_CSV, row)

    # Store in memory — per sensor bucket + combined
    if sensor_id not in records:
        records[sensor_id] = []
    records[sensor_id].append(row)
    records["all"].append(row)

    # Trim memory buffers
    for key in records:
        if len(records[key]) > MAX_RECORDS:
            records[key].pop(0)

    # Console log
    temp_str = f"  Temp: {row['temp_c']:.1f}C" if row['temp_c'] != "" else ""
    print(
        f"[{row['server_time']}] [{sensor_id}/{label}]  "
        f"Accel({row['accel_x']:.3f}, {row['accel_y']:.3f}, {row['accel_z']:.3f})  "
        f"Gyro({row['gyro_x']:.3f}, {row['gyro_y']:.3f}, {row['gyro_z']:.3f})"
        f"{temp_str}",
        flush=True
    )

    return jsonify({
        "status": "ok",
        "sensor_id": sensor_id,
        "records_stored": len(records.get(sensor_id, []))
    }), 200


@app.route("/data", methods=["GET"])
def get_data():
    """Returns last N records from all sensors or a specific sensor.
    Usage: GET /data?n=100
           GET /data?n=100&sensor=sensor_1
    """
    n          = min(int(request.args.get("n", 50)), MAX_RECORDS)
    sensor_key = request.args.get("sensor", "all")

    if sensor_key not in records:
        return jsonify({"error": f"Unknown sensor: {sensor_key}. Available: {list(records.keys())}"}), 404

    return jsonify(records[sensor_key][-n:]), 200


@app.route("/status", methods=["GET"])
def status():
    """Health check — shows record counts per sensor."""
    sensor_counts = {k: len(v) for k, v in records.items()}
    return jsonify({
        "status":        "running",
        "sensors_seen":  [k for k in records.keys() if k != "all"],
        "record_counts": sensor_counts,
        "combined_csv":  COMBINED_CSV,
        "server_time":   datetime.now().isoformat()
    }), 200


@app.route("/clear", methods=["POST"])
def clear():
    """Clears in-memory buffer for all or a specific sensor."""
    sensor_key = request.args.get("sensor", None)
    if sensor_key:
        if sensor_key in records:
            records[sensor_key].clear()
            return jsonify({"status": f"cleared {sensor_key}"}), 200
        return jsonify({"error": "sensor not found"}), 404
    for key in records:
        records[key].clear()
    return jsonify({"status": "all cleared"}), 200


# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_csv(COMBINED_CSV)
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*55}")
    print(f"  Dual IMU Server starting on http://0.0.0.0:{port}")
    print(f"  POST endpoint  : http://<your-ip>:{port}/imu")
    print(f"  All data       : http://localhost:{port}/data?n=50")
    print(f"  Sensor 1 data  : http://localhost:{port}/data?n=50&sensor=sensor_1")
    print(f"  Sensor 2 data  : http://localhost:{port}/data?n=50&sensor=sensor_2")
    print(f"  Health check   : http://localhost:{port}/status")
    print(f"  Combined CSV   : {os.path.abspath(COMBINED_CSV)}")
    print(f"{'='*55}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
