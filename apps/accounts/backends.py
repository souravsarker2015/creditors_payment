from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class UsernameOrEmailBackend(ModelBackend):
    """Sign in with the username (exactly, as before), or with the email
    address on the account when exactly one account has that email."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        username = username.strip()
        try:
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            user = None
            if "@" in username:
                matches = list(UserModel._default_manager.filter(email__iexact=username)[:2])
                user = matches[0] if len(matches) == 1 else None
        if user is None:
            UserModel().set_password(password)   # spend the same time as a real check
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
