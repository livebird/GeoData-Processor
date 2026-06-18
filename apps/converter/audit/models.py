from converter.models import AuditLog as CoreAuditLog

class AuditLog(CoreAuditLog):
    class Meta:
        proxy = True
        app_label = 'audit'
        verbose_name = 'Audit log'
        verbose_name_plural = 'Audit logs'
