"""Synthetic credentials only. No Codex, model, business DB or network calls."""

import json
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloud_expert.model_review import isolated_runtime as ir

SECRET = b"SYNTHETIC-OPAQUE-AUTH-NEVER-LOG-\xff"


@pytest.fixture
def synthetic_source(tmp_path, monkeypatch):
    source = tmp_path / "synthetic-source"
    source.mkdir()
    (source / "auth.json").write_bytes(SECRET)
    (source / "config.toml").write_text('model="synthetic-untrusted"')
    (source / "AGENTS.md").write_text("Synthetic inherited instructions must not enter")
    (source / "rules").mkdir()
    (source / "rules" / "default.rules").write_text("synthetic")
    (source / "skills").mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source))
    return source


@pytest.fixture
def sandbox(synthetic_source, tmp_path, monkeypatch):
    parent = tmp_path / "synthetic-temporary"
    parent.mkdir()
    monkeypatch.setattr(ir, "_temporary_parent", lambda: parent)
    # Synthetic auth only: keep all writes inside the offline verification root.
    monkeypatch.setattr(ir, "_inside_repository", lambda path: False)
    return synthetic_source, parent


def test_opaque_copy_empty_state_actual_private_permissions_and_cleanup(sandbox, capsys):
    source, parent = sandbox
    with ir.isolated_review_runtime() as runtime:
        root = runtime.root
        assert root.parent == parent and runtime.home.parent == runtime.cwd.parent == root
        assert runtime.home.name == "home" and runtime.cwd.name == "work"
        assert list(runtime.cwd.iterdir()) == []
        assert {p.name for p in runtime.home.iterdir()} == {"auth.json", "config.toml"}
        assert (runtime.home / "auth.json").read_bytes() == SECRET
        assert os.stat(source / "auth.json").st_ino != os.stat(runtime.home / "auth.json").st_ino
        for path in (root, runtime.home, runtime.cwd, runtime.home / "auth.json"):
            ir._private_permissions(path, apply=False)
        assert str(source) not in repr(runtime)
        assert "SYNTHETIC-OPAQUE" not in repr(runtime)
        assert (source / "rules" / "default.rules").exists()
    assert not root.exists() and not list(parent.iterdir())
    assert (source / "auth.json").read_bytes() == SECRET
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


def test_public_settings_and_exact_five_disabled_builtin_paths(sandbox):
    with ir.isolated_review_runtime() as runtime:
        config = tomllib.loads((runtime.home / "config.toml").read_text(encoding="utf-8"))
        assert config["suppress_unstable_features_warning"] is True
        assert config["features"]["skip_host_skill_discovery"] is True
        assert {p["path"] for p in config["skills"]["config"]} == {
            (runtime.home / "skills" / ".system" / name / "SKILL.md").as_posix()
            for name in ir.BUILTIN_SKILLS
        }
        assert len(config["skills"]["config"]) == 5
        assert all(p["enabled"] is False for p in config["skills"]["config"])
        assert all(config["features"][name] is False for name in ir.DISABLED_FEATURES)
        args = runtime.config_args
        assert args == ir.isolated_config_args(runtime.home)
        assert args[:2] == ("--ignore-user-config", "--strict-config")
        assert args[-4:] == ("-s", "read-only", "--skip-git-repo-check", "--json")
        assert "--ephemeral" not in args and "resume" not in args
        assert "suppress_unstable_features_warning=true" in args
        assert "--enable" in args and "skip_host_skill_discovery" in args
        assert "-m" not in args and not any("reasoning_effort" in item for item in args)
        cli_settings = [args[index + 1] for index, arg in enumerate(args) if arg == "-c"]
        projected = tomllib.loads("\n".join(cli_settings))
        assert projected["skills"] == config["skills"]


