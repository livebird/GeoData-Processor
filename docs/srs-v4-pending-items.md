# Geo Processing Server — SRS v4 Gap Analysis (Pending Items)

**Generated:** 2026-06-20
**Compared against:** `docs/geo processing server srs v4.md` (v4.0 Draft)
**Codebase:** `apps/` (Django `gps` project + `converter` app) and `gdal_server/`

> Purpose: enumerate, in detail, what the SRS v4 requires that the current implementation does **not yet** satisfy. Items are grouped by SRS section. Each item is marked:
> **❌ Missing** · **🟡 Partial** · **✅ Done** (Done items listed only where useful for context).

---

## 0. Executive Summary

The implementation is a **working monolithic Django app** (`converter`) that covers a meaningful slice of the SRS: most data models exist, file upload (including a real tus.io endpoint) works, GDAL/OGR-style conversion across most formats works, metadata/validation/preview generation work, and the operator UI (Django templates) is broadly present. RBAC tables, audit logging, dispatch records, and an idempotency constraint exist.

However, the system **diverges from the SRS architecture in several load-bearing ways**, and a number of explicit MVP acceptance criteria (Section 17) are **not met**. The largest gaps:

| Theme | Status | Impact |
|-------|--------|--------|
| **Celery as the execution engine** | 🟡 Configured but bypassed — jobs run on Python **threads**, not Celery tasks | High — breaks cancel, retry, priority, resource limits, reliability story |
| **DRF API layer** | ❌ Not used — plain Django function views, no serializers/viewsets | High — violates Section 7.11, 9, FR-API-* |
| **OpenAPI (`drf-spectacular`)** | ❌ Absent | High — MVP criterion #23 |
| **Credential envelope encryption** | ❌ Field exists, no cipher | High — MVP criterion #20, FR-DISP-006, security |
| **The 3 publish workflows (FM / webhook / DB)** | 🟡 Placeholder task stubs, not wired end-to-end | High — MVP criteria #8/#9/#10 |
| **Prometheus / observability** | ❌ Absent | High — MVP criterion #21 |
| **Docker / Docker Compose** | ❌ No Dockerfile or compose file | High — MVP criterion #24 |
| **Supplementary docs** (error catalog, datum grids, config, ROADMAP) | ❌ None exist | Medium — MVP criteria #25, FR-VAL-006, FR-CRS-004 |
| **UUID v7 primary keys** | ❌ All models use UUID v4 | Low/Medium — explicit code-quality rule (19.2) |
| **S3-compatible storage backend** | ❌ Local FS only | Medium — FR-STO-001 |
| **Transformations: clip, simplify, geodesic, add-field** | ❌ Missing | High — MVP criterion #7, FR-GEO-004/005/006 |

---

## 1. Architecture Deviations (SRS §3, §19.3)

### 1.1 ❌ `services/` framework-agnostic layer not as specified
- SRS §3.2 / §19.3 mandate a `services/` package (`gdal_runner.py`, `metadata.py`, `validation.py`, `transformation.py`, `preview.py`, `dispatch.py`, `remote_ingest.py`, `error_catalog.py`) callable by **both** DRF views and Celery tasks, with **no framework coupling** ("the most important boundary in the codebase").
- **Actual:** Core logic lives inside `apps/converter/views.py` (3,600+ lines) and `batchconvert.py`, tightly coupled to Django request/response and threading. There is an `apps/services/` directory but it contains only `test_conversion_matrix.py`. No `metadata.py`, `validation.py`, `transformation.py`, `preview.py`, `dispatch.py`, `remote_ingest.py`, or `error_catalog.py` service modules.
- **Pending:** Extract the conversion/validation/metadata/preview/dispatch logic into framework-agnostic service classes (`TransformationService.run(file_id, params)` style) per §3.2 principle 3.

### 1.2 🟡 Celery wired but not the execution path
- SRS §3.2: "Celery workers run as a **separate service**… The web service does not block on processing." Job system (FR-JOB-*) is explicitly Celery-based.
- **Actual:** `gps/celery.py` and broker config exist, and `tasks.py` defines task stubs — but real conversions are run on a **daemon Python thread** (`_conversion_worker`, `views.py:~2008`). The web process executes the work.
- **Pending:** Move all long-running work to Celery tasks; run a dedicated worker service. This unblocks cancel/retry/priority/resource-limit requirements below.

