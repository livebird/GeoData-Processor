# Software Requirements Specification (SRS)

# Geo Processing Server — v4

**Version:** 4.0 Draft
**Status:** Pre-implementation. Replaces v1, v2, v3 drafts.
**Primary Stack:** Django 5.x + Django REST Framework + Celery + PostgreSQL + RabbitMQ + GDAL/OGR CLI
**Deployment Model:** On-premise and self-hosted VM
**Primary Consumers:** Feature Mapper, future Raster/Vector Serving App, external customer systems, standalone deployments
**Target v1 Ship Date:** 10 weeks (8 weeks build + 2 weeks raster spike, integrated test/polish within build weeks)

-----

## 1. Introduction

### 1.1 Purpose

Geo Processing Server (GPS) is a **conversion, transformation, and workflow-routing service** for geospatial data. Users upload GIS files (or supply remote URLs), GPS validates, converts, and transforms them, then dispatches the result to a configurable destination — Feature Mapper, a future raster/vector serving app, an external webhook, or simple file download.

GPS does **not** serve, browse, or query data long-term. Serving is the responsibility of downstream applications (Feature Mapper for feature data, a future Raster/Vector Serving App for everything else, or the customer’s own systems via webhook/API).

### 1.2 Product Positioning

GPS is the **conversion + routing hub** in the LiveBird GIS ecosystem. It is **not**:

- A general-purpose ETL platform (FME / Alteryx territory)
- A GIS analysis tool (QGIS / ArcGIS territory)
- A web map server or data store (GeoServer / MapServer / pg_featureserv territory)
- A long-term data repository (Feature Mapper and future serving app own that)

GPS **is**: an opinionated ingestion + transformation + routing service that turns messy agency-supplied GIS data into clean, standardized output and delivers it where the customer needs it.

### 1.3 Competitive Differentiators

GPS is justified only because it does these better than existing tools:

1. **Cost vs. FME / ArcGIS Data Interoperability** — bundled into LiveBird suite at materially lower per-deployment cost than FME’s $4,800–25,000/year licensing.
1. **Vertical UX** — operator-grade workflows (“upload Shapefile, reproject, push to Feature Mapper”) in 3 clicks, no FME Workbench learning curve.
1. **Native integration** — Feature Mapper publishing is first-class. Future Raster/Vector Serving App publishing is a stated v1.5 destination.
1. **On-prem first** — works in air-gapped government and defense environments without SaaS dependencies.
1. **Workflow flexibility** — output can go to LiveBird apps, customer external systems, or simple download. Not locked to one destination.

If GPS is not clearly winning on at least one of these axes for a given customer, that customer should use FME or QGIS batch processing instead.

### 1.4 Primary Business Use Cases

- Convert agency Shapefile / KML / CSV to GeoJSON / GeoPackage / GeoParquet for download.
- Reproject, clip, simplify GIS data and deliver to Feature Mapper for an active incident.
- Convert and push GIS data to a customer’s external system via signed webhook.
- Provide standalone on-premise GIS conversion for clients who cannot use SaaS tools.

-----

## 2. Scope

### 2.1 In Scope for v1

**Core capabilities:**

- File upload with resumable upload support (tus.io) for files up to 5 GB
- Remote file ingestion (URL fetch over HTTP/HTTPS, with auth headers and checksum verification)
- Metadata extraction via `ogrinfo`
- Validation (structure, CRS, geometry, encoding)
- Vector format conversion via `ogr2ogr`
- CRS reprojection with documented axis-order and datum-grid policy
- Geometry validation and optional fix
- Transformation operations: clip-by-AOI, simplify, fix-invalid, field selection/rename
- **Lightweight preview layer** — render converted output as map and table view in the UI, ephemeral, before user publishes
- **Workflow dispatcher** — route output to Feature Mapper, external webhook, external database, or download
- Job system with priority queues (Celery), idempotency, retry, cancel-running
- Local + S3-compatible storage with signed URLs
- Audit logging and Django RBAC
- Built-in admin UI via Django admin (file list, job list, audit, credentials, configuration)
- Operator-facing UI via Django templates with embedded React for preview map/table only
- Prometheus metrics + structured JSON logs from day one
- Docker Compose deployment
- OpenAPI documentation via `drf-spectacular`

**Input formats (v1):** Shapefile ZIP, GeoJSON, KML, KMZ, GeoPackage, CSV (lat/lon or WKT), GPX, GeoParquet

**Output formats (v1):** GeoJSON, GeoPackage, FlatGeobuf, GeoParquet, KML, CSV, Shapefile ZIP

**Workflow destinations (v1):**

- Download (no publish)
- Feature Mapper (signed webhook publish)
- External webhook (customer-defined endpoint, signed)
- External database (PostgreSQL/PostGIS connection string supplied by customer)

### 2.2 Raster Spike (v1.0 contingency)

A **2-week raster spike** evaluates demand for raster ingestion before v1 ships. The spike covers GeoTIFF metadata extraction, reprojection, and basic conversion (e.g., to Cloud Optimized GeoTIFF). If the spike confirms real customer demand, basic raster onboarding ships in v1. If not, it moves to v1.5+.

### 2.3 Out of Scope for v1

- **Long-term data storage / serving** — GPS does not host, serve, or browse data.
- **Persistent PostGIS data layer inside GPS** — GPS’s own database is plain PostgreSQL for metadata (jobs, files, audit). It does not load processed GIS data into its own PostGIS for serving. (Workflow `publish_external_database` lets the customer push to their *own* PostGIS — that is not GPS’s storage.)
- Visual workflow builder (graphical node editor)
- Multi-tenant SaaS billing or complex tenant isolation
- CAD/BIM/DWG/DXF processing
- Point cloud processing
- Real-time streaming analytics
- AI features (deferred — see v1.5+)
- Vector tile generation (PMTiles/MVT)
- Geocoding
- “Engine adapter” abstractions for hypothetical future engines (Rust, DuckDB, custom)

### 2.4 Future Scope (Roadmap, Not Requirements)

- v1.5: Future Raster/Vector Serving App destination, AI assists (CRS inference, error explanation), k8s/Helm
- v2: Raster (full pipeline) if demand confirmed
- v2+: Vector tiles, schema mapping AI, workflow builder, geocoding, DuckDB-based analytics, Rust-based large-file processing

Tracked in `ROADMAP.md`. Not in this SRS until promoted by customer demand.

