from rest_framework.routers import DefaultRouter

from .views import (
    OperationInstanceViewSet,
    OperationTypeViewSet,
    StepInstanceViewSet,
    StepViewSet,
    SurgeonViewSet,
)

router = DefaultRouter()
router.register('surgeons', SurgeonViewSet, basename='surgeon')
router.register('operation-types', OperationTypeViewSet, basename='operationtype')
router.register('steps', StepViewSet, basename='step')
router.register('step-instances', StepInstanceViewSet, basename='stepinstance')
router.register('operation-instances', OperationInstanceViewSet, basename='operationinstance')

urlpatterns = router.urls
