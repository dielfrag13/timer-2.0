import csv
import logging

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

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


def _get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

class AuditedTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        username = request.data.get('username', '')
        ip = _get_client_ip(request)
        try:
            response = super().post(request, *args, **kwargs)
        except Exception:
            audit_logger.warning('login_failure', extra={'username': username, 'ip': ip})
            raise
        try:
            user = get_user_model().objects.get(username=username)
            user_id = user.id
        except get_user_model().DoesNotExist:
            user_id = None
        audit_logger.info('login_success', extra={'username': username, 'user_id': user_id, 'ip': ip})
        return response


class LogoutView(APIView):
    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'detail': 'Refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        audit_logger.info('logout', extra={'user_id': request.user.id, 'ip': _get_client_ip(request)})
        return Response(status=status.HTTP_204_NO_CONTENT)


class _AdminWriteOnlyMixin:
    """Read access for any authenticated user; write access for admin only."""

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [IsAuthenticated()]
        return [IsAdminUser()]


class SurgeonViewSet(_AdminWriteOnlyMixin, viewsets.ModelViewSet):
    queryset = Surgeon.objects.all().order_by('last_name', 'first_name')
    serializer_class = SurgeonSerializer
    filterset_fields = ['email']


class OperationTypeViewSet(_AdminWriteOnlyMixin, viewsets.ModelViewSet):
    queryset = OperationType.objects.all().order_by('operation_type')
    serializer_class = OperationTypeSerializer


class StepViewSet(_AdminWriteOnlyMixin, viewsets.ModelViewSet):
    queryset = Step.objects.all().order_by('title')
    serializer_class = StepSerializer


class StepInstanceViewSet(viewsets.ModelViewSet):
    serializer_class = StepInstanceSerializer
    filterset_fields = ['operation_instance']

    def get_queryset(self):
        qs = (
            StepInstance.objects
            .select_related('step', 'operation_instance')
            .order_by('operation_instance', 'order')
        )
        if self.request.user.is_staff:
            return qs
        return qs.filter(operation_instance__surgeon__user=self.request.user)


class OperationInstanceViewSet(viewsets.ModelViewSet):
    filterset_fields = ['surgeon', 'operation_type', 'complete']

    def get_queryset(self):
        qs = (
            OperationInstance.objects
            .select_related('operation_type', 'surgeon')
            .prefetch_related('steps__step')
            .order_by('-date', '-pk')
        )
        if self.request.user.is_staff:
            return qs
        return qs.filter(surgeon__user=self.request.user)

    def get_serializer_class(self):
        if self.action in ('retrieve', 'update', 'partial_update'):
            return OperationInstanceDetailSerializer
        return OperationInstanceSerializer

    def perform_create(self, serializer):
        instance = serializer.save()
        audit_logger.info('operation_create', extra={
            'user_id': self.request.user.id,
            'operation_instance_id': instance.pk,
            'surgeon_id': instance.surgeon_id,
            'operation_type': instance.operation_type.operation_type,
        })

    def perform_update(self, serializer):
        instance = serializer.save()
        audit_logger.info('operation_update', extra={
            'user_id': self.request.user.id,
            'operation_instance_id': instance.pk,
            'surgeon_id': instance.surgeon_id,
            'operation_type': instance.operation_type.operation_type,
        })

    def perform_destroy(self, instance):
        audit_logger.info('operation_delete', extra={
            'user_id': self.request.user.id,
            'operation_instance_id': instance.pk,
            'surgeon_id': instance.surgeon_id,
            'operation_type': instance.operation_type.operation_type,
        })
        instance.delete()

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
        audit_logger.info('operation_complete', extra={
            'user_id': request.user.id,
            'operation_instance_id': op_inst.pk,
            'surgeon_id': op_inst.surgeon_id,
            'operation_type': op_inst.operation_type.operation_type,
        })
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
