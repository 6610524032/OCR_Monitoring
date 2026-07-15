# OCR Monitoring Portable

OCR Monitoring Portable is a web-based OCR monitoring system for reading values from machine HMI screens using computer vision and TrOCR.

The system supports:

- Screen calibration
- Manual ROI configuration
- OCR reading using TrOCR
- Historical data storage
- Docker deployment
- API-based architecture

---

# Project Structure

```
V3
│
├── app
│   ├── processing
│   │     Image processing, OCR, calibration and worker
│   │
│   ├── server
│   │     ├── api_app.py
│   │     ├── database.py
│   │     ├── config.py
│   │     ├── repositories
│   │     │      Database access layer
│   │     └── routes
│   │            REST API endpoints
│   │
│   └── web
│         Flask web interface
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

# Architecture

```
Browser
    │
    ▼
Flask Web
    │
    ▼
REST API
    │
    ▼
Repositories
    │
    ▼
SQLite Database
```

Worker

```
Camera
    │
    ▼
Calibration
    │
    ▼
ROI Crop
    │
    ▼
TrOCR
    │
    ▼
API
    │
    ▼
Database
```

---

# Features

- Screen Calibration
- Perspective Transformation
- Manual ROI Selection
- OCR Reading using Microsoft TrOCR
- OCR History
- Review Page
- Docker Support
- API-based Communication

---

# Technology

Backend

- Python 
- Flask
- OpenCV
- SQLite

OCR

- Microsoft TrOCR
- HuggingFace Transformers
- PyTorch

Frontend

- HTML
- CSS
- JavaScript

Deployment

- Docker
- Docker Compose

---

# Installation

## Clone Project

```bash
git clone https://github.com/<your_username>/OCR_Monitoring_Portable.git

cd OCR_Monitoring_Portable
```

---

## Build Docker

```bash
docker compose build
```

---

## Run

```bash
docker compose up
```

or

```bash
docker compose up --build
```

---

# Web Pages

Web Interface

```
http://localhost:5000
```

API

```
http://localhost:5001
```

---

# Main Pages

## Dashboard

Display latest OCR values.

---

## Live Camera

Display RTSP live stream.

---

## History

Display OCR history.

---

## Settings

Configuration page including

- Screen Calibration
- Calibration Result
- Manual ROI Setup
- Configured Tags

---

# Calibration Workflow

1. Open **Settings**
2. Click all four HMI corners
3. Save Calibration
4. Wait until Calibration Ready
5. Draw ROI
6. Save All Tags

---

# OCR Workflow

```
Capture Image
      │
      ▼
Perspective Calibration
      │
      ▼
Crop ROI
      │
      ▼
TrOCR
      │
      ▼
Save Database
      │
      ▼
Dashboard
```

---

# Docker Containers

The project contains three containers.

| Container | Description |
|-----------|-------------|
| api | REST API Server |
| web | Flask Web UI |
| worker | OCR Worker |

---

# API Authentication

Every API request requires an API Key.

```
Authorization: Bearer <API_KEY>
```

---

# Environment Variables

| Variable | Description |
|----------|-------------|
| API_KEY | API Authentication Key |
| API_SERVER_URL | API Server URL |
| RTSP_URL | RTSP Camera URL |
| HF_HOME | HuggingFace Cache |
| HUGGINGFACE_HUB_CACHE | HuggingFace Cache |

---

# Notes

If no RTSP camera is connected,

- Dashboard still works
- Settings still works
- History still works
- Live page will wait for camera connection

---

# Project Layers

## routes

Contains Flask API endpoints.

Responsible for

- GET
- POST
- Request validation
- JSON response

---

## repositories

Database access layer.

Responsible for

- SELECT
- INSERT
- UPDATE
- DELETE

---

## processing

Image processing module.

Responsible for

- Calibration
- Perspective Transform
- ROI Crop
- OCR
- Worker

---

## web

Frontend interface.

Responsible for

- Dashboard
- Live
- History
- Settings

---