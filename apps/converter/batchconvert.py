import os

import sys

import json

import re

import zipfile



# Fix PROJ_LIB environment variable mismatch

try:

    import pyproj

    proj_data = pyproj.datadir.get_data_dir()

    os.environ['PROJ_LIB'] = proj_data

    os.environ['PROJ_DATA'] = proj_data

except ImportError:

    pass



import numpy as np

import pandas as pd



# Attempt to import libraries with helpful error messages

try:

    import geopandas as gpd

    import rasterio

    from rasterio.features import rasterize, shapes as r_shapes

    from rasterio.warp import calculate_default_transform, reproject, Resampling

    from shapely.geometry import shape as s_shape

    from fiona.drvsupport import supported_drivers

    # Enable more drivers in fiona

    supported_drivers['KML'] = 'rw'

    supported_drivers['LIBKML'] = 'rw'

    supported_drivers['DXF'] = 'rw'

    supported_drivers['GPKG'] = 'rw'

    supported_drivers['GML'] = 'rw'

    supported_drivers['Avro'] = 'rw'

    supported_drivers['Parquet'] = 'rw'

    supported_drivers['Arrow'] = 'rw'

    supported_drivers['GeoParquet'] = 'rw'

    supported_drivers['Arrow IPC'] = 'rw'

    supported_drivers['FlatGeobuf'] = 'rw'

except ImportError as e:

    print(f"Warning: Missing library: {e}")

# Check if rasterio is available
HAS_RASTERIO = 'rasterio' in sys.modules

# Raster format definitions

RASTER_FORMATS = {'GTiff': '.tif', 'PNG': '.png', 'JPEG': '.jpg', 'JPG': '.jpg', 'GPKG': '.gpkg'}

_X_EXACT = {'x', 'longitude', 'long', 'lon', 'lng', 'east', 'easting'}
_Y_EXACT = {'y', 'latitude', 'lat', 'north', 'northing'}
_LAT_SUFFIXES = ('_lat', '_latitude', '_y', '_north', '_northing')
_LON_SUFFIXES = ('_lon', '_lng', '_long', '_longitude', '_x', '_east', '_easting')
_LAT_TOKENS = {'lat', 'latitude', 'y', 'north', 'northing'}
_LON_TOKENS = {'lon', 'lng', 'long', 'longitude', 'x', 'east', 'easting'}
_WKT_COL_NAMES = {'wkt', 'geometry', 'geom', 'the_geom', 'shape', 'geography', 'location'}
_GEOJSON_COL_NAMES = {'geojson', 'geometry_geojson', '__geometry_geojson__'}
_PREFIX_PRIORITY = (
    'origin', 'start', 'from', 'pickup', 'source', 'point',
    'dest', 'destination', 'end', 'to', 'dropoff', 'target',
)
_CSV_COORD_ERROR = (
    "CSV has no recognizable spatial columns. "
    "Provide lat/lon pairs (latitude/longitude, origin_lat/origin_lon, etc.), "
    "a WKT geometry column, or a GeoJSON geometry column."
)


def _normalize_column_name(name):
    return re.sub(r'[^a-z0-9]+', '_', str(name).lower()).strip('_')


def _column_tokens(name):
    return [token for token in _normalize_column_name(name).split('_') if token]


def _column_looks_like_lat(name):
    cl = _normalize_column_name(name)
    if cl in _Y_EXACT:
        return True
    tokens = _column_tokens(name)
    return any(token in _LAT_TOKENS for token in tokens)


def _column_looks_like_lon(name):
    cl = _normalize_column_name(name)
    if cl in _X_EXACT:
        return True
    tokens = _column_tokens(name)
    return any(token in _LON_TOKENS for token in tokens)


def _coord_prefix(name, *, is_lat):
    cl = _normalize_column_name(name)
    suffixes = _LAT_SUFFIXES if is_lat else _LON_SUFFIXES
    tokens = _LAT_TOKENS if is_lat else _LON_TOKENS
    for suf in suffixes:
        if cl.endswith(suf):
            return cl[:-len(suf)].rstrip('_')
    filtered = [token for token in _column_tokens(name) if token not in tokens]
    return '_'.join(filtered)


def _find_wkt_column(columns):
    for col in columns:
        cl = _normalize_column_name(col)
        if cl in _WKT_COL_NAMES:
            return col
        if 'wkt' in cl or cl.endswith('_geom') or cl == 'geom' or 'geometry' in cl:
            return col
    return None


def _find_geojson_column(columns):
    for col in columns:
        cl = _normalize_column_name(col)
        if cl in _GEOJSON_COL_NAMES or 'geojson' in cl:
            return col
    return None


