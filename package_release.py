"""Create a standalone publication ZIP from an explicit project allowlist."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parent
CODE = ['download_data.py', 'audit.py', 'clean.py', 'analysis.py', 'charts.py', 'prediction.py',
        'release_evaluation.py', 'dashboard_data.py', 'streamlit_app.py', 'run_pipeline.py',
        'package_release.py', 'launch_dashboard.ps1', 'requirements.txt', 'requirements-lock.txt', '.gitignore', '.gitattributes',
        '.streamlit/config.toml', '.github/workflows/ci.yml', 'VERSION', 'LICENSE', 'NOTICE',
        'docs/cleaning_rules.md', 'docs/data_dictionary.md', 'docs/release_readme.md',
        'docs/release_notes.md']


def build_release(output_dir):
    files = {relative: ROOT / relative for relative in CODE}
    files['README.md'] = ROOT / 'docs/release_readme.md'
    for pattern in ['tests/test_*.py', 'sql/*.sql', 'reports/*.json', 'reports/*.csv',
                    'reports/*.md', 'reports/figures/*.png']:
        files.update({path.relative_to(ROOT).as_posix(): path for path in ROOT.glob(pattern)})
    contents = {}
    for name, path in sorted(files.items()):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Release file missing or linked: {name}')
        data = path.read_bytes()
        if path.suffix != '.png':
            text = data.decode('utf-8')
            if re.search(r'sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----', text):
                raise ValueError(f'Credential-like content in publication file: {name}')
            if re.search(r'[A-Za-z]:[\\/]Users[\\/]', text):
                raise ValueError(f'Personal absolute path in publication file: {name}')
        contents[name] = data
    version = (ROOT / 'VERSION').read_text().strip()
    manifest = {'version': version, 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    contents['RELEASE_MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f'customer-retention-analytics-v{version}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in contents.items():
            bundle.writestr('customer-retention-analytics/' + name, data)
    return archive


if __name__ == '__main__':
    print(build_release(ROOT / 'dist'))
