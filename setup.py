from setuptools import setup

APP = ['macvms.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': True,
    'packages': ['macvms_pkg'],
    'includes': ['rumps', 'psutil'],
    'plist': {
        'LSUIElement': True,
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)