# Decision: Plugin foundation

## Question

Can SpeakerOps extend pretalx without carrying a fork or patching upstream?

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

## Decision and invariants

Use an AGPL-3.0 plugin package with plugin-owned models, migrations, views,
templates, and receivers. Pretalx remains an unmodified PyPI dependency and
submission/schedule ownership remains upstream.

## Upgrade, rollback, and security impact

An upgrade can break entry-point loading, plugin URL namespacing, metadata
discovery, or `Event` activation behavior. Re-audit those four symbols before
upgrading. Rollback is a plugin package rollback plus plugin migration rollback;
no upstream patch must be reverted. The repository records its derivative-
adjacent relationship and preserves upstream licensing.

## Automated proof

`tests/test_m1.py::test_golden_path_crosses_plugin_boundaries` boots the plugin
through Django and crosses its URL, receiver, model, and template boundaries.
