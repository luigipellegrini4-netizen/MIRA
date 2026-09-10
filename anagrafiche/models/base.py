from django.db import models


class ValidatedModel(models.Model):
    """Validazione per salvataggi ordinari; nessuna operazione di stock."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
