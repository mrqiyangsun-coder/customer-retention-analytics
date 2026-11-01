"""Reproduce the complete local project with the current Python environment."""
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def main():
    for script in ['download_data.py', 'audit.py', 'clean.py', 'analysis.py', 'prediction.py', 'release_evaluation.py']:
        print(f'Running {script}', flush=True)
        subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, check=True)
    print('All pipeline stages completed. Start the dashboard using launch_dashboard.ps1.')


if __name__ == '__main__':
    main()
