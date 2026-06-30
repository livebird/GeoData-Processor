# Geo Processing Server — SRS v4 Gap Analysis (Pending Items)

**Revision 2 — re-verified:** 2026-06-30 (original: 2026-06-20)
**Compared against:** `docs/geo processing server srs v4.md` (v4.0 Draft)
**Codebase:** `apps/` (Django `gps` project + `converter` app, `services/` layer, `gdal_server` app)

> Status legend: **❌ Missing** · **🟡 Partial** · **✅ Done**
> A **🟡 wired-gap** marker means the *capability exists in the service layer* but is **not yet invoked from the actual execution/request path** — the SRS requirement is functionally incomplete until wired.

---

## 0. What Changed Since Revision 1 (2026-06-20 → 2026-06-30)

Substantial progress. Major items that moved to ✅ or near-✅:

| Area | Rev 1 | Rev 2 | Evidence |
|------|-------|-------|----------|
| **Framework-agnostic `services/` layer** | ❌ absent | ✅ **Done** | `apps/services/{gdal_runner,metadata,validation,transformation,preview,dispatch,remote_ingest,error_catalog,crs_policy}.py` — all framework-agnostic |
| **Celery is the execution engine** | 🟡 threads | ✅ **Done** | `tasks.py:257` `execute_workflow_job`; threaded path replaced |
| **Job state machine (8 states)** | 🟡 partial | ✅ **Done** | `models.py:105-114` — created/queued/running/awaiting_preview/completed/failed/cancelled/partial |
| **Cancel via revoke / retry-transient / progress / beat cleanup** | ❌/🟡 | ✅ **Done** | `tasks.py:590` cancel, `:329` transient retry, `:239` update_state, `:645` beat task |
| **Priority queues + time/memory limits** | ❌ | ✅ **Done** | `celery.py` queues high/normal/low, `task_time_limit`, `worker_max_memory_per_child` |
| **Metadata via `ogrinfo -json` + mixed-geometry** | ❌ | ✅ **Done** | `metadata.py:94`, mixed-geom `:296-305` |
| **Transforms: simplify / clip-AOI / geodesic / field ops** | ❌ | ✅ **Done (service)** 🟡 wired | `transformation.py:173-283, 351-355` — but no `transform_download` workflow invokes them |
| **CRS policy: reject-unknown / guess-by-extent / axis-order / NTv2 discovery** | ❌ | ✅ **Done** | `crs_policy.py` + `settings.py:101-122` |
| **Validation severity gating (block dispatch)** | ❌ | ✅ **Done** | `error_catalog.py:279-321`, enforced in `dispatch.py:440-453` |
| **ogr2ogr CLI w/ arg arrays + timeout + layer select** | 🟡 | ✅ **Done** | `ogr_cli.py:54-102` |
| **DRF viewsets + serializers** | ❌ | ✅ **Done (gdal_server)** 🟡 partial wiring | `api_views.py`, `serializers.py`, `gdal_server/` DRF |
| **OpenAPI via drf-spectacular** | ❌ | ✅ **Done** | `gps/urls.py:5,11-15` `/api/schema/`, `/api/docs/`; `SPECTACULAR_SETTINGS` |
| **HMAC-SHA256 sign/verify (canonical JSON+ts+nonce)** | ❌ | ✅ **Done (utility)** 🟡 wired | `api_views.py:283-372` — not called by publish_* tasks |
| **Remote ingest service** | 🟡 inline | ✅ **Done (service)** | `remote_ingest.py` HTTP+S3, timeout, max-size, checksum |
| **Docs: datum-grids, validation rule catalog** | ❌ | ✅ **Done** | `docs/datum-grids.md`, `docs/validation-rule-catalog.md` |
| **All required deps in requirements.txt** | ❌ | ✅ **Done** | DRF, drf-spectacular, simplejwt, django-storages, celery-results/beat, environ, prometheus, json-logger, cryptography |

