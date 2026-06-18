"""Run with: python -m gdal_server (from the GeoData-Processor repo root)."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "gdal_server.app:app",
        host="127.0.0.1",
        port=8002,
        reload=True,
    )
