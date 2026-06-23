from django.contrib import admin

from .models import OperationInstance, OperationType, Step, StepInstance, Surgeon


@admin.register(Surgeon)
class SurgeonAdmin(admin.ModelAdmin):
    pass


@admin.register(OperationType)
class OperationTypeAdmin(admin.ModelAdmin):
    pass


@admin.register(OperationInstance)
class OperationInstanceAdmin(admin.ModelAdmin):
    pass


@admin.register(Step)
class StepAdmin(admin.ModelAdmin):
    pass


@admin.register(StepInstance)
class StepInstanceAdmin(admin.ModelAdmin):
    pass
