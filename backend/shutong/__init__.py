import logging

# Library default: nothing printed unless the app sets up its handlers (shutong.logs.setup_logging).
logging.getLogger("shutong").addHandler(logging.NullHandler())