def _find_coordinate_pairs(columns):
    """Return ordered (lon_col, lat_col, prefix) pairs from tabular columns."""
    columns = list(columns)
    lower = {c: c.lower() for c in columns}

    x_match = [c for c in columns if lower[c] in _X_EXACT]
    y_match = [c for c in columns if lower[c] in _Y_EXACT]
    if x_match and y_match:
        return [(x_match[0], y_match[0], '')]

    pairs = {}
    for c in columns:
        cl = lower[c]
        for suf in _LAT_SUFFIXES:
            if cl.endswith(suf):
                prefix = cl[:-len(suf)].rstrip('_')
                pairs.setdefault(prefix, {})['lat'] = c
                break
        else:
            for suf in _LON_SUFFIXES:
                if cl.endswith(suf):
                    prefix = cl[:-len(suf)].rstrip('_')
                    pairs.setdefault(prefix, {})['lon'] = c
                    break

    result = [
        (cols['lon'], cols['lat'], prefix)
        for prefix, cols in pairs.items()
        if 'lat' in cols and 'lon' in cols
    ]

    if not result:
        lat_cols = [c for c in columns if _column_looks_like_lat(c)]
        lon_cols = [c for c in columns if _column_looks_like_lon(c)]
        used_lon = set()
        for lat_col in lat_cols:
            lat_prefix = _coord_prefix(lat_col, is_lat=True)
            for lon_col in lon_cols:
                if lon_col in used_lon:
                    continue
                if _coord_prefix(lon_col, is_lat=False) == lat_prefix:
                    result.append((lon_col, lat_col, lat_prefix))
                    used_lon.add(lon_col)
                    break
        if not result and lat_cols and lon_cols:
            result.append((lon_cols[0], lat_cols[0], ''))

    def _sort_key(item):
        prefix = item[2]
        if prefix in _PREFIX_PRIORITY:
            return _PREFIX_PRIORITY.index(prefix)
        return len(_PREFIX_PRIORITY)

    result.sort(key=_sort_key)
    return result


def csv_has_spatial_columns(columns):
    """Return True when a CSV header row contains usable spatial data."""
    columns = list(columns)
    if _find_coordinate_pairs(columns):
        return True
    if _find_wkt_column(columns):
        return True
    if _find_geojson_column(columns):
        return True
    return False


def _read_csv_wkt(df, wkt_col):
    from shapely import wkt as wkt_loader

    geom = [
        wkt_loader.loads(value) if isinstance(value, str) and value.strip() else None
        for value in df[wkt_col]
    ]
    drop_cols = [wkt_col]
    geojson_col = _find_geojson_column(df.columns)
    if geojson_col:
        drop_cols.append(geojson_col)
    out = df.drop(columns=[col for col in drop_cols if col in df.columns])
    gdf = gpd.GeoDataFrame(out, geometry=geom, crs="EPSG:4326")
    return gdf


def _read_csv_geojson(df, geojson_col):
    from shapely.geometry import shape

    def _parse_geojson(value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, dict):
            return shape(value)
        if isinstance(value, str) and value.strip():
            try:
                return shape(json.loads(value))
            except Exception:
                return None
        return None

    geom = [_parse_geojson(value) for value in df[geojson_col]]
    drop_cols = [geojson_col]
    wkt_col = _find_wkt_column(df.columns)
    if wkt_col:
        drop_cols.append(wkt_col)
    out = df.drop(columns=[col for col in drop_cols if col in df.columns])
    gdf = gpd.GeoDataFrame(out, geometry=geom, crs="EPSG:4326")
    return gdf


def _read_csv_as_geodataframe(df):
    """Build a GeoDataFrame from a CSV DataFrame using coordinate column pairs."""
    wkt_col = _find_wkt_column(df.columns)
    if wkt_col:
        return _read_csv_wkt(df, wkt_col)

    geojson_col = _find_geojson_column(df.columns)
    if geojson_col:
        return _read_csv_geojson(df, geojson_col)

    pairs = _find_coordinate_pairs(df.columns)
    if not pairs:
        raise ValueError(_CSV_COORD_ERROR)

    pair_map = {prefix: (lon_col, lat_col) for lon_col, lat_col, prefix in pairs}

    if 'origin' in pair_map and 'dest' in pair_map:
        ox, oy = pair_map['origin']
        dx, dy = pair_map['dest']
        from shapely.geometry import LineString

        coords = df[[ox, oy, dx, dy]].astype(float).to_numpy()
        geoms = [LineString([(row[0], row[1]), (row[2], row[3])]) for row in coords]
        gdf = gpd.GeoDataFrame(df, geometry=geoms)
        gdf.set_crs("EPSG:4326", inplace=True)
        return gdf

    lon_col, lat_col, _ = pairs[0]
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df[lon_col].astype(float), df[lat_col].astype(float)),
    )
    gdf.set_crs("EPSG:4326", inplace=True)
    return gdf


