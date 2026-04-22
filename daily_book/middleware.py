from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.messages import get_messages
from daily_book.models import ActivityLog

def get_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0] if xff else request.META.get("REMOTE_ADDR")


class MessageActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not request.user.is_authenticated:
            return response

        # 🔥 IMPORTANT: Use request._messages directly
        storage = getattr(request, '_messages', None)

        if storage:
            for msg in storage._queued_messages:
                ActivityLog.objects.create(
                    user=request.user,
                    level=msg.level_tag,
                    message=str(msg),
                    ip_address=get_ip(request),
                    user_agent=request.META.get("HTTP_USER_AGENT", "")
                )

        return response
