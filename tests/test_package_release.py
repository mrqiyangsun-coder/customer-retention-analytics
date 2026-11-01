from pathlib import Path
import hashlib
import json
import shutil
import unittest
import uuid
import zipfile

from package_release import build_release


class PackageReleaseTests(unittest.TestCase):
    def test_archive_is_standalone_excludes_local_material_and_checksums_match(self):
        target = Path(__file__).resolve().parents[1] / 'data/test_artifacts' / uuid.uuid4().hex
        target.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, target)
        archive = build_release(target)
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            self.assertIn('customer-retention-analytics/README.md', names)
            self.assertIn('customer-retention-analytics/LICENSE', names)
            self.assertIn('customer-retention-analytics/tests/test_prediction.py', names)
            self.assertFalse(any('/data/' in name or '/.venv/' in name or name.endswith('progress.md') for name in names))
            readme = bundle.read('customer-retention-analytics/README.md').decode()
            self.assertNotIn('10982', readme)
            self.assertNotIn('projects/customer_retention', readme)
            manifest = json.loads(bundle.read('customer-retention-analytics/RELEASE_MANIFEST.json'))
            self.assertEqual(manifest['version'], '1.0.0')
            for relative, checksum in manifest['files'].items():
                self.assertEqual(hashlib.sha256(bundle.read('customer-retention-analytics/' + relative)).hexdigest(), checksum)


if __name__ == '__main__':
    unittest.main()