-----

## 3. Architecture

### 3.1 High-Level Architecture

```text
Frontend (Django templates + Django admin + embedded React for preview)
        |
        v
Django + DRF (REST API + server-rendered admin/operator UI)
        |
        +-- ORM -> PostgreSQL (METADATA ONLY: jobs, files, audit, credentials)
        |
        +-- creates Celery task -> RabbitMQ
                                     |
                                     v
                            Celery Worker (separate service, same codebase)
                                     |
                                     +-- imports shared service modules
                                     +-- reads/writes Local FS or S3-compatible storage
                                     +-- runs conversion + transformation (GDAL/OGR CLI)
                                     +-- generates ephemeral preview output
                                     +-- dispatches to workflow destination:
                                              |
                                              +-- Feature Mapper (signed webhook)
                                              +-- External webhook (customer endpoint)
                                              +-- External database (customer PostgreSQL/PostGIS)
                                              +-- Download (output stored, signed URL returned)
```

### 3.2 Architectural Principles

1. **Django serves both API (DRF) and server-rendered admin/operator UI** from the same project. One codebase, two surfaces.
1. **Celery workers run as a separate service** sharing the same codebase. The web service does not block on processing.
1. **Service classes are framework-agnostic.** Both DRF views and Celery tasks call the same `TransformationService.run(file_id, params)` function. No coupling to Django request/response objects in the service layer.
1. **GPS is stateless about GIS data.** GIS payloads flow through; only metadata is persisted in GPS’s own database.
1. **GPS’s PostgreSQL holds metadata only.** No PostGIS extension required for GPS’s own database.
1. **Workflows are the routing primitive.** Adding a new destination means adding a new workflow definition, not refactoring core processing.
1. **GDAL/OGR CLI is the only processor in v1.** No abstract engine adapter base classes.
1. **Preview is ephemeral.** Generated on demand, TTL-bounded, not persisted long-term.

### 3.3 Core Components

|Component             |Responsibility                                   |Lives In          |
|----------------------|-------------------------------------------------|------------------|
|Django web service    |REST API (DRF), admin UI, operator UI            |`web` container   |
|Celery worker service |Executes long-running tasks                      |`worker` container|
|Celery beat (optional)|Scheduled cleanup tasks                          |`beat` container  |
|Storage manager       |Pluggable local / S3 backend                     |shared package    |
|Metadata extractor    |`ogrinfo` wrapper                                |shared package    |
|Validation service    |File structure, CRS, geometry checks             |shared package    |
|Transformation service|Reproject, clip, simplify, fix-invalid, field ops|shared package    |
|Preview service       |Generate ephemeral preview features + summary    |shared package    |
|Workflow dispatcher   |Route output to chosen destination               |shared package    |
|Destination adapters  |Feature Mapper, webhook, customer DB             |shared package    |
|Audit logger          |Captures every state-changing action             |shared package    |

All “shared package” components are plain Python modules importable by both Django views and Celery tasks. No framework coupling.

-----

## 4. Technology Stack

|Layer              |Choice                                                           |Rationale                                            |
|-------------------|-----------------------------------------------------------------|-----------------------------------------------------|
|Web framework      |Django 5.x                                                       |Admin UI free, mature ORM, auth, migrations          |
|API framework      |Django REST Framework                                            |Standard, well-known, integrates with Django auth    |
|OpenAPI            |`drf-spectacular`                                                |Best DRF schema generator                            |
|Async tasks        |Celery 5.x                                                       |Mature priority queues, retry, scheduling, cancel    |
|Broker             |RabbitMQ 3.13                                                    |Durable delivery, priority lanes, DLQ                |
|Result backend     |PostgreSQL via `django-celery-results`                           |Single DB to operate                                 |
|Language           |Python 3.12+                                                     |GDAL bindings, Django compatibility                  |
|Metadata DB        |PostgreSQL 16                                                    |GPS metadata only. No PostGIS extension required.    |
|GIS processor      |GDAL/OGR 3.9+ CLI                                                |Pin major version. No GeoPandas/Fiona for heavy work.|
|Storage            |Local FS or S3-compatible (MinIO/AWS/Wasabi)                     |Pluggable via interface                              |
|Resumable upload   |tus.io protocol via `django-tus` or sidecar `tusd`               |Standardized, frontend-library-friendly              |
|Preview rendering  |GDAL + GeoJSON sampling (no tile server)                         |Keep it simple                                       |
|Frontend (admin)   |Django admin (built-in)                                          |Free 60% of admin UI                                 |
|Frontend (operator)|Django templates + HTMX for interactivity                        |Lightweight, no SPA needed                           |
|Frontend (preview) |Embedded React component with MapLibre GL + a table library      |Only place where rich interactivity matters          |
|Observability      |Prometheus (`django-prometheus`, `celery-prometheus`) + JSON logs|From day one                                         |
|Deployment         |Docker + Docker Compose                                          |k8s manifests in v1.5                                |
|WSGI server        |Gunicorn                                                         |Standard                                             |

**Pinned versions** (worker container): GDAL 3.9.x, PROJ 9.4.x, with NTv2 grid files for North America datums and EPSG database 11.x.

**GDAL config** (set in worker env):

- `GDAL_CACHEMAX=512` (MB, configurable)
- `OGR_USE_NON_DEPRECATED_INTERFACES=YES`
- `OSR_DEFAULT_AXIS_MAPPING_STRATEGY=TRADITIONAL_GIS_ORDER` (lon,lat)
- `CPL_TMPDIR=/tmp/gpst`

-----

## 5. Core Concept: Workflows and Preview

GPS centers on **workflows**. Every job runs a workflow. A workflow is a sequence of steps ending in a destination dispatch.

### 5.1 Workflow Anatomy

```text
Source -> Validate -> Transform -> [Preview?] -> Dispatch -> Destination
```

- **Source** — uploaded file or remote URL
- **Validate** — structure, CRS, geometry checks
- **Transform** — zero or more operations: convert format, reproject, clip, simplify, fix-invalid, select/rename fields
- **Preview** — optional. Generates ephemeral preview output. User can pause workflow at preview, decide to continue or abort.
- **Dispatch** — routes the final output to the destination
- **Destination** — Download / Feature Mapper / External webhook / External database

### 5.2 v1 Workflows

