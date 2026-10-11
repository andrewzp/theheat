# Explicit TLS adapter for synthetic staging

The existing PostgreSQL projection repository and command authority now have an
explicit `for_hosted_staging` factory. It returns the same classes and uses the
same migrations, transaction boundaries, catalog fingerprints and runtime-role
checks. Ordinary construction remains local Unix-socket only. The loopback
preview server still refuses this preview authority.

This is a staging capability. Gist remains production authority. No production
backend, source, writer model, sample count, publishing control or billing setting
is selected or changed by the new factory.

## Explicit inputs

`HostedStagingConfig.load` accepts an absolute private configuration path and a
separate trusted identity receipt. Both files must be regular, single-link,
owner-only files in a private directory. Symlinks, duplicate keys, extra fields,
ambient credentials and changes after loading are refused. The receipt binds the
exact project, branch, endpoint, direct hostname, database, role, purpose and CA
hash. A configuration cannot authorize its own destination.

Each connection rechecks those files and the CA. The connection requires port
5432, TLS hostname verification, channel binding and PostgreSQL 17. Client
certificates, ambient password files, services, generic connection strings,
poolers, GSS encryption and automatic acquisition retries are unavailable.
Client TLS is verified through libpq on the authenticated connection; database/user
identity is checked separately through SQL before repository operations. A
provider proxy can terminate client TLS while its internal backend connection
reports different `pg_stat_ssl` statistics. Backend-hop statistics do not replace
or weaken the required client certificate, hostname or channel-binding checks.
Errors expose
bounded codes rather than raw connection or SQL details.

The existing transaction profile remains Read Committed, with a protected search
path and synchronous commits. Hosted staging adds a five-second connection
bound, ten-second statement timeout, one-second lock timeout and fifteen-second
idle-transaction timeout. These are not a complete Python-operation deadline;
a separately supervised caller must provide that bound.

## Local validation

Tests create a separate ephemeral PostgreSQL 17 server with TLS and SCRAM. They
use invented role passwords and data. Only the test's port constant is redirected
to that server; the production port remains fixed and separately asserted.

The checks exercise actual command edits and approval invalidation, duplicate
commands, revision conflicts, limited-role denials, read-only and lock failures,
disconnect before commit, lost commit acknowledgement, six-station retained
supply, and fresh-process consumers/replay. The restore test transfers both real
application schemas with exact owners/grants, consumes one pending command once
on restore, and verifies that the original database remains unchanged.

Specific TLS negatives reach the owned server: a trusted certificate with the
wrong hostname, a valid unrelated CA, and a server with TLS disabled. They are
distinguished from generic network failures. Expired-certificate and real
provider-outage recovery are not claimed.

Fresh interpreter import-order checks and strict configuration adversaries cover
file permissions, links, duplicate fields, changed identity/CA, ambient secrets,
unsafe destination fields and password/key substitution formats.

## Acceptance limits

These are local TLS observations. They do not establish hosted user
authentication, deployment, a hosted database restore, observed scale-to-zero,
quota recovery, all-writer integration, object/media backup, a monthly spending
ceiling or production disaster recovery.

A staged rehearsal must pin the actual approved endpoint, use separate limited
SQL roles, preserve generated credentials durably before bootstrap mutations,
count every connection, supervise operations with a finite deadline, and keep
uncertain writes unknown until one original-identity read reconciles them. The
private execution packet supplies those controls and remains subject to
engineering review before hosted execution. No schema or role cleanup is an
automatic part of the adapter.