def test_sanitized_environment_no_secrets_or_inherited_locations(sandbox, monkeypatch):
    keys = (
        "OPENAI_API_KEY",
        "CODEX_THREAD_ID",
        "CODEX_CONFIG",
        "CODEX_SQLITE_HOME",
        "GIT_CONFIG_GLOBAL",
        "PYTHONPATH",
        "NODE_OPTIONS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "BASH_ENV",
        "ENV",
        "LD_PRELOAD",
    )
    for key in keys:
        monkeypatch.setenv(key, "SYNTHETIC-DO-NOT-INHERIT")
    with ir.isolated_review_runtime() as runtime:
        assert not set(keys).intersection(runtime.env)
        assert runtime.env["CODEX_HOME"] == str(runtime.home)
        for key in (
            "HOME",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "TEMP",
            "TMP",
            "TMPDIR",
            "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME",
            "XDG_DATA_HOME",
        ):
            assert Path(runtime.env[key]).is_relative_to(runtime.root)
            assert Path(runtime.env[key]).is_dir()
        assert not any("SYNTHETIC-DO-NOT-INHERIT" in value for value in runtime.env.values())
        with pytest.raises(TypeError):
            runtime.env["OPENAI_API_KEY"] = "cannot mutate"
        actual = dict(runtime.attestation)
        assert set(actual) == {
            "schema_version",
            "home",
            "fresh_home",
            "sanitized_environment",
            "private_permissions",
            "credential_copy_only",
            "environment_keys",
        }
        assert actual["schema_version"] == "isolated_review_runtime.v1"
        assert actual["environment_keys"] == sorted(runtime.env)
        assert "SYNTHETIC-OPAQUE" not in json.dumps(actual)


def test_synthetic_python_child_environment_preserves_offline_guard(sandbox):
    with ir.isolated_review_runtime() as runtime:
        environment = dict(runtime.env)
        if os.environ.get("CLOUD_EXPERT_VERIFICATION_ROOT"):
            # Test-only Python child must retain the enclosing offline guard.
            # Production Codex runtime.env deliberately never inherits these keys.
            for key in ("CLOUD_EXPERT_VERIFICATION_ROOT", "PYTHONPATH"):
                assert key not in runtime.env
                environment[key] = os.environ[key]
        probe = """
import json, os, sys
if 'CLOUD_EXPERT_VERIFICATION_ROOT' in os.environ:
    try:
        sys.audit('socket.connect', None, ('127.0.0.1', 5432))
    except PermissionError:
        pass
    else:
        raise AssertionError('synthetic child lost enclosing offline guard')
print(json.dumps({'home': os.environ['CODEX_HOME'], 'cwd': os.getcwd(),
                  'has_parent_thread': 'CODEX_THREAD_ID' in os.environ}))
"""
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                probe,
            ],
            cwd=runtime.cwd,
            env=environment,
            capture_output=True,
            check=True,
            timeout=10,
        )
        result = json.loads(completed.stdout)
        assert result == {
            "home": str(runtime.home),
            "cwd": str(runtime.cwd),
            "has_parent_thread": False,
        }


def test_contexts_are_unique_and_never_reuse_previous_stage(sandbox):
    with ir.isolated_review_runtime() as first, ir.isolated_review_runtime() as second:
        assert first.root != second.root
        (first.cwd / "prior-opinion.txt").write_text("synthetic first opinion")
        assert not list(second.cwd.iterdir())
    assert not first.root.exists() and not second.root.exists()


def test_body_failure_cleans_private_state_without_suppressing_original_exception(sandbox):
    with (
        pytest.raises(RuntimeError, match="synthetic body failure"),
        ir.isolated_review_runtime() as runtime,
    ):
        raise RuntimeError("synthetic body failure")
    assert not runtime.root.exists()


@pytest.mark.parametrize("failure", ["copy", "partial_copy", "config", "root_acl"])
def test_setup_failure_cleans_only_own_root(sandbox, monkeypatch, failure):
    source, parent = sandbox
    unrelated = parent / "unrelated"
    unrelated.mkdir()
    sentinel = unrelated / "keep.txt"
    sentinel.write_text("retain")
    if failure in {"copy", "partial_copy"}:

        def broken_copy(src, dst):
            if failure == "partial_copy":
                dst.write_bytes(SECRET)
            raise OSError("SYNTHETIC-OPAQUE-AUTH-NEVER-LOG")

        monkeypatch.setattr(ir, "_copy_auth", broken_copy)
    elif failure == "config":

        def broken_settings(home):
            raise OSError("synthetic config failure")

        monkeypatch.setattr(ir, "_settings", broken_settings)
    else:

        def broken_permissions(path, *, apply):
            raise ir.RuntimeIsolationError("synthetic_acl_failure")

        monkeypatch.setattr(ir, "_private_permissions", broken_permissions)
    with pytest.raises(ir.RuntimeIsolationError) as caught, ir.isolated_review_runtime():
        pytest.fail("must not yield")
    assert "SYNTHETIC-OPAQUE" not in str(caught.value)
    assert list(parent.iterdir()) == [unrelated]
    assert sentinel.read_text() == "retain" and (source / "auth.json").read_bytes() == SECRET


