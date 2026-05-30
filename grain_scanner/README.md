# 🌾 Grain Scanner

Production-grade grain size measurement system using flatbed scanner images.
Detects individual grains, measures length/width/area in millimetres, and exports results via a REST API and industrial Streamlit dashboard.

---

## Features

| Feature | Details |
|---------|---------|
| **Hardware scanning** | Trigger scans directly from SANE (Linux/macOS), ImageCapture (macOS), or WIA (Windows) |
| **Image input** | Upload PNG / JPEG / TIFF; manual DPI override |
| **Vision pipeline** | Grayscale → Gaussian blur → adaptive threshold → morphology → watershed segmentation |
| **Measurements** | Major axis, minor axis, area, perimeter, aspect ratio, orientation, solidity, eccentricity |
| **Units** | Pixel → mm conversion: `mm = px × (25.4 / DPI)` |
| **Calibration** | From DPI, or auto-detect reference marker (square/circle) in image |
| **Statistics** | Mean, std, min, max + histogram distributions |
| **Export** | CSV download, multi-page PDF report |
| **Database** | SQLite via async SQLAlchemy (scan history, per-grain rows, calibration profiles) |
| **API** | FastAPI with OpenAPI docs at `/docs` |
| **UI** | Streamlit dark dashboard with image preview, charts, measurement table |
| **Docker** | Multi-stage image + docker-compose for API + UI |

---

## Quick Start

### 1. Install dependencies

```bash
cd grain_scanner
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Copy environment config

```bash
cp .env.example .env
# Edit .env if needed
```

### 3. Start the FastAPI backend

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
# API docs: http://localhost:8000/docs
```

### 4. Start the Streamlit dashboard

```bash
streamlit run streamlit_app.py
# Open: http://localhost:8501
```

---

## Docker

```bash
docker-compose up --build
# API:  http://localhost:8000/docs
# UI:   http://localhost:8501
```

---

## Scanner Hardware Integration

The app supports direct scanning via three backends (auto-detected):

| Platform | Backend | Install |
|----------|---------|---------|
| macOS / Linux | SANE | `brew install sane-backends` (macOS) or `apt install sane-utils` |
| macOS | ImageCapture | Built-in (fallback to SANE if available) |
| Windows | WIA | `pip install pywin32` |

In the Streamlit UI, select **🖨️ Scanner / Printer** in the sidebar, click **Detect Scanners**, choose your device, and click **Scan & Process**.

Via API:
```bash
# List devices
GET /api/v1/scanner/devices

# Scan + process in one call
POST /api/v1/scanner/scan-and-process?device_id=...&dpi=300
```

---

## API Reference

```
POST   /api/v1/scans/upload                   Upload image
POST   /api/v1/scans/{id}/process             Process grain detection
GET    /api/v1/scans/{id}                     Scan metadata & status
GET    /api/v1/scans/{id}/measurements        Per-grain measurements
GET    /api/v1/scans/{id}/statistics          Aggregate statistics
GET    /api/v1/scans/{id}/annotated-image     Annotated PNG
GET    /api/v1/scans/{id}/export/csv          Download CSV
GET    /api/v1/scans/{id}/export/pdf          Download PDF report
DELETE /api/v1/scans/{id}                     Delete scan

GET    /api/v1/scanner/devices                List scanners
POST   /api/v1/scanner/scan                   Trigger scan (no processing)
POST   /api/v1/scanner/scan-and-process       Scan + detect + measure

GET    /api/v1/calibration/profiles           List calibration profiles
POST   /api/v1/calibration/profiles/from-dpi  Create DPI profile
POST   /api/v1/calibration/profiles/from-image Auto-calibrate from reference
PUT    /api/v1/calibration/profiles/{id}/activate
```

---

## Run Tests

```bash
pytest tests/ -v --tb=short
```

Phase 1 gate: all tests green, single-grain accuracy ≤ ±0.05 mm.

---

## Project Structure

```
grain_scanner/
├── app/
│   ├── api/routes/         FastAPI endpoints (images, measurements, reports, calibration, scanner)
│   ├── calibration/        CalibrationProfile + Calibrator
│   ├── core/               Settings (pydantic-settings) + loguru logging
│   ├── database/           SQLAlchemy models + async session
│   ├── models/             Pydantic domain models (GrainMeasurement, ScanResult, …)
│   ├── scanner/            Cross-platform scanner driver (SANE / WIA / ImageCapture)
│   ├── services/           ScanService, ExportService, StatsService
│   └── vision/             pipeline → segmentation → measurement → visualization
├── tests/                  pytest suite (synthetic image fixtures)
├── data/uploads/           Uploaded / scanned images
├── outputs/                Annotated result images
├── logs/                   Rotating log files
├── main.py                 FastAPI app entry point
├── streamlit_app.py        Streamlit dashboard
├── requirements.txt
├── Dockerfile              Multi-stage Python 3.12-slim
└── docker-compose.yml      API + UI services
```

---

## Processing Pipeline

```
Raw Image
    └─► Grayscale conversion (cv2.cvtColor)
    └─► Gaussian blur (noise suppression)
    └─► Adaptive threshold (THRESH_BINARY_INV)
    └─► Morphological open + close (remove noise, fill holes)
    └─► Watershed segmentation (distance transform → peak_local_max → watershed)
    └─► skimage.measure.regionprops (area, perimeter, axes, orientation)
    └─► Pixel → mm conversion (mm = px × 25.4 / DPI)
    └─► Annotated image + CSV + PDF export
```

---

## Roadmap

- [ ] Phase 4: Batch processing, WebSocket progress, PDF reports (Phase 3 gate passed)
- [ ] Phase 5: PyInstaller Windows exe packaging
- [ ] React + React Native frontend
- [ ] ONNX ML grain classification (broken grain, foreign particle detection)
- [ ] Auto scanner detection on startup
