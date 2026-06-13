from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class RegisterForm(UserCreationForm):
    phone = forms.CharField(label="手机号", max_length=32, required=False)

    class Meta:
        model = User
        fields = ["username", "phone", "password1", "password2"]


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "phone", "avatar"]
        widgets = {
            "username": forms.TextInput(attrs={"autocomplete": "username"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel", "placeholder": "可选"}),
            "avatar": forms.FileInput(attrs={"accept": "image/*"}),
        }
