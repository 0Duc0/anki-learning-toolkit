"""Build the Learning Toolkit and each part as its own add-on.

    python tools/package.py              → dist/learning_toolkit-<version>.ankiaddon
    python tools/package.py --all        → the toolkit and every single add-on
    python tools/package.py deck_progress

A single add-on is the same code with only one part. It uses the old add-on's folder name and
flat settings file, so it installs over (and keeps the settings of) the earlier stand-alone version.
Versions live in tools/versions.json.
"""
import json
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "learning_toolkit"
VERSIONS = json.loads((ROOT / "tools" / "versions.json").read_text())
SKIP_DIRS = {"__pycache__", "user_files", ".ruff_cache"}
SKIP_FILES = {"meta.json", "_build.py"}
MODULE_KEYS = list(VERSIONS["modules"])


def _files(only: str = ""):
    for path in sorted(PKG.rglob("*")):
        rel = path.relative_to(PKG)
        if path.is_dir() or SKIP_DIRS & set(rel.parts) or path.name in SKIP_FILES or path.suffix == ".pyc":
            continue
        if only and rel.parts[0] in MODULE_KEYS and rel.parts[0] != only:
            continue                                   # other parts are not in a single add-on
        if only and rel.as_posix() in {"manifest.json", "config.json", "config.md"}:
            continue                                   # written below
        yield path, rel.as_posix()


def build_toolkit() -> pathlib.Path:
    version = VERSIONS["toolkit"]
    manifest = json.loads((PKG / "manifest.json").read_text())
    manifest["human_version"] = version
    out = ROOT / "dist" / f"learning_toolkit-{version}.ankiaddon"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path, name in _files():
            if name == "manifest.json":
                continue
            z.write(path, name)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("_build.py", 'ONLY = ""\n')
    return out


def build_single(key: str) -> pathlib.Path:
    info = VERSIONS["modules"][key]
    config = json.loads((PKG / "config.json").read_text()).get(key, {})
    legacy = ROOT / "docs" / "legacy" / key
    manifest = {"package": info["package"], "name": info["name"], "human_version": info["version"],
                "min_point_version": 250200, "homepage": "https://github.com/0Duc0/anki-learning-toolkit"}
    out = ROOT / "dist" / f"{info['package']}-{info['version']}.ankiaddon"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path, name in _files(only=key):
            z.write(path, name)
        z.writestr("_build.py", f'ONLY = "{key}"\n')
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("config.json", json.dumps(config, indent=2, ensure_ascii=False))
        for doc in ("config.md", "README.md"):
            if (legacy / doc).exists():
                z.write(legacy / doc, doc)
    return out


def main(argv=None) -> list[pathlib.Path]:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        built = [build_toolkit()]
    elif args == ["--all"]:
        built = [build_toolkit()] + [build_single(k) for k in MODULE_KEYS]
    else:
        built = [build_single(k) for k in args]
    for path in built:
        print(path.relative_to(ROOT))
    return built


if __name__ == "__main__":
    main()
