import os
import json
from datetime import datetime, timezone
from flask import Flask, request, jsonify, Response
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base

APP_TITLE = "Telemetry Demo"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data.db")
API_KEY = os.environ.get("API_KEY")  # ตั้งค่าเพื่อบังคับตรวจ API key ในคำขอ

app = Flask(__name__)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

class DataPoint(Base):
    __tablename__ = "data_points"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), index=True, nullable=False)
    value = Column(Float, nullable=False)
    meta = Column(Text)  # เก็บ JSON string เพิ่มเติมได้

Base.metadata.create_all(engine)

# ---------- Utilities ----------

def require_api_key():
    if not API_KEY:
        return True
    return request.headers.get("X-API-Key") == API_KEY

ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

def parse_ts(value):
    if not value:
        return datetime.now(timezone.utc)
    # ถ้าเป็นตัวเลข -> unix seconds
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.', '', 1).isdigit()):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except Exception:
        pass
    # ลอง parse ISO
    for fmt in ISO_FORMATS:
        try:
            dt = datetime.strptime(str(value), fmt)
            # เติม timezone เป็น UTC ถ้าไม่ระบุ
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    # สุดท้าย ให้ลอง fromisoformat
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

# ---------- API ----------

@app.post("/api/ingest")
def ingest():
    if not require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    if "value" not in payload:
        return jsonify({"error": "Missing 'value'"}), 400
    try:
        value = float(payload["value"])
    except Exception:
        return jsonify({"error": "'value' must be a number"}), 400

    ts = parse_ts(payload.get("ts"))
    meta = payload.get("meta")
    meta_str = json.dumps(meta, ensure_ascii=False) if meta is not None else None

    db = SessionLocal()
    try:
        dp = DataPoint(ts=ts, value=value, meta=meta_str)
        db.add(dp)
        db.commit()
        return jsonify({"status": "ok", "id": dp.id})
    finally:
        db.close()

@app.get("/api/data")
def api_data():
    db = SessionLocal()
    try:
        q = db.query(DataPoint)
        # filters: since, until (ISO or unix)
        since = request.args.get("since")
        until = request.args.get("until")
        if since:
            q = q.filter(DataPoint.ts >= parse_ts(since))
        if until:
            q = q.filter(DataPoint.ts <= parse_ts(until))
        q = q.order_by(DataPoint.ts.asc())
        rows = q.all()
        data = [{
            "id": r.id,
            "ts": r.ts.astimezone(timezone.utc).isoformat(),
            "value": r.value,
            "meta": json.loads(r.meta) if r.meta else None
        } for r in rows]
        return jsonify(data)
    finally:
        db.close()

# ---------- Frontend (single-file HTML) ----------

