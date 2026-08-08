class PretalxPluginMeta:
    name = "Speaker Operations"
    description = "Speaker and program operations extensions for pretalx."
    category = "FEATURE"
    visible = True
    version = "0.0.0"


class SpeakerOpsConfig:
    name = "pretalx_speakerops"
    label = "speakerops"
    verbose_name = "Speaker Operations"
    PretalxPluginMeta = PretalxPluginMeta

    def ready(self):
        from . import receivers  # noqa: F401
