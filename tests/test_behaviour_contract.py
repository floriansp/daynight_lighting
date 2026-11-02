"""The behaviour contract must stay anchored to real code and real tests.

``docs/BEHAVIOUR.md`` is how we answer "does the software still behave the way
we intended?" before a release.  That answer is only worth one if every clause
still points at code that exists and a test that exists, so the check runs as
part of the normal suite.

The document and its checker are internal, so this module skips in the public
mirror, where neither file is published.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "scripts" / "check_behaviour.py"
DOC = ROOT / "docs" / "BEHAVIOUR.md"

pytestmark = pytest.mark.skipif(
    not (CHECKER.is_file() and DOC.is_file()),
    reason="behaviour contract is internal and not published",
)


def _load_checker():
    """Import ``scripts/check_behaviour.py`` without making it a package."""
    spec = importlib.util.spec_from_file_location("check_behaviour", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules, so the module has
    # to be registered before it is executed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_behaviour_contract_is_anchored():
    """Every clause has a live code anchor and a live test anchor."""
    problems = _load_checker().check()

    assert problems == [], "docs/BEHAVIOUR.md drifted:\n" + "\n".join(problems)


def test_option_table_is_complete():
    """Every configuration option is documented, and nothing else is."""
    checker = _load_checker()
    documented = {
        option.key for option in checker.parse_options(DOC.read_text(encoding="utf-8"))
    }

    assert documented == checker.declared_options()
