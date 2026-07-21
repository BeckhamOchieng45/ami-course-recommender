import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'ami_engine.settings'
django.setup()

from ami_course_recommendations.models import User, UsageEvent
from django.db.models import Count

users_with_counts = (
    UsageEvent.objects
    .filter(event_type='completed')
    .values('user_id')
    .annotate(n=Count('event_id'))
)
count_map = {r['user_id']: r['n'] for r in users_with_counts}
all_ids = set(User.objects.values_list('user_id', flat=True))

cold = [uid for uid in all_ids if uid not in count_map]
between = [uid for uid, n in count_map.items() if 2 <= n <= 4]
heavy = [uid for uid, n in count_map.items() if n >= 8]

print(f"Cold: {len(cold)}, Between: {len(between)}, Heavy: {len(heavy)}")

for label, candidates in [("COLD", cold), ("BETWEEN", between), ("HEAVY", heavy)]:
    uid = candidates[0] if candidates else None
    if uid:
        u = User.objects.get(user_id=uid)
        n = count_map.get(uid, 0)
        print(f"\n{label}: {uid} | role={u.role} | industry={u.industry} | seniority={u.seniority} | completed={n}")
        print(f"  goal: {u.stated_goal}")
        print(f"  interest: {u.true_interest}")
