import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ami_engine.settings')
import django
django.setup()

from ami_course_recommendations.models import UsageEvent
events = UsageEvent.objects.filter(user_id='USR-00025', event_type='completed').values('course_id', 'progress_pct')
for e in events:
    print(e)