**Still pending (the meaningful remaining gaps):** credential **encryption** (lib present, unused), **publish_feature_mapper / publish_external_webhook** still stub comments, **external_database** lacks staging-table+atomic-rename, **Prometheus/JSON-logging not configured** (deps installed but not in `INSTALLED_APPS`/`LOGGING`), **no Docker**, **hardcoded secrets**, **no auth/throttle/RFC7807 on DRF**, **UUID v4 not v7**, **S3 storage backend not configured**, **3 models still missing `org_id`/`updated_at`**, **`transform_download` not wired**.

---

## 1. Executive Summary (current)

| Theme | Status | Notes |
|-------|--------|-------|
| Framework-agnostic `services/` layer | ✅ Done | The single most important boundary now exists |
| Celery execution + full job lifecycle | ✅ Done | Threads replaced; cancel/retry/progress/beat all real |
| Transform capabilities (clip/simplify/geodesic/field) | 🟡 wired-gap | Service complete; no `transform_download` workflow calls it |
| `convert_download` / `download` workflow | ✅ Done | End-to-end via `GDALRunner` |
| `publish_external_database` | 🟡 Partial | Real `to_postgis`, but no staging-table + atomic rename (§7.8.5) |
| `publish_feature_mapper` / `publish_external_webhook` | ❌ Missing | Convert step works; dispatch is a `# (would use requests)` stub |
| Credential envelope encryption | ❌ Missing | `cryptography` installed; `encrypted_secret` still raw `BinaryField` |
| DRF API (schema/docs) | ✅ Done | OpenAPI served; viewsets/serializers exist |
| DRF auth / throttle / RFC 7807 / pagination | ❌ Missing | No auth classes, no throttle, plain-JSON errors |
| Prometheus / JSON logging | ❌ Missing | Deps installed but not in `INSTALLED_APPS`/`MIDDLEWARE`/`LOGGING` |
| Docker / Compose | ❌ Missing | No Dockerfile or compose file |
| Config hygiene (django-environ, secrets) | ❌ Missing | DB password + SECRET_KEY hardcoded in `settings.py` |
| UUID v7 PKs | ❌ Missing | Still `uuid.uuid4` everywhere |
| S3 storage backend | ❌ Missing | `django-storages` installed, not configured |
| Docs (error-catalog.md, configuration.md, README, ROADMAP, api.md) | ❌ Missing | Only datum-grids + validation-rule-catalog exist |

---

## 2. Technology Stack (SRS §4)

✅ **Dependencies now complete** — `requirements.txt` includes `djangorestframework`, `drf-spectacular`, `djangorestframework-simplejwt`, `django-tus`, `django-storages`, `django-celery-results`, `django-celery-beat`, `django-environ`, `django-prometheus`, `celery-prometheus-exporter`, `python-json-logger`, `cryptography`.

Pending:
- 🟡 **Several deps installed but unused/unconfigured:** `django-environ` (settings still hardcoded), `django-storages` (no S3 config), `django-prometheus` (not in `INSTALLED_APPS`), `python-json-logger` (no `LOGGING`), `cryptography` (no Fernet usage), `django-tus` (custom tus endpoint used instead).
- ✅ **GDAL axis-order env config now set** — `settings.py:101-104` sets `OSR_DEFAULT_AXIS_MAPPING_STRATEGY=TRADITIONAL_GIS_ORDER`, `OGR_CT_FORCE_TRADITIONAL_GIS_ORDER=YES`.
- ❌ **`GDAL_CACHEMAX`, `CPL_TMPDIR` not set.**
- ❌ **GDAL/PROJ version pinning** — no pinned worker image (no Docker).
- ❌ **`fastapi`/`uvicorn`/`pydantic`/`pyodbc` leftovers** remain in requirements; reconcile with the Django+DRF+Celery stack.

---

## 3. File Upload & Remote Ingestion (SRS §7.1)

