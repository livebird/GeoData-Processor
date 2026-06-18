"""Client helper for the FastAPI GDAL processing server."""

from typing import Any

import requests


def submit_conversion(
    gdal_server_url: str,
    *,
    task_id: str,
    input_path: str,
    input_driver: str,
    input_driver_ext: str,
    conversion_driver: str,
    conversion_driver_ext: str,
    callback_url: str | None = None,
    conversion_kwargs: dict[str, Any] | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    payload = {
        "task_id": task_id,
        "input_path": input_path,
        "input_driver": input_driver,
        "input_driver_ext": input_driver_ext,
        "conversion_driver": conversion_driver,
        "conversion_driver_ext": conversion_driver_ext,
        "callback_url": callback_url,
        "conversion_kwargs": conversion_kwargs or {},
    }
    response = requests.post(f"{gdal_server_url.rstrip('/')}/convert", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def get_status(gdal_server_url: str, task_id: str, timeout: int = 5) -> dict[str, Any]:
    response = requests.get(f"{gdal_server_url.rstrip('/')}/status/{task_id}", timeout=timeout)
    response.raise_for_status()
    return response.json()