INDEX_HTML = f"""
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{APP_TITLE}</title>
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
  <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap\" rel=\"stylesheet\" />
  <script src=\"https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js\" defer></script>
  <style>
    :root { --fg:#0f172a; --muted:#64748b; --bg:#f8fafc; --card:#ffffff; }
    *{ box-sizing:border-box; }
    body{ margin:0; font-family:Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial; color:var(--fg); background:var(--bg); }
    .wrap{ max-width:920px; margin:40px auto; padding:0 16px; }
    .card{ background:var(--card); border-radius:16px; padding:20px; box-shadow:0 1px 8px rgba(15,23,42,.06); }
    .row{ display:flex; gap:16px; flex-wrap:wrap; }
    .row > *{ flex:1 1 280px; }
    .muted{ color:var(--muted); }
    .kbd{ font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background:#e2e8f0; padding:2px 6px; border-radius:6px; font-size:12px; }
    .input{ width:100%; padding:10px 12px; border:1px solid #e2e8f0; border-radius:10px; }
    button{ padding:10px 14px; border:0; border-radius:12px; background:#0ea5e9; color:white; font-weight:600; cursor:pointer; }
    button:disabled{ background:#94a3b8; cursor:not-allowed; }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1 style=\"margin:0 0 6px\">{APP_TITLE}</h1>
    <div class=\"muted\" style=\"margin-bottom:18px\">Simple time-series ingest & chart</div>

    <div class=\"card\" style=\"margin-bottom:16px\">
      <div class=\"row\">
        <div>
          <label class=\"muted\">Manual add value</label>
          <div style=\"display:flex; gap:8px; margin-top:6px\">
            <input id=\"val\" class=\"input\" type=\"number\" step=\"any\" placeholder=\"e.g. 42.5\" />
            <input id=\"meta\" class=\"input\" placeholder=\"meta JSON (optional)\" />
            <button id=\"btn\">Add</button>
          </div>
          <div class=\"muted\" style=\"margin-top:6px\">curl: <span class=\"kbd\">curl -X POST /api/ingest -H 'Content-Type: application/json' -d '{"value":12.3}'</span></div>
        </div>
        <div>
          <label class=\"muted\">Auto refresh</label>
          <div style=\"display:flex; gap:8px; margin-top:6px; align-items:center\">
            <select id=\"interval\" class=\"input\">
              <option value=\"0\">Off</option>
              <option value=\"5\">5s</option>
              <option value=\"15\">15s</option>
              <option value=\"60\">60s</option>
            </select>
            <button id=\"refresh\">Refresh now</button>
          </div>
        </div>
      </div>
    </div>

    <div class=\"card\">
      <canvas id=\"chart\" height=\"120\"></canvas>
    </div>
  </div>

  <script>
    const apiKey = null; // ใส่เป็น string ถ้าตั้ง API_KEY ฝั่งเซิร์ฟเวอร์ เช่น "mysecret"

    async function fetchData() {
      const res = await fetch('/api/data');
      const data = await res.json();
      return data.map(d => ({
        x: new Date(d.ts),
        y: d.value
      }));
    }

    async function postValue(value, meta) {
      const res = await fetch('/api/ingest', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { 'X-API-Key': apiKey } : {})
        },
        body: JSON.stringify({ value, meta })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t);
      }
      return res.json();
    }

    let chart;
    async function render() {
      const points = await fetchData();
      const ctx = document.getElementById('chart');
      const ds = [{
        label: 'value',
        data: points,
        parsing: false,
        borderWidth: 2,
        tension: 0.2
      }];
      const cfg = {
        type: 'line',
        data: { datasets: ds },
        options: {
          animation: false,
          scales: {
            x: { type: 'time', time: { unit: 'minute' } },
            y: { beginAtZero: true }
          },
          plugins: { legend: { display: true } }
        }
      };
      if (chart) { chart.destroy(); }
      // time scale requires adapter
      await import('https://cdn.jsdelivr.net/npm/luxon@3/build/global/luxon.min.js');
      await import('https://cdn.jsdelivr.net/npm/chartjs-adapter-luxon@1.3.1/dist/chartjs-adapter-luxon.umd.min.js');
      chart = new Chart(ctx, cfg);
    }

    document.getElementById('btn').addEventListener('click', async () => {
      const v = parseFloat(document.getElementById('val').value);
      const mraw = document.getElementById('meta').value.trim();
      const meta = mraw ? JSON.parse(mraw) : undefined;
      if (Number.isNaN(v)) return alert('Please input a number');
      try { await postValue(v, meta); await render(); }
      catch (e) { alert(e.message); }
    });

    document.getElementById('refresh').addEventListener('click', render);

    let timer = null;
    document.getElementById('interval').addEventListener('change', (e) => {
      if (timer) { clearInterval(timer); timer = null; }
      const sec = parseInt(e.target.value, 10);
      if (sec > 0) { timer = setInterval(render, sec * 1000); }
    });

    render();
  </script>
</body>
</html>
"""

@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")

if __name__ == "__main__":
    # สำหรับทดสอบบนเครื่อง
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
