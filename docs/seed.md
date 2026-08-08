# SpeakerOps demo seed

Run after migrations:

```bash
PRETALX_CONFIG_FILE="$PWD/pretalx.cfg" \
  .venv/bin/python -m pretalx speakerops_seed
```

The command is idempotent and creates `speakerops-demo`, demo accounts, varied
pretalx proposal/review/schedule data, plugin onboarding work, and a recorded
mock Accelevents preview.

Demo credentials use the password `speakerops-demo`:

- `admin@example.org` — administrator
- `chair@example.org` — program chair
- `reviewer@example.org` — reviewer
- `speaker@example.org` — speaker

The integration record is a preview-only stub. No external credentials or
network calls are made.
