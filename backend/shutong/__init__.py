import logging

__version__ = "0.3.0"  # kept equal to pyproject.toml and the web / desktop package.json (tests/test_version.py)

# Library default: nothing printed unless the app sets up its handlers (shutong.logs.setup_logging).
logging.getLogger("shutong").addHandler(logging.NullHandler())