### 1.3 ❌ Project structure differs from §19.3
- SRS prescribes `gps/settings/{base,dev,prod}.py`, split apps (`core`, `files`, `workflows`, `transformations`, `preview`, `dispatch`, `audit`, `api/v1`, `ui`, `preview_frontend`), and `services/`.
- **Actual:** Single `gps/settings.py`; one fat `converter` app with thin proxy-model sub-packages (`files/`, `workflows/`, `dispatch/`, `audit/` contain only proxy models for admin grouping). No `api/v1` app, no `transformations` app, no `preview_frontend` React source.
- **Pending:** Optional structural refactor; at minimum split settings into base/dev/prod and create a real `api/v1` DRF app.

### 1.4 ❌ FastAPI/uvicorn leftovers contradict stack
- `requirements.txt` lists `fastapi`, `uvicorn`, `pydantic>=1.10`, `pyodbc`, `python-multipart` — not part of the Django+DRF+Celery stack (§4). `gdal_server/` appears to be a separate standalone Flask/FastAPI-style app outside the SRS scope.
- **Pending:** Reconcile/remove the parallel `gdal_server/` app and stray deps, or document them as out of scope.

---

## 2. Technology Stack Gaps (SRS §4)

Required-but-absent dependencies (not in `requirements.txt`):

| Required (SRS §4) | Purpose | Status |
|-------------------|---------|--------|
| `djangorestframework` | API framework — all of §7.11 | ❌ Missing |
| `drf-spectacular` | OpenAPI 3.1 schema | ❌ Missing |
| `django-tus` / `tusd` | Resumable upload (per §4; note: a hand-rolled tus endpoint exists) | ❌ lib missing |
| `django-storages` | S3-compatible storage | ❌ Missing |
| `django-celery-results` | PostgreSQL result backend | ❌ Missing (uses RPC backend) |
| `django-environ` | Env-based config | ❌ Missing (hardcoded settings) |
| `django-prometheus` / `celery-prometheus-exporter` | Metrics | ❌ Missing |
| `python-json-logger` | Structured JSON logs | ❌ Missing |
| `djangorestframework-simplejwt` | Optional JWT | ❌ Missing |
| `cryptography` / `django-cryptography` | Credential envelope encryption | ❌ Missing |

Other §4 items pending:
- ❌ **GDAL/PROJ version pinning** (GDAL 3.9.x, PROJ 9.4.x, EPSG 11.x, NTv2 grids) — no pinned worker image exists.
- ❌ **GDAL env config** (`GDAL_CACHEMAX`, `OGR_USE_NON_DEPRECATED_INTERFACES`, `OSR_DEFAULT_AXIS_MAPPING_STRATEGY=TRADITIONAL_GIS_ORDER`, `CPL_TMPDIR`) — not set anywhere.
- 🟡 **Settings hardcoded** — DB name/user/password and broker URL are literals in `gps/settings.py` (also a security concern). Should be `django-environ`-driven (§12).

---

## 3. File Upload & Remote Ingestion (SRS §7.1)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-UP-001 | Upload via **DRF** endpoint | 🟡 | Upload works, but via plain Django view, not DRF. |
| FR-UP-002 | Resumable tus.io for >100 MB | ✅ | Hand-rolled tus 1.0.0 endpoint (`views.py:386-567`). Consider standard lib per §4. |
| FR-UP-003 | Max size (5 GB) | ✅ | Enforced. |
| FR-UP-004 | Extension + MIME validation | ✅ | Signature sniffing present. |
| FR-UP-005 | Streaming SHA-256 | ✅ | `_file_sha256`. |
| FR-UP-006 | Remote URL ingestion | 🟡 | Implemented (`ingest_remote_url`) but runs inline, not as a **Celery task** as §7.1 specifies. |
| FR-UP-007 | Remote fetch timeout/retry/max-size | ✅ | Retry+backoff+size cap present. |
| FR-UP-008 | Per-job temp dir isolation | ✅ | UUID workspaces. |
| FR-UP-009 | Path-traversal rejection | ✅ | `check_path_traversal`. |
| FR-UP-010 | Reject Shapefile ZIP missing `.shp/.shx/.dbf` | ✅ | `validate_shapefile_zip`. |
| FR-UP-011 | Flag missing `.prj`, require manual CRS | ✅ | `prj_missing` flag + assign-CRS flow. |
| FR-UP-012 | **CP1252 fallback** for `.dbf` when `.cpg` absent | ❌ | Only `utf-8, errors='ignore'`. No CP1252 fallback or content-sniff path. |
| FR-UP-013 | AV/malware scan hook | ✅ | `scan_file_for_malware` (hook + EICAR), disabled by default. |
| FR-UP-014 | Per-user/service upload quotas | ✅ | `check_and_log_quota` + `UploadQuotaLog`. |

