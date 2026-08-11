# Buzz workflows: verified behavior and known limitations

Verified against the `buzz` CLI on a relay running the `buzz-wiki` demo stack
(`ghcr.io/block/buzz:main`, August 2026). Everything below was exercised with
the official CLI and HTTP surface only.

## Verified working

| Surface | Result |
| --- | --- |
| `workflows create` / `list` / `get` | Work across all four trigger types |
| `workflows update` | Round-trips; `get` reflects the new YAML |
| `workflows trigger` (manual) + `--inputs` | Creates a run; actions execute |
| Trigger: `message_posted` | Fires on kind-40 messages (filter must evaluate true) |
| Trigger: `reaction_added` | Fires on kind-7 reactions (with/without `emoji` gate) |
| Trigger: `schedule` | Fires via cron/interval; manual trigger also works |
| Trigger: `webhook` | `POST /hooks/{id}` with `x-webhook-secret`; bad secret → 401 |
| Action: `send_message` | Posts to the workflow channel |
| Action: `delay` | Pauses then continues (verified 2s step) |
| Action: `call_webhook` | Rejected at save/run for non-owner/non-admin (SEC-006) |
| `workflows delete` | Removes the DB row; the workflow stops firing |

## Trigger filter syntax (important)

Message filters are evalexpr expressions over flat variables. Use the
function form — the `contains` operator is not accepted and silently skips
the run:

```yaml
trigger:
  on: message_posted
  filter: str_contains(trigger_text, "!wf-echo")
```

Available variables (from `buzz-workflow` executor): `trigger_text`,
`trigger_author`, `trigger_channel_id`, `trigger_timestamp`, `trigger_emoji`,
`trigger_message_id`.

## Known limitations (do not workaround — fix upstream)

| Item | Status |
| --- | --- |
| `workflows runs` | CLI returns `[]` by design: run history lives in the DB (`workflow_runs`), not emitted as Nostr events. Needs a real endpoint. |
| Action: `add_reaction` | Broken: posts to `/api/messages/{id}/reactions`, which the relay never exposes → 404. Should submit a kind-7 event instead. |
| Action: `send_dm` | `action not implemented: SendDm` |
| Action: `set_channel_topic` | `action not implemented: SetChannelTopic` |
| Action: `request_approval` | `approval gates not yet implemented — see WF-08` |
| `workflows get`/`list` after delete | Can still surface a ghost workflow from the event store after the DB row is gone |

These are product gaps in the buzz source, not environment issues. Workflow
steps that need them should be held until the upstream actions land.
