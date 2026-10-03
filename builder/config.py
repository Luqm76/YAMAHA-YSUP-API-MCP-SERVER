import os
from pathlib import Path


def data_dir():
    return Path(os.environ.get('YAMAHA_BUILDER_DATA',str(Path(__file__).resolve().parent.parent/'data')))


def association_db(folder=None):
    return Path(os.environ.get('YAMAHA_ASSOCIATIONS_DB',str(Path(folder or data_dir())/'confirmed_associations.sqlite3')))


def optimizer_paths(folder=None):
    return (os.environ.get('YAMAHA_YSUP_ROOT'),
            Path(os.environ.get('YAMAHA_OPTIMIZER_WORK',str(Path(folder or data_dir())/'optimization'))))