Mostly ✅ already. Remaining:

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-UP-001 | Upload via **DRF** endpoint | 🟡 | Works; primary upload still plain Django view. |
| FR-UP-006 | Remote ingestion as a **Celery task** | ✅ Done (service) | `remote_ingest.py` service exists; HTTP+S3, timeout, max-size, checksum. |
| FR-UP-007 | Remote fetch timeout/retry/max-size | 🟡 | Timeout + max-size present; **retry loop missing** in `remote_ingest.py` (single attempt). |
| FR-UP-012 | **CP1252 fallback** for `.dbf` when `.cpg` absent | ❌ | Still not implemented. |

Everything else in §7.1 (tus, size cap, MIME, SHA-256, path-traversal, shapefile completeness, missing-`.prj` flag, AV hook, quotas) remains ✅.

---

## 4. Metadata Extraction (SRS §7.2) — ✅ now substantially Done

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-MD-001 | **`ogrinfo -json`** | ✅ Done | `metadata.py:94` uses `ogrinfo -json`; rasters via `gdalinfo -json`. |
| FR-MD-002 | format/layers/geom/CRS(WKT+EPSG)/bbox/count/fields/encoding/Z-M | ✅ Done | `metadata.py:181-316`. |
| FR-MD-003 | Mixed-geometry detection | ✅ Done | `metadata.py:296-305`. |
| FR-MD-004 | Persist to `GeoFileLayer` | ✅ Done | `metadata.py:502-595`. |

**Pending:** wire the new `metadata.py` service into the upload/validation request path if the legacy view still uses GeoPandas (verify call-site).

---

## 5. Validation (SRS §7.3) — ✅ now Done

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-VAL-001 | GDAL open check | ✅ | `validation.py:493-540`. |
| FR-VAL-002 | Empty/invalid geom (ST_IsValid) | ✅ | Shapely. |
| FR-VAL-003 | Flag self-intersect unless strict | 🟡 | Detected + auto-fixed; per-workflow strict/lenient toggle still implicit. |
| FR-VAL-004 | **Block dispatch on error/critical** | ✅ Done | `error_catalog.py:279-321`, enforced `dispatch.py:440-453`. |
| FR-VAL-005 | Proceed past info/warning | ✅ | `get_non_blocking_errors`. |
| FR-VAL-006 | Versioned validation rule catalog doc | ✅ Done | `docs/validation-rule-catalog.md`. |

---

## 6. Job System (SRS §7.4) — ✅ now largely Done

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-JOB-001 | `Job` row + Celery task | ✅ Done | `tasks.py:257` `execute_workflow_job`. |
| FR-JOB-002 | Idempotency-Key dedupe 24h | ✅ Done | `api_views.py:42-92` IdempotencyMixin + DB constraint. |
| FR-JOB-003 | Priority queues (>500 MB→normal) | ✅ Done | `celery.py` queues; `tasks.py:284-287`. |
| FR-JOB-004 | soft/hard time limit + max-memory | ✅ Done | `celery.py` `task_time_limit`, `task_soft_time_limit`, `worker_max_memory_per_child`. |
| FR-JOB-005 | Cancel via `revoke(terminate=True)` + cleanup | ✅ Done | `tasks.py:590-623`. |
| FR-JOB-006 | Retry transient-only | ✅ Done | `tasks.py:18-22` `TRANSIENT_ERRORS`, `:329`. |
| FR-JOB-007 | Progress via `update_state` | ✅ Done | `tasks.py:239-254`. |
| FR-JOB-008 | Temp cleanup + beat | ✅ Done | `tasks.py:626,645`; beat schedule in `celery.py`. |
| FR-JOB-009 | Worker hostname + duration | ✅ Done | `tasks.py:216-236` `socket.gethostname()` + duration. |
| FR-JOB-010 | Pause at `awaiting_preview`, 24h beat expiry | ✅ Done | `tasks.py:677-692, 712-758`. |

