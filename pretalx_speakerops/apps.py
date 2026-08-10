from django.apps import AppConfig

from . import PretalxPluginMeta


class SpeakerOpsConfig(AppConfig):
    name = "pretalx_speakerops"
    label = "speakerops"
    verbose_name = "Speaker Operations"
    PretalxPluginMeta = PretalxPluginMeta

    def ready(self):
        from pretalx.cfp.flow import QuestionsStep

        from . import (
            receivers,  # noqa: F401
            tasks,  # noqa: F401
        )
        from .cfp import SpeakerOpsQuestionsForm
        from .cfp_lock import install_closed_cfp_guards
        from .program import policy  # noqa: F401

        # Keep pretalx's mature CFP flow and replace only its questions form class.
        # The subclass is a no-op for events without this plugin or persisted rules.
        QuestionsStep.form_class = SpeakerOpsQuestionsForm
        install_closed_cfp_guards()
