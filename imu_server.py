"""
MPU-9250 Dual IMU Server — Flask + SQLite + Live Dashboard
===========================================================
- Receives HTTP POST JSON from two ESP32 nodes at /imu
- Stores data in SQLite database
- Serves a live browser dashboard at /dashboard
- Auto-refreshes plots every 2 seconds via SSE

Install:
    pip install flask

Run:
    python imu_server.py
"""

from flask import Flask, request, jsonify, Response, render_template_string
import sqlite3
import os
import json
import time
from datetime import datetime

app = Flask(__name__)

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────
DB_FILE      = "imu_data.db"
MAX_PLOT_PTS = 200   # points shown on live chart per sensor

# ─────────────────────────────────────────────
#  Database Setup
# ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS imu_readings (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                server_time       TEXT NOT NULL,
                sensor_id         TEXT NOT NULL,
                label             TEXT,
                device_ts_ms      INTEGER,
                accel_x           REAL, accel_y REAL, accel_z REAL,
                gyro_x            REAL, gyro_y  REAL, gyro_z  REAL,
                mag_x             REAL, mag_y   REAL, mag_z   REAL,
                temp_c            REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sensor ON imu_readings(sensor_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time   ON imu_readings(server_time)")
        conn.commit()
    print(f"[DB] SQLite ready: {os.path.abspath(DB_FILE)}")

# ─────────────────────────────────────────────
#  Dashboard HTML
# ─────────────────────────────────────────────
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IMU Live Dashboard</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f1117; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; }
  header { background: #1a1d2e; padding: 16px 24px; border-bottom: 1px solid #2a2d3e;
           display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 1.3rem; color: #7eb8f7; }
  #status-bar { font-size: 0.8rem; color: #888; }
  #status-bar span { color: #4caf50; font-weight: bold; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 16px; }
  .card { background: #1a1d2e; border-radius: 10px; padding: 14px;
          border: 1px solid #2a2d3e; }
  .card h2 { font-size: 0.85rem; color: #888; margin-bottom: 8px;
             text-transform: uppercase; letter-spacing: 1px; }
  .plot { width: 100%; height: 220px; }
  #stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
           padding: 0 16px 16px; }
  .stat { background: #1a1d2e; border-radius: 8px; padding: 12px;
          border: 1px solid #2a2d3e; text-align: center; }
  .stat .val { font-size: 1.4rem; font-weight: bold; color: #7eb8f7; }
  .stat .lbl { font-size: 0.72rem; color: #666; margin-top: 4px; }
  @media(max-width:768px){ .grid{grid-template-columns:1fr;} #stats{grid-template-columns:repeat(2,1fr);} }
</style>
</head>
<body>
<header>
  <h1>🛰️ IMU Live Dashboard — Dual Sensor</h1>
  <div id="status-bar">Status: <span id="conn-status">Connecting...</span> &nbsp;|&nbsp; Last update: <span id="last-update">—</span></div>
</header>

<div id="stats">
  <div class="stat"><div class="val" id="s1-count">—</div><div class="lbl">Sensor 1 Records</div></div>
  <div class="stat"><div class="val" id="s2-count">—</div><div class="lbl">Sensor 2 Records</div></div>
  <div class="stat"><div class="val" id="s1-temp">—</div><div class="lbl">Sensor 1 Temp (°C)</div></div>
  <div class="stat"><div class="val" id="s2-temp">—</div><div class="lbl">Sensor 2 Temp (°C)</div></div>
</div>

<div class="grid">
  <div class="card"><h2>Accelerometer — Sensor 1 (Left)</h2><div id="accel1" class="plot"></div></div>
  <div class="card"><h2>Accelerometer — Sensor 2 (Right)</h2><div id="accel2" class="plot"></div></div>
  <div class="card"><h2>Gyroscope — Sensor 1 (Left)</h2><div id="gyro1" class="plot"></div></div>
  <div class="card"><h2>Gyroscope — Sensor 2 (Right)</h2><div id="gyro2" class="plot"></div></div>
  <div class="card"><h2>Magnetometer — Sensor 1 (Left)</h2><div id="mag1" class="plot"></div></div>
  <div class="card"><h2>Magnetometer — Sensor 2 (Right)</h2><div id="mag2" class="plot"></div></div>
  <div class="card"><h2>Temperature — Both Sensors</h2><div id="temp" class="plot"></div></div>
</div>

<script>
const SENSORS = ['sensor_1', 'sensor_2'];
const N = 200;
const layout = (ylabel) => ({
  paper_bgcolor:'transparent', plot_bgcolor:'transparent',
  font:{color:'#aaa', size:10},
  margin:{l:40,r:10,t:10,b:30},
  xaxis:{showgrid:false, color:'#444'},
  yaxis:{gridcolor:'#2a2d3e', color:'#aaa', title:{text:ylabel,font:{size:10}}},
  legend:{orientation:'h', y:-0.2, font:{size:10}},
  hovermode:'x unified'
});
const cfg = {displayModeBar:false, responsive:true};

function emptyTrace(name, color) {
  return {x:[], y:[], name, line:{color, width:1.5}, type:'scatter', mode:'lines'};
}

// Init all plots
Plotly.newPlot('accel1', [emptyTrace('X','#ef5350'),emptyTrace('Y','#66bb6a'),emptyTrace('Z','#42a5f5')], layout('g'), cfg);
Plotly.newPlot('accel2', [emptyTrace('X','#ef5350'),emptyTrace('Y','#66bb6a'),emptyTrace('Z','#42a5f5')], layout('g'), cfg);
Plotly.newPlot('gyro1',  [emptyTrace('X','#ff7043'),emptyTrace('Y','#26c6da'),emptyTrace('Z','#ab47bc')], layout('dps'), cfg);
Plotly.newPlot('gyro2',  [emptyTrace('X','#ff7043'),emptyTrace('Y','#26c6da'),emptyTrace('Z','#ab47bc')], layout('dps'), cfg);
Plotly.newPlot('mag1',   [emptyTrace('X','#ffa726'),emptyTrace('Y','#ec407a'),emptyTrace('Z','#29b6f6')], layout('uT'), cfg);
Plotly.newPlot('mag2',   [emptyTrace('X','#ffa726'),emptyTrace('Y','#ec407a'),emptyTrace('Z','#29b6f6')], layout('uT'), cfg);
Plotly.newPlot('temp',   [emptyTrace('Sensor 1','#7eb8f7'),emptyTrace('Sensor 2','#f48fb1')], layout('°C'), cfg);

function updatePlot(divId, traceIdx, xs, ys) {
  Plotly.extendTraces(divId, {x:[xs], y:[ys]}, [traceIdx]);
  const el = document.getElementById(divId);
  const maxLen = N;
  if (el.data[traceIdx].x.length > maxLen) {
    const trim = el.data[traceIdx].x.length - maxLen;
    el.data[traceIdx].x.splice(0, trim);
    el.data[traceIdx].y.splice(0, trim);
    Plotly.redraw(divId);
  }
}

async function fetchAndUpdate() {
  try {
    const res  = await fetch('/api/latest?n=20');
    const data = await res.json();

    const s1 = (data.sensor_1 || []);
    const s2 = (data.sensor_2 || []);

    // Update stat cards
    const status = await (await fetch('/status')).json();
    document.getElementById('s1-count').textContent = status.record_counts?.sensor_1 ?? '—';
    document.getElementById('s2-count').textContent = status.record_counts?.sensor_2 ?? '—';
    if (s1.length) document.getElementById('s1-temp').textContent = parseFloat(s1[s1.length-1].temp_c).toFixed(1);
    if (s2.length) document.getElementById('s2-temp').textContent = parseFloat(s2[s2.length-1].temp_c).toFixed(1);

    // Sensor 1
    if (s1.length) {
      const ts = s1.map(r => r.server_time);
      updatePlot('accel1', 0, ts, s1.map(r=>r.accel_x));
      updatePlot('accel1', 1, ts, s1.map(r=>r.accel_y));
      updatePlot('accel1', 2, ts, s1.map(r=>r.accel_z));
      updatePlot('gyro1',  0, ts, s1.map(r=>r.gyro_x));
      updatePlot('gyro1',  1, ts, s1.map(r=>r.gyro_y));
      updatePlot('gyro1',  2, ts, s1.map(r=>r.gyro_z));
      updatePlot('mag1',   0, ts, s1.map(r=>r.mag_x));
      updatePlot('mag1',   1, ts, s1.map(r=>r.mag_y));
      updatePlot('mag1',   2, ts, s1.map(r=>r.mag_z));
      updatePlot('temp',   0, ts, s1.map(r=>r.temp_c));
    }

    // Sensor 2
    if (s2.length) {
      const ts = s2.map(r => r.server_time);
      updatePlot('accel2', 0, ts, s2.map(r=>r.accel_x));
      updatePlot('accel2', 1, ts, s2.map(r=>r.accel_y));
      updatePlot('accel2', 2, ts, s2.map(r=>r.accel_z));
      updatePlot('gyro2',  0, ts, s2.map(r=>r.gyro_x));
      updatePlot('gyro2',  1, ts, s2.map(r=>r.gyro_y));
      updatePlot('gyro2',  2, ts, s2.map(r=>r.gyro_z));
      updatePlot('mag2',   0, ts, s2.map(r=>r.mag_x));
      updatePlot('mag2',   1, ts, s2.map(r=>r.mag_y));
      updatePlot('mag2',   2, ts, s2.map(r=>r.mag_z));
      updatePlot('temp',   1, ts, s2.map(r=>r.temp_c));
    }

    document.getElementById('conn-status').textContent = 'Live';
    document.getElementById('conn-status').style.color = '#4caf50';
    document.getElementById('last-update').textContent = new Date().toLocaleTimeString();

  } catch(e) {
    document.getElementById('conn-status').textContent = 'Error';
    document.getElementById('conn-status').style.color = '#ef5350';
  }
}

fetchAndUpdate();
setInterval(fetchAndUpdate, 2000);
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────

@app.route("/imu", methods=["POST"])
def receive_imu():
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

    with get_db() as conn:
        conn.execute("""
            INSERT INTO imu_readings
              (server_time, sensor_id, label, device_ts_ms,
               accel_x, accel_y, accel_z,
               gyro_x,  gyro_y,  gyro_z,
               mag_x,   mag_y,   mag_z,  temp_c)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(timespec="milliseconds"),
            sensor_id, label, data.get("timestamp"),
            accel.get("x"), accel.get("y"), accel.get("z"),
            gyro.get("x"),  gyro.get("y"),  gyro.get("z"),
            mag.get("x"),   mag.get("y"),   mag.get("z"),
            data.get("temp")
        ))
        conn.commit()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{sensor_id}/{label}] "
          f"Accel({accel.get('x',0):.3f}, {accel.get('y',0):.3f}, {accel.get('z',0):.3f}) "
          f"Temp:{data.get('temp','—')}", flush=True)

    return jsonify({"status": "ok", "sensor_id": sensor_id}), 200


@app.route("/dashboard")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/latest")
def api_latest():
    """Returns last N rows per sensor as JSON for the dashboard."""
    n = min(int(request.args.get("n", 20)), 500)
    result = {}
    with get_db() as conn:
        for sid in ["sensor_1", "sensor_2"]:
            rows = conn.execute("""
                SELECT * FROM imu_readings
                WHERE sensor_id = ?
                ORDER BY id DESC LIMIT ?
            """, (sid, n)).fetchall()
            result[sid] = [dict(r) for r in reversed(rows)]
    return jsonify(result)


@app.route("/data")
def get_data():
    """Returns last N records, optionally filtered by sensor."""
    n          = min(int(request.args.get("n", 50)), 10000)
    sensor_key = request.args.get("sensor", None)
    with get_db() as conn:
        if sensor_key:
            rows = conn.execute("""
                SELECT * FROM imu_readings WHERE sensor_id=?
                ORDER BY id DESC LIMIT ?
            """, (sensor_key, n)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM imu_readings
                ORDER BY id DESC LIMIT ?
            """, (n,)).fetchall()
    return jsonify([dict(r) for r in reversed(rows)])


@app.route("/status")
def status():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM imu_readings").fetchone()[0]
        sensors = conn.execute(
            "SELECT sensor_id, COUNT(*) as cnt FROM imu_readings GROUP BY sensor_id"
        ).fetchall()
    counts = {row["sensor_id"]: row["cnt"] for row in sensors}
    return jsonify({
        "status":        "running",
        "sensors_seen":  list(counts.keys()),
        "record_counts": counts,
        "total_records": total,
        "database":      DB_FILE,
        "server_time":   datetime.now().isoformat()
    })


@app.route("/")
def index():
    return '<meta http-equiv="refresh" content="0;url=/dashboard">'


from flask import send_file

@app.route("/download/db")
def download_db():
    """Download the SQLite database file."""
    return send_file(DB_FILE, as_attachment=True, download_name="imu_data.db")

# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*55}")
    print(f"  Dual IMU Server  —  http://0.0.0.0:{port}")
    print(f"  Dashboard  : http://localhost:{port}/dashboard")
    print(f"  POST data  : http://localhost:{port}/imu")
    print(f"  API latest : http://localhost:{port}/api/latest?n=20")
    print(f"  Status     : http://localhost:{port}/status")
    print(f"  Database   : {os.path.abspath(DB_FILE)}")
    print(f"{'='*55}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
