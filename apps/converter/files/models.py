from converter.models import GeoFile as CoreGeoFile, GeoFileLayer as CoreGeoFileLayer

class GeoFile(CoreGeoFile):
    class Meta:
        proxy = True
        app_label = 'files'
        verbose_name = 'GeoFile'
        verbose_name_plural = 'GeoFiles'

class GeoFileLayer(CoreGeoFileLayer):
    class Meta:
        proxy = True
        app_label = 'files'
        verbose_name = 'GeoFileLayer'
        verbose_name_plural = 'GeoFileLayers'
