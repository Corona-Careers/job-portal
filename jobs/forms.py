from django import forms
from .models import Job, CVSubmission, DetailedApplication, ApplicationLink

class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ['title','department', 'description', 'requirements', 'location', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'requirements': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class CVSubmissionForm(forms.ModelForm):
    class Meta:
        model = CVSubmission
        fields = ['applicant_name', 'applicant_email', 'cv_file', 'department']
        widgets = {
            'applicant_name': forms.TextInput(attrs={'class': 'form-control'}),
            'applicant_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'cv_file': forms.FileInput(attrs={'class': 'form-control'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
        }

class DetailedApplicationForm(forms.ModelForm):
    class Meta:
        model = DetailedApplication
        fields = ['full_name', 'email', 'phone_number', 'cover_letter']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'cover_letter': forms.Textarea(attrs={'class': 'form-control', 'rows': 7}),
        }

class ApplicationLinkForm(forms.ModelForm):
    duration_days = forms.IntegerField(
        min_value=1, 
        initial=7, 
        label="Link Duration (Days)",
        help_text="How many days until this link expires?",
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = ApplicationLink
        fields = ['job']
        widgets = {
            'job': forms.Select(attrs={'class': 'form-select'}),
        }
        help_texts = {
            'job': 'Select a job for this application link, or leave blank for a general application.'
        }

class ApplicationStatusUpdateForm(forms.ModelForm):
    """
    Form for HR to update applicant details AND the status of each interview stage.
    Disables status fields based on the application's current stage.
    """
    class Meta:
        model = DetailedApplication
        fields = [
            
            # Existing status fields
            'interview_date',
            'phone_status', 'phone_comment',
            'hr_status', 'hr_comment',
            'technical_status', 'technical_comment',
            'ceo_status', 'ceo_comment',
        ]
        widgets = {
            'interview_date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'cover_letter': forms.Textarea(attrs={'rows': 5}),
            'phone_comment': forms.Textarea(attrs={'rows': 2}),
            'hr_comment': forms.Textarea(attrs={'rows': 2}),
            'technical_comment': forms.Textarea(attrs={'rows': 2}),
            'ceo_comment': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if not self.instance:
            return
            
        app = self.instance
        current_stage = app.current_stage

        # --- Logic for Status Fields ---
        stages_fields = {
            1: ['phone_status', 'phone_comment'],
            2: ['hr_status', 'hr_comment'],
            3: ['technical_status', 'technical_comment'],
            4: ['ceo_status', 'ceo_comment'],
        }

        # Loop through all stages and disable fields that are not active
        for stage_num, fields in stages_fields.items():
            # The stage is active if it's the current one AND the app isn't completed
            is_active_stage = (stage_num == current_stage and app.overall_status == 'review')
            
            for field_name in fields:
                if field_name in self.fields:
                    # Disable if not the active stage
                    if not is_active_stage:
                        self.fields[field_name].disabled = True
                        
                    # Also disable 'pending' choice for the active stage's status field
                    if is_active_stage and field_name.endswith('_status'):
                        self.fields[field_name].choices = [
                            choice for choice in self.fields[field_name].choices 
                            if choice[0] != DetailedApplication.STATUS_PENDING
                        ]

        # If the application is hired or rejected, disable everything
        if app.overall_status != 'review':
             for field_name in self.fields:
                self.fields[field_name].disabled = True
