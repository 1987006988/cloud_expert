"""Private per-stage CLI state; native trace validation remains the caller's duty.

No process/model is started here. The sole inherited file is an opaque auth.json
copy. This isolates configuration, not a hostile process running as the same user.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

BUILTIN_SKILLS = ("imagegen", "openai-docs", "plugin-creator", "skill-creator", "skill-installer")
DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "hooks",
    "multi_agent",
    "memories",
    "browser_use",
    "computer_use",
    "in_app_browser",
    "code_mode",
    "code_mode_host",
    "image_generation",
    "view_image",
    "skill_search",
    "workspace_dependencies",
    "goals",
    "sleep_tool",
    "tool_suggest",
)
CORE_ENVIRONMENT = frozenset({"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"})
_PREFIX = "cloud-expert-review-"
_WINDOWS = os.name == "nt"


class RuntimeIsolationError(RuntimeError):
    """Fixed diagnostic codes only, never credential contents or source paths."""


def _require(condition: object, code: str) -> None:
    if not condition:
        raise RuntimeIsolationError(code)


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _checked_path(path: Path) -> os.stat_result:
    _require(path.is_absolute() and ".." not in path.parts, "absolute_unambiguous_path_required")
    _require(not (_WINDOWS and path.drive.startswith("\\")), "local_path_required")
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        _require(
            not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400),
            "linked_or_reparse_path_rejected",
        )
        _require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "special_path_rejected")
        if stat.S_ISREG(info.st_mode):
            _require(item == path and info.st_nlink == 1, "hardlinked_path_rejected")
    return info


def _windows_permissions(path: Path, *, apply: bool) -> None:
    """Set/read a protected DACL containing only the token user and LocalSystem."""
    from ctypes import wintypes as w

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    signatures: tuple[tuple[Any, str, list[Any], Any], ...] = (
        (kernel, "GetCurrentProcess", [], w.HANDLE),
        (kernel, "CloseHandle", [w.HANDLE], w.BOOL),
        (kernel, "LocalFree", [pointer], pointer),
        (adv, "OpenProcessToken", [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL),
        (
            adv,
            "GetTokenInformation",
            [w.HANDLE, w.DWORD, pointer, w.DWORD, ctypes.POINTER(w.DWORD)],
            w.BOOL,
        ),
        (adv, "ConvertSidToStringSidW", [pointer, ctypes.POINTER(pointer)], w.BOOL),
        (
            adv,
            "ConvertStringSecurityDescriptorToSecurityDescriptorW",
            [w.LPCWSTR, w.DWORD, ctypes.POINTER(pointer), ctypes.POINTER(w.DWORD)],
            w.BOOL,
        ),
        (adv, "SetFileSecurityW", [w.LPCWSTR, w.DWORD, pointer], w.BOOL),
        (
            adv,
            "GetFileSecurityW",
            [w.LPCWSTR, w.DWORD, pointer, w.DWORD, ctypes.POINTER(w.DWORD)],
            w.BOOL,
        ),
        (
            adv,
            "GetSecurityDescriptorDacl",
            [pointer, ctypes.POINTER(w.BOOL), ctypes.POINTER(pointer), ctypes.POINTER(w.BOOL)],
            w.BOOL,
        ),
        (
            adv,
            "GetSecurityDescriptorOwner",
            [pointer, ctypes.POINTER(pointer), ctypes.POINTER(w.BOOL)],
            w.BOOL,
        ),
        (
            adv,
            "GetSecurityDescriptorControl",
            [pointer, ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD)],
            w.BOOL,
        ),
        (adv, "GetAce", [pointer, w.DWORD, ctypes.POINTER(pointer)], w.BOOL),
    )
    for library, name, args, restype in signatures:
        function = getattr(library, name)
        function.argtypes, function.restype = args, restype

    def check(ok: object) -> None:
        _require(ok, "private_acl_operation_failed")

    def sid_text(sid: Any) -> str:
        converted = pointer()
        check(adv.ConvertSidToStringSidW(sid, ctypes.byref(converted)))
        try:
            return ctypes.wstring_at(converted)
        finally:
            kernel.LocalFree(converted)

    token = w.HANDLE()
    check(adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
    try:
        size = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        check(0 < size.value < 1024 * 1024)
        buffer = ctypes.create_string_buffer(size.value)
        check(adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)))
        user_sid = sid_text(ctypes.cast(buffer, ctypes.POINTER(pointer))[0])
    finally:
        kernel.CloseHandle(token)
    principals = {user_sid, "S-1-5-18"}
    directory = path.is_dir()
    flags = "OICI" if directory else ""

    def read_descriptor() -> Any:
        size = w.DWORD()
        adv.GetFileSecurityW(str(path), 1 | 4, None, 0, ctypes.byref(size))
        check(0 < size.value < 1024 * 1024)
        buffer = ctypes.create_string_buffer(size.value)
        check(adv.GetFileSecurityW(str(path), 1 | 4, buffer, size, ctypes.byref(size)))
        return buffer

    descriptor = read_descriptor()
    owner, defaulted = pointer(), w.BOOL()
    check(adv.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted)))
    check(owner.value and sid_text(owner) == user_sid)
    if apply:
        sddl = f"O:{user_sid}D:P" + "".join(f"(A;{flags};FA;;;{sid})" for sid in sorted(principals))
        allocated_descriptor = pointer()
        check(
            adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(allocated_descriptor), None
            )
        )
        try:
            # Ownership is already checked. Changing it would require WRITE_OWNER,
            # which an owner need not have even though they can protect the DACL.
            check(adv.SetFileSecurityW(str(path), 4 | 0x80000000, allocated_descriptor))
        finally:
            kernel.LocalFree(allocated_descriptor)
    descriptor = read_descriptor()
    control, revision = w.WORD(), w.DWORD()
    check(
        adv.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision))
    )
    check(control.value & 0x1000)
    owner, defaulted = pointer(), w.BOOL()
    check(adv.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted)))
    check(owner.value and sid_text(owner) == user_sid)
    acl, present = pointer(), w.BOOL()
    check(
        adv.GetSecurityDescriptorDacl(
            descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)
        )
    )
    check(present.value and acl.value)
    assert acl.value is not None
    # ACL.AceCount is a WORD at offset 4; ACCESS_ALLOWED_ACE has SID at offset 8.
    count = ctypes.c_ushort.from_address(acl.value + 4).value
    check(count == len(principals))
    observed = set()
    for index in range(count):
        ace = pointer()
        check(adv.GetAce(acl, index, ctypes.byref(ace)))
        assert ace.value is not None
        check(ctypes.c_ubyte.from_address(ace.value).value == 0)
        check(ctypes.c_ubyte.from_address(ace.value + 1).value == (3 if directory else 0))
        check(ctypes.c_uint32.from_address(ace.value + 4).value == 0x1F01FF)
        observed.add(sid_text(pointer(ace.value + 8)))
    check(observed == principals)


def _private_permissions(path: Path, *, apply: bool) -> None:
    if _WINDOWS:
        _windows_permissions(path, apply=apply)
    else:
        mode = 0o700 if path.is_dir() else 0o600
        if apply:
            path.chmod(mode)
        info = path.lstat()
        getuid = getattr(os, "getuid", None)
        _require(callable(getuid), "posix_owner_api_unavailable")
        assert getuid is not None
        accepted_modes = {mode} if apply or path.is_dir() else {0o400, 0o600}
        _require(
            info.st_uid == getuid() and stat.S_IMODE(info.st_mode) in accepted_modes,
            "private_mode_verification_failed",
        )


def protect_local_artifact(path: Path) -> None:
    """Protect an existing regular file or empty directory; never read its contents.

    Protect an empty audit directory before creating sensitive originals in it,
    then protect each original file too. This does not make an artifact public.
    """
    try:
        before = _checked_path(path)
        _require(not path.is_dir() or not any(path.iterdir()), "artifact_directory_must_be_empty")
        _private_permissions(path, apply=True)
        _require(_identity(before) == _identity(_checked_path(path)), "artifact_identity_changed")
    except RuntimeIsolationError:
        raise
    except (OSError, ValueError, TypeError):
        raise RuntimeIsolationError("artifact_protection_failed") from None


def verify_local_artifact(path: Path) -> None:
    """Read-only permission/identity check; no content read or permission repair."""
    try:
        before = _checked_path(path)
        _private_permissions(path, apply=False)
        _require(_identity(before) == _identity(_checked_path(path)), "artifact_identity_changed")
    except RuntimeIsolationError:
        raise
    except (OSError, ValueError, TypeError):
        raise RuntimeIsolationError("artifact_permission_verification_failed") from None


def _settings(home: Path) -> tuple[str, ...]:
    _require(home.is_absolute() and ".." not in home.parts, "absolute_unambiguous_path_required")
    # The installed CLI matches the SKILL.md file, not its containing directory.
    skills = ",".join(
        "{path="
        + json.dumps((home / "skills" / ".system" / name / "SKILL.md").as_posix())
        + ",enabled=false}"
        for name in BUILTIN_SKILLS
    )
    return (
        'model_provider="openai"',
        "project_doc_max_bytes=0",
        'web_search="disabled"',
        'cli_auth_credentials_store="file"',
        "suppress_unstable_features_warning=true",
        f"skills.config=[{skills}]",
    )


def isolated_config_args(home: Path) -> tuple[str, ...]:
    """Pure, stable CLI fragment; caller supplies model, MAX effort and output paths."""
    args = ["--ignore-user-config", "--strict-config"]
    for setting in _settings(home):
        args.extend(["-c", setting])
    args.extend(["--enable", "skip_host_skill_discovery"])
    for feature in DISABLED_FEATURES:
        args.extend(["--disable", feature])
    args.extend(["-s", "read-only", "--skip-git-repo-check", "--json"])
    return tuple(args)


def _environment(root: Path, home: Path, inherited: Mapping[str, str]) -> dict[str, str]:
    result = {}
    for key, value in inherited.items():
        upper = key.upper()
        if upper in CORE_ENVIRONMENT:
            _require(upper not in result and "\0" not in value, "ambiguous_core_environment")
            result[upper] = value
    profile, temporary = root / "profile", root / "tmp"
    paths = {
        "CODEX_HOME": home,
        "HOME": profile,
        "USERPROFILE": profile,
        "APPDATA": profile / "AppData" / "Roaming",
        "LOCALAPPDATA": profile / "AppData" / "Local",
        "XDG_CONFIG_HOME": profile / ".config",
        "XDG_CACHE_HOME": profile / ".cache",
        "XDG_DATA_HOME": profile / ".local" / "share",
        "TEMP": temporary,
        "TMP": temporary,
        "TMPDIR": temporary,
    }
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        result[key] = str(path)
    if _WINDOWS:
        result["HOMEDRIVE"] = profile.drive
        result["HOMEPATH"] = str(profile)[len(profile.drive) :]
    return result


def _auth_source() -> Path:
    configured = os.environ.get("CODEX_HOME")
    home = Path(configured) if configured else Path.home() / ".codex"
    source = home / "auth.json"
    info = _checked_path(source)
    _require(
        stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 1024 * 1024, "auth_file_unavailable"
    )
    return source


def _copy_auth(source: Path, destination: Path) -> None:
    before = _checked_path(source)
    _require(not destination.exists(), "auth_destination_not_empty")
    # Opaque OS/file copy only: no JSON parsing, hashing, repr, logging or telemetry.
    shutil.copyfile(source, destination, follow_symlinks=False)
    after, copied = _checked_path(source), _checked_path(destination)
    _require(
        (_identity(before), before.st_size, before.st_mtime_ns)
        == (_identity(after), after.st_size, after.st_mtime_ns)
        and copied.st_size == before.st_size
        and _identity(copied) != _identity(after),
        "auth_source_changed_during_copy",
    )
    protect_local_artifact(destination)


def _cleanup(root: Path, root_id: tuple[int, int], parent_id: tuple[int, int]) -> None:
    try:
        _require(root.name.startswith(_PREFIX), "cleanup_root_name_mismatch")
        _require(_identity(_checked_path(root.parent)) == parent_id, "cleanup_parent_changed")
        _require(_identity(_checked_path(root)) == root_id, "cleanup_root_changed")
        if not any(root.iterdir()):
            root.rmdir()
            return
        _private_permissions(root, apply=False)
        for directory, directories, files in os.walk(root, followlinks=False):
            for name in (*directories, *files):
                child = Path(directory) / name
                _checked_path(child)
                _require(child.resolve().is_relative_to(root), "cleanup_path_escape")
        # Only the verified, uniquely created root is recursively deleted.
        shutil.rmtree(root)
        _require(not root.exists(), "cleanup_incomplete")
    except RuntimeIsolationError:
        raise
    except (OSError, ValueError, TypeError):
        raise RuntimeIsolationError("private_runtime_cleanup_failed") from None


@dataclass(frozen=True, repr=False)
class IsolatedReviewRuntime:
    root: Path
    home: Path
    cwd: Path
    env: Mapping[str, str] = field(repr=False)
    config_args: tuple[str, ...]
    attestation: Mapping[str, Any] = field(repr=False)

    def __repr__(self) -> str:
        return "IsolatedReviewRuntime(private_state=<redacted>)"


def _temporary_parent() -> Path:
    return Path(tempfile.gettempdir())


def _inside_repository(path: Path) -> bool:
    return path.resolve().is_relative_to(Path(__file__).resolve().parents[3]) or any(
        (ancestor / ".git").exists() for ancestor in (path, *path.parents)
    )


@contextmanager
def isolated_review_runtime() -> Iterator[IsolatedReviewRuntime]:
    """One fresh context per review stage; caller must copy native audit before exit."""
    root = None
    root_id = parent_id = None
    try:
        source = _auth_source()
        parent = _temporary_parent()
        parent_id = _identity(_checked_path(parent))
        _require(
            not _inside_repository(parent),
            "temporary_parent_inside_repository",
        )
        root = Path(tempfile.mkdtemp(prefix=_PREFIX, dir=parent))
        root_id = _identity(_checked_path(root))
        protect_local_artifact(root)
        home, cwd = root / "home", root / "work"
        home.mkdir(mode=0o700)
        cwd.mkdir(mode=0o700)
        protect_local_artifact(home)
        protect_local_artifact(cwd)
        _require(not any(home.iterdir()) and not any(cwd.iterdir()), "runtime_not_empty")
        env = _environment(root, home, os.environ)
        config = (
            "\n".join(
                (
                    *_settings(home),
                    "features.skip_host_skill_discovery=true",
                    *(f"features.{feature}=false" for feature in DISABLED_FEATURES),
                )
            )
            + "\n"
        )
        config_path = home / "config.toml"
        with config_path.open("x", encoding="utf-8") as handle:
            handle.write(config)
        protect_local_artifact(config_path)
        _copy_auth(source, home / "auth.json")
        _private_permissions(root, apply=False)
        runtime = IsolatedReviewRuntime(
            root=root,
            home=home,
            cwd=cwd,
            env=MappingProxyType(env),
            config_args=isolated_config_args(home),
            attestation=MappingProxyType(
                {
                    "schema_version": "isolated_review_runtime.v1",
                    "home": str(home),
                    "fresh_home": True,
                    "sanitized_environment": True,
                    "private_permissions": True,
                    "credential_copy_only": True,
                    "environment_keys": sorted(env),
                }
            ),
        )
    except BaseException as exc:
        if root is not None and root_id is not None and parent_id is not None:
            _cleanup(root, root_id, parent_id)
        if isinstance(exc, (RuntimeIsolationError, KeyboardInterrupt, SystemExit)):
            raise
        raise RuntimeIsolationError("private_runtime_setup_failed") from None
    try:
        yield runtime
    finally:
        assert root is not None and root_id is not None and parent_id is not None
        _cleanup(root, root_id, parent_id)
