# Samples

Each sample reads its settings from the environment, so no credential is
written into a file in this repository.

```bash
export LUNIXI_BASE_URL="https://api.lunixi.com"
export LUNIXI_KEY_ID="kid_..."
export LUNIXI_PRIVATE_KEY_FILE="/secure/path/lunixi-private-key.pem"
```

| Sample | What it shows |
|---|---|
| `06-fraud/standalone_decision.py` | Ask whether one card payment is fraudulent, then branch on all four outcomes. |
| `06-fraud/event_feed.py` | Record events singly and in a batch, including deduplication and partial failure. |
| `06-fraud/read_decision_logs.py` | Read stored decisions and follow the cursor. |
| `06-fraud/verify_webhook.py` | Verify a captured webhook from stdin, fail-closed. |

```bash
python samples/06-fraud/standalone_decision.py
```

These call a live account, so they consume quota and write real events. Run
them against a test key.
