"""Private, bounded copies of configured Gist revisions. Never a restore tool.

Only the standalone CLI starts the POSIX network child. Retained hashes prove
local byte binding, not provider authenticity, transactional state or approval.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import re
import stat
import time
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

from src.evaluation.file_boundary import new_private_directory, read_regular, _read_at

LIMITS = dict(
    files=32,
    fileBytes=8 * 1024 * 1024,
    totalBytes=64 * 1024 * 1024,
    metadataBytes=16 * 1024 * 1024,
    metadataRequests=4,
    metadataMilliseconds=30_000,
    downloadSeconds=180,
)
MAX_DESCRIPTOR = 1024 * 1024
_GIST = re.compile(r"[a-f0-9]{5,40}\Z")
_REVISION = re.compile(r"[a-f0-9]{40}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class GistBackupError(ValueError):
    """One fixed diagnostic, without a provider body, URL or credential."""


def require(condition, code):
    if not condition:
        raise GistBackupError(code)


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "backup_duplicate_key")
            result[key] = value
        return result

    def constant(_):
        raise GistBackupError("backup_invalid_json")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, GistBackupError):
            raise
        raise GistBackupError("backup_invalid_json") from None


def _fixed(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()), "backup_descriptor_shape")


def _date(value):
    require(type(value) is str, "backup_capture_time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.utcoffset() is not None, "backup_capture_time")
        return parsed
    except ValueError:
        raise GistBackupError("backup_capture_time") from None


def validate_descriptors(data):
    value = _json(data)
    _fixed(
        value,
        "schema capture_started_at capture_finished_at metadata_requests sources limits scope",
    )
    require(
        value["schema"] == "theheat-gist-backup-descriptors-v1" and value["limits"] == LIMITS,
        "backup_descriptor_version",
    )
    require(
        _date(value["capture_started_at"]) <= _date(value["capture_finished_at"]),
        "backup_capture_time",
    )
    require(
        type(value["sources"]) is list and 0 < len(value["sources"]) <= 2, "backup_source_limit"
    )
    sources: dict[str, dict] = {}
    for source in value["sources"]:
        _fixed(source, "id roles revision owner metadata_sha256 files")
        sid, revision, owner = source["id"], source["revision"], source["owner"]
        require(
            type(sid) is str
            and _GIST.fullmatch(sid)
            and type(revision) is str
            and _REVISION.fullmatch(revision)
            and type(owner) is str
            and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner)
            and type(source["metadata_sha256"]) is str
            and _SHA.fullmatch(source["metadata_sha256"]),
            "backup_source_identity",
        )
        require(
            type(source["roles"]) is list
            and source["roles"]
            and all(type(role) is str and role in {"state", "feedback"} for role in source["roles"])
            and len(set(source["roles"])) == len(source["roles"]),
            "backup_source_roles",
        )
        require(
            type(source["files"]) is list and 0 < len(source["files"]) <= LIMITS["files"],
            "backup_file_limit",
        )
        files: dict[str, dict] = {}
        for file in source["files"]:
            _fixed(file, "filename source_bytes url raw_revision")
            name = file["filename"]
            require(
                type(name) is str
                and 0 < len(name.encode("utf-8")) <= 1024
                and name not in {".", ".."}
                and not re.search(r"[\x00-\x1f\x7f/\\]", name),
                "backup_filename",
            )
            require(
                type(file["source_bytes"]) is int
                and 0 <= file["source_bytes"] <= LIMITS["fileBytes"],
                "backup_file_limit",
            )
            require(
                type(file["url"]) is str
                and len(file["url"]) <= 8192
                and not re.search(r"[\x00-\x20\x7f]", file["url"]),
                "backup_raw_url",
            )
            try:
                url = urlsplit(file["url"])
                parts = url.path.split("/")
                require(
                    url.scheme == "https"
                    and url.hostname == "gist.githubusercontent.com"
                    and url.port in {None, 443}
                    and not url.username
                    and not url.password
                    and not url.query
                    and not url.fragment
                    and len(parts) == 6
                    and parts[0] == ""
                    and parts[1].lower() == owner.lower()
                    and parts[2] == sid
                    and parts[3] == "raw"
                    and _REVISION.fullmatch(parts[4])
                    and file["raw_revision"] == parts[4]
                    and unquote(parts[5], errors="strict") == name,
                    "backup_raw_url",
                )
            except (ValueError, UnicodeError):
                raise GistBackupError("backup_raw_url") from None
            require(name not in files or files[name] == file, "backup_file_identity_conflict")
            files[name] = file
        normalized = {
            **source,
            "roles": sorted(source["roles"]),
            "files": sorted(files.values(), key=lambda row: row["filename"]),
        }
        if sid in sources:
            old = sources[sid]
            require(
                {k: v for k, v in old.items() if k != "roles"}
                == {k: v for k, v in normalized.items() if k != "roles"},
                "backup_source_identity_conflict",
            )
            normalized["roles"] = sorted(set(old["roles"]) | set(normalized["roles"]))
        sources[sid] = normalized
    roles = [role for source in sources.values() for role in source["roles"]]
    require(roles.count("state") == 1 and roles.count("feedback") <= 1, "backup_source_roles")
    require(
        type(value["metadata_requests"]) is int and value["metadata_requests"] == 2 * len(sources),
        "backup_metadata_count",
    )
    all_files = [
        dict(file, source_id=source["id"], revision=source["revision"])
        for source in sources.values()
        for file in source["files"]
    ]
    require(
        len(all_files) <= LIMITS["files"]
        and sum(file["source_bytes"] for file in all_files) <= LIMITS["totalBytes"],
        "backup_total_limit",
    )
    return {**value, "sources": list(sources.values())}, all_files


def _write(directory, name, body):
    require(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name), "backup_output_name")
    fd = os.open(name, _CREATE, 0o600, dir_fd=directory)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, indent=2).encode()


def _raw_request(url, remaining):
    import requests

    session = requests.Session()
    session.trust_env = False  # No netrc/keychain/proxy credentials or inherited auth.
    try:
        response = session.get(
            url,
            headers={"Accept-Encoding": "identity"},
            stream=True,
            allow_redirects=False,
            timeout=(min(5, remaining), min(10, remaining)),
        )
        try:
            require(
                response.status_code == 200
                and not response.history
                and response.headers.get("Content-Encoding", "identity").lower() == "identity",
                "backup_raw_unavailable",
            )
            yield from response.iter_content(chunk_size=64 * 1024)
        finally:
            response.close()
    finally:
        session.close()


def _download(files, directory, sender, deadline, fetch):
    rows = []
    requests = 0
    try:
        for index, file in enumerate(files):
            remaining = deadline - time.monotonic()
            require(remaining > 0, "backup_deadline")
            part = f"part-{index:04d}"
            digest = hashlib.sha256()
            size = 0
            fd = os.open(part, _CREATE, 0o600, dir_fd=directory)
            requests += 1
            with os.fdopen(fd, "wb") as stream:
                for chunk in (fetch or _raw_request)(file["url"], remaining):
                    require(time.monotonic() < deadline, "backup_deadline")
                    require(type(chunk) is bytes, "backup_raw_bytes")
                    size += len(chunk)
                    require(
                        size <= file["source_bytes"] and size <= LIMITS["fileBytes"],
                        "backup_byte_count",
                    )
                    stream.write(chunk)
                    digest.update(chunk)
                require(size == file["source_bytes"], "backup_byte_count")
                stream.flush()
                os.fsync(stream.fileno())
            sha = digest.hexdigest()
            name = "object-" + sha
            try:
                os.link(
                    part, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False
                )
            except FileExistsError:
                require(
                    hashlib.sha256(_read_at(directory, name, LIMITS["fileBytes"])).hexdigest()
                    == sha,
                    "backup_object_conflict",
                )
            os.unlink(part, dir_fd=directory)
            rows.append(dict(file, sha256=sha, object=name, retained_bytes=size))
        sender.send_bytes(_encoded(dict(ok=True, files=rows, requests=requests)))
    except BaseException as error:
        code = str(error) if isinstance(error, GistBackupError) else "backup_download_unavailable"
        try:
            sender.send_bytes(
                _encoded(dict(ok=False, code=code, completed_files=len(rows), requests=requests))
            )
        except (BrokenPipeError, EOFError, OSError):
            # The parent may have reached its deadline. Never print provider
            # exception text while reporting that already-held outcome.
            pass
    finally:
        sender.close()


def backup_gists(descriptor_path, output_path, *, _fetch=None, _timeout=180):
    """Capture with one owned child; only the parent may mark complete.

    _fetch is an explicit offline transport seam, never a CLI/env fallback.
    A shorter private test deadline cannot increase the fixed production bound.
    """
    require(
        type(_timeout) in {int, float} and 0 < _timeout <= LIMITS["downloadSeconds"],
        "backup_deadline_policy",
    )
    deadline = time.monotonic() + _timeout
    raw = read_regular(descriptor_path, MAX_DESCRIPTOR)
    plan, files = validate_descriptors(raw)
    require("fork" in multiprocessing.get_all_start_methods(), "backup_posix_required")
    with new_private_directory(output_path) as directory:
        _write(directory, "descriptors.json", raw)
        process = None
        receiver = sender = None
        try:
            context = multiprocessing.get_context("fork")
            receiver, sender = context.Pipe(duplex=False)
            reserve = min(2, _timeout / 5)
            process = context.Process(
                target=_download, args=(files, directory, sender, deadline - reserve, _fetch)
            )
            process.start()
            sender.close()
            require(receiver.poll(max(0, deadline - reserve - time.monotonic())), "backup_deadline")
            result = _json(receiver.recv_bytes(MAX_DESCRIPTOR))
            process.join(timeout=max(0, deadline - time.monotonic()))
            require(process.exitcode == 0 and type(result) is dict, "backup_worker_unknown")
            require(result.get("ok") is True, result.get("code", "backup_download_unavailable"))
            rows = result.get("files")
            require(
                type(rows) is list
                and len(rows) == len(files)
                and result.get("requests") == len(files),
                "backup_inventory_incomplete",
            )
            for expected, row in zip(files, rows, strict=True):
                require(
                    type(row) is dict
                    and all(row.get(key) == value for key, value in expected.items())
                    and type(row.get("sha256")) is str
                    and _SHA.fullmatch(row["sha256"])
                    and row.get("object") == "object-" + row["sha256"],
                    "backup_object_binding",
                )
                require(time.monotonic() < deadline, "backup_deadline")
                info = os.stat(row["object"], dir_fd=directory, follow_symlinks=False)
                require(
                    stat.S_ISREG(info.st_mode)
                    and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600,
                    "backup_object_not_private",
                )
                body = _read_at(directory, row["object"], LIMITS["fileBytes"])
                require(
                    len(body) == expected["source_bytes"] == row.get("retained_bytes")
                    and hashlib.sha256(body).hexdigest() == row["sha256"],
                    "backup_object_binding",
                )
            require(time.monotonic() < deadline, "backup_deadline")
            manifest = dict(
                schema="theheat-gist-backup-v1",
                descriptor_sha256=hashlib.sha256(raw).hexdigest(),
                descriptors=plan,
                files=rows,
                completed_at=datetime.now(timezone.utc).isoformat(),
                scope="Literal configured Gist files only; no transaction, media/job backup or restore authority.",
            )
            encoded = _encoded(manifest)
            _write(directory, "manifest.json", encoded)
            require(time.monotonic() < deadline, "backup_deadline")
            summary = dict(
                status="complete",
                files=len(rows),
                objects=len({row["object"] for row in rows}),
                bytes=sum(row["retained_bytes"] for row in rows),
                manifest_sha256=hashlib.sha256(encoded).hexdigest(),
            )
            _write(directory, "COMPLETE.json", _encoded(summary))
            require(time.monotonic() < deadline, "backup_deadline")
            return summary
        except BaseException as error:
            code = str(error) if isinstance(error, GistBackupError) else "backup_capture_incomplete"
            try:
                os.unlink("COMPLETE.json", dir_fd=directory)
            except FileNotFoundError:
                pass
            _write(
                directory,
                "INCOMPLETE.json",
                _encoded(
                    dict(
                        status="incomplete",
                        code=code,
                        requests="unknown if the network worker did not return a complete receipt",
                    )
                ),
            )
            raise GistBackupError(code) from None
        finally:
            if process is not None and process.is_alive():
                process.terminate()
                process.join(timeout=max(0, min(1, deadline - time.monotonic())))
                if process.is_alive():
                    process.kill()
                    process.join(timeout=max(0, deadline - time.monotonic()))
            if receiver is not None:
                receiver.close()
            if sender is not None:
                sender.close()