**Job states:** ✅ all 8 present (`models.py:105-114`).
**Minor caveat:** `confirm_preview` (`tasks.py:737-739`) marks confirmed jobs completed without resuming the remaining steps ("would need to track where to resume") — resume-after-preview is a stub.
**Legacy stubs:** `workflow_dispatch_*` (`tasks.py:117-209`) are old `time.sleep` stubs, now superseded by `execute_workflow_job`; delete to avoid confusion.

---

## 7. Conversion (SRS §7.5) — mostly ✅

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-CONV-001 | `ogr2ogr` via subprocess arg arrays | ✅ Done | `ogr_cli.py:54-102`. |
| FR-CONV-002 | Capture stdout/stderr → `JobLog` | 🟡 | CLI captures output; persistence into `JobLog` not consistently wired. |
| FR-CONV-003 | GeoParquet driver | ✅ Done | enabled. |
| FR-CONV-004 | Layer selection | ✅ Done | `ogr_cli.py:81-82` (`-sql SELECT`). |
| FR-CONV-005 | Preserve attrs/types | ✅ | |
| FR-CONV-006 | GDAL stderr → friendly via error catalog | 🟡 | `services/error_catalog.py` exists and `ogr_cli.py:13-33` maps a few codes; catalog incomplete and **`docs/error-catalog.md` missing**. |
| FR-CONV-007 | Per-conversion timeout (30 min) | 🟡 | ✅ for `ogr2ogr` path (`ogr_cli.py:61`); **missing** on geopandas/rasterio transform paths. |

**Input formats:** ✅ all except **❌ GPX** (still unconfirmed/absent).
**Output formats:** ✅ all.

---

## 8. Reprojection (SRS §7.6) — ✅ now Done

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-CRS-001 | Default 4326; web-map 3857 | ✅ | `crs_policy.py:10-11`. |
| FR-CRS-002 | Target via EPSG/WKT2 | ✅ | `crs_policy.py:32-43`. |
| FR-CRS-003 | Reject unknown source CRS | ✅ Done | `crs_policy.py:71-86` raises (was 🟡 silent-4326 before). |
| FR-CRS-004 | NTv2 grids + coverage doc | 🟡 | Grid **discovery** + PROJ path config done (`crs_policy.py:182-201`, `settings.py:106-122`); `docs/datum-grids.md` ✅; **actual `.gsb` grid files bundling** unverified. |
| FR-CRS-005 | Traditional axis order (lon,lat), configurable | ✅ Done | `crs_policy.py:24-29` + `settings.py:101-104`. |
| FR-CRS-006 | Guess CRS by extent (advisory) | ✅ Done | `crs_policy.py:128-175` (WGS84/WebMercator/UTM with confidence). |

---

## 9. Geometry & Field Transformations (SRS §7.7) — ✅ service Done, 🟡 not wired

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-GEO-001 | ST_IsValid | ✅ | `transformation.py:104-133`. |
| FR-GEO-002 | Fix-invalid | ✅ | `transformation.py:136-170` (Shapely; not `ogr2ogr -makevalid`). |
| FR-GEO-004 | Topology-preserving simplify | ✅ Done | `transformation.py:351-355`. |
| FR-GEO-005 | Clip-by-AOI w/ boundary handling | ✅ Done | `transformation.py:173-200` (clip/drop). |
| FR-GEO-006 | Geodesic area/length | ✅ Done | `transformation.py:203-248` (pyproj `Geod`). |
| FR-FLD-001/002/003 | Field select / rename / add-constant | ✅ Done | `transformation.py:251-283`. |

**🟡 Wired-gap (important):** none of these are invoked by a workflow. `execute_workflow_job` routes only to `download`, `feature_mapper`, `external_webhook`, `external_database` — there is **no `transform_download` workflow** calling `TransformationService`. The transform capability is built but unreachable from a job. **This still blocks MVP criterion #7.**

---

