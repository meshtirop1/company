from hours_tracker.models import CustomUser
if not CustomUser.objects.filter(username='admin').exists():
    CustomUser.objects.create_superuser(username='admin', email='admin@example.com', password='Admin12345!', is_admin=True, is_employee=True)
print('done')