|Code                       |Name                        |Destination      |Purpose                                                                                      |
|---------------------------|----------------------------|-----------------|---------------------------------------------------------------------------------------------|
|`convert_download`         |Convert and Download        |Download         |Convert input to selected format. User downloads file.                                       |
|`transform_download`       |Transform and Download      |Download         |Convert + reproject/clip/simplify. User downloads file.                                      |
|`publish_feature_mapper`   |Publish to Feature Mapper   |Feature Mapper   |Convert + transform + push signed payload to Feature Mapper.                                 |
|`publish_external_webhook` |Publish to External Webhook |Customer endpoint|Convert + transform + signed POST to customer URL with output payload or signed download URL.|
|`publish_external_database`|Publish to External Database|Customer DB      |Convert + transform + load to customer-supplied PostgreSQL/PostGIS connection.               |

### 5.3 Workflow Definition

Workflows are stored as configurable Django model rows (`Workflow`) with parameter schemas, not scattered controller logic. Each workflow defines:

- Code, name, description
- Required parameters (JSON Schema)
- Optional parameters (JSON Schema)
- Step sequence
- Destination type and destination-specific configuration
- Whether preview is offered
- Failure semantics (which steps are retryable via Celery)

### 5.4 Preview Layer

Preview is a **lightweight, ephemeral UI feature**, not a serving layer.

|ID        |Requirement                                                                                                            |
|----------|-----------------------------------------------------------------------------------------------------------------------|
|FR-PRE-001|Preview is generated on demand by a Celery task triggered after transformation.                                        |
|FR-PRE-002|Preview output includes feature count, bounding box, attribute schema, sample features (default 100, max 1000).        |
|FR-PRE-003|Preview exposes a temporary endpoint serving sampled GeoJSON with cache TTL of 1 hour.                                 |
|FR-PRE-004|The frontend renders preview as both a map view (MapLibre GL, embedded React) and a paginated attribute table.         |
|FR-PRE-005|Preview output is garbage-collected by a Celery beat task after TTL expiry or after workflow completes.                |
|FR-PRE-006|Preview is not a serving feature. Long-term browsing belongs to Feature Mapper or the future Raster/Vector Serving App.|
|FR-PRE-007|The user can pause a workflow at preview and choose to continue or abort.                                              |

### 5.5 Why Workflows, Not Workflow Builder

Workflows in v1 are pre-defined sequences with parameters. A graphical workflow builder is considered only when (a) at least 3 paying customers ask for steps the workflows don’t cover and (b) those steps differ between customers.

-----

## 6. User Roles (v1)

Three roles, no more. Implemented via Django’s built-in `Group` + custom permissions.

|Role        |Description                                                                                                                                   |
|------------|----------------------------------------------------------------------------------------------------------------------------------------------|
|**Service** |Machine-to-machine clients (Feature Mapper, internal automation). Auth via DRF Token or API key.                                              |
|**Admin**   |Human operator with full access to jobs, files, configuration, Django admin. Auth via Django session (JWT for SPA-style operator UI optional).|
|**Operator**|Human operator who can upload files, run workflows, download outputs. Cannot change configuration. Limited Django admin access.               |

Django’s permission system covers v1. Tenant-aware permissions (`org_id` scoping) added later via custom permission classes.

-----

## 7. Functional Requirements

### 7.1 File Upload and Remote Ingestion

|ID       |Requirement                                                                                                                                                                 |
|---------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|FR-UP-001|The system accepts uploads via DRF endpoint.                                                                                                                                |
|FR-UP-002|The system supports resumable upload (tus.io protocol) for files larger than 100 MB.                                                                                        |
|FR-UP-003|The system enforces a configurable maximum file size (default 5 GB).                                                                                                        |
|FR-UP-004|The system validates file extension and (where determinable) MIME type.                                                                                                     |
|FR-UP-005|The system calculates SHA-256 checksum streaming during upload.                                                                                                             |
|FR-UP-006|The system supports remote file ingestion: user supplies URL, optional auth headers, optional expected checksum. A Celery task fetches the file into storage as if uploaded.|
|FR-UP-007|The system enforces timeout, retry, and max-size policies on remote fetch.                                                                                                  |
|FR-UP-008|The system isolates per-job temporary directories.                                                                                                                          |
|FR-UP-009|The system rejects path-traversal attempts in supplied filenames.                                                                                                           |
|FR-UP-010|The system rejects Shapefile ZIPs missing `.shp`, `.shx`, or `.dbf`.                                                                                                        |
|FR-UP-011|The system flags (not rejects) Shapefile ZIPs missing `.prj` and requires manual CRS assignment before reprojection-using workflows run.                                    |
|FR-UP-012|The system falls back to CP1252 for `.dbf` encoding when `.cpg` is absent, with a warning. UTF-8 detected by content sniffing.                                              |
|FR-UP-013|The system supports hooks for AV/malware scanning before files become available to processing. (Mandatory for government tier; configurable.)                               |
|FR-UP-014|The system supports per-user / per-service upload quotas.                                                                                                                   |

### 7.2 Metadata Extraction

|ID       |Requirement                                                                                                                                                                                    |
|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|FR-MD-001|The system uses `ogrinfo -json` for metadata extraction.                                                                                                                                       |
|FR-MD-002|The system extracts: format, layer list, geometry type per layer, source CRS (with WKT and EPSG where available), bounding box, feature count, field schema, encoding, Z/M coordinate presence.|
|FR-MD-003|The system detects mixed-geometry-type layers and reports them.                                                                                                                                |
|FR-MD-004|The system persists metadata in `GeoFileLayer` Django model.                                                                                                                                   |

CRS handling: source CRS is stored as both EPSG code (when resolvable) and full WKT2 string. Comparison is by WKT or proj-string equivalence, not string match.

### 7.3 Validation

Severity levels: `info`, `warning`, `error`, `critical`.

|ID        |Requirement                                                                                                            |
|----------|-----------------------------------------------------------------------------------------------------------------------|
|FR-VAL-001|The system verifies that GDAL/OGR can open the file.                                                                   |
|FR-VAL-002|The system identifies layers that are empty, have no geometry, or have invalid geometries (OGC `ST_IsValid` semantics).|
|FR-VAL-003|The system flags (not rejects) self-intersecting polygons unless the chosen workflow requires strict OGC validity.     |
|FR-VAL-004|The system blocks dispatch if `error` or `critical` severity issues exist.                                             |
|FR-VAL-005|The system allows processing to proceed past `info` and `warning`.                                                     |
|FR-VAL-006|The system publishes a documented validation rule catalog (separate doc, versioned).                                   |