def _read_vector(file_path):

    """Robustly read vector files including CSV with coordinates."""

    ext = os.path.splitext(file_path)[1].lower()

    if ext == '.csv':

        df = pd.read_csv(file_path)
        return _read_csv_as_geodataframe(df)

    elif ext == '.arrow':

        try:

            return gpd.read_feather(file_path)

        except Exception:

            pass

    elif ext == '.avro':

        try:

            return gpd.read_file(file_path)

        except Exception:

            import fastavro

            from shapely import wkt

            from shapely.geometry import Point

            import json

            records = []

            with open(file_path, 'rb') as f:

                reader = fastavro.reader(f)

                for record in reader:

                    records.append(record)

            df = pd.DataFrame(records)

            # Check for geometry WKT column (both sanitized and unsanitized names)

            wkt_col = None

            geojson_col = None

            for col in df.columns:

                cl = col.lower()

                if cl in ('__geometry_wkt__', 'geometry_wkt', '_geometry_wkt_', '_geometry_wkt'):

                    wkt_col = col

                if cl in ('__geometry_geojson__', 'geometry_geojson', '_geometry_geojson_', '_geometry_geojson'):

                    geojson_col = col

            if wkt_col:

                geom = [wkt.loads(g) if g else None for g in df[wkt_col]]

                drop_cols = [c for c in [wkt_col, geojson_col] if c is not None and c in df.columns]

                df = df.drop(columns=drop_cols)

                return gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")

            # Fallback: try to reconstruct geometry from lat/lon columns
            try:
                return _read_csv_as_geodataframe(df)
            except ValueError:
                return gpd.GeoDataFrame(df)

    return gpd.read_file(file_path)





def _sanitize_shapefile_columns(gdf):

    """Prepare fields for shapefile DBF output."""

    out = gdf.copy()

    used = set()

    rename_map = {}

    reserved = {'date', 'time', 'datetime', 'select', 'where', 'table', 'from', 'value'}



    for column in out.columns:

        if column == out.geometry.name:

            continue



        safe = re.sub(r'[^0-9A-Za-z_]+', '_', str(column)).strip('_').lower()

        if not safe:

            safe = 'field'

        if safe[0].isdigit():

            safe = f'f_{safe}'

        if safe in reserved:

            safe = f'{safe}_txt'

        safe = safe[:10]



        base = safe[:8] if len(safe) > 8 else safe

        candidate = safe

        counter = 1

        while candidate.lower() in used:

            suffix = str(counter)

            candidate = f"{base[:10 - len(suffix)]}{suffix}"

            counter += 1

        used.add(candidate.lower())

        if candidate != column:

            rename_map[column] = candidate



    if rename_map:

        out = out.rename(columns=rename_map)



    for column in out.columns:

        if column == out.geometry.name:

            continue

        if pd.api.types.is_datetime64_any_dtype(out[column]):

            out[column] = out[column].dt.strftime('%Y-%m-%dT%H:%M:%S')

        elif pd.api.types.is_timedelta64_dtype(out[column]):

            out[column] = out[column].astype(str)

        else:

            out[column] = out[column].map(

                lambda value: value.isoformat()

                if hasattr(value, 'isoformat') and value.__class__.__module__ == 'datetime'

                else value

            )



    return out





def _write_kml(gdf, out_path, driver):

    gdf.to_file(out_path, driver=driver)



# Driver name mapping (UI name -> GDAL/OGR name)

DRIVER_MAP = {

    'KML': 'KML',

    'GeoParquet': 'Parquet',

    'GeoPackage': 'GPKG',

    'Arrow IPC': 'Arrow',

    'Avro': 'Avro',

    'GeoTIFF': 'GTiff',

}



def _sanitize_avro_field_name(name, used):

    field = re.sub(r'\W+', '_', str(name)).strip('_')

    if not field or field[0].isdigit():

        field = f'field_{field}' if field else 'field'

    base = field

    counter = 2

    while field in used:

        field = f'{base}_{counter}'

        counter += 1

    used.add(field)

    return field



def _avro_long(value):

    encoded = (int(value) << 1) ^ (int(value) >> 63)

    out = bytearray()

    while encoded & ~0x7F:

        out.append((encoded & 0x7F) | 0x80)

        encoded >>= 7

    out.append(encoded)

    return bytes(out)



def _avro_bytes(value):

    return _avro_long(len(value)) + value



def _avro_string(value):

    return _avro_bytes(str(value).encode('utf-8'))



def _avro_map(items):

    if not items:

        return _avro_long(0)

    data = bytearray()

    data += _avro_long(len(items))

    for key, value in items.items():

        data += _avro_string(key)

        data += _avro_bytes(value)

    data += _avro_long(0)

    return bytes(data)



