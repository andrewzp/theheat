"""One bounded native preparation; no network, provider or publishing client."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile

from src.commands import postgres_editor_media as domain
from src.commands.schema import CommandError, utc_text
from src.commands.postgres_authority import _clock
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p


def run_native(args, *, input, cwd, env, timeout=45, grace=1):
    """Own one process group; timeout includes up to two seconds of cleanup."""
    child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=cwd, env=env, start_new_session=True)
    try:
        stdout, stderr = child.communicate(input=input, timeout=timeout)
    except BaseException:
        # The rasterizer belongs to this new group even if Python has died.
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.communicate(timeout=grace)
        raise
    result = subprocess.CompletedProcess(args, child.returncode, stdout, stderr)
    result.check_returncode()
    return result


def consume_media_once(authority, resolve_principal, *, command_id=None, now=None):
    """Reconcile first, snapshot under lock, render outside lock, commit once."""
    at = _clock(now)
    # A compact GHCN claim resolves before the locked snapshot; its context is
    # rechecked against that locked state, and consume() resolves its own again.
    from src.commands.postgres_sourced_generation import prepare_ghcn_command
    ghcn = prepare_ghcn_command(authority, command_id)
    try:
        with authority.projections._connection() as c:
            authority._validate(c)
            version, state = authority._state(c, lock=True)
            if command_id is not None and authority._result(c, command_id) is not None:
                return authority._result(c, command_id)
            row = c.execute("SELECT i.command_id FROM theheat_commands.intents i LEFT JOIN theheat_commands.results r USING(command_id) WHERE r.command_id IS NULL ORDER BY i.sequence LIMIT 1").fetchone()
            if row is None:
                return None
            domain.refuse(command_id is None or command_id == row[0], "command_pending")
            command_id = row[0]
            command = authority._intent(c, command_id)[0]
            if command.action != "prepare_media_revision":
                raise CommandError("not_native_preparation", "Use the ordinary local consumer")
            actor = domain.resolve(resolve_principal, command.actor_subject)
            from src.commands.recovery_provenance import require_current
            require_current(authority, command, state)
            draft, value = domain.command_inputs(authority, c, state, command, actor, current_editorial_policy(), at,
                                                 ghcn=ghcn, version=version)
            checkpoint = fingerprint(dict(target=domain._identity(draft), inputs=value))
            spec = p._decode(p._canonical(value["spec"]))
            original = None
            if spec["template"] == "published_nws_radar":
                from src.commands.postgres_published_media import read
                _, original = read(c, spec["evidence"]["input_sha256"])
    except CommandError as exc:
        if exc.code in {"not_native_preparation", "command_pending", "authorization_unavailable"}:
            raise
        # Known preflight refusal is recorded by the same command boundary.
        return authority.consume(resolve_principal, command_id=command_id, now=now, _prepared_media={})
    config = authority.editor_media_configuration
    prepared = dict(command_id=command_id, checkpoint=checkpoint, started_at=utc_text(at))
    folder = Path(tempfile.mkdtemp(prefix=command_id + "-", dir=config["scratch"]))
    folder.chmod(0o700)
    request = dict(spec=spec, output_dir=str(folder), rasterizer=config["rasterizer"])
    if original is not None:
        request.update(original=base64.b64encode(original).decode("ascii"), renderer=value["renderer"])
    try:
        # The fixed child receives only invented source data and local paths.
        # No operator file, provider key, environment credential or command body.
        run = run_native([sys.executable, "-m", "src.commands.preview_media_worker", "--native-child"],
            input=p._canonical(request), timeout=45,
            cwd=Path(__file__).resolve().parents[2], env={"PATH":"/usr/bin:/bin", "HOME":str(folder), "LANG":"en_US.UTF-8",
                "PYTHONPYCACHEPREFIX":str(folder / "bytecode")})
        domain.refuse(len(run.stdout) <= 4096, "native_render_failed")
        output = json.loads(run.stdout)
        manifest_path = Path(output["manifest"])
        domain.refuse(manifest_path.is_relative_to(folder) and not manifest_path.is_symlink(), "native_render_failed")
        manifest = json.loads(manifest_path.read_bytes())
        from src.commands.media_journal import asset_limits
        assets = {}
        for name, bound in asset_limits(manifest).items():
            asset = manifest_path.parent / name
            domain.refuse(not asset.is_symlink() and asset.is_file() and asset.stat().st_size <= bound, "native_render_failed")
            assets[name] = asset.read_bytes()
        prepared.update(manifest=manifest, assets=assets)
    except subprocess.TimeoutExpired:
        prepared["failure"] = "native_render_timeout"
    except (OSError, ValueError, KeyError, CommandError, subprocess.CalledProcessError):
        prepared["failure"] = "native_render_failed"
    # Scratch is private and retained for crash diagnosis; never repair a partial
    # cache in place. A same-command retry reconciles the durable result first.
    authority.last_native_peak_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # None preserves the live clock across the authority lock/proof/commit tail.
    # Explicit fixture time remains deterministic; do not freeze a live sample.
    return authority.consume(resolve_principal, command_id=command_id, now=now, _prepared_media=prepared)


def native_child():
    from src.media.evidence_graphic_render import render_preview
    raw = sys.stdin.buffer.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError("native_input_bound")
    request = json.loads(raw)
    if request.get("spec", {}).get("template") == "published_nws_radar":
        from src.media.published_radar import render
        if set(request) != {"spec", "output_dir", "rasterizer", "original", "renderer"}:
            raise ValueError("native_input_shape")
        path = render(request["spec"], base64.b64decode(request["original"], validate=True), request["renderer"], request["output_dir"])
        print(json.dumps({"manifest": str(path)}))
        return
    if len(raw) > 1_010_000 or set(request) != {"spec", "output_dir", "rasterizer"}:
        raise ValueError("native_input_shape")
    spec = request["spec"]
    path = render_preview(spec["template"], spec["evidence"], expected_evidence_sha256=spec["expected_evidence_sha256"],
                          output_dir=request["output_dir"], pdftoppm=request["rasterizer"])
    print(json.dumps({"manifest":str(path)}))


if __name__ == "__main__":
    if sys.argv[1:] != ["--native-child"]:
        raise SystemExit("explicit_native_child_required")
    native_child()
