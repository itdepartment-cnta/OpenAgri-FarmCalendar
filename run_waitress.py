#!/usr/bin/env python
import logging
import sys
import warnings
import os

from waitress import serve
from farm_calendar.wsgi import application

host = os.getenv('APP_HOST', '0.0.0.0')
port = int(os.getenv('APP_PORT', '8002'))
LOGGING_LEVEL = os.getenv('LOGGING_LEVEL', 'DEBUG')


# PARCHE CNTA: a stdout, para que 'docker logs' siga siendo util.
logging.basicConfig(stream=sys.stdout, level=getattr(logging, LOGGING_LEVEL))

warnings.filterwarnings("ignore")

serve(application, host=host, port=port)
