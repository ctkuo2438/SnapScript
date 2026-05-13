UNSAFE_IMPORT_SNIPPETS = {
    "import_os": "import os\n",
    "import_os_path": "import os.path\n",
    "from_os_path": "from os.path import join\n",
    "import_subprocess": "import subprocess\n",
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
    "exec": "exec(user_code)\n",
    "eval": "eval('1 + 1')\n",
    "compile": "compile('x = 1', '<string>', 'exec')\n",
    "import": "__import__('os')\n",
    "dynamic_import": "__import__('o' + 's')\n",
    "globals": "globals()\n",
    "locals": "locals()\n",
    "getattr": "getattr(__builtins__, 'exec')\n",
    "attribute_eval": "__builtins__.eval('1 + 1')\n",
    "setattr": "setattr(obj, 'name', value)\n",
    "delattr": "delattr(obj, 'name')\n",
}


UNSAFE_OPEN_SNIPPETS = {
    "absolute_unix": "open('/etc/passwd')\n",
    "nested_relative": "open('data/input.csv')\n",
    "traversal": "open('../../secret.txt')\n",
    "home": "open('~/secret.txt')\n",
    "windows_absolute": "open('C:\\\\Users\\\\me\\\\secret.txt')\n",
    "attribute_open_absolute": "__builtins__.open('/etc/passwd')\n",
}
