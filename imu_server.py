"""
MPU-9250 IMU Data Receiver — Flask Server
==========================================
Receives HTTP POST JSON from ESP32 at /imu
Stores data in-memory and logs to CSV file.

Install dependencies:
    pip install flask

Run:
    python imu_server.py

The server listens on 0.0.0.0:5000 — make sure your PC firewall
allows inbound TCP on port 5000, and that the ESP32 and this PC
are on the same WiFi network.
"""

from flask import Flask, request, jsonify
import csv
import os
from datetime import datetime

app = Flask(__name__)

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────
HOST        = "0.0.0.0"   # Accept connections from any device on the network
PORT        = 5000
CSV_FILE    = "imu_data.csv"
MAX_RECORDS = 10000        # Max records kept in memory

# ─────────────────────────────────────────────
#  In-memory store (for live monitoring via /data)
# ─────────────────────────────────────────────
records = []

# ─────────────────────────────────────────────
#  CSV Setup — write header if file is new
# ─────────────────────────────────────────────
CSV_HEADERS = [
    "server_time", "device_timestamp_ms",
    "accel_x", "accel_y", "accel_z",
    "gyro_x",  "gyro_y",  "gyro_z",
    "mag_x",   "mag_y",   "mag_z",
    "temp_c"
]

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
        print(f"[CSV] Created {CSV_FILE}")
    else:
        print(f"[CSV] Appending to existing {CSV_FILE}")

def append_csv(row: dict):
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow(row)

# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────

@app.route("/imu", methods=["POST"])
def receive_imu():
    """Main endpoint — receives JSON from ESP32."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Invalid JSON body"}), 400

    # Parse fields (gracefully handle missing optional fields)
    accel = data.get("accel", {})
    gyro  = data.get("gyro",  {})
    mag   = data.get("mag",   {})

    row = {
        "server_time":          datetime.now().isoformat(timespec="milliseconds"),
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

    # Save to CSV
    append_csv(row)

    # Keep in memory (circular buffer)
    records.append(row)
    if len(records) > MAX_RECORDS:
        records.pop(0)

    # Console log
    print(
        f"[{row['server_time']}]  "
        f"Accel({row['accel_x']:.3f}, {row['accel_y']:.3f}, {row['accel_z']:.3f})  "
        f"Gyro({row['gyro_x']:.3f}, {row['gyro_y']:.3f}, {row['gyro_z']:.3f})"
        + (f"  Temp: {row['temp_c']:.1f}°C" if row['temp_c'] != "" else ""),
        flush=True
    )

    return jsonify({"status": "ok", "records_stored": len(records)}), 200


@app.route("/data", methods=["GET"])
def get_data():
    """Returns the last N records as JSON. Usage: GET /data?n=100"""
    n = min(int(request.args.get("n", 50)), MAX_RECORDS)
    return jsonify(records[-n:]), 200


@app.route("/status", methods=["GET"])
def status():
    """Health check endpoint."""
    return jsonify({
        "status":        "running",
        "records_in_memory": len(records),
        "csv_file":      CSV_FILE,
        "server_time":   datetime.now().isoformat()
    }), 200


@app.route("/clear", methods=["POST"])
def clear():
    """Clears the in-memory buffer (CSV is preserved)."""
    records.clear()
    return jsonify({"status": "cleared"}), 200


# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_csv()
    print(f"\n{'='*50}")
    print(f"  IMU Server starting on http://{HOST}:{PORT}")
    print(f"  POST endpoint : http://<your-ip>:{PORT}/imu")
    print(f"  View data     : http://localhost:{PORT}/data?n=50")
    print(f"  Health check  : http://localhost:{PORT}/status")
    print(f"  CSV output    : {os.path.abspath(CSV_FILE)}")
    print(f"{'='*50}\n")
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)