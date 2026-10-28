from django.db import migrations

def update_existing_users_kyc(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(is_active=True, kyc_status='PENDING').update(kyc_status='APPROVED')

def reverse_update(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_user_account_number_user_government_id_user_ifsc_and_more'),
    ]

    operations = [
        migrations.RunPython(update_existing_users_kyc, reverse_update),
    ]
