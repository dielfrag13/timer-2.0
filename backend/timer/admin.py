from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import OperationInstance, OperationType, Step, StepInstance, Surgeon

User = get_user_model()


class SurgeonInline(admin.StackedInline):
    """
    Shown on the User change page so an admin can attach a Surgeon profile
    when creating a surgeon's login account. The OneToOneField lives on
    Surgeon, so Surgeon is the correct inline model here.
    """
    model = Surgeon
    can_delete = False
    verbose_name_plural = 'Surgeon profile'
    fields = ('first_name', 'last_name', 'email')
    extra = 0


class CustomUserAdmin(UserAdmin):
    inlines = [SurgeonInline]


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


@admin.register(Surgeon)
class SurgeonAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'linked_username')
    readonly_fields = ('linked_username',)

    def linked_username(self, obj):
        return obj.user.username if obj.user else '—'
    linked_username.short_description = 'Login account'


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
