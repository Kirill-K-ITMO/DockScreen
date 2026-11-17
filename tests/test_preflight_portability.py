"""Readiness plumbing checks; no chemistry packages or Vina are required."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.core.preflight import _probe_directory, check_dependencies, check_run


class PreflightPortabilityTests(unittest.TestCase):
    def test_writable_directory_with_spaces_and_cyrillic(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            target = Path(directory) / 'проект с пробелами' / 'output'
            _probe_directory(target)
            self.assertTrue(target.is_dir())
            self.assertEqual(list(target.iterdir()), [])

    def test_dependency_import_failure_is_reported(self):
        def load(name):
            if name == 'meeko':
                raise ImportError('test missing module')

        with patch('src.core.preflight.importlib.import_module', side_effect=load):
            report = check_dependencies()
        self.assertFalse(report.ready)
        self.assertEqual(len(report.errors), 1)
        self.assertIn('meeko: test missing module', report.errors[0])

    def test_invalid_arguments_do_not_continue_to_docker_or_filesystem(self):
        # Isolate argument-validation plumbing from the cache/chemistry imports.
        # CPU validation's actual rules are covered separately in test_cpu_budget.
        invalid = SimpleNamespace(positive=Mock(side_effect=ValueError('invalid workers')))
        docker = Mock()
        with patch.dict('sys.modules', {'src.core.cpu_budget': invalid}):
            with patch('src.core.preflight._probe_directory') as probe:
                report = check_run('.', num_workers='invalid', docker=docker,
                                   rows=[], dependencies=False)
        self.assertFalse(report.ready)
        self.assertEqual(report.errors, ['invalid workers'])
        probe.assert_not_called()
        self.assertEqual(docker.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
