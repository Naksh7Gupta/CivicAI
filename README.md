# CivicAI

AI-powered civic infrastructure monitoring for safer, more accountable communities.

CivicAI uses computer vision to identify and document infrastructure issues from recorded vehicle or mobile-camera footage. The initial focus is pothole detection. The existing YOLO + road-ROI inference path is kept separate from GPS association and reporting so those services do not change model inference.

## Current pipeline

~~~text
Video frame -> road ROI -> YOLO tracking -> evidence crop
                                      |
GPS CSV + frame media timestamp -----+
                                      v
                            SQLite observations
                                      v
                           incident aggregation
                                      v
                      database facts -> report engine
                                      v
                            dashboard/API reports
~~~

## GPS association

GPS is optional. If no track CSV is configured, detections are saved with coordinates unavailable; CivicAI does not generate placeholder coordinates.

Set **GPS_TRACK_CSV** in backend/.env. The CSV must include these columns:

~~~csv
video_timestamp_seconds,latitude,longitude,accuracy_m,location_source,is_simulated
~~~

Use either **video_timestamp_seconds** (seconds from the start of the video) or **timestamp_utc**. If using **timestamp_utc**, also set **VIDEO_START_TIME_UTC** to the UTC start time of the video, including Z or an explicit timezone offset. **location_source** must describe the source (for example phone_gps or synthetic), and **is_simulated** must be explicitly true or false.

CivicAI associates a frame only with the nearest sample inside **GPS_MAX_DELTA_SECONDS** (default 2 seconds). The match stores the time difference, reported accuracy, source, and simulation flag. Low-accuracy and unknown-accuracy fixes remain visibly flagged. A GPS fix describes the camera/vehicle position associated with the frame; it is **not** a surveyed pothole coordinate because camera direction and road offset are not calibrated yet.

## Incident aggregation

A tracker ID within one video session becomes one incident record. Repeated frame detections update that incident's observation count, first/last-seen times, best model confidence, and evidence reference. When the tracker supplies no ID, CivicAI deliberately creates separate candidate records rather than guessing that detections belong to the same physical pothole.

Cross-session spatial deduplication is not enabled yet. It needs a validated camera-to-road location offset and GPS accuracy policy; merging on raw vehicle GPS could incorrectly combine nearby potholes.

## Reports

The API exposes:

- GET /api/incidents
- GET /api/incidents/{id}/report
- GET /api/reports/area?session_id=...
- GET /api/reports/executive-summary?session_id=...

Reports are built from SQLite records. The immutable facts object is separate from the narrative. If an OpenAI-compatible chat-completions endpoint is configured using **LLM_API_BASE_URL**, **LLM_MODEL**, and optionally **LLM_API_KEY**, the report service asks that model for a cautious narrative. Otherwise it returns a deterministic fallback and labels it as such. No LLM credential is required to test the data/report pipeline.

Model confidence is not physical damage severity. The current schema does not claim pothole dimensions, road names, field inspection, repair status, costs, or municipal actions. Human review is required before official use.

## Run

From backend/:

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_api.py
~~~

In another terminal, run the video pipeline with **python -m app.main**. Start the dashboard separately from dashboard/ using **npm install** and **npm run dev**.

Copy **.env.example** to **.env** and set only the paths and optional services you actually have. Never commit .env or API keys.
