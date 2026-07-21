"""
Synthetic data generator for AMI course recommendation engine.

Design:
- Each user has a hidden true_interest variable drawn from ~15 practical business topics.
- That hidden variable probabilistically drives BOTH survey answers AND usage events,
  with realistic noise. This lets us verify the engine recovers the user's real interest
  rather than just running without crashing.
- Course catalog reflects AMI's actual programme areas and practical skill tags.
- Usage events reflect 70/20/10 pedagogy: completed + high-quiz events are the strongest
  signal; started-then-dropped reflects realistic mobile/connectivity drop-off (~30%).
"""

import os
import sys
import random
import json
import datetime
import django
from datetime import timezone as tz

# Bootstrap Django so we can use ORM bulk_create
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ami_engine.settings")
django.setup()

from faker import Faker
from ami_course_recommendations.models import Course, User, UsageEvent, SurveyResponse

fake = Faker()
random.seed(42)


# ---------------------------------------------------------------------------
# AMI-specific constants
# ---------------------------------------------------------------------------

# The 15 practical skill domains that serve as the hidden "true interest" variable.
# Phrased as AMI learners actually talk about their goals.
TRUE_INTEREST_DOMAINS = [
    "cash flow management",
    "financial planning and bookkeeping",
    "sales and customer acquisition",
    "customer retention and service excellence",
    "pricing strategy and margin improvement",
    "business planning and strategy",
    "team management and delegation",
    "performance management and feedback",
    "organisational change and systems",
    "communication and presentation skills",
    "productivity and time management",
    "collaboration and team effectiveness",
    "leadership and decision-making",
    "AI strategy and digital transformation",
    "women in leadership and negotiation",
]

# Skill tags map: domain -> tags associated with courses in that domain
DOMAIN_TO_SKILLS: dict[str, list[str]] = {
    "cash flow management": [
        "cash flow forecasting", "working capital", "liquidity management",
        "accounts receivable", "cash buffer planning",
    ],
    "financial planning and bookkeeping": [
        "bookkeeping basics", "profit and loss statements", "balance sheet reading",
        "financial record-keeping", "tax compliance",
    ],
    "sales and customer acquisition": [
        "sales pipeline management", "cold outreach tactics", "value proposition",
        "lead generation", "sales closing techniques",
    ],
    "customer retention and service excellence": [
        "customer retention tactics", "complaint handling", "NPS measurement",
        "service standards", "customer journey mapping",
    ],
    "pricing strategy and margin improvement": [
        "cost-plus pricing", "value-based pricing", "margin analysis",
        "competitive pricing", "price negotiation",
    ],
    "business planning and strategy": [
        "business model canvas", "strategic planning", "market analysis",
        "competitive strategy", "growth planning",
    ],
    "team management and delegation": [
        "delegation frameworks", "task prioritisation", "team structures",
        "role clarity", "workload management",
    ],
    "performance management and feedback": [
        "performance reviews", "feedback delivery", "goal-setting frameworks",
        "KPI tracking", "coaching conversations",
    ],
    "organisational change and systems": [
        "change management", "systems thinking", "process improvement",
        "organisational design", "culture change",
    ],
    "communication and presentation skills": [
        "business writing", "presentation design", "stakeholder communication",
        "active listening", "public speaking",
    ],
    "productivity and time management": [
        "time blocking", "prioritisation frameworks", "meeting effectiveness",
        "focus and deep work", "digital productivity tools",
    ],
    "collaboration and team effectiveness": [
        "team collaboration", "conflict resolution", "cross-functional working",
        "peer feedback", "psychological safety",
    ],
    "leadership and decision-making": [
        "leadership styles", "decision frameworks", "strategic leadership",
        "crisis management", "executive presence",
    ],
    "AI strategy and digital transformation": [
        "AI for business leaders", "digital transformation roadmap",
        "data-driven decision-making", "automation strategy", "AI risk and ethics",
    ],
    "women in leadership and negotiation": [
        "negotiation for women", "executive presence for women",
        "overcoming bias in the workplace", "building a personal brand",
        "work-life integration",
    ],
}


# Programme area assignment per domain
DOMAIN_TO_PROGRAMME = {
    "cash flow management": "entrepreneurship",
    "financial planning and bookkeeping": "entrepreneurship",
    "sales and customer acquisition": "entrepreneurship",
    "customer retention and service excellence": "entrepreneurship",
    "pricing strategy and margin improvement": "entrepreneurship",
    "business planning and strategy": "entrepreneurship",
    "team management and delegation": "leadership",
    "performance management and feedback": "leadership",
    "organisational change and systems": "leadership",
    "communication and presentation skills": "workplace",
    "productivity and time management": "workplace",
    "collaboration and team effectiveness": "workplace",
    "leadership and decision-making": "leadership",
    "AI strategy and digital transformation": "ai_strategy",
    "women in leadership and negotiation": "womens_leadership",
}

