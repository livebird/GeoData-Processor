# Datum Grid Coverage

This service supports PROJ/GDAL datum transformations that depend on local NTv2
or PROJ grid files.

## Runtime Policy

- Axis order defaults to traditional GIS order: longitude, latitude for
  geographic CRS such as EPSG:4326.
- The default axis mapping strategy is controlled by `GDAL_AXIS_ORDER`.
- The grid search path is controlled by `GDAL_NTV2_GRID_DIRS`.
- Multiple grid directories can be separated with the platform path separator
  (`;` on Windows, `:` on Linux/macOS).

## Default Grid Directory

By default the app checks:

```text
apps/proj_grids
```

Create that directory and place required grid files there, for example:

```text
apps/proj_grids/
  ca_nrc_ntv2_0.tif
  us_noaa_conus.tif
  your-local-grid.gsb
```

Supported local grid extensions include:

- `.gsb`
- `.gtx`
- `.tif`
- `.tiff`

## Coverage

Grid coverage depends on which grid files are installed in `GDAL_NTV2_GRID_DIRS`
or the default `apps/proj_grids` directory. Common examples include:

| Region | Typical grid family | Notes |
| --- | --- | --- |
| Canada | NTv2 / NRCAN grids | Used for NAD27/NAD83 transformations where available. |
| United States | NOAA / NADCON grids | Used for NAD27/NAD83 and related transformations where available. |
| Local jurisdictions | Local `.gsb` grids | Add authority-provided grids to the configured grid directory. |

If no matching grid is available for a transformation, PROJ may either choose a
lower-accuracy fallback operation or fail, depending on the CRS pair and PROJ
database rules. Operators should treat missing-grid warnings as accuracy risks.

## Verification

At runtime, CRS helpers scan `GDAL_NTV2_GRID_DIRS` and the active PROJ data path
for grid files. For production deployments, include the required grid files in
the worker image or mounted volume and set:

```text
GDAL_NTV2_GRID_DIRS=C:\path\to\proj_grids
```

or on Linux:

```text
GDAL_NTV2_GRID_DIRS=/opt/proj_grids
```
