# PyPI publication

The existing Trusted Publisher is unchanged: **Lunixi-Payment/lunixi-python**,
workflow **publish.yml**, environment **pypi**, project **lunixi-sdk**. No new
publisher grant, account, API token or security-policy change is required by this
workflow update. It continues to publish with the existing GitHub OIDC identity.

The public workflow is exported from the repository's publication template to
`.github/workflows/publish.yml`. Include the hardened workflow in the source
release **before creating its immutable tag**; it must also exist on the default
branch for manual dispatch.

For a manual **0.2.1** publication, select **tag v0.2.1** in the GitHub Actions
workflow dispatch ref selector and enter **v0.2.1** in the `tag` input. Selecting
`main` while entering a release tag now fails deliberately. An existing GitHub
Release publication event remains supported, but its payload tag, invocation
ref and SHA must all identify that same release commit. Wait for the source
commit's normal CI checks before publishing; this workflow does not rerun the
SDK/framework suite.

The builder validates a numeric tag, resolves the public tag to a full commit
SHA, compares it with the invocation SHA, and checks out that immutable SHA.
The package must still be named `lunixi-sdk`, and its metadata version must
match the tag. The existing build, Twine checks and wheel/sdist upload/download
path are retained. A separate public receipt records their exact SHA256 hashes
and source identity; the publisher verifies those same downloaded bytes before
uploading. Receipts are not sent to the package index as distribution files.

Only the separate `pypi` publishing job has `id-token: write`. It does not check
out or execute SDK source. The official PyPA action is pinned to verified
**v1.14.3 / 7245906fb61fa33a13554f9d5fb856fe61758086**; PEP740 attestations remain
enabled. The action's publisher identity and attestations belong to the actual
invocation, which is why a manual main invocation cannot build a different tag.

A successful source tag or Actions artifact is not itself a registry release.
After publication, verify the exact version, wheel/sdist integrity and PyPI
attestations through the public registry. Existing files are not overwritten;
this workflow does not enable `skip-existing` or change publisher authorization.

- [PyPI: using an existing Trusted Publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
- [PyPI: producing attestations](https://docs.pypi.org/attestations/producing-attestations/)
- [Pinned official PyPA action](https://github.com/pypa/gh-action-pypi-publish/tree/7245906fb61fa33a13554f9d5fb856fe61758086)