### 7.4 Job System (Celery-based)

Job states (mirrored from Celery + GPS-specific): `created`, `queued`, `running`, `awaiting_preview`, `completed`, `failed`, `cancelled`, `partial`.

|ID        |Requirement                                                                                                                                                                                                                        |
|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|FR-JOB-001|The system creates a `Job` model row and a Celery task for every workflow execution.                                                                                                                                               |
|FR-JOB-002|The system accepts an `Idempotency-Key` header on job creation; duplicate keys within 24h return the original job.                                                                                                                 |
|FR-JOB-003|The system supports job priority via Celery priority queues (low / normal / high). Small files default to high; files >500 MB default to normal.                                                                                   |
|FR-JOB-004|The system enforces per-job resource limits: max memory, max wall-clock time, max output size. Configurable per workflow. Implemented via Celery `soft_time_limit`, `time_limit`, and worker `--max-memory-per-child`.             |
|FR-JOB-005|The system supports cancel-running via Celery `revoke(terminate=True)`; the task’s cleanup handler removes temp files, drops ephemeral preview, and never leaves a destination half-delivered.                                     |
|FR-JOB-006|The system supports retry of failed jobs only for transient errors (worker crash, queue timeout, transient network error to destination). Permanent errors (validation failure, missing CRS, destination 4xx) are not auto-retried.|
|FR-JOB-007|The system tracks job progress as a percentage when the workflow can report it (via Celery task `update_state`).                                                                                                                   |
|FR-JOB-008|The system cleans up temporary files after completion, failure, or cancellation.                                                                                                                                                   |
|FR-JOB-009|The system persists worker hostname and execution duration.                                                                                                                                                                        |
|FR-JOB-010|The system pauses jobs at `awaiting_preview` when the workflow has preview enabled and the user has not yet confirmed. Pause timeout (default 24h) is configurable; a beat task expires unconfirmed jobs.                          |

### 7.5 Conversion

|ID         |Requirement                                                                                           |
|-----------|------------------------------------------------------------------------------------------------------|
|FR-CONV-001|The system uses `subprocess` with argument arrays (never shell strings) to invoke `ogr2ogr`.          |
|FR-CONV-002|The system captures stdout and stderr and persists them to `JobLog`.                                  |
|FR-CONV-003|The system supports output to GeoParquet (via GDAL `Parquet` driver).                                 |
|FR-CONV-004|The system supports layer selection for multi-layer sources.                                          |
|FR-CONV-005|The system preserves attributes and field types where the target format allows.                       |
|FR-CONV-006|The system converts technical GDAL stderr into a user-friendly message via a documented error catalog.|
|FR-CONV-007|The system enforces a per-conversion timeout (default 30 minutes; configurable).                      |

### 7.6 Reprojection

|ID        |Requirement                                                                                                                                             |
|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
|FR-CRS-001|The system defaults operational outputs to EPSG:4326. Web-map outputs may target EPSG:3857.                                                             |
|FR-CRS-002|The system allows explicit target CRS via EPSG code or WKT2 string.                                                                                     |
|FR-CRS-003|The system rejects reprojection if source CRS is unknown and no manual override is supplied.                                                            |
|FR-CRS-004|The system applies datum transformations using bundled NTv2 grid files. Coverage documented in `/docs/datum-grids.md`.                                  |
|FR-CRS-005|The system uses traditional GIS axis order (lon,lat) for EPSG:4326 by default. Configurable.                                                            |
|FR-CRS-006|The system provides a “guess CRS by extent” helper for files with missing or obviously wrong `.prj`. The helper is advisory — the operator must confirm.|

### 7.7 Geometry and Field Transformations

|ID        |Requirement                                                                                                                                                                  |
|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|FR-GEO-001|The system validates geometries using OGC `ST_IsValid` semantics.                                                                                                            |
|FR-GEO-002|The system offers fix-invalid via `ogr2ogr -makevalid`.                                                                                                                      |
|FR-GEO-003|The system documents multi-output behavior of fix-invalid. Stray points are dropped by default; configurable.                                                                |
|FR-GEO-004|The system supports topology-preserving simplification by default. Naive simplification is opt-in.                                                                           |
|FR-GEO-005|The system supports clip-by-AOI with explicit handling of features that span the boundary (clip vs. drop, configurable per workflow).                                        |
|FR-GEO-006|The system calculates area in square meters using geodesic computation and length in meters using geodesic computation. Cartesian computation is opt-in for projected layers.|
|FR-FLD-001|The system supports field selection (subset of fields to retain).                                                                                                            |
|FR-FLD-002|The system supports field rename.                                                                                                                                            |
|FR-FLD-003|The system supports adding constant-value fields (e.g., `source = 'agency_x'`).                                                                                              |

### 7.8 Workflow Definitions (v1)

#### 7.8.1 `convert_download`

1. Validate file.
1. Convert to `target_format`.
1. Store output. Return signed download URL.

#### 7.8.2 `transform_download`

1. Validate file.
1. Apply optional transforms: reproject, clip, simplify, fix-invalid, field ops.
1. Convert to `target_format`.
1. Optionally generate preview, pause for user confirmation.
1. Store output. Return signed download URL.

#### 7.8.3 `publish_feature_mapper`

1. Validate file.
1. Apply transforms (workflow parameter `incident_id` triggers clip-by-incident-boundary).
1. Convert to Feature Mapper’s expected format.
1. Optionally generate preview, pause for user confirmation.
1. POST signed (HMAC-SHA256) payload to Feature Mapper webhook.
1. Persist `DispatchedLayer` row with `target_system='feature_mapper'`.

#### 7.8.4 `publish_external_webhook`

1. Validate file.
1. Apply transforms.
1. Convert to `target_format`.
1. Optionally generate preview.
1. POST signed (HMAC-SHA256) payload to customer-supplied webhook URL. Payload is either inline output (small files) or a signed download URL (large files), per workflow parameter.
1. Persist `DispatchedLayer` row.

#### 7.8.5 `publish_external_database`

1. Validate file.
1. Apply transforms.
1. Optionally generate preview.
1. Connect to customer-supplied PostgreSQL (with PostGIS extension) connection string.
1. Load via `ogr2ogr -f PostgreSQL` to customer-specified schema and table. Use transactional staging table + atomic rename within the customer DB to avoid partial loads.
1. Persist `DispatchedLayer` row with destination metadata (schema, table, host hash). Connection string never persisted in plaintext; only a fingerprint stored.

