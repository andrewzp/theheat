# Private Gist backup

The dashboard can describe the exact versions of its configured state Gist and,
when configured, feedback Gist. The local CLI copies their complete raw files.
This is a read-only operator backup, not a restore command, a state migration or
a publishing action. It does not back up media, databases, workflow inboxes,
external jobs or credentials. Separate Gist snapshots are not a transaction.

1. Use the dashboard's existing authenticated deployment connection to save
   `GET /api/backup-manifest` into a private local `descriptors.json`. The endpoint
   accepts no Gist IDs or URL arguments. Check HTTP success before proceeding;
   an error document is not a backup. Do not put credentials in shell arguments,
   URLs, saved descriptors or chat.
2. In a single-threaded POSIX Python process with the project's dependencies,
   download once into a new directory. Use real canonical parent paths: on
   macOS `/tmp` and `/var` can be symlinks, so use `/private/tmp` or `/private/var`.

   ```sh
   python scripts/backup_gist.py \
     --descriptors /absolute/private/path/descriptors.json \
     --output /absolute/private/path/new-backup
   ```

3. Require exit code zero and a `complete` result. Keep the entire directory:
   `descriptors.json`, `manifest.json`, `COMPLETE.json` and every `object-*` file.
   The manifest maps original, inert filenames to exact raw bytes, byte counts
   and SHA-256 hashes. Files with equal bytes share one object; their separate
   source/file entries remain. A raw-file revision can differ from its enclosing
   Gist revision. Literal numeric spelling and unknown fields are not rewritten.

The CLI never reads credential stores, sends authentication, follows redirects
or retries a failed raw request. Private raw access that requires authentication
is an explicit incomplete result. Do not substitute API content, remove files
or raise limits to make the operation appear complete.

Metadata is limited to four requests, 16 MiB per response and 30 seconds for the
whole descriptor request. Downloads permit at most 32 files, 8 MiB per file and
64 MiB overall, with a 180-second whole-operation budget. One owned POSIX child
performs network work; the parent stops it at the deadline and creates the
complete marker only after its normal exit and a full byte/hash reread. Host
suspension or blocked disk I/O cannot have a realtime completion guarantee.

Output uses a newly created private directory and exclusive private files;
symlinks, devices, FIFOs, traversals and existing output directories are refused.
If a request fails, a stream ends early, bytes exceed a limit or the worker's
outcome is unknown, the CLI exits nonzero. The partial directory is kept with
`INCOMPLETE.json` when it can be written. Its files are evidence of the attempt,
not an accepted backup. Never infer success from an object or manifest alone.

Backups are kept by default. This tool schedules, uploads and deletes nothing.
A local copy is lost with its device; arrange an approved private offsite copy
separately. Do not delete prior snapshots or the only complete copy as part of
credential rotation. Hashes detect local byte changes; they do not certify
provider authenticity, source truth, review or posting permission.
