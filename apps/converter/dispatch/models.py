from converter.models import DispatchedLayer as CoreDispatchedLayer, DestinationCredential as CoreDestinationCredential

class DispatchedLayer(CoreDispatchedLayer):
    class Meta:
        proxy = True
        app_label = 'dispatch'
        verbose_name = 'Dispatched layer'
        verbose_name_plural = 'Dispatched layers'

class DestinationCredential(CoreDestinationCredential):
    class Meta:
        proxy = True
        app_label = 'dispatch'
        verbose_name = 'Destination credential'
        verbose_name_plural = 'Destination credentials'
