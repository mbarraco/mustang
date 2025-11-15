from django import forms
from django.utils.translation import gettext_lazy as _

from allauth.account.adapter import get_adapter
from allauth.account.utils import setup_user_email


class UsernameOnlySignupForm(forms.Form):
    username = forms.CharField(
        label=_("Username"),
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    password1 = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label=_("Password (again)"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if username:
            username = get_adapter().clean_username(username)
        return username

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(
                _("The two password fields didn’t match.")
            )
        return password2

    def save(self, request):
        adapter = get_adapter()
        user = adapter.new_user(request)
        self.cleaned_data["email"] = ""
        adapter.save_user(request, user, self, commit=False)
        setup_user_email(request, user, [], False)
        user.save()
        return user

    def signup(self, request, user):
        return user
