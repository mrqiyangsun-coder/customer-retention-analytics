"""Download/cache the official source workbook and record its provenance."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from urllib.request import Request, urlopen
import zipfile


ROOT = Path(__file__).resolve().parent
DATASET_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"
ARCHIVE_URL = "https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip"


def main():
    raw = ROOT / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    target = raw / "online_retail_II.xlsx"
    metadata_path = target.with_suffix(".source.json")
    if target.exists():
        if not metadata_path.exists():
            raise RuntimeError("Existing workbook has no provenance. Keep it and audit with --input, or choose another source directory.")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if hashlib.sha256(target.read_bytes()).hexdigest() != metadata["sha256"]:
            raise RuntimeError("Existing workbook differs from its source checksum; refusing to overwrite it.")
        print(f"Using verified cached workbook: {target}")
        return

    archive = raw / "source.zip"
    if not archive.exists():
        print("Downloading official UCI source archive...", flush=True)
        partial = raw / "source.zip.part"
        # A failed transfer is never treated as a valid cache entry.
        with urlopen(Request(ARCHIVE_URL, headers={"User-Agent": "retention-analytics-project/1.0"}), timeout=120) as response:
            with partial.open("wb") as output:
                shutil.copyfileobj(response, output)
        partial.replace(archive)
    with zipfile.ZipFile(archive) as bundle:
        members = [item for item in bundle.infolist() if Path(item.filename).name.lower() == target.name.lower()]
        if len(members) != 1:
            raise RuntimeError("Official archive did not contain exactly one expected workbook.")
        with bundle.open(members[0]) as source, target.open("xb") as output:
            shutil.copyfileobj(source, output)
    metadata = {
        "dataset": "Online Retail II", "dataset_url": DATASET_URL, "archive_url": ARCHIVE_URL,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "size_bytes": target.stat().st_size,
        "license": "CC BY 4.0", "citation": "Chen, D. (2012). Online Retail II. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {target}; {metadata['size_bytes']:,} bytes; SHA-256 {metadata['sha256']}")


if __name__ == "__main__":
    main()
