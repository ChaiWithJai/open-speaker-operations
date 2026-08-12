from django.contrib import admin

from .models import (
    AcceleventsConnection,
    CommandReceipt,
    ExternalIdentity,
    FieldMapping,
    OnboardingTask,
    OnboardingTemplate,
    OutboxEvent,
    PreviewRun,
    ReminderReceipt,
    Resource,
    ResourceVersion,
    ScheduleIcsIdentity,
    SyncAttempt,
    SyncItem,
    SyncPreview,
    SyncRun,
    TaskDefinition,
    TaskEvidence,
    TransitionLog,
    WorkflowActionReceipt,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CommandReceipt)
class CommandReceiptAdmin(ReadOnlyAdmin):
    list_display = ("event", "key", "command", "aggregate_type", "created_at")
    list_filter = ("event", "command")
    search_fields = ("key",)


@admin.register(WorkflowActionReceipt)
class WorkflowActionReceiptAdmin(ReadOnlyAdmin):
    list_display = (
        "event",
        "workflow",
        "status",
        "correlation_id",
        "actor",
        "confirmed_at",
    )
    list_filter = ("event", "workflow", "status")
    search_fields = ("correlation_id",)


@admin.register(TransitionLog)
class TransitionLogAdmin(ReadOnlyAdmin):
    list_display = ("event", "aggregate_type", "from_state", "to_state", "actor", "timestamp")
    list_filter = ("event",)


@admin.register(OutboxEvent)
class OutboxEventAdmin(ReadOnlyAdmin):
    list_display = ("event", "kind", "aggregate_type", "created", "processed")
    list_filter = ("event", "kind")


@admin.register(OnboardingTemplate)
class OnboardingTemplateAdmin(admin.ModelAdmin):
    list_display = ("event", "slug", "name", "active")


@admin.register(TaskDefinition)
class TaskDefinitionAdmin(admin.ModelAdmin):
    list_display = ("event", "template", "position", "slug", "name", "task_type", "active")
    list_filter = ("event", "active")


@admin.register(OnboardingTask)
class OnboardingTaskAdmin(admin.ModelAdmin):
    list_display = ("event", "speaker", "definition", "status", "due_date", "completed_at")
    list_filter = ("event", "status")


@admin.register(TaskEvidence)
class TaskEvidenceAdmin(ReadOnlyAdmin):
    list_display = ("event", "task", "speaker", "kind")


@admin.register(ReminderReceipt)
class ReminderReceiptAdmin(ReadOnlyAdmin):
    list_display = ("event", "task", "sent_at")


@admin.register(PreviewRun)
class PreviewRunAdmin(admin.ModelAdmin):
    list_display = ("event", "status", "created_at")


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("event", "slug", "title")


@admin.register(ResourceVersion)
class ResourceVersionAdmin(admin.ModelAdmin):
    list_display = ("event", "resource", "version", "published_at", "created_by")


@admin.register(ScheduleIcsIdentity)
class ScheduleIcsIdentityAdmin(ReadOnlyAdmin):
    list_display = ("event", "submission", "uid")


@admin.register(AcceleventsConnection)
class AcceleventsConnectionAdmin(admin.ModelAdmin):
    list_display = ("event", "base_url", "status")


@admin.register(FieldMapping)
class FieldMappingAdmin(admin.ModelAdmin):
    list_display = ("connection", "external_field", "local_field")


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(ReadOnlyAdmin):
    list_display = ("event", "local_type", "local_id", "external_id")


@admin.register(SyncPreview)
class SyncPreviewAdmin(ReadOnlyAdmin):
    list_display = ("event", "connection", "created_at")


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ("event", "status", "created_at")


@admin.register(SyncItem)
class SyncItemAdmin(admin.ModelAdmin):
    list_display = ("run", "action", "status", "external_id")
    list_filter = ("run", "status", "action")


@admin.register(SyncAttempt)
class SyncAttemptAdmin(ReadOnlyAdmin):
    list_display = ("item", "status", "attempt", "created_at")