## 10. Workflow Definitions (SRS §5, §7.8)

| Workflow | Status | Notes |
|----------|--------|-------|
| `convert_download` (`download`) | ✅ Done | `tasks.py:352-416` real GDAL conversion. |
| `transform_download` | ❌ Missing | No workflow_code wires the transform service (see §9). |
| `publish_feature_mapper` | ❌ Missing | `tasks.py:419-467` converts then `# (Implementation would use requests library with signature)` — no actual POST/sign. |
| `publish_external_webhook` | ❌ Missing | `tasks.py:470-518` converts then `# (Implementation would use requests library)` — no POST. |
| `publish_external_database` | 🟡 Partial | `tasks.py:521-587` → `DispatchService.dispatch_to_postgresql` real; but `to_postgis(if_exists=fail/replace)` — **no staging table + atomic rename** (§7.8.5), no connection-string fingerprinting. |

- ✅ Workflows seeded as model rows with `parameters_schema` (`operator_sync.py`).
- 🟡 Seeded codes (`file-conversion`, `coordinate-reprojection`, `location-export`) don't match the SRS canonical codes / the `execute_workflow_job` routing keys (`download`, `feature_mapper`, …) — naming is inconsistent across seed vs. runner.

---

## 11. Workflow Dispatcher (SRS §7.9)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-DISP-001 | One destination per job | ✅ | |
| FR-DISP-002 | HMAC-SHA256 canonical JSON + ts + nonce | ✅ Done (utility) 🟡 wired | `api_views.py:283-372` real sign+verify; **not called by publish_* tasks**. Used in location-export path (`models.py:459-465` signature fields). |
| FR-DISP-003 | Connectivity check before dispatch | ❌ Missing | No pre-flight check in `dispatch.py`. |
| FR-DISP-004 | Dispatch status + re-dispatch on transient | 🟡 | Status tracked; redispatch endpoint exists in operator UI; transient handling minimal. |
| FR-DISP-005 | Unique constraint | ✅ | `models.py:217-222`. |
| FR-DISP-006 | Secrets **envelope-encrypted** (Fernet) | ❌ Missing | `cryptography` installed but unused; `encrypted_secret` raw `BinaryField`; `dispatch.py` `DestinationCredential` holds plaintext password. |
| FR-DISP-007 | Dispatch-retry without re-conversion | 🟡 | Redispatch action exists; re-sign/skip-conversion path not proven. |

---

## 12. Storage (SRS §7.10)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-STO-001 | `StorageBackend` w/ Local + **S3** | 🟡 | `dispatch.py:332-414` has S3 *dispatch*, and `django-storages` installed, but **no `DEFAULT_FILE_STORAGE`/S3 config** — Django storage is still local only. |
| FR-STO-002 | Signed time-limited URLs | 🟡 | HMAC utility exists; **no S3 presigned URLs / local signed-URL TTL**. |
| FR-STO-003 | Retention per category via beat | 🟡 | Temp/orphan cleanup beat done (`tasks.py:645`); per-category retention (originals/outputs/preview/logs) not implemented. |
| FR-STO-004 | GDPR cascading delete + audit | 🟡 | ORM cascades; no dedicated GDPR flow. |

---

## 13. API Surface (SRS §7.11)

**Now uses DRF** — `api_views.py` has real `viewsets.ModelViewSet` (`JobViewSet`, `GeoFileViewSet`, `WorkflowViewSet`, …) and `serializers.py` has `ModelSerializer`s. `gdal_server/` is a DRF app mounted at `/api/`.

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-API-001 | RFC 7807 Problem Details | ❌ Missing | Errors still plain `{'error': ...}` JSON. |
| FR-API-002 | Auth on every endpoint | ❌ Missing | No `authentication_classes`/`permission_classes` on viewsets; `REST_FRAMEWORK` sets only schema class. |
| FR-API-003 | Idempotency-Key on job create/redispatch | ✅ Done | `api_views.py:42-92`. |
| FR-API-004 | DRF pagination | 🟡 | Manual page/page_size in `preview.py`; no `DEFAULT_PAGINATION_CLASS`. |
| FR-API-005 | **OpenAPI 3.1 via drf-spectacular** | ✅ Done | `gps/urls.py:11-15` `/api/schema/`, `/api/docs/`, `/api/redoc/`; `SPECTACULAR_SETTINGS`. |
| FR-API-006 | Versioning policy | 🟡 | `/api/v1/` prefix on some routes; no formal negotiation. |
| FR-API-007 | Rate limiting (60 RPM) | ❌ Missing | No throttle classes. |

