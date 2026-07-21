"""Helper script to identify representative users for sample outputs."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ami_engine.settings')

import django
django.setup()

from ami_course_recommendations.models import User, UsageEvent
from django.db.models import Count

count_map = {
    r['user_id']: r['n']
    for r in UsageEvent.objects.filter(event_type='completed')
    .values('user_id').annotate(n=Count('event_id'))
}
all_ids = set(User.objects.values_list('user_id', flat=True))

cold = [uid for uid in all_ids if uid not in count_map]
between = [uid for uid, n in count_map.items() if 2 <= n <= 4]
heavy = [uid for uid, n in count_map.items() if n >= 8]

print(f"Cold:{len(cold)}  Between:{len(between)}  Heavy:{len(heavy)}")
print()

for label, lst in [("COLD", cold), ("BETWEEN", between), ("HEAVY", heavy)]:
    if lst:
        uid = lst[0]
        u = User.objects.get(user_id=uid)
        n = count_map.get(uid, 0)
        print(f"{label}: {uid}")
        print(f"  role={u.role}  seniority={u.seniority}  industry={u.industry}")
        print(f"  completed_courses={n}")
        print(f"  true_interest={u.true_interest}")
        print(f"  stated_goal={u.stated_goal}")
        print()
