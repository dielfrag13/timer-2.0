"""
Unit tests for timer.services.

Covers:
- compute_dist_from_average: no history, correct percentage, scoping rules
- get_suggested_steps: personal history, cross-surgeon fallback, empty fallback
- complete_operation: happy path, all guard clauses, sequential time validation
"""

import datetime

import pytest

from timer.models import OperationInstance, OperationType, Step, StepInstance, Surgeon
from timer.services import complete_operation, compute_dist_from_average, get_suggested_steps

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def surgeon():
    return Surgeon.objects.create(first_name="Jane", last_name="Smith", email="jane@example.com")


@pytest.fixture
def other_surgeon():
    return Surgeon.objects.create(first_name="Bob", last_name="Jones", email="bob@example.com")


@pytest.fixture
def op_type():
    return OperationType.objects.create(operation_type="Knee Replacement")


@pytest.fixture
def other_op_type():
    return OperationType.objects.create(operation_type="Hip Replacement")


@pytest.fixture
def step_incision():
    return Step.objects.create(title="Incision")


@pytest.fixture
def step_closure():
    return Step.objects.create(title="Closure")


def make_op(surgeon, op_type, complete=False, in_room_time=None, date=None):
    return OperationInstance.objects.create(
        surgeon=surgeon,
        operation_type=op_type,
        date=date or datetime.date(2024, 1, 1),
        complete=complete,
        in_room_time=in_room_time,
    )


def make_si(op, step, order=0, start_time=None, end_time=None, elapsed_time=None):
    return StepInstance.objects.create(
        step=step,
        operation_instance=op,
        order=order,
        start_time=start_time,
        end_time=end_time,
        elapsed_time=elapsed_time,
    )


# ---------------------------------------------------------------------------
# compute_dist_from_average
# ---------------------------------------------------------------------------

class TestComputeDistFromAverage:
    def test_returns_none_when_elapsed_time_missing(self, surgeon, op_type, step_incision):
        op = make_op(surgeon, op_type, complete=True)
        si = make_si(op, step_incision, elapsed_time=None)
        assert compute_dist_from_average(si) is None

    def test_returns_none_when_no_history(self, surgeon, op_type, step_incision):
        op = make_op(surgeon, op_type, complete=True)
        si = make_si(op, step_incision, elapsed_time=120)
        assert compute_dist_from_average(si) is None

    def test_positive_when_slower_than_average(self, surgeon, op_type, step_incision):
        hist_op = make_op(surgeon, op_type, complete=True)
        make_si(hist_op, step_incision, elapsed_time=100)

        current_op = make_op(surgeon, op_type, complete=True)
        current_si = make_si(current_op, step_incision, elapsed_time=150)

        assert compute_dist_from_average(current_si) == pytest.approx(50.0)

    def test_negative_when_faster_than_average(self, surgeon, op_type, step_incision):
        hist_op = make_op(surgeon, op_type, complete=True)
        make_si(hist_op, step_incision, elapsed_time=100)

        current_op = make_op(surgeon, op_type, complete=True)
        current_si = make_si(current_op, step_incision, elapsed_time=80)

        assert compute_dist_from_average(current_si) == pytest.approx(-20.0)

    def test_averages_multiple_historical_records(self, surgeon, op_type, step_incision):
        for elapsed in [100, 200]:
            op = make_op(surgeon, op_type, complete=True)
            make_si(op, step_incision, elapsed_time=elapsed)

        current_op = make_op(surgeon, op_type, complete=True)
        current_si = make_si(current_op, step_incision, elapsed_time=150)

        assert compute_dist_from_average(current_si) == pytest.approx(0.0)

    def test_excludes_different_surgeon(self, surgeon, other_surgeon, op_type, step_incision):
        other_op = make_op(other_surgeon, op_type, complete=True)
        make_si(other_op, step_incision, elapsed_time=100)

        current_op = make_op(surgeon, op_type, complete=True)
        current_si = make_si(current_op, step_incision, elapsed_time=150)

        assert compute_dist_from_average(current_si) is None

    def test_excludes_different_operation_type(self, surgeon, op_type, other_op_type, step_incision):
        other_op = make_op(surgeon, other_op_type, complete=True)
        make_si(other_op, step_incision, elapsed_time=100)

        current_op = make_op(surgeon, op_type, complete=True)
        current_si = make_si(current_op, step_incision, elapsed_time=150)

        assert compute_dist_from_average(current_si) is None

    def test_excludes_incomplete_operations(self, surgeon, op_type, step_incision):
        incomplete_op = make_op(surgeon, op_type, complete=False)
        make_si(incomplete_op, step_incision, elapsed_time=100)

        current_op = make_op(surgeon, op_type, complete=True)
        current_si = make_si(current_op, step_incision, elapsed_time=150)

        assert compute_dist_from_average(current_si) is None


