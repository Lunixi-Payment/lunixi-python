# Contributing

Preserve the existing fraud API while extending payment helpers. Use verified gateway contracts and official dependency/framework documentation. Keep payment evidence and retries in the common Commerce service; framework layers handle native authentication, CSRF, data ownership and atomic native updates.

Run the locked development environment, Ruff format/check, Mypy, Bandit, pip-audit, complete pytest suite and wheel/sdist checks. Native framework tests require the optional framework dependencies on Python 3.12+. Add failure/race tests for financial changes; do not merely mirror methods. Keep English/Turkish docs and original Lunixi assets synchronized. Never commit secrets, virtual environments, databases, certificates, local paths or built distributions. Synthetic fixture keys are explicitly marked and grant no access.
