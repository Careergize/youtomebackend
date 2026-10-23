from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('matchmaking', '0005_profile_last_seen_at')]
    operations = [migrations.AddField(model_name='message', name='read_at', field=models.DateTimeField(null=True, blank=True))]
