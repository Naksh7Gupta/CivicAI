# CivicAI

AI-powered civic infrastructure monitoring for safer, more accountable
communities.

CivicAI uses computer vision to identify and document infrastructure issues
from recorded vehicle video files. The initial focus is pothole detection,
with the architecture designed to support additional civic infrastructure
categories over time.

## Project status

The repository currently contains the initial backend structure and a
YOLO-based pothole model. Detection, tracking, persistence, and reporting
modules are scaffolded and ready for implementation.

## How it works

```text
Video file
          |
          v
Frame acquisition and preprocessing
          |
          v
Pothole detection
          |
          v
Object tracking and validation
          |
          v
Evidence crop storage
          |
          v
SQLite database
          |
          v
Reports and dashboard
```

Each validated observation is intended to include:

- Issue category and detection confidence
- Timestamp and tracking information
- GPS coordinates when available
- A reference to the captured visual evidence

## Repository structure

```text
CivicAI/
├── backend/
│   ├── app/
│   │   ├── core/              # Configuration and logging
│   │   ├── database/          # Database connection, models, repositories
│   │   ├── detection/         # Detection and tracking
│   │   ├── ingestion/         # Stream and frame processing
│   │   ├── services/          # Application workflows and storage
│   │   ├── utils/             # Shared image utilities
│   │   └── main.py            # Backend entry point
│   ├── data/
│   │   └── civicai.db         # Local SQLite database
│   ├── models/
│   │   └── pothole.pt         # Pothole detection model
│   ├── storage/
│   │   └── potholes/          # Stored detection crops
│   ├── .env                   # Local environment configuration
│   └── requirements.txt       # Python dependencies
├── dashboard/                 # React/Vite operations dashboard
└── references/                # Reference images, notebook, and source model
```

## Getting started

### Prerequisites

- Python 3.10 or newer
- Git
- A virtual environment

### Setup

From the project root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The dependency file is currently a placeholder while the backend modules are
being implemented. Add runtime dependencies there before running the
application.

### Road ROI configuration

The video pipeline optionally loads a road-specific segmentation model from
`backend/models/segmentation_model.pt`. Set
`ROAD_SEGMENTATION_MODEL_PATH` in `backend/.env` to use another local weights
file. The model's road class defaults to class `0`; override it with
`ROAD_SEGMENTATION_CLASS_ID` when needed. A missing model, empty mask, or
unusable crop falls back to full-frame pothole detection.

The mask is converted to a padded crop (`ROI_PADDING_RATIO`, default `0.15`).
YOLO detections are translated back to the original video coordinates before
they are persisted, while the output video shows the road mask and detections.

### Run the dashboard

Install the backend dependencies, start the API, and start the dashboard in
separate terminals:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_api.py
```

```powershell
cd dashboard
npm install
npm run dev
```

The dashboard reads only from `GET /api/potholes`. Detection crops are stored
as image BLOBs in SQLite and served by `GET /api/potholes/{id}/image`; no
frontend seed or synthetic detection data is used. GPS values are shown when
the backend begins persisting them; existing records correctly report GPS as
unavailable.

### Configuration

Set local values in `backend/.env`. Do not commit credentials, API keys, or
other secrets. The local database is stored at `backend/data/civicai.db`, and
evidence crops are stored under `backend/storage/potholes/`.

## Development workflow

1. Add or update a backend module under `backend/app/`.
2. Keep model files in `backend/models/`.
3. Store generated evidence under `backend/storage/`.
4. Persist structured detection data in SQLite.
5. Add tests alongside the feature before integrating it into the detection
   workflow.

## Planned capabilities

- Video-file ingestion
- Road-segmentation ROI preprocessing before pothole detection
- Pothole detection and multi-frame tracking
- GPS-aware infrastructure observations
- Evidence image management
- Interactive map and detection history
- Area-level infrastructure summaries
- AI-assisted report generation based on validated detections
- Additional monitoring modules for footpaths, waste, road markings, and signs

## Responsible use

CivicAI is intended to support infrastructure inspection and prioritization.
Model predictions should be reviewed and validated before being used for
official decisions. Detection confidence is an indicator, not proof that an
issue exists.