**Pending in §7.1:** FR-UP-012 (CP1252), and move FR-UP-001/006 onto DRF + Celery.

---

## 4. Metadata Extraction (SRS §7.2)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-MD-001 | Use **`ogrinfo -json`** | ❌ | Uses geopandas/rasterio, not `ogrinfo -json`. SRS names the tool explicitly. |
| FR-MD-002 | Extract format/layers/geom-type/CRS(WKT+EPSG)/bbox/count/fields/encoding/Z-M | 🟡 | Most fields captured, but driven by GeoPandas, not the `ogrinfo` contract; Z/M detection is implicit. |
| FR-MD-003 | Detect & report **mixed-geometry** layers | ❌ | No mixed-geometry detection/reporting. |
| FR-MD-004 | Persist to `GeoFileLayer` | ✅ | Model exists and is populated. |

**Pending:** Switch metadata extraction to an `ogrinfo -json` wrapper (`services/metadata.py`); add mixed-geometry detection; store CRS as both EPSG **and** WKT2 with proj-equivalence comparison (§7.2 closing note).

---

## 5. Validation (SRS §7.3)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-VAL-001 | GDAL can open file | ✅ | Open attempt + exception capture. |
| FR-VAL-002 | Identify empty/no-geom/invalid-geom layers (ST_IsValid) | ✅ | Shapely `make_valid`/`is_valid`. |
| FR-VAL-003 | **Flag** (not reject) self-intersecting polygons unless workflow needs strict OGC | 🟡 | Validity detected, but no per-workflow strict/lenient policy switch. |
| FR-VAL-004 | **Block dispatch** on `error`/`critical` | ❌ | No gating mechanism — severity is reported but does not block workflow execution/dispatch. |
| FR-VAL-005 | Allow proceed past info/warning | 🟡 | Implicitly allowed (nothing blocks). |
| FR-VAL-006 | Published **validation rule catalog** (versioned doc) | ❌ | No `docs/validation-rules.md`. |

**Pending:** FR-VAL-004 dispatch-gating on severity; FR-VAL-003 per-workflow strictness; FR-VAL-006 versioned catalog doc.

---

## 6. Job System (SRS §7.4) — Celery-based

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-JOB-001 | `Job` row + Celery task per workflow | 🟡 | Job rows created; execution is **threaded**, not a Celery task. |
| FR-JOB-002 | `Idempotency-Key`, dedupe within 24h | 🟡 | DB unique constraint `(org_id, idempotency_key)` exists; 24h-window header handling not fully wired through DRF. |
| FR-JOB-003 | **Priority queues** (low/normal/high; >500 MB→normal) | ❌ | `priority` field exists; no Celery priority routing. |
| FR-JOB-004 | Resource limits (`soft_time_limit`/`time_limit`/`--max-memory-per-child`) | 🟡 | Time limits set in `celery.py`, but since work runs on threads they are not enforced; no memory cap. |
| FR-JOB-005 | **Cancel-running** via `revoke(terminate=True)` + cleanup, no half-delivery | ❌ | Threaded jobs cannot be revoked/terminated; no terminate path. |
| FR-JOB-006 | Retry **transient-only** | 🟡 | Example retry in `tasks.py` stub; not applied to the real conversion path; no transient-vs-permanent classification. |
| FR-JOB-007 | Progress percent via `update_state` | 🟡 | `progress_percent` updated manually; not via Celery `update_state`. |
| FR-JOB-008 | Temp cleanup after end/fail/cancel | 🟡 | Cleanup on success/error paths; no beat task for orphans. |
| FR-JOB-009 | Persist worker hostname + duration | 🟡 | Fields exist; hostname not populated (no `socket.gethostname()`); duration partial. |
| FR-JOB-010 | Pause at `awaiting_preview`, 24h timeout via beat | 🟡 | Preview confirm/abort flow exists; no `awaiting_preview` state enum value used and **no beat task** to expire unconfirmed jobs. |

