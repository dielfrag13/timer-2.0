import datetime

from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower


class Surgeon(models.Model):
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(max_length=254, unique=True)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return self.full_name

    class Meta:
        constraints = [
            UniqueConstraint(
                Lower('first_name'),
                Lower('last_name'),
                name='unique_surgeon_name_ci',
            )
        ]


class OperationType(models.Model):
    operation_type = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.operation_type

    class Meta:
        constraints = [
            UniqueConstraint(
                Lower('operation_type'),
                name='unique_operation_type_ci',
            )
        ]


class OperationInstance(models.Model):
    operation_type = models.ForeignKey(OperationType, on_delete=models.CASCADE)
    surgeon = models.ForeignKey(Surgeon, on_delete=models.CASCADE)
    date = models.DateField()
    detail = models.TextField(max_length=500, blank=True)
    in_room_time = models.TimeField(null=True, blank=True)
    complete = models.BooleanField(default=False)
    elapsed_time = models.IntegerField(null=True, blank=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.elapsed_time and self.steps.exists():
            first = self.steps.first()
            last = self.steps.last()
            if first.start_time and last.end_time:
                st = datetime.datetime.combine(datetime.date.today(), first.start_time)
                et = datetime.datetime.combine(datetime.date.today(), last.end_time)
                self.elapsed_time = (et - st).seconds
                super().save(update_fields=['elapsed_time'])

    def __str__(self):
        return f"{self.operation_type} — {self.date}"


class Step(models.Model):
    title = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.title

    class Meta:
        constraints = [
            UniqueConstraint(
                Lower('title'),
                name='unique_step_title_ci',
            )
        ]


class StepInstance(models.Model):
    step = models.ForeignKey(Step, on_delete=models.CASCADE, related_name='instances')
    operation_instance = models.ForeignKey(
        OperationInstance, on_delete=models.CASCADE, related_name='steps'
    )
    order = models.PositiveIntegerField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    elapsed_time = models.IntegerField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.elapsed_time and self.start_time and self.end_time:
            st = datetime.datetime.combine(datetime.date.today(), self.start_time)
            et = datetime.datetime.combine(datetime.date.today(), self.end_time)
            self.elapsed_time = (et - st).seconds
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.step.title} ({self.operation_instance})"

    class Meta:
        ordering = ['order']
