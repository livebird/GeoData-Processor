from converter.models import Workflow as CoreWorkflow, GeoProcessingJob, GeoProcessingJobLog

class Workflow(CoreWorkflow):
    class Meta:
        proxy = True
        app_label = 'workflows'
        verbose_name = 'Workflow'
        verbose_name_plural = 'Workflows'

class Job(GeoProcessingJob):
    class Meta:
        proxy = True
        app_label = 'workflows'
        verbose_name = 'Job'
        verbose_name_plural = 'Jobs'

class JobLog(GeoProcessingJobLog):
    class Meta:
        proxy = True
        app_label = 'workflows'
        verbose_name = 'Job log'
        verbose_name_plural = 'Job logs'