### 7.9 Workflow Dispatcher

|ID         |Requirement                                                                                                                                          |
|-----------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
|FR-DISP-001|The system dispatches to exactly one destination per job.                                                                                            |
|FR-DISP-002|The system signs all webhook calls with HMAC-SHA256 over canonical JSON body, including timestamp + nonce to prevent replay.                         |
|FR-DISP-003|The system verifies destination availability with a connectivity check before dispatching large payloads.                                            |
|FR-DISP-004|The system tracks dispatch status per job and supports re-dispatch on transient failure.                                                             |
|FR-DISP-005|The system enforces a unique constraint on (`target_system`, `target_layer_id`, `target_database_fingerprint`) where applicable in `DispatchedLayer`.|
|FR-DISP-006|Customer-supplied secrets are stored envelope-encrypted (Fernet via `django-cryptography` or equivalent) and never logged.                           |
|FR-DISP-007|The system provides a dispatch-retry endpoint that re-delivers without re-running conversion.                                                        |

### 7.10 Storage

Local filesystem and S3-compatible storage are pluggable behind a single Django storage backend interface. Categories: original uploads, temporary processing files (per-job, isolated, auto-cleaned), processed outputs, ephemeral preview outputs, job logs.

|ID        |Requirement                                                                                                                                                                                                           |
|----------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|FR-STO-001|The system stores files via a `StorageBackend` interface with `LocalStorage` and `S3Storage` in v1 (use `django-storages` where it fits cleanly).                                                                     |
|FR-STO-002|The system generates signed/time-limited URLs for download (S3 native signed URLs; local equivalent is short-lived signed URL via DRF view).                                                                          |
|FR-STO-003|The system enforces documented retention per category (originals: indefinite by default; temp: cleaned at job end; outputs: 30 days configurable; preview: 1 hour; logs: 90 days). Retention enforced via Celery beat.|
|FR-STO-004|The system supports GDPR-style cascading delete via Django ORM cascade rules + audit-log entry.                                                                                                                       |

### 7.11 API Surface

```http
# Files
POST   /api/v1/files/upload                       # standard upload, <100MB
POST   /api/v1/files/upload/tus                   # resumable upload endpoint
POST   /api/v1/files/ingest-remote                # ingest from remote URL
GET    /api/v1/files/{id}
GET    /api/v1/files/{id}/metadata
DELETE /api/v1/files/{id}

# Validation
POST   /api/v1/files/{id}/validate
GET    /api/v1/files/{id}/validation-result

# Workflows and jobs
GET    /api/v1/workflows
POST   /api/v1/workflows/{code}/run               # creates a job (Celery task)
GET    /api/v1/jobs
GET    /api/v1/jobs/{id}
GET    /api/v1/jobs/{id}/logs
POST   /api/v1/jobs/{id}/cancel
POST   /api/v1/jobs/{id}/retry
POST   /api/v1/jobs/{id}/confirm-preview
POST   /api/v1/jobs/{id}/abort-after-preview

# Preview
GET    /api/v1/jobs/{id}/preview/summary
GET    /api/v1/jobs/{id}/preview/features         # paginated GeoJSON
GET    /api/v1/jobs/{id}/preview/attributes       # paginated table data

# Outputs and dispatched layers
GET    /api/v1/outputs/{id}/download              # signed redirect
GET    /api/v1/dispatched-layers
GET    /api/v1/dispatched-layers/{id}
POST   /api/v1/dispatched-layers/{id}/redispatch

# Destination credentials
GET    /api/v1/destination-credentials
POST   /api/v1/destination-credentials
DELETE /api/v1/destination-credentials/{id}

# Admin
GET    /api/v1/admin/stats
GET    /api/v1/admin/audit
# Django admin lives at /admin/  (built-in, separate from DRF)
```

|ID        |Requirement                                                                                                               |
|----------|--------------------------------------------------------------------------------------------------------------------------|
|FR-API-001|All DRF endpoints return structured JSON; errors follow RFC 7807 Problem Details (or DRF default with type/detail fields).|
|FR-API-002|All endpoints require auth (DRF token / session / API key).                                                               |
|FR-API-003|Job-creation and re-dispatch endpoints accept `Idempotency-Key` header.                                                   |
|FR-API-004|List endpoints support pagination via DRF defaults.                                                                       |
|FR-API-005|OpenAPI 3.1 spec generated by `drf-spectacular` served at `/api/v1/schema/`.                                              |
|FR-API-006|API versioning: breaking changes get a new prefix (`/api/v2/`). v1 supported for at least 12 months past v2 release.      |
|FR-API-007|Rate limiting: per-API-key via DRF throttling, default 60 RPM, configurable.                                              |

-----

## 8. Django Models / Database Design

GPS uses PostgreSQL for metadata only. No PostGIS extension required for GPS’s own DB. All models include `created_at`, `updated_at`, and a nullable `org_id UUID`.

### 8.1 Core Models (Django)

