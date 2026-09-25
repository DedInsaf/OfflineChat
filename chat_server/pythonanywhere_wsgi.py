"""Copy this entry point into PythonAnywhere's Web > WSGI configuration file."""
import sys
from pathlib import Path

project = str(Path.home() / "offlinechat-service")
if project not in sys.path:
    sys.path.insert(0, project)

from chat_server.wsgi import hosted_application

application = hosted_application()
