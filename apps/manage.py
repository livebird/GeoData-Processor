#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

# Add the apps directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fix PROJ_LIB environment variable mismatch before any other imports
try:
    import pyproj
    proj_data = pyproj.datadir.get_data_dir()
    os.environ['PROJ_LIB'] = proj_data
    os.environ['PROJ_DATA'] = proj_data
except ImportError:
    pass


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gps.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()