```python
# Simplified — actual definitions in app code

class GeoFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    org_id = models.UUIDField(null=True, blank=True, db_index=True)
    original_file_name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=20, choices=[('upload', 'Upload'), ('remote', 'Remote')])
    source_url = models.TextField(null=True, blank=True)
    file_type = models.CharField(max_length=100)
    mime_type = models.CharField(max_length=150)
    storage_backend = models.CharField(max_length=50)
    storage_path = models.TextField()
    size_bytes = models.BigIntegerField()
    checksum_sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey('auth.User', null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class GeoFileLayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    file = models.ForeignKey(GeoFile, on_delete=models.CASCADE, related_name='layers')
    layer_name = models.CharField(max_length=255)
    geometry_type = models.CharField(max_length=100)
    has_z = models.BooleanField(default=False)
    has_m = models.BooleanField(default=False)
    source_crs_epsg = models.IntegerField(null=True, blank=True)
    source_crs_wkt = models.TextField(null=True, blank=True)
    feature_count = models.BigIntegerField()
    bbox = models.JSONField()
    fields = models.JSONField()
    encoding = models.CharField(max_length=50)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

class Workflow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    code = models.SlugField(unique=True, max_length=100)
    name = models.CharField(max_length=255)
    description = models.TextField()
    destination_type = models.CharField(max_length=50, choices=[
        ('download', 'Download'),
        ('feature_mapper', 'Feature Mapper'),
        ('webhook', 'External Webhook'),
        ('database', 'External Database'),
    ])
    parameters_schema = models.JSONField()
    preview_enabled = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    org_id = models.UUIDField(null=True, blank=True, db_index=True)
    workflow_code = models.CharField(max_length=100)
    celery_task_id = models.CharField(max_length=255, db_index=True)
    status = models.CharField(max_length=20)
    priority = models.CharField(max_length=10, default='normal')
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    input_file = models.ForeignKey(GeoFile, null=True, on_delete=models.SET_NULL, related_name='input_jobs')
    output_file = models.ForeignKey(GeoFile, null=True, on_delete=models.SET_NULL, related_name='output_jobs')
    parameters = models.JSONField()
    progress_percent = models.IntegerField(default=0)
    preview_ready = models.BooleanField(default=False)
    preview_confirmed_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=100, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    requested_by = models.ForeignKey('auth.User', null=True, on_delete=models.SET_NULL)
    worker_hostname = models.CharField(max_length=100, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['org_id', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False),
                name='ux_jobs_idempotency'),
        ]
        indexes = [models.Index(fields=['status', '-created_at'])]

class JobLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='logs')
    log_level = models.CharField(max_length=10)
    message = models.TextField()
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

class DispatchedLayer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    org_id = models.UUIDField(null=True, blank=True, db_index=True)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='dispatches')
    target_system = models.CharField(max_length=100)
    target_layer_id = models.CharField(max_length=255, null=True, blank=True)
    target_endpoint = models.TextField(null=True, blank=True)
    target_database_fingerprint = models.CharField(max_length=64, null=True, blank=True)
    payload_metadata = models.JSONField(default=dict)
    status = models.CharField(max_length=20)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['target_system', 'target_layer_id', 'target_database_fingerprint'],
                condition=models.Q(target_layer_id__isnull=False),
                name='ux_dispatched_target'),
        ]

class DestinationCredential(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    org_id = models.UUIDField(null=True, blank=True, db_index=True)
    name = models.CharField(max_length=255)
    target_type = models.CharField(max_length=50)
    encrypted_secret = models.BinaryField()       # envelope-encrypted
    metadata = models.JSONField(default=dict)     # non-sensitive: URL, host, schema
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    org_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor_type = models.CharField(max_length=20)
    actor_id = models.CharField(max_length=100)
    action = models.CharField(max_length=100)
    resource_type = models.CharField(max_length=50, null=True, blank=True)
    resource_id = models.CharField(max_length=100, null=True, blank=True)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
```

Django admin is registered for all of the above with sensible `list_display`, `search_fields`, `list_filter`. This is the v1 admin UI — no custom build required.

-----

## 9. Authentication and Authorization

|ID         |Requirement                                                                                                                                |
|-----------|-------------------------------------------------------------------------------------------------------------------------------------------|
|FR-AUTH-001|Service-to-service auth uses DRF `TokenAuthentication` (rotatable).                                                                        |
|FR-AUTH-002|Human auth uses Django session for the server-rendered UI. For SPA-style operator UI, JWT via `djangorestframework-simplejwt` is available.|
|FR-AUTH-003|Webhook-out calls sign requests with HMAC-SHA256 over canonical JSON body, with timestamp + nonce to prevent replay.                       |
|FR-AUTH-004|Webhook-in calls (e.g., Feature Mapper triggering jobs in GPS) verify the same signature scheme.                                           |
|FR-AUTH-005|Every state-changing API call writes to `AuditLog` via DRF middleware.                                                                     |
|FR-AUTH-006|Secrets live in environment variables, an external secret store, or in `DestinationCredential` envelope-encrypted. Never logged.           |
|FR-AUTH-007|Django permission system enforces role-based access. v1 uses three groups: `Service`, `Admin`, `Operator`.                                 |

-----

## 10. Error Handling

### 10.1 Error Response Format

DRF default exception handler is replaced with one producing RFC 7807 Problem Details payloads.

```json
{
  "type": "https://docs.gps.livebird/errors/missing-crs",
  "title": "Missing CRS",
  "status": 422,
  "detail": "The uploaded file does not contain coordinate reference system information.",
  "instance": "/api/v1/jobs/01HX...",
  "extras": { "file_id": "..." }
}
```

### 10.2 Error Catalog

Documented catalog mapping GDAL/OGR stderr patterns and internal error codes to user-friendly messages. The catalog is a versioned document (`/docs/error-catalog.md`).

v1 ship requires at least the top 30 most common GDAL errors mapped.

-----

## 11. Non-Functional Requirements

### 11.1 Performance

|ID          |Requirement                                                                                                          |
|------------|---------------------------------------------------------------------------------------------------------------------|
|NFR-PERF-001|Status / metadata API responds within 300ms p95 under 50 RPS load. (Django + gunicorn with appropriate worker count.)|
|NFR-PERF-002|A 500MB Shapefile completes `transform_download` within 5 minutes on a 4-core / 16GB worker.                         |
|NFR-PERF-003|A 50MB Shapefile completes `convert_download` within 60 seconds on the same hardware.                                |
|NFR-PERF-004|Preview generation (sample features + bbox + schema) completes within 10 seconds for any file under 1GB.             |
|NFR-PERF-005|The system supports at least 4 concurrent Celery worker processes per host.                                          |

### 11.2 Scalability

Celery workers scale horizontally. Web service (Django + gunicorn) scales horizontally behind reverse proxy. Single-VM deployment supported (Docker Compose); multi-host deployment supported via shared PostgreSQL + RabbitMQ + S3.

### 11.3 Reliability

Worker crash mid-task: Celery acks-late + visibility timeout ensures task is re-delivered. Idempotency keys ensure the redo is safe. Dispatch is the final step and only happens after all earlier steps succeed. Original uploads are not auto-deleted. Dispatch retries do not re-run conversion.

### 11.4 Security

Authentication on every endpoint. Path-traversal and command-injection prevention enforced (subprocess argument arrays only). Uploaded files in non-public storage. Signed download URLs with TTL. Optional AV scanning hook (mandatory for government tier). Logs scrub credentials. Django permissions enforce resource-level access. Customer destination credentials envelope-encrypted at rest. Django CSRF protection on session-authenticated endpoints. Standard Django security middleware enabled.