**Also:** the DRF `api_views.py` viewsets may not all be registered in a router/urls — `converter/urls.py` still maps the `/api/v1/...` paths to **function views**. Confirm router registration so the viewsets (and their schema) are actually served.

---

## 14. Models / Database (SRS §8)

✅ All 8 models exist; ✅ Job state machine complete; ✅ dispatch unique constraint.

Pending deviations (unchanged since Rev 1):

| Item | SRS | Actual | Status |
|------|-----|--------|--------|
| Primary keys | UUID v7 | `uuid.uuid4` everywhere (`models.py:15,40,69,127,182,203,231,262`) | ❌ |
| `org_id` present | all models | **missing** on `GeoFileLayer`, `Workflow`, `GeoProcessingJobLog` | ❌ |
| `org_id` type | `UUIDField` | `AuditLog.org_id` is `CharField(36)` (`models.py:263`) | 🟡 |
| `updated_at` present | all models | **missing** on `GeoFileLayer`, `Workflow`, `JobLog`, `DispatchedLayer`, `AuditLog` | 🟡 |
| `encrypted_secret` | envelope-encrypted | raw `BinaryField` (`models.py:235`), no cipher | ❌ |
| Legacy models | — | `ConversionJob` family still parallel to `GeoProcessingJob` | 🟡 consolidate |

---

## 15. Authentication & Authorization (SRS §9)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-AUTH-001 | DRF TokenAuthentication | 🟡 | `rest_framework.authtoken` in `INSTALLED_APPS`; **not active** (no default auth classes). |
| FR-AUTH-002 | Session + optional JWT | 🟡 | Session ✅; `simplejwt` installed but **no config/endpoints**. |
| FR-AUTH-003/004 | Webhook HMAC sign + verify | ✅ Done (utility) 🟡 wired | `api_views.py:283-372`; not wired into publish_* tasks. |
| FR-AUTH-005 | Audit via **middleware** | 🟡 | Signal-based logging (`signals.py`); no request/response middleware. |
| FR-AUTH-006 | Secrets in env, never logged | ❌ | `SECRET_KEY`, DB password `admin123`, broker creds **hardcoded** in `settings.py:6,73-82,141`. |
| FR-AUTH-007 | RBAC 3 Django Groups | ❌ | Custom `Rbac*` tables exist, **not enforced**; not wired to Django `Group`/permissions. |

---

## 16. Error Handling (SRS §10)

