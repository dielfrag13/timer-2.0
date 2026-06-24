"""
Unit tests for timer.serializers.

Covers:
- StepInstanceSerializer: computed dist_from_average, step_title, expected fields
- OperationInstanceSerializer: flat (no nested steps), expected fields
- OperationInstanceDetailSerializer: includes nested steps, expected fields
"""

import datetime

import pytest

from timer.models import OperationInstance, OperationType, Step, StepInstance, Surgeon
from timer.serializers import (
    OperationInstanceDetailSerializer,
    OperationInstanceSerializer,
    StepInstanceSerializer,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def surgeon():
    return Surgeon.objects.create(first_name="Jane", last_name="Smith", email="jane@example.com")


@pytest.fixture
def op_type():
    return OperationType.objects.create(operation_type="Knee Replacement")


@pytest.fixture
def step():
    return Step.objects.create(title="Incision")


@pytest.fixture
def op(surgeon, op_type):
    return OperationInstance.objects.create(
        surgeon=surgeon,
        operation_type=op_type,
        date=datetime.date(2024, 1, 1),
        in_room_time=datetime.time(8, 0),
    )


@pytest.fixture
def step_instance(op, step):
    return StepInstance.objects.create(
        step=step,
        operation_instance=op,
        order=0,
        start_time=datetime.time(8, 0),
        end_time=datetime.time(8, 30),
        elapsed_time=1800,
    )


class TestStepInstanceSerializer:
    def test_expected_fields(self, step_instance):
        data = StepInstanceSerializer(step_instance).data
        assert set(data.keys()) == {
            'id', 'step', 'step_title', 'order',
            'start_time', 'end_time', 'elapsed_time', 'dist_from_average',
        }

    def test_step_title_populated(self, step_instance):
        data = StepInstanceSerializer(step_instance).data
        assert data['step_title'] == 'Incision'

    def test_dist_from_average_none_when_no_history(self, step_instance):
        data = StepInstanceSerializer(step_instance).data
        assert data['dist_from_average'] is None

    def test_dist_from_average_none_when_elapsed_time_missing(self, op, step):
        si = StepInstance.objects.create(step=step, operation_instance=op, order=0)
        data = StepInstanceSerializer(si).data
        assert data['dist_from_average'] is None


class TestOperationInstanceSerializer:
    def test_expected_fields(self, op):
        data = OperationInstanceSerializer(op).data
        assert set(data.keys()) == {
            'id', 'operation_type', 'surgeon', 'date',
            'detail', 'in_room_time', 'complete', 'elapsed_time',
        }

    def test_excludes_nested_steps(self, op, step_instance):
        data = OperationInstanceSerializer(op).data
        assert 'steps' not in data


class TestOperationInstanceDetailSerializer:
    def test_expected_fields(self, op):
        data = OperationInstanceDetailSerializer(op).data
        assert set(data.keys()) == {
            'id', 'operation_type', 'surgeon', 'date',
            'detail', 'in_room_time', 'complete', 'elapsed_time', 'steps',
        }

    def test_includes_nested_steps(self, op, step_instance):
        data = OperationInstanceDetailSerializer(op).data
        assert len(data['steps']) == 1
        assert data['steps'][0]['step_title'] == 'Incision'

    def test_empty_steps_when_none_exist(self, op):
        data = OperationInstanceDetailSerializer(op).data
        assert data['steps'] == []