# Level distribution by domain - reflects AMI's learner range
DOMAIN_TO_LEVELS: dict[str, list[str]] = {
    "cash flow management": ["foundational", "intermediate"],
    "financial planning and bookkeeping": ["foundational", "foundational", "intermediate"],
    "sales and customer acquisition": ["foundational", "intermediate"],
    "customer retention and service excellence": ["foundational", "intermediate"],
    "pricing strategy and margin improvement": ["foundational", "intermediate"],
    "business planning and strategy": ["foundational", "intermediate", "advanced"],
    "team management and delegation": ["intermediate", "advanced"],
    "performance management and feedback": ["intermediate", "advanced"],
    "organisational change and systems": ["advanced", "advanced"],
    "communication and presentation skills": ["foundational", "intermediate"],
    "productivity and time management": ["foundational", "intermediate"],
    "collaboration and team effectiveness": ["foundational", "intermediate"],
    "leadership and decision-making": ["intermediate", "advanced", "advanced"],
    "AI strategy and digital transformation": ["advanced", "advanced"],
    "women in leadership and negotiation": ["intermediate", "advanced"],
}

# Role -> seniority label
ROLE_TO_SENIORITY = {
    "micro_business_owner": "micro-entrepreneur",
    "sme_manager": "sme-manager",
    "corporate_employee": "early-career",
    "senior_executive": "senior-leader",
}

# Seniority -> preferred level(s)
SENIORITY_TO_LEVELS = {
    "micro-entrepreneur": ["foundational", "foundational", "intermediate"],
    "sme-manager": ["foundational", "intermediate", "intermediate", "advanced"],
    "early-career": ["foundational", "intermediate"],
    "senior-leader": ["intermediate", "advanced", "advanced"],
}

# Role distribution: skewed toward micro/SME per AMI's actual learner base
ROLE_WEIGHTS = {
    "micro_business_owner": 0.35,
    "sme_manager": 0.35,
    "corporate_employee": 0.20,
    "senior_executive": 0.10,
}

COMPANY_SIZE_BY_ROLE = {
    "micro_business_owner": ["micro", "micro", "small"],
    "sme_manager": ["small", "small", "medium"],
    "corporate_employee": ["medium", "large"],
    "senior_executive": ["medium", "large", "large"],
}

INDUSTRIES = [
    "retail", "agriculture", "financial_services",
    "manufacturing", "professional_services", "ngo_development",
    "technology", "hospitality",
]

# Stated goals phrased in outcome-oriented language (AMI testimonial style)
STATED_GOALS_BY_ROLE = {
    "micro_business_owner": [
        "improve my cash flow management so I can stop borrowing at the end of the month",
        "understand my numbers and keep proper financial records",
        "find more customers and grow my monthly revenue",
        "price my products correctly so I can make a real profit",
        "build a simple business plan to take to the bank",
        "keep my existing customers coming back consistently",
    ],
    "sme_manager": [
        "delegate more effectively so I can focus on growing the business",
        "build a team that delivers results without constant supervision",
        "set clear performance targets and hold people accountable",
        "improve how we communicate and collaborate across departments",
        "scale the business without everything depending on me personally",
        "understand strategy and make better long-term decisions",
    ],
    "corporate_employee": [
        "improve my communication skills to advance my career",
        "become more productive and manage my workload better",
        "collaborate more effectively with my team and stakeholders",
        "develop my leadership skills to move into management",
        "learn to give and receive feedback constructively",
    ],
    "senior_executive": [
        "lead organisational change and get buy-in from my team",
        "develop a digital transformation strategy for my company",
        "build a high-performance leadership team",
        "improve my strategic decision-making under uncertainty",
        "understand how AI can create competitive advantage for my business",
        "develop women leaders in my organisation",
    ],
}


# ---------------------------------------------------------------------------
# Course generator
# ---------------------------------------------------------------------------

# Prerequisites: only where a real learning progression exists
PREREQUISITE_CHAINS: list[tuple[str, str]] = [
    # bookkeeping -> cash flow -> financial planning (foundational progression)
    ("CRS-ENT-001", "CRS-ENT-002"),   # Bookkeeping -> Cash Flow Forecasting
    ("CRS-ENT-002", "CRS-ENT-003"),   # Cash Flow -> Advanced Financial Management
    # basic sales -> pipeline management
    ("CRS-ENT-010", "CRS-ENT-011"),   # Sales Fundamentals -> Sales Pipeline Mastery
    # team basics -> delegation -> performance
    ("CRS-LDR-001", "CRS-LDR-002"),   # Team Structures -> Delegation Frameworks
    ("CRS-LDR-002", "CRS-LDR-003"),   # Delegation -> Performance Management
    # AI fundamentals -> AI strategy
    ("CRS-AI-001", "CRS-AI-002"),     # AI Fundamentals -> AI Strategy
]

