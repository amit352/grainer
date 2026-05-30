# Grainer

Computer vision system for automated grain quality analysis. Detects individual grains from flatbed scanner or camera images, measures size/shape in millimetres, grades quality A–F, and exposes results via a REST API and Streamlit dashboard.

---

## Features

- **Vision pipeline** — multi-channel CLAHE fusion, per-blob EDT thresholding, watershed segmentation
- **Cluster handling** — second-pass splitting of touching grains; irrecoverable clusters estimated by area
- **Quality grading** — A–F grade based on broken ratio, foreign matter (< 30 % reference size), and size uniformity CV
- **Reference calibration** — auto-detects ISO 7810 credit/Aadhaar card in image for px→mm scale
- **Scanner integration** — ESCL/eSCL network scanner support with stuck-job recovery
- **REST API** — FastAPI with OpenAPI docs; upload, process, measure, export CSV/PDF
- **Dashboard** — Streamlit UI with annotated image, grain table, quality report, and cluster overlay
- **Licensing** — Ed25519 machine-bound license keys with coupon redemption
- **Packaging** — PyInstaller + Inno Setup for Windows distribution

---

## Quick Start

```bash
make install      # create venv and install dependencies
make env          # copy .env.example → .env
make up           # start API (:8000) + UI (:8501) in background
make down         # stop both
```

API docs: `http://localhost:8000/docs`  
Dashboard: `http://localhost:8501`

---

## Project Structure

```
grain_scanner/       FastAPI backend + Streamlit UI (core app)
  app/
    api/             REST endpoints
    vision/          pipeline → segmentation → measurement → visualization
    scanner/         ESCL scanner driver
    services/        scan, export, stats
    models/          Pydantic domain models
    database/        SQLAlchemy async + SQLite
  tests/             pytest suite
  main.py            FastAPI entry point
  streamlit_app.py   Streamlit dashboard

license_server/      Railway-hosted license validation service
packaging/           Windows installer (PyInstaller spec + Inno Setup)
Makefile             Dev, test, packaging, and licensing targets
```

---

## Run Tests

```bash
make test
```

---

## Docker

```bash
make docker-up    # build and start API + UI via docker-compose
make docker-down
```

---

## Makefile Targets

```
make install     Install dependencies
make up          Start API + UI in background
make down        Stop background services
make logs        Tail API and UI logs
make test        Run full test suite
make coverage    Tests with coverage report
make lint        Run ruff
make clean       Remove venv, cache, outputs, db
make keygen      Generate Ed25519 license keypair
make license     Issue a license key (MID=<machine-id>)
make coupon      Create coupon codes on license server
make docker-up   Start via docker-compose
```
