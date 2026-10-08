#!/usr/bin/env python3
"""Centralized build configuration loading and validation."""
from __future__ import annotations

import functools
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml

from policy import PROFILE_NAME
