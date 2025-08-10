import os
import json
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base

APP_TITLE = "Telemetry Demo"
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data.db")
API_KEY = os.environ.get("API_KEY")  # ตั้งไว้เพื่อเปิดใช้การตรวจ API key

app = Flask(__name__)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

class DataPoint(Base):
    __tablename__ = "data_points"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), index=True, nullable=False)
    value = Column(Float, nullable=False)
    meta = Column(Text)  # JSON string

Base.metadata.create_all(engine)

# -------- Utils --------
ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

def parse_ts(value):
    if not value:
        return datetime.now(timezone.utc)
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.', '', 1).isdigit()):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except Exception:
        pass
    for fmt in ISO_FORMATS:
        try:
            dt = datetime.strptime(str(value), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def require_api_key():
    if not API_KEY:
        return True
    return request.headers.get("X-API-Key") == API_KEY

# -------- API --------
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

# -------- UI --------
@app.get("/")
def index():
    return render_template("index.html", title=APP_TITLE)

# -------- UI --------
@app.get("/chart")
def chart():
    return render_template("chart.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