def _write_avro_dataframe(df, out_path):

    from shapely.geometry import mapping



    is_gdf = isinstance(df, gpd.GeoDataFrame)

    used_names = set()

    source_columns = []



    for col in df.columns:

        if is_gdf and col == df.geometry.name:

            continue

        source_columns.append((col, _sanitize_avro_field_name(col, used_names)))



    if is_gdf:

        source_columns.append(('__geometry_wkt__', _sanitize_avro_field_name('geometry_wkt', used_names)))

        source_columns.append(('__geometry_geojson__', _sanitize_avro_field_name('geometry_geojson', used_names)))



    schema = {

        'type': 'record',

        'name': 'Feature',

        'namespace': 'batchconvert',

        'fields': [

            {'name': avro_name, 'type': ['null', 'string'], 'default': None}

            for _, avro_name in source_columns

        ],

    }



    def encode_nullable_string(value):

        try:

            is_missing = pd.isna(value)

            if not isinstance(is_missing, bool):

                is_missing = False

        except Exception:

            is_missing = False

        if value is None or is_missing:

            return _avro_long(0)

        return _avro_long(1) + _avro_string(value)



    records = bytearray()

    for _, row in df.iterrows():

        geom = row.geometry if is_gdf else None

        for source_name, _ in source_columns:

            if source_name == '__geometry_wkt__':

                value = geom.wkt if geom is not None and not geom.is_empty else None

            elif source_name == '__geometry_geojson__':

                value = json.dumps(mapping(geom)) if geom is not None and not geom.is_empty else None

            else:

                value = row.get(source_name)

            records += encode_nullable_string(value)



    sync = os.urandom(16)

    metadata = {

        'avro.schema': json.dumps(schema, separators=(',', ':')).encode('utf-8'),

        'avro.codec': b'null',

    }



    with open(out_path, 'wb') as f:

        f.write(b'Obj\x01')

        f.write(_avro_map(metadata))

        f.write(sync)

        f.write(_avro_long(len(df)))

        f.write(_avro_long(len(records)))

        f.write(records)

        f.write(sync)



def _write_arrow_dataframe(gdf, out_path):

    try:

        import pyarrow.feather  # noqa: F401

    except ImportError as exc:

        raise RuntimeError(

            "Arrow IPC conversion requires pyarrow. Install it with: pip install pyarrow"

        ) from exc

    gdf.to_feather(out_path)



def matching_input_extensions(input_driver_ext):
    """Return filename suffixes that satisfy a driver extension (e.g. GeoJSON accepts .json)."""
    ext = (input_driver_ext or "").lower()
    if ext == ".geojson":
        return (".geojson", ".json")
    return (ext,)


def path_matches_driver_ext(path, input_driver_ext):
    p_lower = path.lower()
    for ext in matching_input_extensions(input_driver_ext):
        if p_lower.endswith(ext):
            return True
    if (input_driver_ext or "").lower() == ".gdb" and p_lower.endswith(".gdbtable"):
        return True
    return False


def _find_input_files(input_path, input_driver_ext):

    print(f"[DEBUG] _find_input_files called:")
    print(f"  input_path: {input_path}")
    print(f"  input_driver_ext: {input_driver_ext}")
    print(f"  input_path exists: {os.path.exists(input_path) if isinstance(input_path, str) else 'N/A'}")

    if isinstance(input_path, str):

        if os.path.isdir(input_path):

            files = []

            for root, dirs, fnames in os.walk(input_path):

                for item in dirs + fnames:

                    if path_matches_driver_ext(item, input_driver_ext):

                        files.append(os.path.join(root, item))

            print(f"[DEBUG] Found {len(files)} files in directory")
            return files

        else:

            matches = path_matches_driver_ext(input_path, input_driver_ext)
            print(f"[DEBUG] File path matches extension: {matches}")
            return [input_path] if matches else []

    else:

        files = [f for f in input_path if path_matches_driver_ext(f, input_driver_ext)]
        print(f"[DEBUG] Found {len(files)} files from list")
        return files



