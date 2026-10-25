import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from psydroid.storage import write_json


class AtomicStorageTests(unittest.TestCase):
    def test_interrupted_replace_preserves_previous_document(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'settings.json'
            write_json(file, {'name': 'old'})
            with patch('psydroid.storage.os.replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    write_json(file, {'name': 'new'})
            self.assertEqual(json.loads(file.read_text()), {'name': 'old'})
            self.assertEqual(list(Path(directory).iterdir()), [file])

    def test_unicode_and_invalid_value_leave_valid_document(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'settings.json'
            write_json(file, {'name': 'Android • café'})
            with self.assertRaises(TypeError):
                write_json(file, {'bad': object()})
            self.assertEqual(json.loads(file.read_text(encoding='utf-8')), {'name': 'Android • café'})


if __name__ == '__main__':
    unittest.main()
