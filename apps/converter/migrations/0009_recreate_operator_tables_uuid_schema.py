"""Recreate operator-panel tables so PostgreSQL matches UUID-based models.

Migration 0006 created integer primary keys; 0007 altered Django state to UUID
but PostgreSQL PK types were not updated. Tables are empty, so drop + recreate.
"""

from django.db import migrations

DROP_ORDER = [
    'dispatched_layers',
    'geo_processing_job_logs',
    'geo_processing_jobs',
    'geo_file_layers',
    'rbac_principal_roles',
    'rbac_role_permissions',
    'destination_credentials',
    'audit_log',
    'workflows',
    'geo_files',
    'rbac_permissions',
    'rbac_roles',
    'batch_table_details',
]

CREATE_ORDER = [
    'GeoFile',
    'Workflow',
    'RbacRole',
    'RbacPermission',
    'GeoFileLayer',
    'GeoProcessingJob',
    'GeoProcessingJobLog',
    'DispatchedLayer',
    'RbacRolePermission',
    'RbacPrincipalRole',
    'DestinationCredential',
    'AuditLog',
    'BatchTableDetails',
]


def recreate_operator_tables(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        for table in DROP_ORDER:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')

    for model_name in CREATE_ORDER:
        model = apps.get_model('converter', model_name)
        schema_editor.create_model(model)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('converter', '0008_alter_geofile_source_type'),
    ]

    operations = [
        migrations.RunPython(recreate_operator_tables, noop_reverse),
    ]
