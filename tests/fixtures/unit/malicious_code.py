UNSAFE_IMPORT_OS = "import os\n"

UNSAFE_IMPORT_SUBPROCESS = "import subprocess\n"

UNSAFE_SHELL_OS_SYSTEM = """
import os

os.system("rm -rf /")
"""

UNSAFE_SHELL_SUBPROCESS_RUN = """
import subprocess

subprocess.run(["ls"])
"""

UNSAFE_DYNAMIC_IMPORT_DUNDER = '__import__("os")\n'

UNSAFE_DYNAMIC_IMPORT_IMPORTLIB = """
import importlib

importlib.import_module("os")
"""

UNSAFE_EXEC = 'exec("print(1)")\n'

UNSAFE_EVAL = 'eval("1 + 1")\n'

UNSAFE_GETATTR = 'getattr(__builtins__, "exec")\n'

UNSAFE_ABSOLUTE_OPEN = 'open("/etc/passwd")\n'

UNSAFE_TRAVERSAL_OPEN = 'open("../secret.txt")\n'

SAFE_PANDAS_IO = """
from _snapscript_paths import INPUT_PATH, OUTPUT_PATH
import pandas as pd

df = pd.read_csv(INPUT_PATH)
df.to_csv(OUTPUT_PATH, index=False)
"""

SAFE_RELATIVE_OPEN = """
with open("notes.txt", "w") as file:
    file.write("ok")
"""


UNSAFE_IMPORT_SNIPPETS = {
    "import_os": UNSAFE_IMPORT_OS,
    "import_os_path": "import os.path\n",
    "from_os_path": "from os.path import join\n",
    "import_subprocess": UNSAFE_IMPORT_SUBPROCESS,
    "import_socket": "import socket\n",
    "import_http_client": "import http.client\n",
    "from_urllib_request": "from urllib.request import urlopen\n",
    "import_requests": "import requests\n",
    "import_ftplib": "import ftplib\n",
    "import_smtplib": "import smtplib\n",
    "import_pickle": "import pickle\n",
    "import_shelve": "import shelve\n",
    "import_ctypes": "import ctypes\n",
    "import_importlib": "import importlib\n",
    "import_code": "import code\n",
    "import_codeop": "import codeop\n",
    "import_sys": "import sys\n",
}

UNSAFE_CALL_SNIPPETS = {
    "shell_os_system": UNSAFE_SHELL_OS_SYSTEM,
    "shell_subprocess_run": UNSAFE_SHELL_SUBPROCESS_RUN,
    "dynamic_import_dunder": UNSAFE_DYNAMIC_IMPORT_DUNDER,
    "dynamic_import_dunder_concatenated": "__import__('o' + 's')\n",
    "dynamic_import_importlib": UNSAFE_DYNAMIC_IMPORT_IMPORTLIB,
    "exec": UNSAFE_EXEC,
    "eval": UNSAFE_EVAL,
    "compile": "compile('x = 1', '<string>', 'exec')\n",
    "globals": "globals()\n",
    "locals": "locals()\n",
    "getattr": UNSAFE_GETATTR,
    "attribute_eval": "__builtins__.eval('1 + 1')\n",
    "setattr": "setattr(obj, 'name', value)\n",
    "delattr": "delattr(obj, 'name')\n",
}

UNSAFE_OPEN_SNIPPETS = {
    "absolute_open": UNSAFE_ABSOLUTE_OPEN,
    "relative_path_with_separator": "open('data/input.csv')\n",
    "traversal_open": UNSAFE_TRAVERSAL_OPEN,
    "home": "open('~/secret.txt')\n",
    "windows_absolute": "open('C:\\\\Users\\\\me\\\\secret.txt')\n",
    "attribute_open_absolute": "__builtins__.open('/etc/passwd')\n",
}

SAFE_SNIPPETS = {
    "pandas_io": SAFE_PANDAS_IO,
    "relative_open": SAFE_RELATIVE_OPEN,
}
