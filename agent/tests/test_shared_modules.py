"""Tests for agent modules that the arena reuses after the PoC archive."""

import os
import subprocess
import sys

import pytest

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_reused_modules_do_not_import_poc_code():
    code = (
        "import sys, runtime.models, runtime.a2a_card;"
        "bad = [m for m in ('runtime.tools', 'runtime.delegation', 'node')"
        " if m in sys.modules];"
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], cwd=AGENT_DIR, check=True)


def test_build_model_rejects_unknown_provider():
    from runtime.models import build_model

    with pytest.raises(ValueError, match="Unsupported MODEL_PROVIDER"):
        build_model({"provider": "other"})


def test_build_model_bedrock_requires_model_id():
    from runtime.models import build_model

    with pytest.raises(ValueError, match="MODEL_ID is required"):
        build_model({"provider": "bedrock"})

