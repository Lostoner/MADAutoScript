"""Small regression checks for the export boundary; no emulator or user config."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_release import assert_no_private_paths, public_catalog


class ReleasePrivacyTests(unittest.TestCase):
    def test_catalog_exports_game_definitions_only(self):
        definitions = {'game_version': 'test', 'sweep': {}, 'normal_zones': {}, 'characters': []}
        local = dict(definitions, source='capture', zone_evidence='local', roster_evidence='local')
        self.assertEqual(public_catalog(local), definitions)
        self.assertIn('zone_evidence', local)

    def test_private_paths_detected_in_serialized_and_binary_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root/'private project'/str(chr(0x6d4b))
            published = root/'release'
            published.mkdir()
            probe = published/'probe.dat'
            path = str(private/'evidence.json')
            variants = (path, path.replace('\\', '/'), (private/'evidence.json').as_uri(),
                        json.dumps({'evidence': path}, ensure_ascii=False),
                        json.dumps({'evidence': path}, ensure_ascii=True))
            for value in variants:
                for encoding in ('utf-8', 'utf-16le'):
                    with self.subTest(value=value, encoding=encoding):
                        probe.write_bytes(value.encode(encoding))
                        with self.assertRaisesRegex(RuntimeError, 'probe.dat'):
                            assert_no_private_paths(published, [private])
            # A marker straddling the streaming boundary is still detected.
            probe.write_bytes(b'x' * (1024 * 1024 - 5) + path.encode('utf-8'))
            with self.assertRaises(RuntimeError):
                assert_no_private_paths(published, [private])
            probe.write_text('src/game_catalog.json\nhttps://github.com/\n', encoding='utf-8')
            assert_no_private_paths(published, [private])


if __name__ == '__main__':
    unittest.main()