Compliance-readiness baseline: SOC 2 control mapping documented. CJIS, FedRAMP, HIPAA: gap analysis documented; full compliance is per-deployment work, not v1 scope.

### 11.5 Maintainability

Service classes are framework-agnostic — both DRF views and Celery tasks call them with plain Python arguments. No engine-adapter abstractions. No persistent GIS-data layer. Pydantic (or Django serializers) for request/response. Unit tests for services. Integration tests for workflows end-to-end. Sample test datasets included.

### 11.6 Deployment

Docker + Docker Compose for v1. Helm chart and k8s manifests in v1.5. Environment-based configuration via `django-environ`. PostgreSQL and RabbitMQ provisioned via Compose for development; expected external-managed in production. GDAL/PROJ pinned in worker image.

-----

## 12. Configuration

Environment-variable based via `django-environ`. Documented in `/docs/configuration.md`. Categories: database connection, Celery broker, storage backend, upload limits, remote ingestion limits, worker concurrency and per-workflow resource limits, job and pause timeouts, GDAL config, default and allowed CRS list, API auth keys and JWT signing keys, integration endpoints, retention policies, encryption key for destination credentials.

-----

## 13. Monitoring and Observability

### 13.1 v1 Observability

`django-prometheus` exposes web metrics. `celery-prometheus-exporter` exposes worker metrics. Structured JSON logs to stdout via `python-json-logger`. OpenTelemetry tracing optional.

Key metrics: jobs created/completed/failed by workflow, job duration histogram, queue depth by priority, worker CPU/memory, storage bytes by category, API latency, dispatch success/failure per destination type.

### 13.2 v1 Dashboards

Two Grafana dashboards ship with the product: “Operations” (queue, jobs, dispatch failures) and “Capacity” (storage, CPU, memory).

-----

## 14. Deployment Architecture

### 14.1 Single VM (Default)

```text
docker-compose.yml
  web               (Django + gunicorn + DRF)
  worker            (Celery worker)        [scale: N]
  beat              (Celery beat, single)
  postgres          (PostgreSQL 16)
  rabbitmq          (3.13)
  reverse_proxy     (Caddy or Nginx)
```

### 14.2 Production On-Premise

PostgreSQL and RabbitMQ usually external. Storage is MinIO or NAS. Reverse proxy terminates TLS.

### 14.3 Air-Gapped Deployment

Supported. Container images and PROJ grid files shipped as a tarball. No external network calls during runtime. AV scanning hook calls customer-provided scanner on-host. Remote URL ingestion disabled in air-gapped mode unless customer provides an internal-only allowlist.

-----

## 15. Frontend (Built Into Django)

Three frontend surfaces, one Django project:

1. **Django Admin** — file list, job list with status filters, audit log view, destination-credential management (with the secret field hidden), workflow management, user/group management. Free. ~60% of v1 admin UI requirements covered out of the box.
1. **Operator UI** — Django templates with HTMX for interactivity. Screens: file upload (incl. tus.io and remote URL), validation result, workflow selection + parameters, job progress, output download list, dispatched-layers list.
1. **Preview UI** — A single embedded React component (built separately, served as a static bundle) rendered into a Django template. Uses MapLibre GL for the map and a lightweight table component for attributes. This is the only place where rich client-side interactivity is justified.

This avoids a separate Next.js app entirely. Saves ~3 weeks of frontend scaffolding.

-----

## 16. Roadmap

|Version|Theme                                                                                                 |Target                    |
|-------|------------------------------------------------------------------------------------------------------|--------------------------|
|v1.0   |Conversion + workflow dispatcher + preview, vector-only (raster spike outcome dependent)              |10 weeks                  |
|v1.1   |Customer-driven additions from v1 user feedback                                                       |TBD                       |
|v1.5   |k8s/Helm, destination: future Raster/Vector Serving App, AI assists (CRS inference, error explanation)|After v1 customer feedback|
|v2.0   |Raster (full) — only if v1 raster spike confirmed demand                                              |Demand-driven             |
|v2+    |Vector tiles, schema mapping AI, workflow builder, geocoding                                          |Demand-driven             |

Items beyond v1.5 tracked in `ROADMAP.md`. Not requirements until promoted by customer demand.

-----

## 17. MVP Acceptance Criteria

The v1.0 MVP ships when **all** of the following are demonstrably true:

1. User can upload Shapefile ZIP, GeoJSON, KML, GeoPackage, GeoParquet, and CSV.
1. Resumable upload (tus.io) works for files up to 5 GB.
1. Remote file ingestion from URL works, with checksum verification.
1. System extracts metadata and stores it.
1. System validates files and reports issues by severity.
1. `convert_download` workflow successfully outputs all listed v1 output formats.
1. `transform_download` workflow correctly applies reproject, clip, simplify, fix-invalid, and field operations.
1. `publish_feature_mapper` workflow publishes signed payloads to Feature Mapper and persists references.
1. `publish_external_webhook` workflow signs and delivers to a customer-supplied URL.
1. `publish_external_database` workflow loads to a customer-supplied PostgreSQL/PostGIS connection.
1. Reprojection to EPSG:4326 and EPSG:3857 works correctly with documented axis-order policy.
1. Preview generates feature count, bbox, schema, and sample features within NFR-PERF-004 limits, viewable on map and table.
1. User can pause workflow at preview, confirm to continue, or abort.
1. Performance targets in NFR-PERF-002 / 003 are met on reference hardware.
1. Audit log captures all state-changing actions.
1. Django RBAC enforces three working roles via Groups.
1. Idempotent job creation works across retries (Celery + DB unique constraint).
1. Cancel-running cleans up partial state and never leaves a destination half-delivered.
1. Re-dispatch endpoint can re-deliver to destination without re-running conversion.
1. Destination credentials are envelope-encrypted at rest and never logged.
1. Prometheus metrics and structured logs are emitted from web and worker.
1. OpenAPI 3.1 spec via `drf-spectacular` is published and accurate.
1. Django admin works for all core models with sensible filters.
1. Docker Compose stack starts cleanly on a fresh host.
1. Error catalog has at least 30 mapped GDAL errors.
1. Raster spike outcome documented (go / no-go decision recorded).

-----

## 18. Risks and Mitigations

