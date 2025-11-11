import uuid

from django.db import models


class BaseModel(models.Model):
    """Abstract base that adds auto ID, UUID surrogate, and audit timestamps."""

    id = models.BigAutoField(primary_key=True)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        