**Job-state coverage:** SRS requires `created, queued, running, awaiting_preview, completed, failed, cancelled, partial`. Implementation uses ad-hoc strings (`pending/processing/completed/failed/cancelled`); **`queued`, `awaiting_preview`, `partial` are absent**.

**Pending (high priority):** Re-platform job execution onto Celery so FR-JOB-003/004/005/006/007/010 become real; add beat tasks; complete the state machine.

---

## 7. Conversion (SRS §7.5)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-CONV-001 | `subprocess` argument arrays for `ogr2ogr` | 🟡 | `gdal_cli_convert.py` builds arg arrays correctly, **but it is a reference module — production path uses geopandas/rasterio wrappers, not `ogr2ogr`**. SRS §3.2 says "GDAL/OGR CLI is the only processor in v1." |
| FR-CONV-002 | Capture stdout/stderr → `JobLog` | 🟡 | CLI module captures output, but production wrappers log to console/exceptions, not consistently to `JobLog`. |
| FR-CONV-003 | GeoParquet via `Parquet` driver | ✅ | Supported. |
| FR-CONV-004 | Layer selection for multi-layer sources | ❌ | No layer-select parameter (`-sql`/layer name) in the conversion path. |
| FR-CONV-005 | Preserve attributes/field types | ✅ | Generally preserved. |
| FR-CONV-006 | GDAL stderr → friendly message via **error catalog** | ❌ | No error catalog mapping (`docs/error-catalog.md` missing). |
| FR-CONV-007 | Per-conversion timeout (default 30 min) | ❌ | No timeout on the conversion subprocess/wrapper. |

**Input formats:** ✅ Shapefile ZIP, GeoJSON, KML, KMZ, GeoPackage, CSV, GeoParquet — **❌ GPX missing**.
**Output formats:** ✅ all listed (GeoJSON, GeoPackage, FlatGeobuf, GeoParquet, KML, CSV, Shapefile ZIP).

**Pending:** Standardize on `ogr2ogr` CLI (§3.2 principle), add GPX input, layer selection (FR-CONV-004), per-conversion timeout (FR-CONV-007), and error-catalog translation (FR-CONV-006).

---

## 8. Reprojection (SRS §7.6)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-CRS-001 | Default EPSG:4326; web-map 3857 | ✅ | Supported. |
| FR-CRS-002 | Target CRS via EPSG or WKT2 | ✅ | Supported. |
| FR-CRS-003 | Reject reprojection when source CRS unknown & no override | 🟡 | Raster path rejects; vector path **silently assumes EPSG:4326** — violates intent. |
| FR-CRS-004 | NTv2 datum grids + coverage doc | ❌ | No bundled NTv2 grids; no `docs/datum-grids.md`. |
| FR-CRS-005 | Traditional GIS axis order (lon,lat), configurable | ❌ | No explicit `OSR_DEFAULT_AXIS_MAPPING_STRATEGY` / axis-order policy. |
| FR-CRS-006 | "Guess CRS by extent" advisory helper | ❌ | Not implemented (assign-CRS UI exists but no extent-based guess). |

**Pending:** FR-CRS-003 (stop silent 4326 assumption on vectors), FR-CRS-004 (NTv2 + doc), FR-CRS-005 (axis-order policy), FR-CRS-006 (guess-by-extent helper).

---

## 9. Geometry & Field Transformations (SRS §7.7)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-GEO-001 | ST_IsValid semantics | ✅ | Via Shapely. |
| FR-GEO-002 | Fix-invalid via `ogr2ogr -makevalid` | 🟡 | Done via Shapely `make_valid`, not `ogr2ogr -makevalid`. |
| FR-GEO-003 | Document multi-output of fix-invalid; drop stray points (configurable) | ❌ | No documented behavior / configurability. |
| FR-GEO-004 | **Topology-preserving simplification** (naive opt-in) | ❌ | No simplify operation at all. |
| FR-GEO-005 | **Clip-by-AOI** with boundary handling | ❌ | Not implemented. |
| FR-GEO-006 | **Geodesic area/length** (Cartesian opt-in) | ❌ | No area/length computation. |
| FR-FLD-001 | Field selection (subset) | 🟡 | Only a geometry-only fallback; no user-driven subset. |
| FR-FLD-002 | Field rename | 🟡 | Only auto-rename for Shapefile DBF compliance; no user-driven rename. |
| FR-FLD-003 | Add constant-value field | ❌ | Not implemented. |