|Risk                                                    |Likelihood|Impact|Mitigation                                                                                                                               |
|--------------------------------------------------------|----------|------|-----------------------------------------------------------------------------------------------------------------------------------------|
|GDAL version drift across deployments                   |Medium    |High  |Pin GDAL/PROJ in worker image. Regression tests against pinned versions.                                                                 |
|Datum transformation accuracy issues                    |Medium    |High  |Bundle NTv2 grids. Document coverage. Warn on out-of-grid reprojections.                                                                 |
|Feature Mapper API contract changes break dispatch      |Medium    |Medium|Versioned destination adapter + consumer-driven contract tests.                                                                          |
|Customer webhook returns 5xx repeatedly                 |High      |Low   |Bounded retry with exponential backoff + DLQ + redispatch endpoint.                                                                      |
|Customer DB connection fails or has wrong perms         |High      |Low   |Pre-flight connectivity + permission check before loading. Clear error messages.                                                         |
|Large files OOM workers                                 |Medium    |High  |Celery `--max-memory-per-child`. Per-job memory limits via cgroups. Streaming where GDAL supports it. Reject files exceeding hard limits.|
|Cancelled-running job leaves orphaned customer-DB tables|Medium    |High  |Transactional staging schema in customer DB; atomic rename at end; rollback on cancel.                                                   |
|Scope creep into FME or serving territory               |High      |High  |SRS explicitly cuts engine adapters, persistent GIS data layer, and serving. Roadmap items require customer evidence.                    |
|AV scanning required by government client at last minute|Medium    |Medium|AV hook in v1, configurable.                                                                                                             |
|Raster demand turns out high after v1 ships without it  |Low       |Medium|2-week raster spike informs the decision.                                                                                                |
|Preview becomes a de facto serving feature              |Medium    |Medium|TTL-bounded, sample-only, hard cap on feature count. Documented as not a serving feature.                                                |
|Django + Celery async throughput too low under load     |Low       |Low   |Adequate for on-prem use case (low concurrency). Move to ASGI + Uvicorn if needed in v2.                                                 |
|Embedded React preview component becomes its own SPA    |Medium    |Medium|Strict scope: map + table only. No additional pages. No routing. Pure component.                                                         |

-----

## 19. Implementation Guidance

This is guidance for the engineering team, not a build script for an AI agent.

### 19.1 Phased Build (10 weeks)

**Weeks 1-2:** Django project skeleton, app structure, models + migrations, Django admin registration, Celery wiring, config via `django-environ`, audit logging middleware, storage abstraction, file upload (standard + tus.io + remote URL).

**Weeks 3-4:** Metadata extraction service, validation service, Celery tasks for ingest/validate, base `convert_download` workflow end-to-end. Operator UI templates (Django + HTMX) for upload + job list.

**Weeks 5-6:** Transformation service (reproject, clip, simplify, fix-invalid, field ops). `transform_download` workflow. Preview service. Embedded React preview component (MapLibre + table). Pause-and-confirm flow.

**Weeks 7-8:** Workflow dispatcher. `publish_feature_mapper`, `publish_external_webhook`, `publish_external_database` workflows. Webhook signing utility. Destination credentials (envelope-encrypted). Re-dispatch endpoint.

**Weeks 9-10 (parallel with weeks 7-8):** Raster spike. Two engineers, two weeks. Output: go/no-go decision document.

**Throughout:** Hardening, error catalog growth, performance testing, docs.

### 19.2 Code Quality Rules

- Service classes are framework-agnostic Python. Both DRF views and Celery tasks call them.
- Django serializers (DRF) for request/response. Pydantic for internal service contracts where helpful.
- `subprocess.run` with argument arrays for GDAL/OGR. Never shell strings.
- Stdout and stderr captured and persisted to `JobLog`.
- All file paths validated through a single utility before disk access.
- UUID v7 for all primary keys.
- Storage and destinations defined behind interfaces (`StorageBackend`, `DispatchDestination`). **Do not** define interfaces for things without multiple implementations (no `EngineAdapter`).
- Tests for: metadata extraction, validation rules, idempotency, workflow execution end-to-end, preview generation, dispatch signing, dispatch failure recovery.
- Customer credentials decrypted into memory only at use time and zeroed after.
- Celery tasks are idempotent and check `Job.status` before doing destructive work.

### 19.3 Project Structure

```text
geo-processing-server/
  manage.py
  pyproject.toml19.3 Project Structure
  
  gps/                          # Django project
    settings/{base,dev,prod}.py
    urls.py
    celery.py
  apps/
    core/                       # config, logging, errors, crypto, audit middleware
    files/                      # GeoFile, GeoFileLayer, upload, remote ingest
    workflows/                  # Workflow, Job, JobLog, workflow runner
    transformations/            # transformation service (framework-agnostic)
    preview/                    # preview service + DRF endpoints
    dispatch/                   # DispatchedLayer, destination adapters, credentials
    audit/                      # AuditLog
    api/v1/                     # DRF viewsets, serializers, routers (thin wrappers around services)
    ui/                         # Django templates + HTMX views for operator UI
    preview_frontend/           # React source for the preview component (built to static bundle)
  services/                     # framework-agnostic shared services
    gdal_runner.py
    metadata.py
    validation.py
    transformation.py
    preview.py
    dispatch.py
    remote_ingest.py
    error_catalog.py
  tests/{unit,integration,fixtures}/
  docker/{Dockerfile.web,Dockerfile.worker,docker-compose.yml}
  docs/{configuration,error-catalog,datum-grids,api}.md
  ROADMAP.md
  README.md
```

`services/` contains the framework-agnostic core. `apps/` contains Django-specific code (models, views, admin). Both Django views and Celery tasks call into `services/`. This is the most important boundary in the codebase.

No placeholder modules. No “future engine” files. No persistent-GIS-data layer.

-----

## 20. Final Product Statement

```text
Geo Processing Server v1 is a conversion, transformation, and routing service
built on Django + DRF + Celery.

It takes messy GIS data from agencies, validates and transforms it,
lets the user preview the result, and delivers it to wherever the user wants:
download, Feature Mapper, customer webhook, or customer database.

It does not store, serve, or browse data long-term.
That is the job of Feature Mapper, the future Raster/Vector Serving App,
or the customer's own systems.

Django admin handles 60% of admin UI for free.
The only custom frontend is a small React component for the preview map and table.
```

Anything that doesn’t directly serve that statement is out of scope for v1. Anything that does is in scope.