COURSE_DURATION_BY_LEVEL = {
    "foundational": (45, 90),
    "intermediate": (60, 150),
    "advanced": (90, 180),
}


def build_course_catalog() -> list[dict]:
    """
    Build ~200 courses spread across AMI programme areas.
    Returns list of course dicts ready for Course.objects.create().
    """
    courses = []
    
    # Course title templates per domain
    title_templates: dict[str, list[str]] = {
        "cash flow management": [
            "Cash Flow Forecasting for Small Businesses",
            "Managing Working Capital in Your Business",
            "Advanced Cash Flow Analysis and Planning",
            "Liquidity Management for SME Owners",
            "Cash Buffer Planning: Surviving Lean Months",
        ],
        "financial planning and bookkeeping": [
            "Introduction to Business Bookkeeping",
            "Reading Your Profit and Loss Statement",
            "Balance Sheet Basics for Non-Accountants",
            "Financial Record-Keeping Systems That Scale",
            "Tax Compliance for Small Business Owners",
            "From Receipts to Financial Statements",
        ],
        "sales and customer acquisition": [
            "Sales Fundamentals for Business Owners",
            "Building a Sales Pipeline That Converts",
            "Cold Outreach and Lead Generation Tactics",
            "Crafting a Compelling Value Proposition",
            "Sales Closing Techniques That Work",
            "Building a Referral Engine for Your Business",
        ],
        "customer retention and service excellence": [
            "Turning First-Time Buyers Into Loyal Customers",
            "Handling Complaints and Turning Critics Into Advocates",
            "Measuring and Improving Customer Satisfaction",
            "Designing a Customer Service Standard",
            "Customer Journey Mapping for SMEs",
        ],
        "pricing strategy and margin improvement": [
            "Pricing Your Products for Profit, Not Just Revenue",
            "Value-Based Pricing: Charge What You're Worth",
            "Understanding Your Margins and Cost Structure",
            "Competitive Pricing Without Racing to the Bottom",
            "Negotiation Skills for Business Owners",
        ],
        "business planning and strategy": [
            "Building a One-Page Business Plan",
            "Business Model Canvas: Practical Application",
            "Market Analysis for Growing Businesses",
            "Strategic Planning for SME Leaders",
            "Competitive Strategy: Finding Your Edge",
            "Growth Planning: From Survival to Scale",
            "Scenario Planning Under Uncertainty",
        ],
        "team management and delegation": [
            "Introduction to Managing a Team",
            "Delegation Frameworks That Actually Work",
            "Building Role Clarity in Your Organisation",
            "Managing Up, Down and Across",
            "Team Structures for Growing Businesses",
        ],
        "performance management and feedback": [
            "Setting Goals Your Team Will Actually Chase",
            "Giving Feedback That Drives Performance",
            "Running Effective Performance Reviews",
            "KPI Design for Non-Finance Managers",
            "Coaching Conversations for Line Managers",
            "Holding People Accountable Without Micromanaging",
        ],
        "organisational change and systems": [
            "Leading Organisational Change",
            "Systems Thinking for Business Leaders",
            "Process Improvement in a Growing Business",
            "Designing Your Organisation for Scale",
            "Building a Culture That Sticks",
        ],
        "communication and presentation skills": [
            "Business Writing That Gets Results",
            "Presenting With Confidence and Clarity",
            "Stakeholder Communication for Managers",
            "Active Listening in Professional Settings",
            "Public Speaking for Business Leaders",
            "Writing Persuasive Proposals and Reports",
        ],
        "productivity and time management": [
            "Time Blocking and Deep Work for Managers",
            "Prioritisation Frameworks for Busy Leaders",
            "Running Meetings That Don't Waste Time",
            "Digital Productivity Tools for the Workplace",
            "Managing Energy, Not Just Time",
        ],
        "collaboration and team effectiveness": [
            "Building a High-Trust Team Culture",
            "Conflict Resolution in the Workplace",
            "Cross-Functional Collaboration That Works",
            "Giving and Receiving Peer Feedback",
            "Creating Psychological Safety in Your Team",
        ],
        "leadership and decision-making": [
            "Leadership Styles: Choosing the Right Approach",
            "Making Better Decisions Under Pressure",
            "Strategic Leadership for Senior Managers",
            "Crisis Management and Resilient Leadership",
            "Developing Executive Presence",
            "Leading Diverse and Inclusive Teams",
        ],
        "AI strategy and digital transformation": [
            "AI Fundamentals for Business Leaders",
            "Building an AI Strategy for Your Organisation",
            "Digital Transformation: Where to Start",
            "Data-Driven Decision-Making for Executives",
            "Automation Strategy: What to Automate and What Not To",
            "AI Risk, Ethics and Governance for Leaders",
        ],
        "women in leadership and negotiation": [
            "Negotiation Skills for Women in Business",
            "Building Executive Presence as a Woman Leader",
            "Navigating Bias in the Workplace",
            "Personal Branding for Women Professionals",
            "Work-Life Integration for Female Leaders",
            "Sponsorship vs Mentorship: Building Your Career Network",
        ],
    }

    # Course ID counters per programme area
    id_counters: dict[str, int] = {}
    area_abbrev = {
        "entrepreneurship": "ENT",
        "leadership": "LDR",
        "workplace": "WRK",
        "ai_strategy": "AI",
        "womens_leadership": "WLD",
    }

    for domain, titles in title_templates.items():
        programme = DOMAIN_TO_PROGRAMME[domain]
        abbrev = area_abbrev[programme]
        levels = DOMAIN_TO_LEVELS[domain]

        for idx, title in enumerate(titles):
            level = levels[idx % len(levels)]
            area_count = id_counters.get(abbrev, 0) + 1
            id_counters[abbrev] = area_count
            course_id = f"CRS-{abbrev}-{area_count:03d}"

            min_dur, max_dur = COURSE_DURATION_BY_LEVEL[level]
            duration = random.randint(min_dur, max_dur)

            # Pick 3-6 skills from this domain, add 0-1 from adjacent domain
            primary_skills = random.sample(
                DOMAIN_TO_SKILLS[domain],
                k=min(random.randint(3, 5), len(DOMAIN_TO_SKILLS[domain]))
            )

            # 30% chance of 1 cross-domain skill to reflect real course overlap
            cross_skills: list[str] = []
            if random.random() < 0.3:
                other_domain = random.choice([d for d in TRUE_INTEREST_DOMAINS if d != domain])
                cross_skills = [random.choice(DOMAIN_TO_SKILLS[other_domain])]

            # Free access (85%) vs paid certificate (15%) - AMI's low-cost model
            is_paid = random.random() < 0.15

            courses.append({
                "course_id": course_id,
                "title": title,
                "programme_area": programme,
                "level": level,
                "skills_taught": primary_skills + cross_skills,
                "duration_mins": duration,
                "prerequisites": [],  # Assigned later via PREREQUISITE_CHAINS
                "is_paid": is_paid,
                "_domain": domain,  # Internal - not stored; used for prerequisite wiring
            })

    # Wire prerequisites by position in chains (resolve IDs already assigned)
    # Build title -> course_id lookup
    title_to_id = {c["title"]: c["course_id"] for c in courses}

    prereq_title_pairs = [
        ("Introduction to Business Bookkeeping", "Cash Flow Forecasting for Small Businesses"),
        ("Cash Flow Forecasting for Small Businesses", "Advanced Cash Flow Analysis and Planning"),
        ("Sales Fundamentals for Business Owners", "Building a Sales Pipeline That Converts"),
        ("Introduction to Managing a Team", "Delegation Frameworks That Actually Work"),
        ("Delegation Frameworks That Actually Work", "Setting Goals Your Team Will Actually Chase"),
        ("AI Fundamentals for Business Leaders", "Building an AI Strategy for Your Organisation"),
    ]

    # Build lookup by title
    id_by_title = {c["title"]: c["course_id"] for c in courses}

    for prereq_title, dependent_title in prereq_title_pairs:
        if prereq_title in id_by_title and dependent_title in id_by_title:
            dep_id = id_by_title[dependent_title]
            pre_id = id_by_title[prereq_title]
            for c in courses:
                if c["course_id"] == dep_id:
                    c["prerequisites"] = [pre_id]

    # Remove internal key before DB insertion
    for c in courses:
        c.pop("_domain", None)

    return courses


