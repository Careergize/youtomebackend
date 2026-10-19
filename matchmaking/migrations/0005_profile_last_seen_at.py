from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('matchmaking', '0004_call')]
    operations = [
        migrations.AddField(
            model_name='profile', name='last_seen_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
