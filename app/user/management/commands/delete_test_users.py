# distributorplatform/app/user/management/commands/delete_test_users.py

from django.core.management.base import BaseCommand
from user.models import CustomUser

class Command(BaseCommand):
    help = 'Deletes all non-superuser accounts from the database.'

    def handle(self, *args, **options):
        # Find all users who are NOT superusers
        users_to_delete = CustomUser.objects.filter(is_superuser=False)

        count = users_to_delete.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No non-superuser accounts found to delete.'))
            return

        # Delete the users
        users_to_delete.delete()

        self.stdout.write(self.style.SUCCESS(f'Successfully deleted {count} non-superuser accounts.'))