# ---------------------------------------------------------------------------
# User generator
# ---------------------------------------------------------------------------

def pick_weighted(options: dict) -> str:
    """Pick a key from a dict of {key: weight} using weighted random selection."""
    keys = list(options.keys())
    weights = list(options.values())
    return random.choices(keys, weights=weights, k=1)[0]


def build_users(n: int = 1000) -> list[dict]:
    """
    Generate n users with hidden true_interest variable.
    The hidden variable is correlated with role to ensure sensible
    recommendation signals, with noise so it's not perfectly predictable.
    """
    # Domain -> roles that are naturally interested in it
    DOMAIN_ROLE_AFFINITY: dict[str, list[str]] = {
        "cash flow management": ["micro_business_owner", "sme_manager"],
        "financial planning and bookkeeping": ["micro_business_owner"],
        "sales and customer acquisition": ["micro_business_owner", "sme_manager"],
        "customer retention and service excellence": ["micro_business_owner", "sme_manager"],
        "pricing strategy and margin improvement": ["micro_business_owner"],
        "business planning and strategy": ["micro_business_owner", "sme_manager", "senior_executive"],
        "team management and delegation": ["sme_manager", "senior_executive"],
        "performance management and feedback": ["sme_manager", "corporate_employee", "senior_executive"],
        "organisational change and systems": ["senior_executive"],
        "communication and presentation skills": ["corporate_employee", "sme_manager"],
        "productivity and time management": ["corporate_employee", "sme_manager"],
        "collaboration and team effectiveness": ["corporate_employee", "sme_manager"],
        "leadership and decision-making": ["senior_executive", "sme_manager"],
        "AI strategy and digital transformation": ["senior_executive"],
        "women in leadership and negotiation": ["corporate_employee", "senior_executive", "sme_manager"],
    }

    users = []
    for i in range(n):
        user_id = f"USR-{i+1:05d}"
        role = pick_weighted(ROLE_WEIGHTS)
        seniority = ROLE_TO_SENIORITY[role]

        # 70% chance the true_interest is in a domain naturally aligned with role
        # 30% chance it's any domain (cross-cutting curiosity / career transition)
        aligned_domains = [d for d, roles in DOMAIN_ROLE_AFFINITY.items() if role in roles]
        if random.random() < 0.70 and aligned_domains:
            true_interest = random.choice(aligned_domains)
        else:
            true_interest = random.choice(TRUE_INTEREST_DOMAINS)

        company_sizes = COMPANY_SIZE_BY_ROLE[role]
        company_size = random.choice(company_sizes)

        industry = random.choice(INDUSTRIES)

        # Stated goal: pick one that matches role, with slight noise
        goals_pool = STATED_GOALS_BY_ROLE[role]
        stated_goal = random.choice(goals_pool)

        users.append({
            "user_id": user_id,
            "role": role,
            "seniority": seniority,
            "industry": industry,
            "company_size": company_size,
            "stated_goal": stated_goal,
            "true_interest": true_interest,
        })

    return users


