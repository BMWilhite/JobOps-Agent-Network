"""Startup contracts, including a cached screener from before the exception existed."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import qualification_agent
import screening_errors


class ScreeningImportTests(unittest.TestCase):
    def test_all_layers_share_the_same_exception_and_legacy_import_works(self):
        import jobops_service
        import streamlit_app

        for module in (qualification_agent, jobops_service, streamlit_app):
            self.assertIs(module.BatchScreeningError, screening_errors.BatchScreeningError)
        self.assertTrue(issubclass(screening_errors.BatchScreeningError, ValueError))

    def test_service_and_ui_import_with_cached_screener_missing_exception(self):
        cached = types.ModuleType('qualification_agent')
        for name in ('cache_key', 'dry_screen', 'screen_batch'):
            setattr(cached, name, getattr(qualification_agent, name))
        # Execute fresh service/UI modules, without calling main() or touching storage.
        with patch.dict(sys.modules, {'qualification_agent': cached}):
            for name in ('jobops_service', 'streamlit_app'):
                spec = importlib.util.find_spec(name)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertIs(module.BatchScreeningError, screening_errors.BatchScreeningError)
