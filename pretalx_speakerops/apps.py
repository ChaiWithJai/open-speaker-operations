from django.apps import AppConfig

from . import PretalxPluginMeta


class SpeakerOpsConfig(AppConfig):
    name = "pretalx_speakerops"
    label = "speakerops"
    verbose_name = "Speaker Operations"
    PretalxPluginMeta = PretalxPluginMeta

    def ready(self):
        from . import receivers  # noqa: F401