def batch_convert(input_path, output_path, input_driver, input_driver_ext, conversion_driver, conversion_driver_ext, **kwargs):

    """Batch Conversion Tool using GeoPandas and Rasterio (GDAL-based)"""

    conversion_crs = kwargs.get('conversion_crs')

    print(f"[INFO] Starting batch conversion:")
    print(f"  Input path: {input_path}")
    print(f"  Output path: {output_path}")
    print(f"  Input driver: {input_driver} ({input_driver_ext})")
    print(f"  Output driver: {conversion_driver} ({conversion_driver_ext})")
    print(f"  CRS: {conversion_crs}")

    

    # Map driver names if necessary

    input_driver = DRIVER_MAP.get(input_driver, input_driver)

    conversion_driver = DRIVER_MAP.get(conversion_driver, conversion_driver)

    print(f"[INFO] Mapped drivers: input={input_driver}, output={conversion_driver}")



    files_to_process = _find_input_files(input_path, input_driver_ext)

    print(f"[INFO] Found {len(files_to_process)} files to process")

    if not files_to_process:

        print(f"[ERROR] No files found matching extension {input_driver_ext} in {input_path}")
        raise ValueError(f"No files were found for conversion. Input path: {input_path}, Extension: {input_driver_ext}")



    os.makedirs(output_path, exist_ok=True)
    print(f"[INFO] Output directory created: {output_path}")

    

    # Determine input type from the first file

    first_file = files_to_process[0]

    input_is_raster = input_driver in RASTER_FORMATS

    print(f"[INFO] Input type detection: driver in RASTER_FORMATS = {input_is_raster}")

    

    if input_driver == 'GPKG':

        try:

            if HAS_RASTERIO:

                with rasterio.open(first_file) as src:

                    input_is_raster = True

            else:

                input_is_raster = False

        except Exception:

            input_is_raster = False

            

    # Fallback check for input type

    if not input_is_raster and input_driver_ext.lower() in ['.tif', '.tiff', '.png', '.jpg', '.jpeg']:

        input_is_raster = True

    print(f"[INFO] Final input type: raster={input_is_raster}")

    

    # Determine output type

    # If conversion_driver is in RASTER_FORMATS, it's potentially a raster

    output_is_raster = conversion_driver in RASTER_FORMATS

    print(f"[INFO] Output type detection: driver in RASTER_FORMATS = {output_is_raster}")

    

    # Ambiguity check for dual-purpose formats like GeoPackage (GPKG)

    # If input is vector and output is GPKG, we default to vector-to-vector 

    # UNLESS the user explicitly wanted a raster (which we can't know for sure here, 

    # but we'll prioritize vector-to-vector for GPKG if input is vector).

    if conversion_driver == 'GPKG' and not input_is_raster:

        output_is_raster = False

    

    # Fallback check for output type from extension

    if not output_is_raster and conversion_driver_ext.lower() in ['.tif', '.png', '.jpg']:

        output_is_raster = True

    print(f"[INFO] Final output type: raster={output_is_raster}")

    print(f"[INFO] Conversion type: {'raster->raster' if input_is_raster and output_is_raster else 'vector->vector' if not input_is_raster and not output_is_raster else 'vector->raster' if not input_is_raster and output_is_raster else 'raster->vector'}")



    if input_is_raster and output_is_raster:

        print(f"[INFO] Calling _raster_to_raster")
        _raster_to_raster(files_to_process, output_path, conversion_driver, conversion_driver_ext, conversion_crs)

    elif not input_is_raster and not output_is_raster:

        print(f"[INFO] Calling _vector_to_vector")
        _vector_to_vector(files_to_process, output_path, conversion_driver, conversion_driver_ext, conversion_crs)

    elif not input_is_raster and output_is_raster:

        print(f"[INFO] Calling _vector_to_raster")
        _vector_to_raster(files_to_process, output_path, conversion_driver, conversion_driver_ext, conversion_crs)

    elif input_is_raster and not output_is_raster:

        print(f"[INFO] Calling _raster_to_vector")
        _raster_to_vector(files_to_process, output_path, conversion_driver, conversion_driver_ext, conversion_crs)



    # Return list of converted files

    out_files = []

    for root, _, filenames in os.walk(output_path):

        for f in filenames:

            out_files.append(os.path.join(root, f))

    print(f"[INFO] Conversion complete. Output files: {len(out_files)}")
    if not out_files:
        print(f"[ERROR] No output files were produced in {output_path}")
        raise RuntimeError(f"No files were produced during conversion. Output directory: {output_path}")
    return out_files



