from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.request import Request, urlopen

import stableamd_server as base

VECTOR_DEPENDENCY_ID = "text-to-svg-v1"
VTRACER_VERSION = "1.0.0-alpha.4"
VTRACER_URL = (
    "https://github.com/visioncortex/vtracer/releases/download/1.0.0-alpha.4/"
    "vtracer-x86_64-pc-windows-msvc.zip"
)
VTRACER_BYTES = 965_231
VTRACER_SHA256 = "8eadb5529864265f003f791ad9cb128e1b9b8b8af8c21016f38b04706bcf3531"
RESVG_PY_VERSION = "0.5.0"
DOWNLOAD_CHUNK_BYTES = 1024 * 1024

VTRACER_PROFILES = {
    "simple": [
        "--preset", "poster",
        "--mode", "spline",
        "--filter-speckle", "8",
        "--simplify", "2.5",
        "--path-precision", "2",
        "--optimize", "2",
    ],
    "medium": [
        "--preset", "poster",
        "--mode", "spline",
        "--filter-speckle", "4",
        "--simplify", "1.5",
        "--path-precision", "2",
        "--optimize", "2",
    ],
    "detailed": [
        "--preset", "poster",
        "--mode", "spline",
        "--filter-speckle", "2",
        "--simplify", "0.75",
        "--path-precision", "3",
        "--optimize", "1",
    ],
}


def _tools_root(repo_root: Path) -> Path:
    return (
        Path(repo_root).resolve()
        / ".runtime"
        / "stableamd"
        / "tools"
        / "vtracer"
    ).resolve()


def _version_root(repo_root: Path) -> Path:
    return (_tools_root(repo_root) / VTRACER_VERSION).resolve()


def vtracer_executable(repo_root: Path) -> Path:
    return (_version_root(repo_root) / "vtracer.exe").resolve()


def vtracer_manifest(repo_root: Path) -> Path:
    return (_version_root(repo_root) / "stableamd-install.json").resolve()


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _vtracer_status(repo_root: Path) -> str:
    executable = vtracer_executable(repo_root)
    manifest_path = vtracer_manifest(repo_root)
    if not executable.exists() and not manifest_path.exists():
        return "missing"
    if not executable.is_file() or not manifest_path.is_file():
        return "invalid"
    manifest = _read_manifest(manifest_path)
    if not manifest:
        return "invalid"
    if (
        manifest.get("version") != VTRACER_VERSION
        or manifest.get("archiveBytes") != VTRACER_BYTES
        or str(manifest.get("archiveSha256") or "").lower() != VTRACER_SHA256.lower()
    ):
        return "invalid"
    return "ready"


def _preview_status() -> tuple[str, str | None]:
    try:
        installed = metadata.version("resvg_py")
    except metadata.PackageNotFoundError:
        return "missing", None
    except Exception:
        return "invalid", None
    if installed != RESVG_PY_VERSION:
        return "invalid", str(installed)
    return "ready", str(installed)


