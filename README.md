# CivicAI

AI-powered civic infrastructure monitoring for safer, more accountable
communities.

CivicAI uses computer vision to identify and document infrastructure issues
from recorded vehicle video files. The initial focus is pothole detection,
with the architecture designed to support additional civic infrastructure
categories over time.

## Project status

The ROI branch now includes the YOLO pothole pipeline, timestamp-aligned GPS
association, SQLite incident grouping, evidence retrieval, and an on-demand
LLM incident-report endpoint. The T4/YOLO inference path remains separate from
report generation.

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
│   ├── .env.example           # Safe configuration template
│   ├── .env                   # Local-only configuration (ignored)
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

The backend requirements file contains the current runtime dependencies. The
reporting client uses Python's standard-library HTTP client, so no additional
LLM SDK is required.

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
The backend loads the `.pth` road checkpoint through MMSegmentation and uses
the Ultralytics model only for pothole detection.
Segmentation runs on frame 1 and every 20th frame by default
(`ROI_SEGMENTATION_INTERVAL`); intervening frames reuse the latest mask
geometry while YOLO still runs on each current frame.


### GPS trace association

For recorded videos, provide a sidecar CSV whose timestamps are milliseconds
from the beginning of the video. Copy
`backend/data/gps_trace.template.csv`, populate it with the GPS samples
belonging to that recording, and set `GPS_TRACE_PATH` in the local
`backend/.env`.

Required columns:

- `elapsed_ms`: timestamp on the video timeline
- `latitude`, `longitude`: supplied GPS coordinates

Optional columns:

- `accuracy_m`: reported GPS accuracy in metres
- `source`: for example `phone_gps` or `synthetic`
- `is_simulated`: `true` for generated test coordinates, `false` for real GPS

Synthetic samples must use `source=synthetic` and
`is_simulated=true`. CivicAI interpolates between compatible nearby samples
when the time gap is at most 3 seconds, otherwise it uses a nearest sample
within 1.5 seconds. If no valid sample is close enough, the observation remains
without coordinates. Incident merging only uses coordinates with known
accuracy of 20 metres or better and keeps simulated and real locations separate.

**Location limitation:** the recorded coordinate represents the vehicle's
estimated position at the frame timestamp. It is not a surveyed coordinate of
the pothole itself; camera direction and distance still need calibration.

### Incident reports

The API exposes:

- `GET /api/incidents` — aggregated incident records
- `GET /api/incidents/{id}` — verified facts, limitations and evidence references
- `POST /api/incidents/{id}/report` — generate and save an LLM-assisted report
- `GET /api/reports/{id}` — retrieve a saved report

Set `GEMINI_API_KEY` in the local `backend/.env` to enable report generation.
Optionally set `GEMINI_MODEL`; the default is `gemini-2.5-flash`. The report
keeps deterministic database facts separate from LLM narrative, validates
evidence IDs, and explicitly lists missing inspection data. Model confidence
is never converted into physical severity.

Run the backend tests from the `backend` directory:

```bash
python -m unittest discover -s tests
```

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
Set `VIDEO_PATH` in `backend/.env` to the absolute path of the video file to
process. The default reference video is not included in Git because reference
assets are ignored.

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
