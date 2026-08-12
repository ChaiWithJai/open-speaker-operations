import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings


@pytest.mark.django_db
@override_settings(MIGRATION_MODULES={})
def test_plugin_migration_graph_is_consistent():
    loader = MigrationLoader(connection, ignore_no_migrations=True)

    assert ("speakerops", "0026_speakeroperationsprofile_headshot_metadata") in loader.graph.nodes
    assert ("speakerops", "0027_workflowactionreceipt") in loader.graph.nodes
    assert not loader.detect_conflicts()