- ❌ RFC 7807 Problem Details — not implemented.
- 🟡 **Error catalog** — `services/error_catalog.py` exists (code-level enums/mapping) but the **versioned `docs/error-catalog.md` (≥30 GDAL errors) is still missing**, and the GDAL-stderr mapping is incomplete (MVP criterion #25).

---

## 17. Non-Functional (SRS §11)

- ❌ NFR-PERF-001..005 unverified (no benchmarks).
- 🟡 Security improved (axis-order, validation gating, HMAC utility) **but** hardcoded secrets, no credential encryption, no signed URLs, no API auth remain.
- 🟡 Maintainability much improved (services layer ✅); test coverage still thin (`tests.py`, `services/test_conversion_matrix.py`).
- ❌ Deployment (§11.6) — no Docker/env-config/pinned image.

---

## 18. Configuration (SRS §12)

- ❌ `django-environ` installed but unused; settings hardcoded (some `os.environ.get` with insecure defaults).
- ❌ `docs/configuration.md` missing.
- 🟡 GDAL/CRS env config present (`settings.py:101-122`); broader categories (retention, per-workflow resource limits, encryption key, allowed-CRS list) absent.

---

## 19. Observability (SRS §13)

- ❌ `django-prometheus` installed but **not in `INSTALLED_APPS`/`MIDDLEWARE`**; no metrics endpoint.
- ❌ `python-json-logger` installed but **no `LOGGING` dict** in settings; logging is ad-hoc.
- ❌ Grafana dashboards not shipped.

---

## 20. Deployment (SRS §14)

- ❌ No `docker-compose.yml`, no `Dockerfile.web`/`Dockerfile.worker`, no gunicorn, no reverse proxy, no air-gapped packaging. (MVP criterion #24.)

---

## 21. Frontend (SRS §15)

- ✅ Django admin for all core models.
- ✅ Operator UI templates present.
- ❌ **Embedded React preview component (MapLibre + table)** — no `preview_frontend/` React source; only a prebuilt `job-preview.bundle.js`. (FR-PRE-004.)

---

## 22. Preview Layer (SRS §5.4)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-PRE-001 | Generated by Celery task | 🟡 | `preview.py` service exists; confirm it runs as a Celery task vs inline. |
| FR-PRE-002 | count+bbox+schema+sample (max 1000) | ✅ | `preview.py`. |
| FR-PRE-003 | Temp endpoint, 1h TTL | 🟡 | Django cache TTL; not a dedicated temp endpoint. |
| FR-PRE-004 | MapLibre map + table (React) | ❌ | React source missing. |
| FR-PRE-005 | GC by Celery beat | 🟡 | Orphan beat exists; preview-specific GC not explicit. |
| FR-PRE-007 | Pause → continue/abort | ✅ | confirm/abort endpoints + `confirm_preview` task (resume is a stub). |

---

## 23. Raster Spike (SRS §2.2)

- 🟡 `raster_spike.py` capability exists (metadata, reproject, COG).
- ❌ Go/no-go decision document still not recorded (MVP criterion #26).

---

## 24. MVP Acceptance Criteria Scorecard (SRS §17)

| # | Criterion | Rev 1 | Rev 2 |
|---|-----------|-------|-------|
| 1 | Upload core formats | ✅ | ✅ |
| 2 | Resumable tus up to 5 GB | ✅ | ✅ |
| 3 | Remote ingestion w/ checksum | 🟡 | ✅ (service; add retry) |
| 4 | Extract & store metadata | 🟡 | ✅ (ogrinfo -json) |
| 5 | Validate & report by severity | 🟡 | ✅ (gating done) |
| 6 | `convert_download` all formats | ✅ | ✅ |
| 7 | `transform_download` transforms | ❌ | 🟡 (service done, **not wired to a workflow**) |
| 8 | `publish_feature_mapper` | ❌ | ❌ (dispatch still stub) |
| 9 | `publish_external_webhook` | ❌ | ❌ (dispatch still stub) |
| 10 | `publish_external_database` | ❌ | 🟡 (real load; no staging/atomic) |
| 11 | Reproject 4326/3857 + axis-order | 🟡 | ✅ |
| 12 | Preview on map+table | 🟡 | 🟡 (no React map+table) |
| 13 | Pause/confirm/abort | ✅ | ✅ (resume stub) |
| 14 | Perf targets | ❌ | ❌ unverified |
| 15 | Audit all state-changes | 🟡 | 🟡 (signals, no middleware) |
| 16 | RBAC three roles via Groups | ❌ | ❌ |
| 17 | Idempotent job creation | 🟡 | ✅ |
| 18 | Cancel-running cleans state | ❌ | ✅ (revoke + cleanup) |
| 19 | Re-dispatch w/o re-conversion | 🟡 | 🟡 |
| 20 | Credentials envelope-encrypted | ❌ | ❌ |
| 21 | Prometheus + structured logs | ❌ | ❌ (deps installed, unconfigured) |
| 22 | OpenAPI 3.1 via drf-spectacular | ❌ | ✅ |
| 23 | Django admin all models | ✅ | ✅ |
| 24 | Docker Compose starts clean | ❌ | ❌ |
| 25 | Error catalog ≥30 GDAL errors | ❌ | ❌ (code catalog only; no doc) |
| 26 | Raster spike go/no-go doc | ❌ | ❌ |

**Met:** ~12 of 26 fully (was ~4); ~6 partial; ~8 not met. Big jump driven by the Celery re-platform, services layer, CRS/validation/metadata work, and OpenAPI.

---

## 25. Missing Documentation (SRS §10.2, §12, §16, §19.3)

| Doc | Status |
|-----|--------|
| `docs/datum-grids.md` | ✅ Done |
| `docs/validation-rule-catalog.md` | ✅ Done |
| `docs/error-catalog.md` (≥30 GDAL errors) | ❌ Missing |
| `docs/configuration.md` | ❌ Missing |
| `docs/api.md` | ❌ Missing |
| `README.md` | ❌ Missing |
| `ROADMAP.md` | ❌ Missing |

---

## 26. Recommended Priority Order (remaining work)

**P0 — close the MVP gaps:**
1. **Wire `transform_download`** — add a workflow_code that calls `TransformationService` (clip/simplify/geodesic/field). Capability exists; just unreachable (MVP #7).
2. **Implement `publish_feature_mapper` + `publish_external_webhook` dispatch** — replace the `# would use requests` stubs with real signed `requests.post` using the existing `generate_hmac_signature` utility (MVP #8/#9, FR-DISP-002 wiring).
3. **Credential envelope encryption** — use the installed `cryptography` (Fernet) on `DestinationCredential.encrypted_secret` (MVP #20, FR-DISP-006).
4. **`publish_external_database` staging-table + atomic rename** in customer DB (§7.8.5).
5. **DRF auth + throttle + RFC 7807 handler**, and register viewsets in a router so the OpenAPI schema covers them (FR-API-001/002/007).

**P1 — productionization:**
6. **Configure Prometheus + JSON logging** — deps are installed; add to `INSTALLED_APPS`/`MIDDLEWARE` and a `LOGGING` dict (MVP #21).
7. **Docker Compose** stack + pinned GDAL/PROJ image + `GDAL_CACHEMAX`/`CPL_TMPDIR` (MVP #24).
8. **Move secrets to `django-environ`** — DB password, SECRET_KEY, broker creds out of `settings.py`.
9. **S3 storage backend** (`django-storages` `DEFAULT_FILE_STORAGE`) + signed/TTL URLs (§7.10).
10. **`docs/error-catalog.md`** with ≥30 GDAL errors wired to `error_catalog.py` (MVP #25).

**P2 — correctness/polish:**
11. Model cleanups: **UUID v7**, add `org_id` to GeoFileLayer/Workflow/JobLog, add `updated_at` to the 5 models, fix `AuditLog.org_id` type, consolidate legacy `ConversionJob`.
12. **RBAC via Django Groups** (Service/Admin/Operator) + audit **middleware** (FR-AUTH-005/007).
13. **React preview component** (MapLibre + table) (FR-PRE-004).
14. Reconcile **workflow seed codes** with `execute_workflow_job` routing keys; implement resume-after-preview.
15. Remote-ingest **retry loop**; per-conversion **timeout** on geopandas/rasterio paths; **GPX** input; CP1252 `.dbf` fallback; remaining docs (README, ROADMAP, configuration, api).

---

*Rev 2 reflects a re-read on 2026-06-30. Items marked 🟡 wired-gap have working service code that no execution path calls yet — verify call-sites before sign-off.*
