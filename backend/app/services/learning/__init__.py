"""The learning layer: reading progress, study sets, learning plans and the summarize / compare agents.

Every generated sentence goes through the same generate -> verify -> refusal-policy stages as /ask (see grounded.py);
every document id a caller supplies is checked against services/acl.py and reported as 404 when unreadable."""

from app.services.learning.agents import AgentService
from app.services.learning.plans import PlanService
from app.services.learning.progress import ProgressService
from app.services.learning.study_sets import StudySetService

__all__ = ["AgentService", "PlanService", "ProgressService", "StudySetService"]
