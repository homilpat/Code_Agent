# One deleted repository breaks every command once a policy file exists

When `policy/security.yaml` exists in the trusted store, commands load it with
`load_policy(trusted_root, repository_roots)`, passing the root of every registered repository.
If any registered repository has since been deleted or moved, every command fails with
`INVALID_INPUT_OR_ENVIRONMENT`, including commands for other, healthy repositories.

The repository roots are only passed so that a trusted store located inside a repository is
refused. A root that no longer exists cannot contain the store.

Expected behaviour:

- `load_policy` ignores registered repository roots that no longer exist and continues loading.
- A trusted store inside an existing registered repository is still refused with
  `ACCESS_DENIED`, regardless of the order of the repository roots.