# ---------------------------------------------------------------------------
# Survey response generator
# ---------------------------------------------------------------------------

def build_survey(user: dict) -> dict:
    """
    Generate a survey response for a user.

    The hidden true_interest drives 70% of the tags; the remaining 30% are
    noise from other domains (realistic: people have multiple interests).
    """
    interest = user["true_interest"]
    primary_skills = DOMAIN_TO_SKILLS[interest]

    # Goals: 2-3 tags from true_interest domain
    n_goals = random.randint(2, 3)
    goal_tags = random.sample(primary_skills, k=min(n_goals, len(primary_skills)))

    # Skill gaps: 2-4 tags, mostly from true_interest, 1 possibly from adjacent
    n_gaps = random.randint(2, 4)
    gap_tags = random.sample(primary_skills, k=min(n_gaps - 1, len(primary_skills)))
    # Add one cross-domain gap ~40% of the time
    if random.random() < 0.4:
        other = random.choice([d for d in TRUE_INTEREST_DOMAINS if d != interest])
        gap_tags.append(random.choice(DOMAIN_TO_SKILLS[other]))

    # Preferred topics: 1-3 tags, 50% from true_interest, rest from random domains
    pref_tags: list[str] = []
    if random.random() < 0.5:
        pref_tags = random.sample(primary_skills, k=min(2, len(primary_skills)))
    other_domain = random.choice([d for d in TRUE_INTEREST_DOMAINS if d != interest])
    pref_tags.append(random.choice(DOMAIN_TO_SKILLS[other_domain]))

    # Confidence by topic: 1-5 scale; true_interest area has lower confidence
    # (users seek learning in areas they feel less confident about)
    confidence: dict[str, int] = {}
    for domain in random.sample(TRUE_INTEREST_DOMAINS, k=5):
        if domain == interest:
            confidence[domain] = random.randint(1, 3)  # Less confident = more motivated to learn
        else:
            confidence[domain] = random.randint(2, 5)

    return {
        "user_id": user["user_id"],
        "skill_gaps": gap_tags,
        "goals": goal_tags,
        "preferred_topics": pref_tags,
        "confidence_by_topic": confidence,
    }


# ---------------------------------------------------------------------------
# Usage event generator
# ---------------------------------------------------------------------------