def _vector_to_vector(files, out_dir, driver, ext, crs):

    print(f"[INFO] _vector_to_vector called with {len(files)} files, driver={driver}, ext={ext}")

    last_error = None
    success_count = 0

    for f in files:

        try:

            print(f"[INFO] Processing file: {os.path.basename(f)}")

            gdf = _read_vector(f)

            print(f"[INFO] Read file successfully, {len(gdf)} features")

            if gdf.empty:
                print(f"[WARNING] Empty GeoDataFrame, skipping: {os.path.basename(f)}")
                continue

            if not isinstance(gdf, gpd.GeoDataFrame) or gdf.geometry.name not in gdf.columns:
                raise ValueError(f"{os.path.basename(f)} has no geometry. {_CSV_COORD_ERROR}")

            

            # Ensure geometries are valid

            gdf['geometry'] = gdf.geometry.make_valid()

            

            # Handle CRS transformation

            if crs:

                # User provided a target CRS

                if gdf.crs is None: gdf.set_crs("EPSG:4326", inplace=True)

                gdf = gdf.to_crs(f"EPSG:{crs}" if str(crs).isdigit() else crs)

            

            # KML MUST be in WGS84 (EPSG:4326). 

            # If the output driver is KML, we force it to 4326 if it's not already.

            if driver in ['KML', 'LIBKML']:

                if gdf.crs is None:

                    gdf.set_crs("EPSG:4326", inplace=True)

                elif str(gdf.crs).upper() not in ['EPSG:4326', 'WGS 84']:

                    gdf = gdf.to_crs("EPSG:4326")

                

                # Sanitize coordinates for KML compliance (lon -180 to 180, lat -90 to 90)

                from shapely.ops import transform

                def _normalize_kml_coords(x, y, z=None):

                    nx = (x + 180) % 360 - 180

                    ny = max(-90, min(90, y))

                    return (nx, ny, z) if z is not None else (nx, ny)

                

                gdf['geometry'] = gdf.geometry.map(lambda g: transform(_normalize_kml_coords, g) if g is not None else None)

                

                # Sanitize attributes for KML (convert to string if problematic)

                # Some OGR KML drivers fail on certain field types or names

                for col in gdf.columns:

                    if col != gdf.geometry.name:

                        gdf[col] = gdf[col].astype(str)

            

            out_name = os.path.splitext(os.path.basename(f))[0] + ext

            out_path = os.path.join(out_dir, out_name)

            print(f"[INFO] Writing output to: {out_path}")

            

            if driver == 'CSV':

                gdf.to_csv(out_path, index=False)
                print(f"[OK] Written CSV: {out_name}")

            elif driver == 'Parquet':

                gdf.to_parquet(out_path)
                print(f"[OK] Written Parquet: {out_name}")

            elif driver == 'Arrow':

                _write_arrow_dataframe(gdf, out_path)
                print(f"[OK] Written Arrow: {out_name}")

            elif driver == 'Avro':

                _write_avro_dataframe(gdf, out_path)
                print(f"[OK] Written Avro: {out_name}")

            else:

                # Final check for geometry consistency for Shapefile

                if driver == 'ESRI Shapefile':

                    from shapely.geometry import MultiPolygon, Polygon

                    if any(gdf.geometry.type == 'Polygon') and any(gdf.geometry.type == 'MultiPolygon'):

                        gdf['geometry'] = [MultiPolygon([g]) if isinstance(g, Polygon) else g for g in gdf.geometry]

                    gdf = _sanitize_shapefile_columns(gdf)

                

                try:

                    # DXF is handled here too now via robust fallback

                    print(f"[INFO] Writing with driver: {driver}")
                    _write_kml(gdf, out_path, driver)
                    print(f"[OK] Written with driver {driver}: {out_name}")

                except Exception as e:

                    error_str = str(e).lower()

                    if "field" in error_str or "translate" in error_str or "feature" in error_str:

                        # Fallback: Try saving without attributes if the driver rejects them

                        print(f"[RETRY] {out_name}: Saving without attributes due to: {e}")

                        try:

                            _write_kml(gdf[[gdf.geometry.name]], out_path, driver)
                            print(f"[OK] Written without attributes: {out_name}")

                        except Exception as e2:

                            print(f"[ERROR] Failed to write without attributes: {e2}")
                            raise e2

                    else:

                        print(f"[ERROR] Failed to write: {e}")
                        raise e

            success_count += 1
            print(f"[OK] Converted: {out_name}")

        except Exception as e:

            last_error = e
            print(f"[ERROR] {f}: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")

    print(f"[INFO] _vector_to_vector complete. Success: {success_count}/{len(files)}")
    if last_error and not any(os.listdir(out_dir) if os.path.isdir(out_dir) else []):
        print(f"[ERROR] No output files produced in {out_dir}")
        raise RuntimeError(str(last_error))


def _raster_to_raster(files, out_dir, driver, ext, crs):

    print(f"[INFO] _raster_to_raster called with {len(files)} files, driver={driver}, ext={ext}")

    for f in files:

        try:

            print(f"[INFO] Processing file: {os.path.basename(f)}")

            with rasterio.open(f) as src:

                profile = src.profile.copy()

                data = src.read()

                print(f"[INFO] Read raster: {src.width}x{src.height}, {src.count} bands, dtype={src.dtypes[0]}")

                

                if crs:

                    from rasterio.crs import CRS

                    dst_crs = CRS.from_epsg(int(crs)) if str(crs).isdigit() else CRS.from_user_input(crs)

                    transform, width, height = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds)

                    profile.update(crs=dst_crs, transform=transform, width=width, height=height)

                    dst_data = np.zeros((src.count, height, width), dtype=src.dtypes[0])

                    for i in range(1, src.count + 1):

                        reproject(rasterio.band(src, i), dst_data[i-1], dst_transform=transform, dst_crs=dst_crs, resampling=Resampling.nearest)

                    data = dst_data

                    print(f"[INFO] Reprojected to {crs}")



                profile.update(driver=driver)

                if driver in ['PNG', 'JPEG']:

                    profile.update(dtype='uint8', count=min(src.count, 4))

                    if data.dtype != 'uint8':

                        data = ((data - data.min()) / (data.max() - data.min()) * 255).astype('uint8')

                    print(f"[INFO] Converted to uint8 for PNG/JPEG")

                

                out_name = os.path.splitext(os.path.basename(f))[0] + ext
                out_path = os.path.join(out_dir, out_name)
                print(f"[INFO] Writing output to: {out_path}")

                with rasterio.open(out_path, 'w', **profile) as dst:

                    dst.write(data)

                print(f"[OK] Converted: {out_name}")

        except Exception as e:

            print(f"[ERROR] {f}: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")



