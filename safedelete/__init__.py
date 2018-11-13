# flake8: noqa
import logging

from .config import (DEFAULT_DELETED, DELETED_INVISIBLE, DELETED_VISIBLE_BY_PK, DELETED_VISIBLE_BY_FIELD,
                     HARD_DELETE, HARD_DELETE_NOCASCADE, SOFT_DELETE, SOFT_DELETE_CASCADE,
                     NO_DELETE)

__all__ = [
    'DEFAULT_DELETED',
    'HARD_DELETE',
    'SOFT_DELETE',
    'SOFT_DELETE_CASCADE',
    'HARD_DELETE_NOCASCADE',
    'NO_DELETE',
    'DELETED_INVISIBLE',
    'DELETED_VISIBLE_BY_PK',
    'DELETED_VISIBLE_BY_FIELD',
]

__version__ = "0.5.2dev"
default_app_config = 'safedelete.apps.SafeDeleteConfig'

# Gets the root logger so that all the sub loggers inherit from the level of this one
logger = logging.getLogger()
