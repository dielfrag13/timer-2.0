import csv
import logging

from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import OperationInstance, OperationType, Step, StepInstance, Surgeon
from .serializers import (
    OperationInstanceDetailSerializer,
    OperationInstanceSerializer,
    OperationTypeSerializer,
    StepInstanceSerializer,
    StepSerializer,
    SurgeonSerializer,
)
from .services import complete_operation, compute_dist_from_average, get_suggested_steps

audit_logger = logging.getLogger('timer.audit')


class SurgeonViewSet(viewsets.ModelViewSet):
    queryset = Surgeon.objects.all().order_by('last_name', 'first_name')
    serializer_class = SurgeonSerializer
    filterset_fields = ['email']


class OperationTypeViewSet(viewsets.ModelViewSet):
    queryset = OperationType.objects.all().order_by('operation_type')
    serializer_class = OperationTypeSerializer


class StepViewSet(viewsets.ModelViewSet):
    queryset = Step.objects.all().order_by('title')
    serializer_class = StepSerializer


class StepInstanceViewSet(viewsets.ModelViewSet):
    queryset = (
        StepInstance.objects
        .select_related('step', 'operation_instance')
        .order_by('operation_instance', 'order')
    )
    serializer_class = StepInstanceSerializer
    filterset_fields = ['operation_instance']


class OperationInstanceViewSet(viewsets.ModelViewSet):
    queryset = (
        OperationInstance.objects
        .select_related('operation_type', 'surgeon')
        .prefetch_related('steps__step')
        .order_by('-date', '-pk')
    )
    filterset_fields = ['surgeon', 'operation_type', 'complete']

    def get_serializer_class(self):
        if self.action in ('retrieve', 'update', 'partial_update'):
            return OperationInstanceDetailSerializer
        return OperationInstanceSerializer

    @action(detail=True, methods=['get'], url_path='suggested-steps')
    def suggested_steps(self, request, pk=None):
        op_inst = self.get_object()
        steps = get_suggested_steps(op_inst)
        return Response(StepSerializer(steps, many=True).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        op_inst = self.get_object()
        try:
            complete_operation(op_inst)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        op_inst.refresh_from_db()
        # M3 will add request.user.id here once auth is in place
        audit_logger.info(
            'operation_complete',
            extra={
                'operation_instance_id': op_inst.pk,
                'surgeon_id': op_inst.surgeon_id,
                'operation_type': op_inst.operation_type.operation_type,
            },
        )
        return Response(OperationInstanceDetailSerializer(op_inst).data)

    @action(detail=True, methods=['get'], url_path='export-csv')
    def export_csv(self, request, pk=None):
        op_inst = self.get_object()
        filename = f"{op_inst.operation_type.operation_type}_{op_inst.date}.csv"
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow(['Step', 'Start Time', 'End Time', 'Elapsed Time (s)', 'Dist from Average (%)'])
        for step_inst in op_inst.steps.select_related('step').all():
            dist = compute_dist_from_average(step_inst)
            writer.writerow([
                step_inst.step.title,
                step_inst.start_time or '',
                step_inst.end_time or '',
                step_inst.elapsed_time or '',
                f"{dist:.2f}" if dist is not None else 'N/A',
            ])

        return response
