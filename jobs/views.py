from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Job, CVSubmission, ApplicationLink, DetailedApplication
from .forms import CVSubmissionForm, DetailedApplicationForm, JobForm, ApplicationLinkForm, ApplicationStatusUpdateForm
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.contrib import messages
from django.shortcuts import redirect
from django.core.mail import send_mail
from django.conf import settings

def send_applicant_notification(application, stage_name, new_status, comment):
    """
    Sends an email to the applicant about their status change.
    """
    if new_status == DetailedApplication.STATUS_PENDING:
        return # Don't send emails for 'pending'

    job_title = application.link.job.title if application.link.job else "General Application"
    
    if new_status == DetailedApplication.STATUS_PASSED:
        subject = f"Congratulations! Update on your application for {job_title}"
    else: # STATUS_FAILED
        subject = f"Update on your application for {job_title}"

    html_message = render_to_string('emails/status_notification.html', {
        'applicant_name': application.full_name,
        'job_title': job_title,
        'stage_name': stage_name,
        'status': new_status,
        'status_display': 'Passed' if new_status == 'passed' else 'Not Selected',
        'comment': comment,
    })

    send_mail(
        subject,
        '', # Plain text message (optional)
        settings.DEFAULT_FROM_EMAIL, # Configure this in your settings.py
        [application.email],
        html_message=html_message,
        fail_silently=False
    )

# Helper function to check if a user is HR (staff)
def is_hr_user(user):
    return user.is_authenticated and user.is_staff

class HRRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin to ensure user is logged in and is an HR staff member."""
    def test_func(self):
        return is_hr_user(self.request.user)

# --- Applicant Views ---

class JobListView(ListView):
    """Displays a list of all active jobs for applicants."""
    model = Job
    template_name = 'jobs/job_list.html'
    context_object_name = 'jobs'
    
    def get_queryset(self):
        return Job.objects.filter(is_active=True).order_by('-created_at')

class JobDetailView(DetailView):
    model = Job
    template_name = 'jobs/job_detail.html'
    context_object_name = 'job'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = CVSubmissionForm()
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = CVSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.job = self.object
            submission.save()

            # --- SEND EMAIL ---
            subject = f"New CV Submission for {self.object.title}"
            html_message = render_to_string('emails/application_notification.html', {
                'job': self.object,
                'applicant': submission,
            })

            email = EmailMessage(
                subject=subject,
                body=html_message,
                from_email='hr.career@corona.eg',
                to=['hr.career@corona.eg',submission.applicant_email],  # add more HR emails if needed
            )
            email.content_subtype = 'html'

            if submission.cv_file:
                submission.cv_file.open('rb')
                email.attach(submission.cv_file.name, submission.cv_file.read(),"application/pdf")
                submission.cv_file.close()

            email.send(fail_silently=False)
            # --- END EMAIL ---

            messages.success(request, 'Your application has been submitted successfully!')
            return redirect('job-detail', pk=self.object.pk)

        context = self.get_context_data()
        context['form'] = form
        return self.render_to_response(context)

def application_form_view(request, token):
    """Handles the detailed application form submitted via a temporary link."""
    try:
        link = ApplicationLink.objects.get(token=token)
    except ApplicationLink.DoesNotExist:
        return render(request, 'jobs/link_invalid.html')

    # Check for expiration and reuse
    if timezone.now() > link.expires_at:
        return render(request, 'jobs/link_expired.html', {'link': link})
    if link.is_used:
        return render(request, 'jobs/link_invalid.html', {'message': 'This application link has already been used.'})

    if request.method == 'POST':
        form = DetailedApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            application = form.save(commit=False)
            application.link = link
            application.save()

            # --- SEND EMAIL ---
            subject = f"Detailed Application for {link.job.title}"
            html_message = render_to_string('emails/application_notification.html', {
                'job': link.job,
                'applicant': application,
            })

            email = EmailMessage(
                subject=subject,
                body=html_message,
                from_email='hr.career@corona.eg',
                to=['hr.career@corona.eg',application.email],
            )
            email.content_subtype = 'html'
            email.send(fail_silently=False)
            # --- END EMAIL ---

            link.is_used = True
            link.save()

            return render(request, 'jobs/application_success.html')
    else:
        form = DetailedApplicationForm()

    return render(request, 'jobs/application_form.html', {'form': form, 'job': link.job})

# --- HR Views ---

@login_required
@user_passes_test(is_hr_user)
def hr_dashboard(request):
    """Dashboard for HR, showing job stats and links to management pages."""
    jobs = Job.objects.filter(created_by=request.user).order_by('-created_at')
    recent_submissions = CVSubmission.objects.filter(job__in=jobs).order_by('-submitted_at')[:10]
    recent_applications = DetailedApplication.objects.filter(link__created_by=request.user).order_by('-submitted_at')[:10]
    
    context = {
        'jobs': jobs,
        'recent_submissions': recent_submissions,
        'recent_applications': recent_applications
    }
    return render(request, 'jobs/hr_dashboard.html', context)


class JobCreateView(HRRequiredMixin, CreateView):
    model = Job
    form_class = JobForm
    template_name = 'jobs/job_form.html'
    success_url = reverse_lazy('hr-dashboard')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)

class JobUpdateView(HRRequiredMixin, UpdateView):
    model = Job
    form_class = JobForm
    template_name = 'jobs/job_form.html'
    success_url = reverse_lazy('hr-dashboard')

    def get_queryset(self):
        return Job.objects.filter(created_by=self.request.user)

class JobDeleteView(HRRequiredMixin, DeleteView):
    model = Job
    template_name = 'jobs/job_confirm_delete.html'
    success_url = reverse_lazy('hr-dashboard')
    
    def get_queryset(self):
        return Job.objects.filter(created_by=self.request.user)

@login_required
@user_passes_test(is_hr_user)
def toggle_job_status(request, pk):
    """Toggles the is_active status of a job."""
    job = get_object_or_404(Job, pk=pk, created_by=request.user)
    job.is_active = not job.is_active
    job.save()
    return redirect('hr-dashboard')

@login_required
@user_passes_test(is_hr_user)
def view_cv_submissions(request, job_pk):
    """Displays all CV submissions for a specific job."""
    job = get_object_or_404(Job, pk=job_pk, created_by=request.user)
    submissions = job.submissions.all().order_by('-submitted_at')
    return render(request, 'jobs/cv_list.html', {'job': job, 'submissions': submissions})

@login_required
@user_passes_test(is_hr_user)
def generate_application_link(request):
    """Generates a temporary link for a detailed application."""
    if request.method == 'POST':
        form = ApplicationLinkForm(request.POST)
        form.fields['job'].queryset = Job.objects.filter(created_by=request.user)
        if form.is_valid():
            link = form.save(commit=False)
            link.created_by = request.user
            link.expires_at = timezone.now() + timedelta(days=form.cleaned_data.get('duration_days', 7))
            link.save()
            full_link = request.build_absolute_uri(reverse('application-form', args=[str(link.token)]))
            return render(request, 'jobs/link_generated.html', {'link': full_link})
    else:
        form = ApplicationLinkForm()
        form.fields['job'].queryset = Job.objects.filter(created_by=request.user)
        
    return render(request, 'jobs/generate_link_form.html', {'form': form})
    
@login_required
@user_passes_test(is_hr_user)
def view_detailed_applications(request):
    """Lists all detailed applications received from generated links."""
    applications = DetailedApplication.objects.filter(link__created_by=request.user).order_by('-submitted_at')
    return render(request, 'jobs/detailed_application_list.html', {'applications': applications})

@login_required
@user_passes_test(is_hr_user)
def update_application_status(request, pk):
    """
    Manages the 4-stage interview status update for a DetailedApplication.
    """
    application = get_object_or_404(DetailedApplication, pk=pk, link__created_by=request.user)
    
    # Store old statuses to check what changed
    old_statuses = {
        'phone': application.phone_status,
        'hr': application.hr_status,
        'technical': application.technical_status,
        'ceo': application.ceo_status,
    }

    if request.method == 'POST':
        form = ApplicationStatusUpdateForm(request.POST, instance=application)
        if form.is_valid():
            new_app = form.save(commit=False)
            
            # --- Update Overall Status ---
            if new_app.ceo_status == DetailedApplication.STATUS_PASSED:
                new_app.overall_status = DetailedApplication.OVERALL_STATUS_HIRED
            elif any(s == DetailedApplication.STATUS_FAILED for s in [new_app.phone_status, new_app.hr_status, new_app.technical_status, new_app.ceo_status]):
                new_app.overall_status = DetailedApplication.OVERALL_STATUS_REJECTED
            else:
                new_app.overall_status = DetailedApplication.OVERALL_STATUS_REVIEW
            
            new_app.save()

            # --- Check for changes and send emails ---
            new_statuses = {
                'phone': new_app.phone_status,
                'hr': new_app.hr_status,
                'technical': new_app.technical_status,
                'ceo': new_app.ceo_status,
            }
            
            stage_names = {
                'phone': 'Phone Interview',
                'hr': 'HR Interview',
                'technical': 'Technical Interview',
                'ceo': 'CEO Interview',
            }

            for stage_key in stage_names.keys():
                old_s = old_statuses[stage_key]
                new_s = new_statuses[stage_key]
                
                # If status changed from 'pending' to something else
                if old_s == DetailedApplication.STATUS_PENDING and new_s != DetailedApplication.STATUS_PENDING:
                    stage_name = stage_names[stage_key]
                    comment = getattr(new_app, f"{stage_key}_comment")
                    try:
                        send_applicant_notification(new_app, stage_name, new_s, comment)
                    except Exception as e:
                        messages.error(request, f"Failed to send email: {e}")

            messages.success(request, f"Application status for {application.full_name} has been updated.")
            return redirect('update-application-status', pk=application.pk)
    else:
        form = ApplicationStatusUpdateForm(instance=application)

    return render(request, 'jobs/application_status_form.html', {
        'form': form,
        'application': application
    })


@login_required
@user_passes_test(is_hr_user)
def view_detailed_applications(request):
    """Lists all detailed applications received from generated links."""
    applications = DetailedApplication.objects.filter(link__created_by=request.user).order_by('-submitted_at')
    return render(request, 'jobs/detailed_application_list.html', {'applications': applications})

