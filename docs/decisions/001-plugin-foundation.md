# Decision: Plugin foundation

## Question

Can SpeakerOps extend pretalx without carrying a fork or patching upstream?

## Goal and architecture depth

The original goal is an open-source speaker/program-management clone that a
judge can walk through on a golden path and that we can keep upgrading before
the deadline. The pretalx-first decision was already made; this record decides
the coupling level: fork, PyPI plugin, or the clean-room fallback. It is the
highest-level architectural constraint in this series, not a local model or
view choice, so it was deliberately resolved before feature work.

## Baseline and evidence

The pinned dependency is `pretalx==2025.2.2`. In that package,
`pretalx/settings.py` loads `pretalx.plugin` entry points into
`INSTALLED_APPS`; `pretalx/urls.py` imports plugin `urls.urlpatterns` under the
`plugins` namespace; `pretalx/common/plugins.py:get_all_plugins()` discovers
metadata; and `pretalx/event/models/event.py:Event.plugin_list`,
`enable_plugin()`, and `disable_plugin()` provide event activation.

## Cheaper seams rejected

Configuration alone cannot add plugin models, URLs, templates, or lifecycle
behavior. A direct core patch would make the product dependent on a fork even
though the verified entry-point and Django-app seams already cover the need.
Vendoring pretalx would duplicate upstream security and migration work.

The fork would buy atomic reach into every upstream invariant, but would make
every upstream fix a merge, expand the review surface from this plugin to the
whole pretalx tree, and attach corresponding-source obligations to modified
upstream code. The plugin buys a small reviewable diff and cheap upgrades, but
cannot add a hook where pretalx has none. In particular, `pretalx/orga/signals.py`
has `nav_event`, `nav_global`, and `nav_event_settings`, but no speaker-area
navigation signal; that cost forced the separate URL decision in record 003.
Also, `pretalx/common/signals.py:EventPluginSignal._is_active()` gates signal
receivers only: `pretalx/urls.py` mounts plugin URLs unconditionally, so every
view must enforce activation and authorization itself.

## How the choice was made

The spike installed and booted `pretalx==2025.2.2`, activated the entry-point
plugin in an event, rendered its organiser URL, and verified navigation and
templates with a Django client. We also checked the installed source rather
than trusting a map. The quick heuristic was “configuration before plugin,
plugin before signal, signal before core patch”; the plugin passed the actual
boot/render test without requiring a fork. A failed environment attempt showed
Python 3.10 could not run this pretalx release, fixed with `uv` and Python 3.11.
`pretalx[test]` was also tried and rejected by the package metadata; `[dev]`
is the real extra. Finally, the PyPI wheel contains no upstream test fixtures,
so this repository hand-rolls factories. That is a standing cost, and the one
place a fork would have been cheaper.

## Decision and invariants

Use an AGPL-3.0 plugin package with plugin-owned models, migrations, views,
templates, and receivers. Pretalx remains an unmodified PyPI dependency and
submission/schedule ownership remains upstream.

## Upgrade, rollback, and security impact

The plugin choice did not come for free: missing speaker navigation, un-gated
URLs, hand-rolled fixtures, and inability to patch an upstream transaction are
ongoing costs. An upgrade can break entry-point loading, plugin URL namespacing,
metadata discovery, or `Event` activation behavior. Re-audit those four symbols
before upgrading. Rollback is a plugin package rollback plus plugin migration
rollback; no upstream patch must be reverted. The repository records its
derivative-adjacent relationship and preserves upstream licensing.

## Automated proof

`tests/test_m1.py::test_golden_path_crosses_plugin_boundaries` boots the plugin
through Django and crosses its URL, receiver, model, and template boundaries.
