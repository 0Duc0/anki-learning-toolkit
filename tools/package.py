"""Build dist/learning_toolkit-<version>.ankiaddon (a zip of the package contents)."""
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "learning_toolkit"
SKIP_DIRS = {"__pycache__", "user_files"}
SKIP_FILES = {"meta.json"}


def main() -> pathlib.Path:
    version = json.loads((PKG / "manifest.json").read_text())["human_version"]
    out = ROOT / "dist" / f"learning_toolkit-{version}.ankiaddon"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(PKG.rglob("*")):
            rel = path.relative_to(PKG)
            if path.is_dir() or SKIP_DIRS & set(rel.parts) or path.name in SKIP_FILES or path.suffix == ".pyc":
                continue
            z.write(path, rel.as_posix())
    print(out)
    return out


if __name__ == "__main__":
    main()
