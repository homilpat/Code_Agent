# `status` reports head_state UNRESOLVED for a healthy branch checkout

`kh status` on a repository whose HEAD is `ref: refs/heads/main` and whose branch ref resolves to
a valid object id (a loose `refs/heads/main` file or an entry in `packed-refs`) returns
`"head_state": "UNRESOLVED"`, even though `branch` and `declared_head_oid` are filled in.

`UNRESOLVED` is meant for a HEAD or ref that could not be resolved, so callers cannot tell a
healthy checkout apart from a missing ref.

Expected behaviour:

- HEAD is a symbolic ref to `refs/heads/<branch>` and that ref resolves: `head_state` is `NORMAL`.
- HEAD is a symbolic ref whose ref does not exist: `head_state` stays `UNRESOLVED`.
- HEAD is a raw object id (detached): `head_state` stays `DETACHED`.
- All existing validation and blocking behaviour is unchanged.
