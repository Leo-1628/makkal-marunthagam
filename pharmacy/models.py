from django.db import models

class Medicine(models.Model):
    brand_name = models.CharField(max_length=200)
    combination = models.CharField(max_length=500)
    drug_code = models.CharField(max_length=100)
    manufacturer = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.brand_name