def _vector_to_raster(files, out_dir, driver, ext, crs):

    print(f"[INFO] _vector_to_raster called with {len(files)} files, driver={driver}, ext={ext}")

    for f in files:

        try:

            print(f"[INFO] Processing file: {os.path.basename(f)}")

            gdf = _read_vector(f)

            print(f"[INFO] Read vector file, {len(gdf)} features")

            if gdf.empty:
                print(f"[WARNING] Empty GeoDataFrame, skipping: {os.path.basename(f)}")
                continue

            if crs:

                if gdf.crs is None: gdf.set_crs("EPSG:4326", inplace=True)

                gdf = gdf.to_crs(f"EPSG:{crs}" if str(crs).isdigit() else crs)

                print(f"[INFO] Reprojected to {crs}")

            

            bounds = gdf.total_bounds

            if bounds[2] == bounds[0] or bounds[3] == bounds[1]:

                # Fix for point geometries or zero-area bounds

                bounds = [bounds[0]-1, bounds[1]-1, bounds[2]+1, bounds[3]+1]

                print(f"[INFO] Adjusted zero-area bounds")

            

            res = max(bounds[2]-bounds[0], bounds[3]-bounds[1]) / 1000

            transform = rasterio.transform.from_bounds(*bounds, 1000, 1000)

            

            shapes = [(g, 255) for g in gdf.geometry if g is not None and not g.is_empty]

            if not shapes:

                print(f"[WARNING] No valid geometries to rasterize in {f}")

                continue

            print(f"[INFO] Rasterizing {len(shapes)} geometries")

            burned = rasterize(shapes, out_shape=(1000, 1000), transform=transform)

            

            profile = {

                'driver': driver, 'height': 1000, 'width': 1000, 'count': 1,

                'dtype': 'uint8', 'crs': gdf.crs, 'transform': transform

            }

            

            out_name = os.path.splitext(os.path.basename(f))[0] + ext
            out_path = os.path.join(out_dir, out_name)
            print(f"[INFO] Writing output to: {out_path}")

            with rasterio.open(out_path, 'w', **profile) as dst:

                dst.write(burned, 1)

            print(f"[OK] Rasterized: {out_name}")

        except Exception as e:

            print(f"[ERROR] {f}: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")



