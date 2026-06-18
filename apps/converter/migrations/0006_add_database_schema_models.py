# Generated migration for complete database schema with safe handling of existing tables

from django.db import migrations, models


def create_models_if_not_exist(apps, schema_editor):
    """Log whether schema tables already exist (CreateModel ops still run below)."""
    tables_to_check = [
        'geo_files', 'geo_file_layers', 'workflows', 'geo_processing_jobs',
        'geo_processing_job_logs', 'dispatched_layers', 'destination_credentials',
        'audit_log', 'rbac_roles', 'rbac_permissions', 'rbac_role_permissions',
        'rbac_principal_roles', 'batch_table_details'
    ]
    existing_tables = {
        name.lower()
        for name in schema_editor.connection.introspection.table_names()
    }
    existing_our_tables = [t for t in tables_to_check if t.lower() in existing_tables]
    if existing_our_tables:
        print(f"Found existing tables: {existing_our_tables}")
    else:
        print("Creating new schema tables...")


class Migration(migrations.Migration):

    dependencies = [
        ('converter', '0005_conversionjob_prj_missing'),
    ]

    operations = [
        migrations.RunPython(create_models_if_not_exist),
        
        migrations.CreateModel(
            name='GeoFile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('org_id', models.IntegerField(blank=True, db_column='org_id', null=True)),
                ('original_file_name', models.CharField(db_column='original_file_name', max_length=260)),
                ('source_type', models.CharField(blank=True, db_column='source_type', default='', max_length=50)),
                ('source_url', models.URLField(blank=True, db_column='source_url', max_length=512, null=True)),
                ('file_type', models.CharField(blank=True, db_column='file_type', default='', max_length=50)),
                ('mime_type', models.CharField(blank=True, db_column='mime_type', default='', max_length=100)),
                ('storage_backend', models.CharField(blank=True, db_column='storage_backend', default='local', max_length=50)),
                ('storage_path', models.CharField(db_column='storage_path', max_length=512)),
                ('size_bytes', models.BigIntegerField(db_column='size_bytes', default=0)),
                ('checksum_sha256', models.CharField(blank=True, db_column='checksum_sha256', default='', max_length=64)),
                ('uploaded_by', models.IntegerField(blank=True, db_column='uploaded_by', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
                ('updated_at', models.DateTimeField(auto_now=True, db_column='updated_at')),
            ],
            options={
                'db_table': 'geo_files',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='GeoFileLayer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_id', models.IntegerField(db_column='file_id')),
                ('layer_name', models.CharField(db_column='layer_name', max_length=255)),
                ('geometry_type', models.CharField(blank=True, db_column='geometry_type', default='', max_length=50)),
                ('has_z', models.BooleanField(db_column='has_z', default=False)),
                ('has_m', models.BooleanField(db_column='has_m', default=False)),
                ('source_crs_epsg', models.CharField(blank=True, db_column='source_crs_epsg', default='', max_length=50)),
                ('source_crs_wkt', models.TextField(blank=True, db_column='source_crs_wkt', default='')),
                ('feature_count', models.IntegerField(blank=True, db_column='feature_count', null=True)),
                ('bbox', models.TextField(blank=True, db_column='bbox', default='')),
                ('fields', models.TextField(blank=True, db_column='fields', default='')),
                ('encoding', models.CharField(blank=True, db_column='encoding', default='utf-8', max_length=50)),
                ('metadata', models.TextField(blank=True, db_column='metadata', default='')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
            ],
            options={
                'db_table': 'geo_file_layers',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Workflow',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_column='code', max_length=100, unique=True)),
                ('name', models.CharField(db_column='name', max_length=255)),
                ('description', models.TextField(blank=True, db_column='description', default='')),
                ('destination_type', models.CharField(db_column='destination_type', max_length=100)),
                ('parameters_schema', models.TextField(blank=True, db_column='parameters_schema', default='')),
                ('preview_enabled', models.BooleanField(db_column='preview_enabled', default=False)),
                ('is_active', models.BooleanField(db_column='is_active', default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
            ],
            options={
                'db_table': 'workflows',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='GeoProcessingJob',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('org_id', models.IntegerField(blank=True, db_column='org_id', null=True)),
                ('workflow_code', models.CharField(db_column='workflow_code', max_length=100)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], db_column='status', default='pending', max_length=50)),
                ('priority', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], db_column='priority', default='medium', max_length=20)),
                ('idempotency_key', models.CharField(blank=True, db_column='idempotency_key', default='', max_length=255)),
                ('input_file_id', models.IntegerField(blank=True, db_column='input_file_id', null=True)),
                ('output_file_id', models.IntegerField(blank=True, db_column='output_file_id', null=True)),
                ('parameters', models.TextField(blank=True, db_column='parameters', default='')),
                ('progress_percent', models.IntegerField(db_column='progress_percent', default=0)),
                ('preview_ready', models.BooleanField(db_column='preview_ready', default=False)),
                ('preview_confirmed_at', models.DateTimeField(blank=True, db_column='preview_confirmed_at', null=True)),
                ('error_code', models.CharField(blank=True, db_column='error_code', default='', max_length=100)),
                ('error_message', models.TextField(blank=True, db_column='error_message', default='')),
                ('requested_by', models.IntegerField(blank=True, db_column='requested_by', null=True)),
                ('worker_id', models.CharField(blank=True, db_column='worker_id', default='', max_length=255)),
                ('started_at', models.DateTimeField(blank=True, db_column='started_at', null=True)),
                ('completed_at', models.DateTimeField(blank=True, db_column='completed_at', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
                ('updated_at', models.DateTimeField(auto_now=True, db_column='updated_at')),
            ],
            options={
                'db_table': 'geo_processing_jobs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='GeoProcessingJobLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_id', models.IntegerField(db_column='job_id')),
                ('log_level', models.CharField(choices=[('debug', 'Debug'), ('info', 'Info'), ('warning', 'Warning'), ('error', 'Error'), ('critical', 'Critical')], db_column='log_level', max_length=20)),
                ('message', models.TextField(db_column='message')),
                ('details', models.TextField(blank=True, db_column='details', default='')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
            ],
            options={
                'db_table': 'geo_processing_job_logs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='DispatchedLayer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('org_id', models.IntegerField(blank=True, db_column='org_id', null=True)),
                ('job_id', models.IntegerField(db_column='job_id')),
                ('target_system', models.CharField(db_column='target_system', max_length=100)),
                ('target_layer_id', models.CharField(db_column='target_layer_id', max_length=255)),
                ('target_endpoint', models.CharField(blank=True, db_column='target_endpoint', default='', max_length=512)),
                ('target_database_fingerprint', models.CharField(blank=True, db_column='target_database_fingerprint', default='', max_length=255)),
                ('payload_metadata', models.TextField(blank=True, db_column='payload_metadata', default='')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('dispatched', 'Dispatched'), ('confirmed', 'Confirmed'), ('failed', 'Failed')], db_column='status', default='pending', max_length=50)),
                ('response_code', models.IntegerField(blank=True, db_column='response_code', null=True)),
                ('response_message', models.TextField(blank=True, db_column='response_message', default='')),
                ('dispatched_at', models.DateTimeField(blank=True, db_column='dispatched_at', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
            ],
            options={
                'db_table': 'dispatched_layers',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='DestinationCredential',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('org_id', models.IntegerField(blank=True, db_column='org_id', null=True)),
                ('name', models.CharField(db_column='name', max_length=255)),
                ('target_type', models.CharField(db_column='target_type', max_length=100)),
                ('encrypted_secret', models.TextField(db_column='encrypted_secret')),
                ('metadata', models.TextField(blank=True, db_column='metadata', default='')),
                ('is_active', models.BooleanField(db_column='is_active', default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
                ('updated_at', models.DateTimeField(auto_now=True, db_column='updated_at')),
            ],
            options={
                'db_table': 'destination_credentials',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('org_id', models.IntegerField(blank=True, db_column='org_id', null=True)),
                ('actor_type', models.CharField(db_column='actor_type', max_length=50)),
                ('actor_id', models.IntegerField(db_column='actor_id')),
                ('action', models.CharField(choices=[('create', 'Create'), ('update', 'Update'), ('delete', 'Delete'), ('read', 'Read'), ('execute', 'Execute')], db_column='action', max_length=50)),
                ('resource_type', models.CharField(db_column='resource_type', max_length=100)),
                ('resource_id', models.CharField(db_column='resource_id', max_length=255)),
                ('details', models.TextField(blank=True, db_column='details', default='')),
                ('ip_address', models.GenericIPAddressField(blank=True, db_column='ip_address', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
            ],
            options={
                'db_table': 'audit_log',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='RbacRole',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_column='code', max_length=100, unique=True)),
                ('name', models.CharField(db_column='name', max_length=255)),
            ],
            options={
                'db_table': 'rbac_roles',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='RbacPermission',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_column='code', max_length=100, unique=True)),
            ],
            options={
                'db_table': 'rbac_permissions',
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='RbacRolePermission',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role_id', models.IntegerField(db_column='role_id')),
                ('permission_id', models.IntegerField(db_column='permission_id')),
            ],
            options={
                'db_table': 'rbac_role_permissions',
                'unique_together': {('role_id', 'permission_id')},
            },
        ),
        migrations.CreateModel(
            name='RbacPrincipalRole',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('principal_id', models.IntegerField(db_column='principal_id')),
                ('principal_type', models.CharField(choices=[('user', 'User'), ('group', 'Group'), ('org', 'Organization')], db_column='principal_type', max_length=50)),
                ('role_id', models.IntegerField(db_column='role_id')),
                ('org_id', models.IntegerField(blank=True, db_column='org_id', null=True)),
            ],
            options={
                'db_table': 'rbac_principal_roles',
                'unique_together': {('principal_id', 'principal_type', 'role_id', 'org_id')},
            },
        ),
        migrations.CreateModel(
            name='BatchTableDetails',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('table_name', models.CharField(db_column='table_name', max_length=255)),
                ('actual_table_name', models.CharField(db_column='actual_table_name', max_length=255)),
                ('org_id', models.IntegerField(blank=True, db_column='org_id', null=True)),
                ('actor_type', models.CharField(blank=True, db_column='actor_type', default='', max_length=50)),
                ('actor_id', models.IntegerField(blank=True, db_column='actor_id', null=True)),
                ('action', models.CharField(blank=True, db_column='action', default='', max_length=50)),
                ('resource_type', models.CharField(blank=True, db_column='resource_type', default='', max_length=100)),
                ('resource_id', models.CharField(blank=True, db_column='resource_id', default='', max_length=255)),
                ('details', models.TextField(blank=True, db_column='details', default='')),
                ('ipaddress', models.GenericIPAddressField(blank=True, db_column='ipaddress', null=True)),
                ('user_agent', models.CharField(blank=True, db_column='user_agent', default='', max_length=512)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
                ('name', models.CharField(blank=True, db_column='name', default='', max_length=255)),
                ('group_id', models.IntegerField(blank=True, db_column='group_id', null=True)),
                ('permission', models.CharField(blank=True, db_column='permission', default='', max_length=255)),
                ('content_type', models.CharField(blank=True, db_column='content_type', default='', max_length=100)),
                ('codename', models.CharField(blank=True, db_column='codename', default='', max_length=100)),
                ('void', models.BooleanField(db_column='void', default=False)),
                ('ondelete', models.CharField(blank=True, db_column='ondelete', default='CASCADE', max_length=50)),
                ('secret', models.TextField(blank=True, db_column='secret', default='')),
                ('app_label', models.CharField(blank=True, db_column='app_label', default='', max_length=100)),
                ('validation_domainid', models.CharField(blank=True, db_column='validation_domainid', default='', max_length=255)),
                ('name_id', models.IntegerField(blank=True, db_column='name_id', null=True)),
            ],
            options={
                'db_table': 'batch_table_details',
                'ordering': ['-created_at'],
            },
        ),
    ]