def vector_dependency_status(repo_root: Path) -> dict[str, Any]:
    vtracer_status = _vtracer_status(repo_root)
    preview_status, installed_preview = _preview_status()
    if vtracer_status == "ready" and preview_status == "ready":
        status = "ready"
    elif "invalid" in {vtracer_status, preview_status}:
        status = "invalid"
    else:
        status = "missing"
    return {
        "id": VECTOR_DEPENDENCY_ID,
        "ready": status == "ready",
        "status": status,
        "restartRequired": False,
        "vtracer": {
            "status": vtracer_status,
            "version": VTRACER_VERSION,
            "path": str(vtracer_executable(repo_root)),
            "archiveBytes": VTRACER_BYTES,
            "archiveSha256": VTRACER_SHA256,
        },
        "previewRenderer": {
            "status": preview_status,
            "package": "resvg_py",
            "version": RESVG_PY_VERSION,
            "installedVersion": installed_preview,
        },
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    for member in members:
        normalized = str(member.filename).replace("\\", "/")
        pure = PurePosixPath(normalized)
        if not normalized or pure.is_absolute() or ".." in pure.parts:
            raise base.StableAmdBridgeError("VTracer archive contains an unsafe path and was not installed.")
        if len(pure.parts) > 0 and ":" in pure.parts[0]:
            raise base.StableAmdBridgeError("VTracer archive contains an unsafe drive path and was not installed.")
    return members


def _install_vtracer(repo_root: Path, *, urlopen_fn=urlopen) -> bool:
    current = _vtracer_status(repo_root)
    if current == "ready":
        return False
    if current == "invalid":
        raise base.StableAmdBridgeError(
            f"VTracer installation at '{_version_root(repo_root)}' is invalid. Move it aside before managed installation."
        )

    tools_root = _tools_root(repo_root)
    tools_root.mkdir(parents=True, exist_ok=True)
    version_root = _version_root(repo_root)
    if version_root.exists():
        try:
            has_entries = any(version_root.iterdir()) if version_root.is_dir() else True
        except OSError:
            has_entries = True
        if has_entries:
            raise base.StableAmdBridgeError(
                f"VTracer target '{version_root}' already exists but is not a verified managed installation."
            )
        version_root.rmdir()

    token = uuid.uuid4().hex
    archive_path = tools_root / f".vtracer-{token}.partial.zip"
    temporary_root = tools_root / f".vtracer-{token}.tmp-install"
    digest = hashlib.sha256()
    total = 0
    request = Request(
        VTRACER_URL,
        headers={"User-Agent": "StableAMD/0.3 vector-installer"},
        method="GET",
    )
    try:
        with urlopen_fn(request, timeout=60) as response, archive_path.open("wb") as output:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > VTRACER_BYTES:
                    raise base.StableAmdBridgeError("VTracer download exceeded its pinned expected size.")
                digest.update(chunk)
                output.write(chunk)
        if total != VTRACER_BYTES:
            raise base.StableAmdBridgeError(
                f"VTracer size mismatch: expected {VTRACER_BYTES} bytes, received {total}."
            )
        if digest.hexdigest().lower() != VTRACER_SHA256.lower():
            raise base.StableAmdBridgeError("VTracer checksum mismatch. The downloaded archive was not installed.")

        temporary_root.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = _safe_zip_members(archive)
            archive.extractall(temporary_root, members=members)

        executables = [path for path in temporary_root.rglob("vtracer.exe") if path.is_file()]
        if len(executables) != 1:
            raise base.StableAmdBridgeError(
                f"VTracer archive must contain exactly one vtracer.exe; found {len(executables)}."
            )

        staged_version = tools_root / f".vtracer-{token}.tmp-version"
        staged_version.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copy2(executables[0], staged_version / "vtracer.exe")
            manifest = {
                "schemaVersion": 1,
                "dependencyId": VECTOR_DEPENDENCY_ID,
                "version": VTRACER_VERSION,
                "archiveUrl": VTRACER_URL,
                "archiveBytes": VTRACER_BYTES,
                "archiveSha256": VTRACER_SHA256,
            }
            (staged_version / "stableamd-install.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            staged_version.replace(version_root)
        except Exception:
            shutil.rmtree(staged_version, ignore_errors=True)
            raise
        return True
    except zipfile.BadZipFile as exc:
        raise base.StableAmdBridgeError("VTracer download is not a valid ZIP archive.") from exc
    finally:
        archive_path.unlink(missing_ok=True)
        shutil.rmtree(temporary_root, ignore_errors=True)


def _install_preview_renderer(*, run_fn=subprocess.run) -> bool:
    preview_status, _ = _preview_status()
    if preview_status == "ready":
        return False

    try:
        completed = run_fn(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--only-binary=:all:",
                "--no-deps",
                f"resvg_py=={RESVG_PY_VERSION}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise base.StableAmdBridgeError(f"Could not install SVG preview renderer: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "pip install failed").strip()
        raise base.StableAmdBridgeError(f"Could not install SVG preview renderer: {detail[-4000:]}")

    installed_status, installed_version = _preview_status()
    if installed_status != "ready":
        raise base.StableAmdBridgeError(
            "SVG preview renderer installation completed but the required "
            f"resvg_py=={RESVG_PY_VERSION} is not active (found {installed_version or 'none'})."
        )
    return True


def install_vector_dependencies(
    repo_root: Path,
    *,
    urlopen_fn=urlopen,
    run_fn=subprocess.run,
) -> dict[str, Any]:
    before = vector_dependency_status(repo_root)
    vtracer_changed = _install_vtracer(repo_root, urlopen_fn=urlopen_fn)
    preview_changed = False
    if before["previewRenderer"]["status"] != "ready":
        preview_changed = _install_preview_renderer(run_fn=run_fn)
    result = vector_dependency_status(repo_root)
    if not result["ready"]:
        raise base.StableAmdBridgeError(
            "Vector dependencies were installed but StableAMD could not verify the complete Text-to-SVG toolchain."
        )
    return {
        **result,
        "installed": True,
        "vtracerChanged": vtracer_changed,
        "previewRendererChanged": preview_changed,
        "restartRequired": False,
    }


def build_vtracer_args(
    input_path: Path,
    output_path: Path,
    detail: str,
    max_colors: int | None,
) -> list[str]:
    normalized_detail = str(detail or "").strip().lower()
    profile = VTRACER_PROFILES.get(normalized_detail)
    if profile is None:
        raise base.StableAmdBridgeError("Vector detail must be simple, medium, or detailed.")
    if max_colors is not None and max_colors not in {2, 4, 8, 16}:
        raise base.StableAmdBridgeError("Vector colors must be auto, 2, 4, 8, or 16.")

    args = [
        "--input", str(Path(input_path)),
        "--output", str(Path(output_path)),
        *profile,
    ]
    if max_colors is not None:
        args.extend(["--max-colors", str(max_colors)])
    return args


def run_vtracer(
    repo_root: Path,
    input_path: Path,
    output_path: Path,
    *,
    detail: str,
    max_colors: int | None,
    run_fn=subprocess.run,
) -> Path:
    executable = vtracer_executable(repo_root)
    if _vtracer_status(repo_root) != "ready":
        raise base.StableAmdBridgeError("VTracer is not installed or its managed installation is invalid.")

    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    command = [str(executable), *build_vtracer_args(Path(input_path), output, detail, max_colors)]
    try:
        completed = run_fn(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise base.StableAmdBridgeError("VTracer timed out after 120 seconds.") from exc
    except OSError as exc:
        raise base.StableAmdBridgeError(f"VTracer could not be started: {exc}") from exc
    if completed.returncode != 0:
        detail_text = (completed.stderr or completed.stdout or "VTracer failed").strip()
        raise base.StableAmdBridgeError(f"VTracer failed: {detail_text[-4000:]}")
    if not output.is_file() or output.stat().st_size <= 0:
        raise base.StableAmdBridgeError("VTracer completed without creating an SVG output file.")
    return output