def _raster_to_vector(files, out_dir, driver, ext, crs):

    print(f"[INFO] _raster_to_vector called with {len(files)} files, driver={driver}, ext={ext}")

    for f in files:

        try:

            print(f"[INFO] Processing file: {os.path.basename(f)}")

            with rasterio.open(f) as src:

                data = src.read(1)

                print(f"[INFO] Read raster: {src.width}x{src.height}, nodata={src.nodata}")

                if src.nodata is not None:

                    mask = data != src.nodata

                else:

                    # Extract all non-zero pixels if nodata is not set (better than data > 0 which ignores negatives)

                    mask = data != 0

                

                # Extract shapes

                results = (

                    {'properties': {'raster_val': float(v) if isinstance(v, (np.floating, float)) else int(v)}, 'geometry': s}

                    for i, (s, v) in enumerate(r_shapes(data, mask=mask, transform=src.transform))

                )

                geoms = list(results)

                if not geoms:

                    print(f"[WARNING] No geometries extracted from raster: {f}")

                    continue

                gdf = gpd.GeoDataFrame.from_features(geoms, crs=src.crs)

                print(f"[INFO] Extracted {len(gdf)} geometries")

            

            # Ensure geometries are valid and handle MultiPolygons

            if not gdf.empty:

                gdf['geometry'] = gdf.geometry.make_valid()

                if any(gdf.geometry.type == 'MultiPolygon'):

                    gdf = gdf.explode(index_parts=False)

                    print(f"[INFO] Exploded MultiPolygons")



            # Handle CRS transformation

            if crs:

                # User provided a target CRS

                if gdf.crs is None: gdf.set_crs("EPSG:4326", inplace=True)

                gdf = gdf.to_crs(f"EPSG:{crs}" if str(crs).isdigit() else crs)

                print(f"[INFO] Reprojected to {crs}")



            # KML MUST be in WGS84 (EPSG:4326).

            # If the output driver is KML, we force it to 4326 if it's not already.

            if driver in ['KML', 'LIBKML']:

                if gdf.crs is None:

                    gdf.set_crs("EPSG:4326", inplace=True)

                elif str(gdf.crs).upper() not in ['EPSG:4326', 'WGS 84']:

                    gdf = gdf.to_crs("EPSG:4326")



                # Sanitize coordinates for KML compliance (lon -180 to 180, lat -90 to 90)

                from shapely.ops import transform

                def _normalize_kml_coords(x, y, z=None):

                    nx = (x + 180) % 360 - 180

                    ny = max(-90, min(90, y))

                    return (nx, ny, z) if z is not None else (nx, ny)



                gdf['geometry'] = gdf.geometry.map(lambda g: transform(_normalize_kml_coords, g) if g is not None else None)



                # Sanitize attributes for KML (convert to string if problematic)

                for col in gdf.columns:

                    if col != gdf.geometry.name:

                        gdf[col] = gdf[col].astype(str)

                

            out_name = os.path.splitext(os.path.basename(f))[0] + ext

            out_path = os.path.join(out_dir, out_name)

            print(f"[INFO] Writing output to: {out_path}")

            

            if driver == 'CSV':

                gdf.to_csv(out_path, index=False)

                print(f"[OK] Written CSV: {out_name}")

            elif driver == 'Parquet':

                gdf.to_parquet(out_path)

                print(f"[OK] Written Parquet: {out_name}")

            elif driver == 'Arrow':

                _write_arrow_dataframe(gdf, out_path)

                print(f"[OK] Written Arrow: {out_name}")

            elif driver == 'Avro':

                _write_avro_dataframe(gdf, out_path)

                print(f"[OK] Written Avro: {out_name}")

            else:

                # Final check for geometry consistency for Shapefile

                if driver == 'ESRI Shapefile':

                    from shapely.geometry import MultiPolygon, Polygon

                    if any(gdf.geometry.type == 'Polygon') and any(gdf.geometry.type == 'MultiPolygon'):

                        gdf['geometry'] = [MultiPolygon([g]) if isinstance(g, Polygon) else g for g in gdf.geometry]

                    gdf = _sanitize_shapefile_columns(gdf)

                

                try:

                    print(f"[INFO] Writing with driver: {driver}")
                    gdf.to_file(out_path, driver=driver)
                    print(f"[OK] Written with driver {driver}: {out_name}")

                except Exception as e:

                    error_str = str(e).lower()

                    if "field" in error_str or "translate" in error_str or "feature" in error_str:

                        # Fallback: Try saving without attributes

                        print(f"[RETRY] {out_name}: Saving without attributes due to: {e}")

                        try:

                            gdf[[gdf.geometry.name]].to_file(out_path, driver=driver)
                            print(f"[OK] Written without attributes: {out_name}")

                        except Exception as e2:

                            print(f"[ERROR] Failed to write without attributes: {e2}")
                            raise e2

                    else:

                        print(f"[ERROR] Failed to write: {e}")
                        raise e

            print(f"[OK] Vectorized: {out_name}")

        except Exception as e:

            print(f"[ERROR] {f}: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")





def get_gdal_info(file_path):

    """Return GDAL/OGR metadata dict for a geospatial file.



    Tries rasterio first (for raster files), then geopandas/fiona (for vector

    files).  Returns an empty dict if the file is not a recognised geospatial

    format or if the required libraries are not available.

    """

    info = {}

    if not os.path.exists(file_path):

        return info



    ext = os.path.splitext(file_path)[1].lower()



    # --- Try raster first ---------------------------------------------------

    raster_exts = {'.tif', '.tiff', '.png', '.jpg', '.jpeg', '.gpkg'}

    if ext in raster_exts:

        try:

            with rasterio.open(file_path) as src:

                info['driver'] = src.driver

                info['crs'] = str(src.crs) if src.crs else None

                info['width'] = src.width

                info['height'] = src.height

                info['bands'] = src.count

                info['dtype'] = str(src.dtypes[0]) if src.dtypes else None

                info['bounds'] = dict(zip(

                    ['left', 'bottom', 'right', 'top'], src.bounds

                ))

                info['type'] = 'raster'

                return info

        except Exception:

            pass  # fall through – might be a vector GPKG



    # --- Try vector ---------------------------------------------------------

    vector_exts = {

        '.shp', '.geojson', '.json', '.kml', '.gpkg', '.gdb',

        '.dxf', '.csv', '.gml', '.fgb', '.parquet', '.arrow', '.avro',

    }

    if ext in vector_exts:

        try:

            gdf = gpd.read_file(file_path, rows=0)  # schema only

            info['driver'] = getattr(gdf, '_metadata', {}).get('driver', None)

            info['crs'] = str(gdf.crs) if gdf.crs else None

            info['geometry_type'] = str(gdf.geometry.geom_type.unique()[0]) if not gdf.empty else None

            info['type'] = 'vector'



            # Try to get feature count without reading all rows

            try:

                full = gpd.read_file(file_path)

                info['feature_count'] = len(full)

                info['columns'] = [c for c in full.columns if c != full.geometry.name]

                if not full.empty:

                    info['bounds'] = dict(zip(

                        ['minx', 'miny', 'maxx', 'maxy'], full.total_bounds

                    ))

                    info['geometry_type'] = str(full.geometry.geom_type.unique()[0])

            except Exception:

                pass



            return info

        except Exception:

            pass



    return info

