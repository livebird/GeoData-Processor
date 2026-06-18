from django.apps import AppConfig


class ConverterConfig(AppConfig):
    name = 'converter'
    
    def ready(self):
        """Load signal handlers when app is ready"""
        import converter.signals
