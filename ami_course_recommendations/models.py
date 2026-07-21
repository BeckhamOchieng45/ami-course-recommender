"""
Django models for AMI course recommendation system.

These models capture the schema outlined in the case study with AMI-specific
refinements (programme areas, realistic learner roles, etc.).
"""

from django.db import models
from django.db.models import JSONField


class Course(models.Model):
    """
    Course catalog with AMI programme areas and practical skill tags.
    """
    LEVEL_CHOICES = [
        ('foundational', 'Foundational (Micro-Entrepreneurs)'),
        ('intermediate', 'Intermediate (SME Managers)'),
        ('advanced', 'Advanced (Senior Leaders)'),
    ]
    
    PROGRAMME_AREA_CHOICES = [
        ('entrepreneurship', 'Entrepreneurship & Business Growth'),
        ('leadership', 'Executive, Leadership & Management'),
        ('workplace', 'Workplace Learning & Professional Growth'),
        ('ai_strategy', 'AI Strategy for Senior Leaders'),
        ('womens_leadership', "Women's Leadership Development"),
    ]
    
    course_id = models.CharField(max_length=50, primary_key=True)
    title = models.CharField(max_length=200)
    programme_area = models.CharField(max_length=50, choices=PROGRAMME_AREA_CHOICES)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    skills_taught = JSONField(default=list, help_text="List of skill tags")
    duration_mins = models.IntegerField()
    prerequisites = JSONField(default=list, help_text="List of prerequisite course_ids")
    is_paid = models.BooleanField(default=False, help_text="Paid certificate vs free access")
    
    class Meta:
        db_table = 'courses'
    
    def __str__(self):
        return f"{self.course_id}: {self.title}"


class User(models.Model):
    """
    Learner profile spanning micro-entrepreneurs to senior executives.
    """
    ROLE_CHOICES = [
        ('micro_business_owner', 'Micro-Business Owner'),
        ('sme_manager', 'SME Manager'),
        ('corporate_employee', 'Corporate Employee'),
        ('senior_executive', 'Senior Executive'),
    ]
    
    INDUSTRY_CHOICES = [
        ('retail', 'Retail'),
        ('agriculture', 'Agriculture'),
        ('financial_services', 'Financial Services'),
        ('manufacturing', 'Manufacturing'),
        ('professional_services', 'Professional Services'),
        ('ngo_development', 'NGO/Development'),
        ('technology', 'Technology'),
        ('hospitality', 'Hospitality'),
    ]
    
    COMPANY_SIZE_CHOICES = [
        ('micro', 'Micro (1-10 employees)'),
        ('small', 'Small (11-50 employees)'),
        ('medium', 'Medium (51-250 employees)'),
        ('large', 'Large (251+ employees)'),
    ]
    
    user_id = models.CharField(max_length=50, primary_key=True)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES)
    industry = models.CharField(max_length=50, choices=INDUSTRY_CHOICES)
    company_size = models.CharField(max_length=20, choices=COMPANY_SIZE_CHOICES)
    seniority = models.CharField(max_length=50)  # Derived from role
    stated_goal = models.TextField(help_text="Outcome-oriented goal statement")
    
    # Hidden variable for data generator - not used in recommendation logic
    true_interest = models.CharField(
        max_length=100,
        blank=True,
        help_text="Hidden variable for synthetic data generation only"
    )
    
    class Meta:
        db_table = 'users'
    
    def __str__(self):
        return f"{self.user_id}: {self.role}"


class UsageEvent(models.Model):
    """
    Course interaction events reflecting 70/20/10 pedagogy emphasis on application.
    """
    EVENT_TYPE_CHOICES = [
        ('started', 'Started'),
        ('completed', 'Completed'),
        ('dropped', 'Dropped'),
    ]
    
    event_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='usage_events')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='usage_events')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    progress_pct = models.FloatField(help_text="0-100")
    quiz_score = models.FloatField(null=True, blank=True, help_text="0-100, null if not completed")
    timestamp = models.DateTimeField()
    
    class Meta:
        db_table = 'usage_events'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'event_type']),
            models.Index(fields=['course', 'event_type']),
        ]
    
    def __str__(self):
        return f"{self.user_id} {self.event_type} {self.course_id}"


class SurveyResponse(models.Model):
    """
    Self-reported learning needs and interests.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, related_name='survey')
    skill_gaps = JSONField(default=list, help_text="List of skill gap tags")
    goals = JSONField(default=list, help_text="List of goal tags")
    preferred_topics = JSONField(default=list, help_text="List of topic preference tags")
    confidence_by_topic = JSONField(default=dict, help_text="Dict of topic -> confidence score (1-5)")
    
    class Meta:
        db_table = 'survey_responses'
    
    def __str__(self):
        return f"Survey: {self.user_id}"