def build_usage_events(
    user: dict,
    courses_by_domain: dict[str, list[dict]],
    all_courses: list[dict],
) -> list[dict]:
    """
    Generate usage events for a user.

    Reflects 70/20/10 pedagogy:
    - Completed courses in the user's interest domain have high progress + quiz scores
    - Started-then-dropped reflects real mobile/connectivity constraints (~30% drop rate)
    - Cold-start users (20% of population) have zero or 1 usage event

    Usage drives the behavior-based scorer in the engine.
    """
    interest = user["true_interest"]
    seniority = user["seniority"]
    preferred_levels = SENIORITY_TO_LEVELS[seniority]

    # Cold-start: ~20% of users have no usage history (brand new)
    if random.random() < 0.20:
        return []

    # Heavy users (10%) have 8-15 events; typical users have 2-7
    if random.random() < 0.10:
        n_events = random.randint(8, 15)
    else:
        n_events = random.randint(2, 7)

    # Pick courses to interact with: 70% from interest domain, 30% from adjacent
    interest_courses = courses_by_domain.get(interest, [])
    # Filter to seniority-appropriate levels
    interest_courses_leveled = [
        c for c in interest_courses if c["level"] in preferred_levels
    ]
    if not interest_courses_leveled:
        interest_courses_leveled = interest_courses  # Fall back if no level match

    # Pool to draw from
    n_interest = max(1, int(n_events * 0.70))
    n_adjacent = n_events - n_interest

    event_courses = []
    if interest_courses_leveled:
        event_courses += random.sample(
            interest_courses_leveled, k=min(n_interest, len(interest_courses_leveled))
        )

    # Adjacent courses from other domains
    other_courses = [c for c in all_courses if c["_domain"] != interest]
    if other_courses:
        event_courses += random.sample(other_courses, k=min(n_adjacent, len(other_courses)))

    # Deduplicate and cap
    seen_ids: set[str] = set()
    unique_courses = []
    for c in event_courses:
        if c["course_id"] not in seen_ids:
            seen_ids.add(c["course_id"])
            unique_courses.append(c)

    events = []
    base_time = fake.date_time_between(
        start_date="-18m", end_date="now"
    ).replace(tzinfo=tz.utc)

    for offset, course in enumerate(unique_courses):
        timestamp = base_time + datetime.timedelta(days=offset * random.randint(3, 21))
        in_interest_domain = (course.get("_domain") == interest)

        # Drop probability: 30% for adjacent courses, 15% for interest domain
        drop_prob = 0.15 if in_interest_domain else 0.30

        if random.random() < drop_prob:
            # Dropped: low progress, no quiz score
            events.append({
                "user_id": user["user_id"],
                "course_id": course["course_id"],
                "event_type": "dropped",
                "progress_pct": random.uniform(5, 45),
                "quiz_score": None,
                "timestamp": timestamp.isoformat(),
            })
        else:
            # Completed: high progress, quiz score correlated with interest alignment
            progress = random.uniform(85, 100)
            base_quiz = 70 if in_interest_domain else 55
            quiz = min(100, random.gauss(base_quiz, 12))
            events.append({
                "user_id": user["user_id"],
                "course_id": course["course_id"],
                "event_type": "completed",
                "progress_pct": progress,
                "quiz_score": round(quiz, 1),
                "timestamp": timestamp.isoformat(),
            })

    return events


# ---------------------------------------------------------------------------
# Orchestration: build everything and insert into the database
# ---------------------------------------------------------------------------

def build_courses_by_domain(courses_with_domain: list[dict]) -> dict[str, list[dict]]:
    """Index courses by their domain for fast lookup during event generation."""
    result: dict[str, list[dict]] = {}
    for course in courses_with_domain:
        domain = course.get("_domain", "")
        if domain not in result:
            result[domain] = []
        result[domain].append(course)
    return result