**Pending (blocks MVP criterion #7):** simplify, clip-by-AOI, geodesic measures, user-driven field select/rename, add-constant-field. This is the bulk of the `transform_download` value proposition.

---

## 10. Workflow Definitions (SRS §5, §7.8)

The 5 v1 workflows:

| Workflow | Status | Notes |
|----------|--------|-------|
| `convert_download` | 🟡 | Conversion + download works; not modeled as a clean workflow-runner step sequence. |
| `transform_download` | 🟡 | Convert + download path exists, but transforms (clip/simplify/geodesic/field ops) are missing (§9). |
| `publish_feature_mapper` | ❌ | Only a placeholder task stub in `tasks.py`; not wired end-to-end; no real signed POST. |
| `publish_external_webhook` | ❌ | Placeholder stub; no real signed delivery. |
| `publish_external_database` | ❌ | Placeholder stub; no `ogr2ogr -f PostgreSQL` staging-table + atomic-rename load. |

- 🟡 Workflows **are** stored as `Workflow` model rows with `parameters_schema` (good, matches §5.3), and `ensure_default_workflows()` seeds a few — but only ~3 defaults, and the publish destinations are not executable.
- ✅ Preview pause/confirm flow exists (`confirm-preview` / `abort-after-preview`).

**Pending:** Implement the three `publish_*` workflows end-to-end (signed dispatch, DB staging load), and a real workflow runner that executes the documented step sequences per §7.8.

---

## 11. Workflow Dispatcher (SRS §7.9)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-DISP-001 | Exactly one destination per job | ✅ | Enforced by design. |
| FR-DISP-002 | HMAC-SHA256 over canonical JSON + timestamp + nonce (anti-replay) | ❌ | Only a simulated hash in a stub; no canonical-JSON signing, no timestamp/nonce. |
| FR-DISP-003 | Connectivity check before large dispatch | ❌ | Not implemented. |
| FR-DISP-004 | Per-job dispatch status + re-dispatch on transient failure | 🟡 | Status tracked; redispatch endpoint exists; transient-failure handling minimal. |
| FR-DISP-005 | Unique `(target_system, target_layer_id, target_db_fingerprint)` | ✅ | Constraint present. |
| FR-DISP-006 | Secrets **envelope-encrypted** (Fernet/`django-cryptography`), never logged | ❌ | `encrypted_secret` is a raw `BinaryField`; **no cipher**; admin masks display only. |
| FR-DISP-007 | Dispatch-retry endpoint (no re-conversion) | 🟡 | `redispatch_action` exists; not proven to skip conversion / re-sign properly. |

**Pending (high):** FR-DISP-002 real HMAC signing, FR-DISP-003 connectivity preflight, FR-DISP-006 actual encryption.

---

## 12. Storage (SRS §7.10)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-STO-001 | `StorageBackend` interface w/ `LocalStorage` + `S3Storage` | ❌ | Local filesystem only; no pluggable backend, no S3. |
| FR-STO-002 | Signed/time-limited download URLs | 🟡 | Output download endpoint exists; no true signed/TTL URL (S3-native or local signed). |
| FR-STO-003 | Documented retention per category via beat (orig/temp/output/preview/logs) | ❌ | No retention beat tasks; preview uses Django cache TTL only. |
| FR-STO-004 | GDPR cascading delete + audit entry | 🟡 | ORM cascades exist; no dedicated GDPR-delete flow + audit. |

**Pending:** S3 backend + `StorageBackend` interface, signed-URL generation, retention beat tasks, GDPR-delete flow.

---

## 13. API Surface (SRS §7.11) — DRF

**Framework:** ❌ DRF not actually used (no serializers/viewsets); endpoints are plain Django function views.

Endpoint coverage vs. the documented REST surface:

| Endpoint group | Status |
|----------------|--------|
| `POST /files/upload`, `/upload/tus`, `/ingest-remote` | 🟡 present (non-DRF; paths differ) |
| `GET /files/{id}`, `/metadata`, `DELETE` | 🟡 partial |
| `POST /files/{id}/validate`, `GET /validation-result` | 🟡 partial |
| `GET /workflows`, `POST /workflows/{code}/run` | 🟡 partial |
| `GET /jobs`, `/jobs/{id}`, `/jobs/{id}/logs` | 🟡 partial |
| `POST /jobs/{id}/cancel`, `/retry` | ❌ cancel/retry not real (threaded) |
| `POST /jobs/{id}/confirm-preview`, `/abort-after-preview` | ✅ |
| `GET /jobs/{id}/preview/summary` `/features` `/attributes` | ✅ |
| `GET /outputs/{id}/download` | 🟡 |
| `GET /dispatched-layers`, `/{id}`, `POST /{id}/redispatch` | 🟡 |
| `GET/POST/DELETE /destination-credentials` | 🟡 (no encryption) |
| `GET /admin/stats`, `/admin/audit` | 🟡 |

| ID | Requirement | Status |
|----|-------------|--------|
| FR-API-001 | RFC 7807 Problem Details errors | ❌ plain `{'error': ...}` JSON |
| FR-API-002 | Auth on every endpoint | 🟡 session only; many API views likely unauthenticated |
| FR-API-003 | `Idempotency-Key` on job-create/redispatch | 🟡 partial |
| FR-API-004 | Pagination via DRF defaults | 🟡 custom pagination, not DRF |
| FR-API-005 | **OpenAPI 3.1 via `drf-spectacular`** at `/api/v1/schema/` | ❌ absent |
| FR-API-006 | Versioning (`/api/v2` policy) | 🟡 `/api/v1/` prefix only |
| FR-API-007 | Rate limiting (DRF throttle, 60 RPM) | ❌ absent |

**Pending (high):** Adopt DRF properly (serializers, viewsets, token auth, throttling), RFC 7807 handler, `drf-spectacular` schema.

---

## 14. Models / Database (SRS §8)

✅ All 8 SRS models exist (`GeoFile`, `GeoFileLayer`, `Workflow`, `GeoProcessingJob`=Job, `GeoProcessingJobLog`=JobLog, `DispatchedLayer`, `DestinationCredential`, `AuditLog`), registered in Django admin.

Pending deviations:

| Item | SRS | Actual | Status |
|------|-----|--------|--------|
| Primary keys | **UUID v7** (`uuid7`, §19.2) | `uuid.uuid4` everywhere | ❌ |
| `org_id` on all models | required everywhere | **missing** on `GeoFileLayer`, `Workflow`, `JobLog` | ❌ |
| `org_id` type | `UUIDField` | `AuditLog.org_id` is `CharField(36)` | 🟡 type mismatch |
| `updated_at` on all models | required | **missing** on `GeoFileLayer`, `Workflow`, `JobLog`, `DispatchedLayer`, `AuditLog` | 🟡 |
| `encrypted_secret` | envelope-encrypted | raw `BinaryField`, no cipher | ❌ |
| Extra non-SRS models | — | `ConversionJob`, `ConversionInputFile`, `LocationExport`, `SearchLog`, `BatchTableDetails`, `Rbac*` | (legacy/parallel models — consolidate) |

**Pending:** UUID v7 default, add missing `org_id`/`updated_at`, fix `AuditLog.org_id` type, consolidate the legacy `ConversionJob`-family with the SRS `Job` model.

---

## 15. Authentication & Authorization (SRS §9)

| ID | Requirement | Status |
|----|-------------|--------|
| FR-AUTH-001 | DRF `TokenAuthentication` (rotatable) | ❌ absent |
| FR-AUTH-002 | Django session (UI) + optional JWT | 🟡 session yes, JWT no |
| FR-AUTH-003 | Webhook-out HMAC-SHA256 + timestamp + nonce | ❌ stub only |
| FR-AUTH-004 | Webhook-in signature verification | ❌ absent |
| FR-AUTH-005 | Every state-changing call → `AuditLog` via **middleware** | 🟡 logged via signals/helpers, not middleware; coverage partial |
| FR-AUTH-006 | Secrets in env/secret-store/encrypted, never logged | 🟡 not encrypted; some secrets hardcoded in settings |
| FR-AUTH-007 | Django RBAC: 3 groups (Service/Admin/Operator) | 🟡 custom `Rbac*` tables exist but **no enforcement**; not wired to Django `Group`/permissions as SRS specifies |

**Pending:** Token auth, audit **middleware**, real webhook signing/verification, enforce the three roles via Django Groups/permissions (the SRS explicitly says use built-in Groups, not custom RBAC tables).

---

## 16. Error Handling (SRS §10)

- ❌ FR (10.1) RFC 7807 Problem Details — not implemented.
- ❌ FR (10.2) **Error catalog** (`docs/error-catalog.md`, ≥30 GDAL errors mapped) — missing entirely. (MVP criterion #25.)

---

## 17. Non-Functional Requirements (SRS §11)

| Area | Status | Notes |
|------|--------|-------|
| NFR-PERF-001..005 | ❌ unverified | No load tests / benchmarks; threaded execution undermines concurrency targets. |
| §11.4 Security | 🟡 | Path-traversal ✅, subprocess arrays (in CLI module) ✅, AV hook ✅; **but** no credential encryption, hardcoded DB/broker creds, no signed URLs, auth gaps. |
| §11.4 Compliance baseline | ❌ | No SOC 2 control mapping / CJIS-FedRAMP-HIPAA gap doc. |
| §11.5 Maintainability | 🟡 | Service layer not framework-agnostic; few tests (`tests.py`, `test_conversion_matrix.py` only). |
| §11.6 Deployment | ❌ | No Docker/Compose, no env-based config, no pinned GDAL image. |

---

## 18. Configuration (SRS §12)

- ❌ No `django-environ`; settings are hardcoded literals.
- ❌ No `docs/configuration.md`.
- ❌ Many required config categories absent (retention policies, per-workflow resource limits, encryption key, allowed-CRS list, integration endpoints, job/pause timeouts).

---

## 19. Monitoring & Observability (SRS §13)

- ❌ `django-prometheus` / `celery-prometheus-exporter` — absent. (MVP criterion #21.)
- 🟡 Structured logs — job activity persisted to `JobLog`/`AuditLog`, but no `python-json-logger` stdout JSON logging.
- ❌ Two Grafana dashboards (Operations, Capacity) — not shipped.

---

## 20. Deployment Architecture (SRS §14)

- ❌ No `docker-compose.yml` (web/worker/beat/postgres/rabbitmq/reverse_proxy). (MVP criterion #24.)
- ❌ No `Dockerfile.web` / `Dockerfile.worker`.
- ❌ No Gunicorn config, no reverse proxy (Caddy/Nginx).
- ❌ No air-gapped packaging (PROJ grid tarball, etc.).

---

## 21. Frontend (SRS §15)

- ✅ Django admin registered for all core models with filters.
- ✅ Operator UI templates present (upload, validation, workflow run, job list/detail/logs, preview, dispatched list, outputs).
- ❌ **Embedded React preview component** (MapLibre GL map + table) — `preview_frontend/` React source is absent; a `job-preview.bundle.js` exists but there is no React source per §15/FR-PRE-004. Map+table interactivity is not confirmed.

---

## 22. Preview Layer detail (SRS §5.4)

| ID | Requirement | Status |
|----|-------------|--------|
| FR-PRE-001 | Preview generated by **Celery task** post-transform | ❌ generated inline in views, not Celery |
| FR-PRE-002 | count + bbox + schema + sample (100 default, max 1000) | 🟡 sample present; verify max-1000 cap |
| FR-PRE-003 | Temp endpoint serving sampled GeoJSON, 1h cache TTL | 🟡 Django cache TTL 3600s; not a dedicated temp endpoint |
| FR-PRE-004 | Map (MapLibre, React) + paginated table | ❌ React component source missing |
| FR-PRE-005 | GC by **Celery beat** after TTL/completion | ❌ no beat GC task |
| FR-PRE-006 | Not a serving feature | ✅ ephemeral by design |
| FR-PRE-007 | Pause → continue/abort | ✅ confirm/abort endpoints |

---

## 23. Raster Spike (SRS §2.2)

- 🟡 `raster_spike.py` implements GeoTIFF metadata extraction, reprojection, and COG conversion — **the technical capability exists**.
- ❌ No **go/no-go decision document** recorded (MVP criterion #26 requires the outcome documented).

---

## 24. MVP Acceptance Criteria Scorecard (SRS §17)

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Upload Shapefile/GeoJSON/KML/GPKG/GeoParquet/CSV | ✅ |
| 2 | Resumable tus.io up to 5 GB | ✅ (custom impl) |
| 3 | Remote ingestion w/ checksum | 🟡 (inline, not Celery) |
| 4 | Extract & store metadata | 🟡 (not via ogrinfo) |
| 5 | Validate & report by severity | 🟡 (no dispatch gating) |
| 6 | `convert_download` all output formats | ✅ |
| 7 | `transform_download` reproject/clip/simplify/fix/field ops | ❌ (clip/simplify/field ops/geodesic missing) |
| 8 | `publish_feature_mapper` signed + persisted | ❌ |
| 9 | `publish_external_webhook` signed delivery | ❌ |
| 10 | `publish_external_database` load to PostGIS | ❌ |
| 11 | Reproject 4326 & 3857, axis-order policy | 🟡 (no axis-order policy) |
| 12 | Preview count/bbox/schema/sample on map+table | 🟡 (no React map+table) |
| 13 | Pause/confirm/abort at preview | ✅ |
| 14 | Perf targets (NFR-PERF-002/003) | ❌ unverified |
| 15 | Audit log all state-changing actions | 🟡 (partial coverage) |
| 16 | RBAC three roles via Groups | ❌ (custom tables, no enforcement) |
| 17 | Idempotent job creation across retries | 🟡 (constraint yes, Celery retry no) |
| 18 | Cancel-running cleans partial state | ❌ (threaded, no revoke) |
| 19 | Re-dispatch without re-conversion | 🟡 |
| 20 | Credentials envelope-encrypted, never logged | ❌ |
| 21 | Prometheus + structured logs (web+worker) | ❌ |
| 22 | OpenAPI 3.1 via drf-spectacular | ❌ |
| 23 | Django admin for all core models | ✅ |
| 24 | Docker Compose starts cleanly | ❌ |
| 25 | Error catalog ≥30 GDAL errors | ❌ |
| 26 | Raster spike go/no-go documented | ❌ |

**Met:** ~4 of 26 fully; ~9 partial; ~13 not met.

---

## 25. Missing Documentation (SRS §10.2, §12, §16, §19.3)

All absent — none of these files exist:
- ❌ `README.md`
- ❌ `ROADMAP.md`
- ❌ `docs/configuration.md`
- ❌ `docs/error-catalog.md` (≥30 GDAL errors)
- ❌ `docs/datum-grids.md`
- ❌ `docs/api.md`
- ❌ `docs/validation-rules.md` (validation rule catalog)

---

## 26. Recommended Priority Order

**P0 — MVP blockers / architectural:**
1. Re-platform job execution from threads to **Celery** (unblocks FR-JOB-003/004/005/006/007/010, cancel, retry, reliability).
2. Implement the **three publish workflows** end-to-end (FM / webhook / external DB) with real HMAC-SHA256 signing (FR-DISP-002) and PostGIS staging load.
3. **Credential envelope encryption** (Fernet) — security + MVP #20.
4. Complete **`transform_download`** transforms: clip-by-AOI, simplify, geodesic measures, field select/rename/add-constant (MVP #7).
5. Adopt **DRF** + **drf-spectacular** + RFC 7807 + token auth + throttling (§7.11, §9, MVP #22).

**P1 — productionization:**
6. **Docker Compose** stack (web/worker/beat/postgres/rabbitmq/proxy) + pinned GDAL/PROJ image + GDAL env config (MVP #24).
7. **Prometheus** metrics + JSON logging + Grafana dashboards (MVP #21).
8. **S3 storage backend** + signed URLs + retention beat tasks (§7.10).
9. **Error catalog** doc + GDAL-stderr translation (MVP #25, FR-CONV-006).

**P2 — correctness/compliance polish:**
10. Switch metadata to `ogrinfo -json`; mixed-geometry detection; CRS WKT2 storage.
11. Validation **dispatch gating** on severity (FR-VAL-004).
12. CRS: stop silent 4326 vector assumption, NTv2 grids + doc, axis-order policy, guess-by-extent helper.
13. **React preview component** (MapLibre + table) per §15.
14. Model cleanups: UUID v7, missing `org_id`/`updated_at`, `AuditLog.org_id` type, consolidate legacy `ConversionJob` family.
15. RBAC via Django Groups; audit **middleware**; CP1252 `.dbf` fallback; GPX input; per-conversion timeout.
16. Remaining docs: README, ROADMAP, configuration, datum-grids, validation-rules, api.

---

*This document reflects a static read of the codebase as of 2026-06-20. Items marked 🟡 warrant a closer per-file confirmation before estimation.*
