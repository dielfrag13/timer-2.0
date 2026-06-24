"""
Business logic for the timer app.

Functions here are kept separate from views so they can be tested independently
and reused across API actions without coupling to HTTP concerns.
"""

import datetime

from .models import OperationInstance, Step, StepInstance


def compute_dist_from_average(step_instance) -> float | None:
    """
    Return how far this step's elapsed time deviates from the surgeon's
    historical average for the same step in the same operation type.

    Scoping rules (matches Timer 1.0 behaviour):
    - Same step title
    - Same surgeon
    - Same operation type
    - Completed operations only
    - The current step instance is excluded so it doesn't skew its own result

    Returns a float percentage (positive = above/slower, negative = below/faster),
    or None when there is no history or elapsed_time is not yet recorded.
    """
    if step_instance.elapsed_time is None:
        return None

    historical_times = list(
        StepInstance.objects
        .filter(
            step__title=step_instance.step.title,
            operation_instance__surgeon=step_instance.operation_instance.surgeon,
            operation_instance__operation_type=step_instance.operation_instance.operation_type,
            operation_instance__complete=True,
            elapsed_time__isnull=False,
        )
        .exclude(pk=step_instance.pk)
        .values_list('elapsed_time', flat=True)
    )

    if not historical_times:
        return None

    avg = sum(historical_times) / len(historical_times)

    if avg == 0:
        return None

    return ((step_instance.elapsed_time - avg) / avg) * 100


def get_suggested_steps(operation_instance) -> 'QuerySet[Step]':
    """
    Return an ordered list of Steps to pre-populate the step list for a new
    operation, based on prior history.

    Resolution order:
    1. Most recent completed operation by the same surgeon of the same type.
    2. Most recent completed operation of the same type by any surgeon.
    3. Empty queryset if no history exists.
    """
    ref_op = (
        OperationInstance.objects
        .filter(
            surgeon=operation_instance.surgeon,
            operation_type=operation_instance.operation_type,
            complete=True,
        )
        .exclude(pk=operation_instance.pk)
        .order_by('-date', '-pk')
        .first()
    )

    if ref_op is None:
        ref_op = (
            OperationInstance.objects
            .filter(
                operation_type=operation_instance.operation_type,
                complete=True,
            )
            .exclude(pk=operation_instance.pk)
            .order_by('-date', '-pk')
            .first()
        )

    if ref_op is None:
        return Step.objects.none()

    return (
        Step.objects
        .filter(instances__operation_instance=ref_op)
        .order_by('instances__order')
    )


def complete_operation(operation_instance) -> None:
    """
    Validate and finalise an operation:
    - in_room_time must be set
    - All steps must have an end_time
    - Step end_times must be strictly increasing
    - Computes start_time and elapsed_time for each StepInstance
    - Sets elapsed_time and complete=True on the OperationInstance

    Raises ValueError with a descriptive message if any validation fails.
    """
    if operation_instance.complete:
        raise ValueError("Operation is already complete.")

    if not operation_instance.in_room_time:
        raise ValueError("Operation has not been started (in_room_time is not set).")

    steps = list(
        operation_instance.steps
        .select_related('step')
        .order_by('order')
    )

    if not steps:
        raise ValueError("Operation has no steps.")

    missing = [s.step.title for s in steps if not s.end_time]
    if missing:
        raise ValueError(f"Missing end time for: {', '.join(missing)}.")

    for i in range(1, len(steps)):
        if steps[i].end_time <= steps[i - 1].end_time:
            raise ValueError(
                f"'{steps[i].step.title}' end time must be after "
                f"'{steps[i - 1].step.title}' end time."
            )

    today = datetime.date.today()
    current_start = operation_instance.in_room_time
    for step in steps:
        step.start_time = current_start
        st = datetime.datetime.combine(today, current_start)
        et = datetime.datetime.combine(today, step.end_time)
        step.elapsed_time = int((et - st).total_seconds())
        current_start = step.end_time
        step.save(update_fields=['start_time', 'elapsed_time'])

    st = datetime.datetime.combine(today, steps[0].start_time)
    et = datetime.datetime.combine(today, steps[-1].end_time)
    operation_instance.elapsed_time = int((et - st).total_seconds())
    operation_instance.complete = True
    operation_instance.save(update_fields=['elapsed_time', 'complete'])