def generate_all(n_users: int = 1000, clear: bool = True) -> None:
    """
    Generate the full synthetic dataset and write it to the database.

    Args:
        n_users: Number of user records to create.
        clear: If True, wipe existing data before inserting.
    """
    if clear:
        print("Clearing existing data...")
        SurveyResponse.objects.all().delete()
        UsageEvent.objects.all().delete()
        User.objects.all().delete()
        Course.objects.all().delete()

    # --- Courses ---
    print("Generating course catalog...")

    # We need _domain for event generation, so build with domain first
    # then build the internal lookup, then strip _domain before DB insert
    raw_courses = []

    # Re-run build_course_catalog but keep the _domain key in memory
    # (We replicate the catalog logic here so we can keep _domain)
    title_templates: dict[str, list[str]] = {
        "cash flow management": [
            "Cash Flow Forecasting for Small Businesses",
            "Managing Working Capital in Your Business",
            "Advanced Cash Flow Analysis and Planning",
            "Liquidity Management for SME Owners",
            "Cash Buffer Planning: Surviving Lean Months",
        ],
        "financial planning and bookkeeping": [
            "Introduction to Business Bookkeeping",
            "Reading Your Profit and Loss Statement",
            "Balance Sheet Basics for Non-Accountants",
            "Financial Record-Keeping Systems That Scale",
            "Tax Compliance for Small Business Owners",
            "From Receipts to Financial Statements",
        ],
        "sales and customer acquisition": [
            "Sales Fundamentals for Business Owners",
            "Building a Sales Pipeline That Converts",
            "Cold Outreach and Lead Generation Tactics",
            "Crafting a Compelling Value Proposition",
            "Sales Closing Techniques That Work",
            "Building a Referral Engine for Your Business",
        ],
        "customer retention and service excellence": [
            "Turning First-Time Buyers Into Loyal Customers",
            "Handling Complaints and Turning Critics Into Advocates",
            "Measuring and Improving Customer Satisfaction",
            "Designing a Customer Service Standard",
            "Customer Journey Mapping for SMEs",
        ],
        "pricing strategy and margin improvement": [
            "Pricing Your Products for Profit, Not Just Revenue",
            "Value-Based Pricing: Charge What You're Worth",
            "Understanding Your Margins and Cost Structure",
            "Competitive Pricing Without Racing to the Bottom",
            "Negotiation Skills for Business Owners",
        ],
        "business planning and strategy": [
            "Building a One-Page Business Plan",
            "Business Model Canvas: Practical Application",
            "Market Analysis for Growing Businesses",
            "Strategic Planning for SME Leaders",
            "Competitive Strategy: Finding Your Edge",
            "Growth Planning: From Survival to Scale",
            "Scenario Planning Under Uncertainty",
        ],
        "team management and delegation": [
            "Introduction to Managing a Team",
            "Delegation Frameworks That Actually Work",
            "Building Role Clarity in Your Organisation",
            "Managing Up, Down and Across",
            "Team Structures for Growing Businesses",
        ],
        "performance management and feedback": [
            "Setting Goals Your Team Will Actually Chase",
            "Giving Feedback That Drives Performance",
            "Running Effective Performance Reviews",
            "KPI Design for Non-Finance Managers",
            "Coaching Conversations for Line Managers",
            "Holding People Accountable Without Micromanaging",
        ],
        "organisational change and systems": [
            "Leading Organisational Change",
            "Systems Thinking for Business Leaders",
            "Process Improvement in a Growing Business",
            "Designing Your Organisation for Scale",
            "Building a Culture That Sticks",
        ],
        "communication and presentation skills": [
            "Business Writing That Gets Results",
            "Presenting With Confidence and Clarity",
            "Stakeholder Communication for Managers",
            "Active Listening in Professional Settings",
            "Public Speaking for Business Leaders",
            "Writing Persuasive Proposals and Reports",
        ],
        "productivity and time management": [
            "Time Blocking and Deep Work for Managers",
            "Prioritisation Frameworks for Busy Leaders",
            "Running Meetings That Don't Waste Time",
            "Digital Productivity Tools for the Workplace",
            "Managing Energy, Not Just Time",
        ],
        "collaboration and team effectiveness": [
            "Building a High-Trust Team Culture",
            "Conflict Resolution in the Workplace",
            "Cross-Functional Collaboration That Works",
            "Giving and Receiving Peer Feedback",
            "Creating Psychological Safety in Your Team",
        ],
        "leadership and decision-making": [
            "Leadership Styles: Choosing the Right Approach",
            "Making Better Decisions Under Pressure",
            "Strategic Leadership for Senior Managers",
            "Crisis Management and Resilient Leadership",
            "Developing Executive Presence",
            "Leading Diverse and Inclusive Teams",
        ],
        "AI strategy and digital transformation": [
            "AI Fundamentals for Business Leaders",
            "Building an AI Strategy for Your Organisation",
            "Digital Transformation: Where to Start",
            "Data-Driven Decision-Making for Executives",
            "Automation Strategy: What to Automate and What Not To",
            "AI Risk, Ethics and Governance for Leaders",
        ],
        "women in leadership and negotiation": [
            "Negotiation Skills for Women in Business",
            "Building Executive Presence as a Woman Leader",
            "Navigating Bias in the Workplace",
            "Personal Branding for Women Professionals",
            "Work-Life Integration for Female Leaders",
            "Sponsorship vs Mentorship: Building Your Career Network",
        ],
    }

    area_abbrev = {
        "entrepreneurship": "ENT",
        "leadership": "LDR",
        "workplace": "WRK",
        "ai_strategy": "AI",
        "womens_leadership": "WLD",
    }
    id_counters: dict[str, int] = {}

    for domain, titles in title_templates.items():
        programme = DOMAIN_TO_PROGRAMME[domain]
        abbrev = area_abbrev[programme]
        levels = DOMAIN_TO_LEVELS[domain]

        for idx, title in enumerate(titles):
            level = levels[idx % len(levels)]
            area_count = id_counters.get(abbrev, 0) + 1
            id_counters[abbrev] = area_count
            course_id = f"CRS-{abbrev}-{area_count:03d}"

            min_dur, max_dur = COURSE_DURATION_BY_LEVEL[level]
            duration = random.randint(min_dur, max_dur)

            primary_skills = random.sample(
                DOMAIN_TO_SKILLS[domain],
                k=min(random.randint(3, 5), len(DOMAIN_TO_SKILLS[domain]))
            )
            cross_skills: list[str] = []
            if random.random() < 0.3:
                other_domain = random.choice([d for d in TRUE_INTEREST_DOMAINS if d != domain])
                cross_skills = [random.choice(DOMAIN_TO_SKILLS[other_domain])]

            is_paid = random.random() < 0.15

            raw_courses.append({
                "course_id": course_id,
                "title": title,
                "programme_area": programme,
                "level": level,
                "skills_taught": primary_skills + cross_skills,
                "duration_mins": duration,
                "prerequisites": [],
                "is_paid": is_paid,
                "_domain": domain,
            })

    # Wire prerequisites
    prereq_title_pairs = [
        ("Introduction to Business Bookkeeping", "Cash Flow Forecasting for Small Businesses"),
        ("Cash Flow Forecasting for Small Businesses", "Advanced Cash Flow Analysis and Planning"),
        ("Sales Fundamentals for Business Owners", "Building a Sales Pipeline That Converts"),
        ("Introduction to Managing a Team", "Delegation Frameworks That Actually Work"),
        ("Delegation Frameworks That Actually Work", "Setting Goals Your Team Will Actually Chase"),
        ("AI Fundamentals for Business Leaders", "Building an AI Strategy for Your Organisation"),
    ]
    id_by_title = {c["title"]: c["course_id"] for c in raw_courses}
    for prereq_title, dep_title in prereq_title_pairs:
        if prereq_title in id_by_title and dep_title in id_by_title:
            dep_id = id_by_title[dep_title]
            pre_id = id_by_title[prereq_title]
            for c in raw_courses:
                if c["course_id"] == dep_id:
                    c["prerequisites"] = [pre_id]

    print(f"  {len(raw_courses)} courses generated")

    # Build domain index (keep _domain in raw_courses for event generation)
    courses_by_domain = build_courses_by_domain(raw_courses)

    # Insert courses (strip _domain)
    course_objects = []
    for c in raw_courses:
        course_objects.append(Course(
            course_id=c["course_id"],
            title=c["title"],
            programme_area=c["programme_area"],
            level=c["level"],
            skills_taught=c["skills_taught"],
            duration_mins=c["duration_mins"],
            prerequisites=c["prerequisites"],
            is_paid=c["is_paid"],
        ))
    Course.objects.bulk_create(course_objects)
    print(f"  Inserted {len(course_objects)} courses into DB")

    # --- Users ---
    print(f"Generating {n_users} users...")
    user_dicts = build_users(n_users)
    user_objects = [
        User(
            user_id=u["user_id"],
            role=u["role"],
            seniority=u["seniority"],
            industry=u["industry"],
            company_size=u["company_size"],
            stated_goal=u["stated_goal"],
            true_interest=u["true_interest"],
        )
        for u in user_dicts
    ]
    User.objects.bulk_create(user_objects)
    print(f"  Inserted {len(user_objects)} users into DB")

    # --- Surveys ---
    print("Generating survey responses...")
    survey_objects = [
        SurveyResponse(
            user_id=u["user_id"],
            skill_gaps=s["skill_gaps"],
            goals=s["goals"],
            preferred_topics=s["preferred_topics"],
            confidence_by_topic=s["confidence_by_topic"],
        )
        for u in user_dicts
        for s in [build_survey(u)]
    ]
    SurveyResponse.objects.bulk_create(survey_objects)
    print(f"  Inserted {len(survey_objects)} survey responses into DB")

    # --- Usage events ---
    print("Generating usage events...")
    all_events: list[UsageEvent] = []
    for u in user_dicts:
        events = build_usage_events(u, courses_by_domain, raw_courses)
        for e in events:
            all_events.append(UsageEvent(
                user_id=e["user_id"],
                course_id=e["course_id"],
                event_type=e["event_type"],
                progress_pct=e["progress_pct"],
                quiz_score=e["quiz_score"],
                timestamp=e["timestamp"],
            ))

    UsageEvent.objects.bulk_create(all_events, batch_size=500)
    print(f"  Inserted {len(all_events)} usage events into DB")

    # --- Summary ---
    cold_start_users = sum(1 for u in user_dicts if not any(
        e["user_id"] == u["user_id"] for e in []  # Will check from events
    ))
    n_completed = sum(1 for e in all_events if e.event_type == "completed")
    n_dropped = sum(1 for e in all_events if e.event_type == "dropped")

    print("\n=== Generation complete ===")
    print(f"  Courses:         {Course.objects.count()}")
    print(f"  Users:           {User.objects.count()}")
    print(f"  Survey responses:{SurveyResponse.objects.count()}")
    print(f"  Usage events:    {UsageEvent.objects.count()}")
    print(f"    Completed: {n_completed}  |  Dropped: {n_dropped}")
    print(f"  Drop rate:       {n_dropped / max(1, n_completed + n_dropped):.1%}")


if __name__ == "__main__":
    generate_all(n_users=1000, clear=True)