@pytest.mark.parametrize("invalid", ["missing", "empty", "directory", "oversized", "hardlink"])
def test_invalid_auth_fails_before_creating_runtime(sandbox, invalid):
    source, parent = sandbox
    auth = source / "auth.json"
    if invalid == "hardlink":
        os.link(auth, source / "another-link")
    else:
        auth.unlink()
        if invalid == "empty":
            auth.touch()
        elif invalid == "directory":
            auth.mkdir()
        elif invalid == "oversized":
            auth.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ir.RuntimeIsolationError), ir.isolated_review_runtime():
        pytest.fail("must not yield")
    assert not list(parent.iterdir())


def test_default_auth_home_only_when_codex_home_absent(sandbox, monkeypatch):
    source, _ = sandbox
    default = source.parent / "profile"
    default.mkdir()
    default_home = default / ".codex"
    default_home.mkdir()
    (default_home / "auth.json").write_bytes(b"SYNTHETIC-DEFAULT")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(ir.Path, "home", classmethod(lambda cls: default))
    with ir.isolated_review_runtime() as runtime:
        assert (runtime.home / "auth.json").read_bytes() == b"SYNTHETIC-DEFAULT"


def test_bad_explicit_home_does_not_fallback(sandbox, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "relative-home")
    with (
        pytest.raises(ir.RuntimeIsolationError, match="absolute_unambiguous_path_required"),
        ir.isolated_review_runtime(),
    ):
        pytest.fail("must not yield")