# ---------------------------------------------------------------------------
# get_suggested_steps
# ---------------------------------------------------------------------------

class TestGetSuggestedSteps:
    def test_returns_empty_when_no_history(self, surgeon, op_type):
        op = make_op(surgeon, op_type)
        assert list(get_suggested_steps(op)) == []

    def test_priority_1_same_surgeon_same_type(
        self, surgeon, other_surgeon, op_type, step_incision, step_closure
    ):
        ref_op = make_op(surgeon, op_type, complete=True)
        make_si(ref_op, step_incision, order=0)
        make_si(ref_op, step_closure, order=1)

        other_op = make_op(other_surgeon, op_type, complete=True)
        make_si(other_op, step_incision, order=0)

        new_op = make_op(surgeon, op_type)
        assert list(get_suggested_steps(new_op)) == [step_incision, step_closure]

    def test_priority_2_falls_back_to_any_surgeon(
        self, surgeon, other_surgeon, op_type, step_incision, step_closure
    ):
        ref_op = make_op(other_surgeon, op_type, complete=True)
        make_si(ref_op, step_incision, order=0)
        make_si(ref_op, step_closure, order=1)

        new_op = make_op(surgeon, op_type)
        assert list(get_suggested_steps(new_op)) == [step_incision, step_closure]

    def test_returns_steps_in_order(self, surgeon, op_type, step_incision, step_closure):
        ref_op = make_op(surgeon, op_type, complete=True)
        make_si(ref_op, step_closure, order=0)
        make_si(ref_op, step_incision, order=1)

        new_op = make_op(surgeon, op_type)
        assert list(get_suggested_steps(new_op)) == [step_closure, step_incision]

    def test_excludes_incomplete_operations(self, surgeon, op_type, step_incision):
        incomplete_op = make_op(surgeon, op_type, complete=False)
        make_si(incomplete_op, step_incision, order=0)

        new_op = make_op(surgeon, op_type)
        assert list(get_suggested_steps(new_op)) == []


# ---------------------------------------------------------------------------
# complete_operation
# ---------------------------------------------------------------------------

class TestCompleteOperation:
    def test_happy_path(self, surgeon, op_type, step_incision, step_closure):
        op = make_op(surgeon, op_type, in_room_time=datetime.time(8, 0))
        si1 = make_si(op, step_incision, order=0, end_time=datetime.time(8, 30))
        si2 = make_si(op, step_closure, order=1, end_time=datetime.time(9, 0))

        complete_operation(op)

        op.refresh_from_db()
        si1.refresh_from_db()
        si2.refresh_from_db()

        assert op.complete is True
        assert op.elapsed_time == 3600

        assert si1.start_time == datetime.time(8, 0)
        assert si1.elapsed_time == 1800

        assert si2.start_time == datetime.time(8, 30)
        assert si2.elapsed_time == 1800

    def test_raises_if_already_complete(self, surgeon, op_type):
        op = make_op(surgeon, op_type, complete=True, in_room_time=datetime.time(8, 0))
        with pytest.raises(ValueError, match="already complete"):
            complete_operation(op)

    def test_raises_if_no_in_room_time(self, surgeon, op_type):
        op = make_op(surgeon, op_type)
        with pytest.raises(ValueError, match="in_room_time"):
            complete_operation(op)

    def test_raises_if_no_steps(self, surgeon, op_type):
        op = make_op(surgeon, op_type, in_room_time=datetime.time(8, 0))
        with pytest.raises(ValueError, match="no steps"):
            complete_operation(op)

    def test_raises_if_step_missing_end_time(self, surgeon, op_type, step_incision):
        op = make_op(surgeon, op_type, in_room_time=datetime.time(8, 0))
        make_si(op, step_incision, order=0, end_time=None)
        with pytest.raises(ValueError, match="Missing end time"):
            complete_operation(op)

    def test_raises_if_end_times_equal(self, surgeon, op_type, step_incision, step_closure):
        op = make_op(surgeon, op_type, in_room_time=datetime.time(8, 0))
        make_si(op, step_incision, order=0, end_time=datetime.time(8, 30))
        make_si(op, step_closure, order=1, end_time=datetime.time(8, 30))
        with pytest.raises(ValueError, match="end time must be after"):
            complete_operation(op)

    def test_raises_if_end_times_decreasing(self, surgeon, op_type, step_incision, step_closure):
        op = make_op(surgeon, op_type, in_room_time=datetime.time(8, 0))
        make_si(op, step_incision, order=0, end_time=datetime.time(8, 30))
        make_si(op, step_closure, order=1, end_time=datetime.time(8, 15))
        with pytest.raises(ValueError, match="end time must be after"):
            complete_operation(op)
