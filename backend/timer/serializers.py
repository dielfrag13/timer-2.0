from rest_framework import serializers

from .models import OperationInstance, OperationType, Step, StepInstance, Surgeon
from .services import compute_dist_from_average


class SurgeonSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Surgeon
        fields = ['id', 'first_name', 'last_name', 'email', 'full_name']


class OperationTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationType
        fields = ['id', 'operation_type']


class StepSerializer(serializers.ModelSerializer):
    class Meta:
        model = Step
        fields = ['id', 'title']


class StepInstanceSerializer(serializers.ModelSerializer):
    step_title = serializers.CharField(source='step.title', read_only=True)
    elapsed_time = serializers.IntegerField(read_only=True)
    dist_from_average = serializers.SerializerMethodField()

    class Meta:
        model = StepInstance
        fields = [
            'id', 'step', 'step_title', 'order',
            'start_time', 'end_time', 'elapsed_time', 'dist_from_average',
        ]

    def get_dist_from_average(self, obj) -> float | None:
        return compute_dist_from_average(obj)


class OperationInstanceSerializer(serializers.ModelSerializer):
    """List and create. No nested steps — avoids N+1 on list views."""

    class Meta:
        model = OperationInstance
        fields = [
            'id', 'operation_type', 'surgeon', 'date', 'detail',
            'in_room_time', 'complete', 'elapsed_time',
        ]
        read_only_fields = ['elapsed_time']


class OperationInstanceDetailSerializer(serializers.ModelSerializer):
    """Retrieve, update, partial_update. Includes nested steps with dist_from_average."""

    steps = StepInstanceSerializer(many=True, read_only=True)

    class Meta:
        model = OperationInstance
        fields = [
            'id', 'operation_type', 'surgeon', 'date', 'detail',
            'in_room_time', 'complete', 'elapsed_time', 'steps',
        ]
        read_only_fields = ['elapsed_time']