def test_artifact_protection_preserves_bytes_and_checks_permissions(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    ir.protect_local_artifact(stage)
    path = stage / "runtime.local-only.jsonl"
    original = b'SYNTHETIC LOCAL ONLY {"creator_account_id":"fixture"}\r\n'
    path.write_bytes(original)
    ir.protect_local_artifact(path)
    ir._private_permissions(path, apply=False)
    ir.verify_local_artifact(path)
    ir.verify_local_artifact(stage)
    assert path.read_bytes() == original
    with pytest.raises(ir.RuntimeIsolationError, match="artifact_directory_must_be_empty"):
        ir.protect_local_artifact(stage)


def test_artifact_hardlink_rejected_without_altering_target(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(SECRET)
    linked = tmp_path / "linked"
    os.link(target, linked)
    with pytest.raises(ir.RuntimeIsolationError, match="hardlinked_path_rejected"):
        ir.protect_local_artifact(linked)
    assert target.read_bytes() == SECRET


def _symlink(link, target, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("OS account cannot create symlinks")


def test_auth_link_rejected(sandbox):
    source, parent = sandbox
    original = source / "original"
    (source / "auth.json").rename(original)
    _symlink(source / "auth.json", original)
    with (
        pytest.raises(ir.RuntimeIsolationError, match="linked_or_reparse_path_rejected"),
        ir.isolated_review_runtime(),
    ):
        pytest.fail("must not yield")
    assert not list(parent.iterdir())


def test_cleanup_rejects_escape_link_never_deletes_external_target(sandbox):
    source, _ = sandbox
    link = None
    try:
        with (
            pytest.raises(ir.RuntimeIsolationError, match="linked_or_reparse_path_rejected"),
            ir.isolated_review_runtime() as runtime,
        ):
            link = runtime.cwd / "escape"
            _symlink(link, source, directory=True)
        assert (source / "auth.json").read_bytes() == SECRET
        assert runtime.root.exists()
    finally:
        if link is not None and link.is_symlink():
            link.unlink()
        if "runtime" in locals() and runtime.root.exists():
            ir._cleanup(
                runtime.root,
                ir._identity(runtime.root.stat()),
                ir._identity(runtime.root.parent.stat()),
            )


def test_cleanup_refuses_replaced_root_identity(sandbox):
    with ir.isolated_review_runtime() as runtime:
        with pytest.raises(ir.RuntimeIsolationError, match="cleanup_root_changed"):
            ir._cleanup(runtime.root, (-1, -1), ir._identity(runtime.root.parent.stat()))
        assert runtime.root.exists()


def test_cleanup_refuses_hardlinked_file(sandbox):
    with ir.isolated_review_runtime() as runtime:
        outside = sandbox[0] / "auth.json"
        link = runtime.cwd / "hardlink"
        os.link(outside, link)
        try:
            with pytest.raises(ir.RuntimeIsolationError, match="hardlinked_path_rejected"):
                ir._cleanup(
                    runtime.root,
                    ir._identity(runtime.root.stat()),
                    ir._identity(runtime.root.parent.stat()),
                )
            assert outside.read_bytes() == SECRET
        finally:
            link.unlink()


@pytest.mark.parametrize(
    "directory,mode,owner,apply,accepted",
    [
        (False, 0o600, 1234, False, True),
        (False, 0o400, 1234, False, True),
        (False, 0o640, 1234, False, False),
        (False, 0o600, 9999, False, False),
        (True, 0o700, 1234, False, True),
        (True, 0o710, 1234, False, False),
        (True, 0o400, 1234, False, False),
        (False, 0o644, 1234, True, True),
        (True, 0o755, 1234, True, True),
    ],
)
def test_synthetic_posix_private_mode_logic(monkeypatch, directory, mode, owner, apply, accepted):
    """Mocked POSIX permission logic only; this is not native POSIX validation."""
    monkeypatch.setattr(ir, "_WINDOWS", False)
    monkeypatch.setattr(ir, "os", SimpleNamespace(getuid=lambda: 1234))
    kind = stat.S_IFDIR if directory else stat.S_IFREG
    info = SimpleNamespace(st_uid=owner, st_mode=kind | mode)
    changes = []

    def chmod(new_mode):
        changes.append(new_mode)
        info.st_mode = kind | new_mode

    path = SimpleNamespace(is_dir=lambda: directory, lstat=lambda: info, chmod=chmod)
    if accepted:
        ir._private_permissions(path, apply=apply)
    else:
        with pytest.raises(ir.RuntimeIsolationError, match="private_mode_verification_failed"):
            ir._private_permissions(path, apply=apply)
    assert changes == ([0o700 if directory else 0o600] if apply else [])
    if not apply:
        assert stat.S_IMODE(info.st_mode) == mode


def test_core_environment_case_collision_is_rejected(tmp_path):
    with pytest.raises(ir.RuntimeIsolationError, match="ambiguous_core_environment"):
        ir._environment(tmp_path, tmp_path / "home", {"PATH": "a", "Path": "b"})


@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_interrupted_setup_still_cleans_copied_credential(sandbox, monkeypatch, error):
    def interrupted(source, destination):
        destination.write_bytes(SECRET)
        raise error("synthetic setup interruption")

    monkeypatch.setattr(ir, "_copy_auth", interrupted)
    expected = ir.RuntimeIsolationError if error is RuntimeError else error
    with pytest.raises(expected), ir.isolated_review_runtime():
        pytest.fail("must not yield")
    assert not list(sandbox[1].iterdir())


def test_auth_copy_source_mutation_fails_closed(sandbox, monkeypatch):
    original = ir.shutil.copyfile

    def altered(source, destination, **kwargs):
        result = original(source, destination, **kwargs)
        source.write_bytes(b"SYNTHETIC-CHANGED-AFTER-COPY")
        return result

    monkeypatch.setattr(ir.shutil, "copyfile", altered)
    with (
        pytest.raises(ir.RuntimeIsolationError, match="auth_source_changed_during_copy"),
        ir.isolated_review_runtime(),
    ):
        pytest.fail("must not yield")
    assert not list(sandbox[1].iterdir())


def test_auth_source_parent_link_is_rejected(sandbox, monkeypatch):
    source, parent = sandbox
    link = source.parent / "source-alias"
    _symlink(link, source, directory=True)
    monkeypatch.setenv("CODEX_HOME", str(link))
    with (
        pytest.raises(ir.RuntimeIsolationError, match="linked_or_reparse_path_rejected"),
        ir.isolated_review_runtime(),
    ):
        pytest.fail("must not yield")
    assert not list(parent.iterdir())


def test_config_args_escape_paths_as_toml_without_filesystem_access(tmp_path):
    home = tmp_path / 'synthetic "quoted" home'
    args = ir.isolated_config_args(home)
    settings = [args[index + 1] for index, item in enumerate(args) if item == "-c"]
    config = tomllib.loads("\n".join(settings))
    assert (
        config["skills"]["config"][0]["path"]
        == (home / "skills/.system/imagegen/SKILL.md").as_posix()
    )
    assert not home.exists()


def test_cleanup_failure_is_reported_not_silently_ignored(sandbox, monkeypatch):
    original = ir.shutil.rmtree

    def failed_remove(path):
        raise OSError("synthetic cleanup denial")

    try:
        with (
            pytest.raises(ir.RuntimeIsolationError, match="private_runtime_cleanup_failed"),
            ir.isolated_review_runtime() as runtime,
        ):
            monkeypatch.setattr(ir.shutil, "rmtree", failed_remove)
        assert runtime.root.exists()
        ir._private_permissions(runtime.root, apply=False)
    finally:
        monkeypatch.setattr(ir.shutil, "rmtree", original)
        if "runtime" in locals() and runtime.root.exists():
            ir._cleanup(
                runtime.root,
                ir._identity(runtime.root.stat()),
                ir._identity(runtime.root.parent.stat()),
            )


def test_verify_is_readonly_and_never_repairs_permissions(tmp_path, monkeypatch):
    path = tmp_path / "original.jsonl"
    path.write_bytes(SECRET)
    ir.protect_local_artifact(path)

    def no_read(*args, **kwargs):
        pytest.fail("verification must not open content")

    monkeypatch.setattr(ir.Path, "open", no_read)
    permissions = ir._private_permissions
    calls = []

    def observe(path, *, apply):
        calls.append(apply)
        permissions(path, apply=apply)

    monkeypatch.setattr(ir, "_private_permissions", observe)
    ir.verify_local_artifact(path)
    assert calls == [False]

    def denied(path, *, apply):
        assert apply is False
        raise ir.RuntimeIsolationError("synthetic_acl_not_private")

    monkeypatch.setattr(ir, "_private_permissions", denied)
    with pytest.raises(ir.RuntimeIsolationError, match="synthetic_acl_not_private"):
        ir.verify_local_artifact(path)


def test_verify_rejects_identity_change(tmp_path, monkeypatch):
    path = tmp_path / "original"
    path.write_bytes(SECRET)
    ir.protect_local_artifact(path)
    identities = iter([(1, 1), (1, 2)])
    monkeypatch.setattr(ir, "_identity", lambda info: next(identities))
    with pytest.raises(ir.RuntimeIsolationError, match="artifact_identity_changed"):
        ir.verify_local_artifact(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows protected DACL semantics")
def test_windows_unprotected_artifact_fails_readonly_verification(tmp_path):
    path = tmp_path / "unprotected-original"
    path.write_bytes(SECRET)
    with pytest.raises(ir.RuntimeIsolationError, match="private_acl_operation_failed"):
        ir.verify_local_artifact(path)
    assert path.read_bytes() == SECRET
    ir.protect_local_artifact(path)
    ir.verify_local_artifact(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only attribute is independent of DACL")
def test_windows_readonly_attribute_keeps_private_acl_valid(tmp_path):
    path = tmp_path / "readonly-original"
    path.write_bytes(SECRET)
    ir.protect_local_artifact(path)
    try:
        path.chmod(stat.S_IREAD)
        ir.verify_local_artifact(path)
        assert path.read_bytes() == SECRET
        assert not path.stat().st_mode & stat.S_IWRITE
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_never_copies_credentials_to_repository_temp(synthetic_source, monkeypatch):
    repository = Path(ir.__file__).resolve().parents[3]
    assert ir._inside_repository(repository)
    monkeypatch.setattr(ir, "_temporary_parent", lambda: repository)
    copied = []
    monkeypatch.setattr(ir, "_copy_auth", lambda *args: copied.append(args))
    with (
        pytest.raises(ir.RuntimeIsolationError, match="temporary_parent_inside_repository"),
        ir.isolated_review_runtime(),
    ):
        pytest.fail("must not yield")
    assert not copied
    assert (synthetic_source / "auth.json").read_bytes() == SECRET


def test_rejects_another_git_checkout_as_temp_parent(synthetic_source, tmp_path, monkeypatch):
    parent = tmp_path / "other-checkout"
    parent.mkdir()
    (parent / ".git").write_text("synthetic git worktree marker")
    # Separate synthetic installation ensures the Git-marker branch is exercised.
    monkeypatch.setattr(ir, "__file__", str(tmp_path / "install/src/pkg/review/runtime.py"))
    assert not parent.is_relative_to(Path(ir.__file__).resolve().parents[3])
    assert ir._inside_repository(parent)
    monkeypatch.setattr(ir, "_temporary_parent", lambda: parent)
    copied = []
    monkeypatch.setattr(ir, "_copy_auth", lambda *args: copied.append(args))
    with (
        pytest.raises(ir.RuntimeIsolationError, match="temporary_parent_inside_repository"),
        ir.isolated_review_runtime(),
    ):
        pytest.fail("must not yield")
    assert not copied
    assert {p.name for p in parent.iterdir()} == {".git"}
    assert (synthetic_source / "auth.json").read_bytes() == SECRET
