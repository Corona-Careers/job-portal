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
from django.db import models
from django.http import JsonResponse
from django.db.models import Q
from django.utils.timesince import timesince
from django.db.models import Count
from icalendar import Calendar, Event
import pytz

def send_applicant_notification(application, stage_name, new_status, comment):
    """
    Sends TWO separate emails:
    1. To Applicant: Friendly "Congratulations" or Update email.
    2. To HR: Factual "Interview Scheduled" email (Only if interview is set).
    """
    if new_status == DetailedApplication.STATUS_PENDING:
        return 

    job_title = application.link.job.title if application.link.job else "General Application"
    
    # 1. Define the progression path
    NEXT_STAGE_MAP = {
        'Phone Interview': 'HR Interview',
        'HR Interview': 'Technical Interview',
        'Technical Interview': 'CEO Interview',
        'CEO Interview': 'Final Offer Meeting'
    }

    # 2. Determine Event Details
    event_stage_name = stage_name
    
    # Applicant Subject Line Logic
    if new_status == DetailedApplication.STATUS_PASSED:
        event_stage_name = NEXT_STAGE_MAP.get(stage_name, stage_name)
        subject_applicant = f"Congratulations! You've moved to the {event_stage_name}"
    else:
        subject_applicant = f"Update on your application for {job_title}"

    has_interview = application.interview_date is not None

    # 3. Create Calendar Event Data (Generate once, use twice)
    ics_data = None
    if has_interview:
        ics_data = create_calendar_event(
            summary=f"{event_stage_name} with Corona: {application.full_name}", 
            start_time=application.interview_date,
            description=f"Scheduled {event_stage_name} for {job_title}.\n\nNotes: {comment}",
            location="Online / Corona HQ"
        )

    # =====================================================
    # 📧 EMAIL 1: To Applicant (Friendly Template)
    # =====================================================
    html_applicant = render_to_string('emails/status_notification.html', {
        'applicant_name': application.full_name,
        'job_title': job_title,
        'stage_name': stage_name,          
        'next_stage': event_stage_name,   
        'status': new_status,
        'status_display': 'Passed' if new_status == 'passed' else 'Not Selected',
        'comment': comment,
        'interview_date': application.interview_date if has_interview else None
    })

    email_app = EmailMessage(
        subject_applicant,
        html_applicant, 
        settings.DEFAULT_FROM_EMAIL,
        [application.email], # ✅ Send ONLY to Applicant
    )
    email_app.content_subtype = "html"

    if ics_data:
        email_app.attach('interview_invite.ics', ics_data, 'text/calendar')

    email_app.send(fail_silently=False)

    # =====================================================
    # 📧 EMAIL 2: To HR (Factual Template)
    # =====================================================
    # Only notify HR if an interview is actually scheduled
    if has_interview:
        subject_hr = f"📅 Interview Scheduled: {application.full_name} ({event_stage_name})"
        
        # Use the new HTML template you created
        html_hr = render_to_string('emails/hr_interview_notification.html', {
            'job_title': job_title,
            'applicant_name': application.full_name,
            'stage_name': event_stage_name,
            'interview_date': application.interview_date
        })

        # Define HR Recipients
        hr_recipients = ['hr.career@corona.eg'] # Add your hardcoded email
        
        # # Optionally add the user who created the link
        # if application.link.created_by and application.link.created_by.email:
        #     hr_recipients.append(application.link.created_by.email)
        
        # Remove duplicates
        hr_recipients = list(set(hr_recipients))

        email_hr = EmailMessage(
            subject_hr,
            html_hr, 
            settings.DEFAULT_FROM_EMAIL,
            hr_recipients, # ✅ Send ONLY to HR list
        )
        email_hr.content_subtype = "html"

        if ics_data:
            email_hr.attach('interview_invite.ics', ics_data, 'text/calendar')

        email_hr.send(fail_silently=False)
        
def create_calendar_event(summary, start_time, description, location="Online/Phone"):
    cal = Calendar()
    cal.add('prodid', '-//Corona Hiring System//corona.eg//')
    cal.add('version', '2.0')

    event = Event()
    event.add('summary', summary)

    if start_time.tzinfo:
        start_time = start_time.astimezone(pytz.utc)

    event.add('dtstart', start_time)
    # Assume 1 hour duration for interviews
    event.add('dtend', start_time + timedelta(hours=1))
    event.add('dtstamp', timezone.now())
    event.add('description', description)
    event.add('location', location)
    
    cal.add_component(event)
    return cal.to_ical()

# Helper function to check if a user is HR (staff)
def is_hr_user(user):
    return user.is_authenticated and user.is_staff

def get_unseen_notifications(request):
    unseen_cvs = CVSubmission.objects.filter(
        (Q(job__created_by=request.user) | Q(job__isnull=True)), 
        viewed=False
    ).order_by('-submitted_at')

    unseen_applications = DetailedApplication.objects.filter(
        link__created_by=request.user, 
        viewed=False
    ).order_by('-submitted_at')

    # Build quick-link URLs for each notification
    cvs_data = []
    for cv in unseen_cvs:
        if cv.job:
            title = cv.job.title
            url = reverse('view-cv-submissions', kwargs={'job_pk': cv.job.id})
        else:
            title = "General Application"
            # Ensure you have a URL pattern named 'view-general-submissions' in urls.py
            url = reverse('view-general-submissions')

        cvs_data.append({
            "name": cv.applicant_name,
            "job_title": title,
            "url": url
        })

    apps_data = [
        {
            "name": app.full_name,
            "job_title": app.link.job.title if app.link.job else "General",
            "url": reverse('update-application-status', kwargs={'pk': app.pk})
        }
        for app in unseen_applications
    ]

    return cvs_data, apps_data

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
        queryset = Job.objects.filter(is_active=True).order_by('-created_at')
        # 1. Get parameters from the URL
        query = self.request.GET.get('q', '').strip()
        department = self.request.GET.get('department', '').strip()
        location = self.request.GET.get('location', '').strip()

        # 2. Apply Search
        if query:
            queryset = queryset.filter(
                models.Q(title__icontains=query) |
                models.Q(description__icontains=query) |
                models.Q(location__icontains=query)
            )

        # 3. Apply Department Filter
        if department:
            queryset = queryset.filter(department=department)

        # 4. Apply Location Filter
        if location:
            queryset = queryset.filter(location=location)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass current filters back to template (so dropdowns stay selected)
        context['search_query'] = self.request.GET.get('q', '')
        context['selected_department'] = self.request.GET.get('department', '')
        context['selected_location'] = self.request.GET.get('location', '')

        active_jobs = Job.objects.filter(is_active=True)
        
        context['departments'] = active_jobs.values_list('department', flat=True).distinct().order_by('department')
        context['locations'] = active_jobs.values_list('location', flat=True).distinct().order_by('location')

        return context

class JobDetailView(DetailView):
    model = Job
    template_name = 'jobs/job_detail.html'
    context_object_name = 'job'

    def get_object(self, queryset=None):
        """Allow this view to work for both job-specific and general applications."""
        try:
            return super().get_object(queryset)
        except Exception:
            return None  # no job = general application
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = CVSubmissionForm()

        # 🧠 Remove department for job-specific form
        if self.object is not None:
            form.fields.pop('department', None)

        context['form'] = form
        return context

    def post(self, request, *args, **kwargs):
        # ... (Logic to get job instance remains the same) ...
        job = None
        try:
            job = self.get_object()
        except Exception:
            pass

        form = CVSubmissionForm(request.POST, request.FILES)
        if job:
            form.fields.pop('department', None)

        if form.is_valid():
            submission = form.save(commit=False)
            submission.job = job
            if job:
                submission.department = job.department
            submission.save()

            # =====================================================
            # 📨 EMAIL 1: Notification to HR (Technical Info)
            # =====================================================
            subject_hr = f"New CV Submission: {job.title if job else 'General Application'}"
            
            # This uses your existing table-based template for HR
            html_hr = render_to_string('emails/application_notification.html', {
                'job': job,
                'applicant': submission,
            })

            email_hr = EmailMessage(
                subject=subject_hr,
                body=html_hr,
                from_email='hr.career@corona.eg',
                to=['hr.career@corona.eg'], # ✅ HR Only
            )
            email_hr.content_subtype = 'html'

            # Attach the CV for HR
            if submission.cv_file:
                submission.cv_file.open('rb')
                email_hr.attach(submission.cv_file.name, submission.cv_file.read(), "application/pdf")
                submission.cv_file.close()

            email_hr.send(fail_silently=False)

            # =====================================================
            # 📨 EMAIL 2: Acknowledgement to Applicant (Friendly)
            # =====================================================
            subject_app = f"We received your CV: {job.title if job else 'General Application'}"
            
            # This uses the NEW friendly template
            html_app = render_to_string('emails/cv_acknowledgement.html', {
                'job': job,
                'applicant': submission,
            })

            send_mail(
                subject_app,
                '', # Plain text content (optional)
                'hr.career@corona.eg',
                [submission.applicant_email], # ✅ Applicant Only
                html_message=html_app,
                fail_silently=False
            )

            messages.success(request, 'Your CV has been submitted successfully!')
            if job:
                return redirect('job-detail', pk=job.pk)
            else:
                return redirect('general-application')

        # Form invalid: re-render page
        context = self.get_context_data()
        context['form'] = form
        return self.render_to_response(context)

def application_form_view(request, token):
    """Handles the detailed application form submitted via a temporary link."""
    try:
        link = ApplicationLink.objects.get(token=token)
    except ApplicationLink.DoesNotExist:
        return render(request, 'jobs/link_invalid.html')

    # Check for expiration or reuse
    if timezone.now() > link.expires_at:
        return render(request, 'jobs/link_expired.html', {'link': link})
    if link.is_used:
        return render(request, 'jobs/link_invalid.html', {
            'message': 'This application link has already been used.'
        })

    job = link.job  # can be None for general applications

    if request.method == 'POST':
        form = DetailedApplicationForm(request.POST, request.FILES)
        # In views.py inside application_form_view

    # ... (previous code for validation and saving) ...
        if form.is_valid():
            application = form.save(commit=False)
            application.link = link
            application.save()

            # ✅ Define the base subject
            if job:
                subject_base = job.title
            else:
                subject_base = "General Application"

            # =====================================================
            # 📨 EMAIL 1: Notification to HR (Technical Info)
            # =====================================================
            # Keep using the existing table-based template for HR
            html_hr = render_to_string('emails/application_notification.html', {
                'job': job,
                'applicant': application,
            })

            send_mail(
                subject=f"Detailed Application: {subject_base}",
                message='',
                from_email='hr.career@corona.eg',
                recipient_list=['hr.career@corona.eg'], # ✅ HR Only
                html_message=html_hr,
                fail_silently=False
            )

            # =====================================================
            # 📨 EMAIL 2: Acknowledgement to Applicant (Friendly)
            # =====================================================
            # Use the NEW friendly template created above
            html_app = render_to_string('emails/detailed_application_acknowledgement.html', {
                'job': job,
                'applicant': application,
            })

            send_mail(
                subject=f"Application Received: {subject_base}",
                message='',
                from_email='hr.career@corona.eg',
                recipient_list=[application.email], # ✅ Applicant Only
                html_message=html_app,
                fail_silently=False
            )

            # Mark the link as used
            link.is_used = True
            link.save()

            return render(request, 'jobs/application_success.html', {'job': job})

    else:
        form = DetailedApplicationForm()

    # Render form (job may be None)
    return render(request, 'jobs/application_form.html', {
        'form': form,
        'job': job,
        'page_title': job.title if job else "General Application",
    })

# --- HR Views ---

@login_required
@user_passes_test(is_hr_user)
def hr_dashboard(request):
    """Dashboard for HR, showing job stats and links to management pages."""
    jobs = (
        Job.objects.filter(created_by=request.user)
        .annotate(cv_count=Count('submissions', distinct=True))
        .annotate(application_count=Count('application_links__application_details', distinct=True))
        .order_by('-created_at')
    )

    #recent_submissions = CVSubmission.objects.filter(job__created_by=request.user).order_by('-submitted_at')[:10]
    #recent_applications = DetailedApplication.objects.filter(link__created_by=request.user).order_by('-submitted_at')[:10]
    total_submissions = CVSubmission.objects.filter(job__created_by=request.user).count()
    total_applications = DetailedApplication.objects.filter(link__created_by=request.user).count()
    unseen_cvs, unseen_apps = get_unseen_notifications(request)
    total_unseen_notifications = len(unseen_cvs) + len(unseen_apps)
    #total_general_submissions = CVSubmission.objects.filter(job__isnull=True).count()
    # 🆕 General submissions (no job linked)
    general_cv_count = CVSubmission.objects.filter(job__isnull=True).count()
    general_app_count = DetailedApplication.objects.filter(link__job__isnull=True).count()

    context = {
        'jobs': jobs,
        # 'recent_submissions': recent_submissions,
        # 'recent_applications': recent_applications,
        'total_submissions' : total_submissions,
        'total_applications' : total_applications,
        'total_general_submissions': general_cv_count,
        'general_cv_count': general_cv_count,
        'general_app_count': general_app_count,
        'unseen_cvs': unseen_cvs,
        'unseen_apps': unseen_apps,
        'total_unseen_notifications': total_unseen_notifications,
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

    # ✅ Handle search and optional department filter
    # 🔍 Get search query
    query = request.GET.get('q', '').strip()

    # Apply search filter if needed
    if query:
        submissions = submissions.filter(
            Q(applicant_name__icontains=query) |
            Q(applicant_email__icontains=query))

    # Mark unseen submissions as seen
    for cv in submissions:
        if not cv.viewed:
            cv.viewed = True
            cv.save(update_fields=['viewed'])

    context = {
        'job': job,
        'submissions': submissions,
        'query': query,
        'filter_enabled': False,  # 🔹 Hide filter in job-based page
    }

    return render(request, 'jobs/cv_list.html', context)

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
def generate_link_from_cv(request, cv_id):
    """
    Generate and email an application link directly from a CV submission.
    Works for both job-specific and general CVs.
    """
    # ✅ Allow HR to generate link for both job-based and general CVs
    try:
        cv = CVSubmission.objects.get(id=cv_id)
        if cv.job and cv.job.created_by != request.user:
            messages.error(request, "❌ You are not authorized to manage this CV.")
            return redirect('hr-dashboard')
    except CVSubmission.DoesNotExist:
        messages.error(request, "❌ CV not found.")
        return redirect('hr-dashboard')

    # ✅ Create the link (even if job=None)
    link = ApplicationLink.objects.create(
        job=cv.job,
        created_by=request.user,
        expires_at=timezone.now() + timedelta(days=7)
    )

    # ✅ Build the full application URL
    full_link = request.build_absolute_uri(reverse('application-form', args=[str(link.token)]))

    # ✅ Email subject and body (dynamic for general/job cases)
    if cv.job:
        subject = f"Next Step for Your Application at Corona: {cv.job.title}"
        job_title = cv.job.title
    else:
        subject = "Next Step for Your Application at Corona"
        job_title = "General Application"

    # ✅ HTML email
    html_message = render_to_string('emails/detailed_application_invite.html', {
        'applicant_name': cv.applicant_name,
        'job_title': job_title,
        'link': full_link,
    })

    # ✅ Send the email
    try:
        send_mail(
            subject,
            '',  # plain text version not needed
            settings.DEFAULT_FROM_EMAIL,
            [cv.applicant_email],
            html_message=html_message,
            fail_silently=False,
        )
        messages.success(request, f"✅ Application link sent to {cv.applicant_email}.")
    except Exception as e:
        messages.error(request, f"❌ Failed to send email: {e}")

    # ✅ Redirect to correct HR page
    if cv.job:
        return redirect('view-cv-submissions', job_pk=cv.job.pk)
    else:
        return redirect('view-general-submissions')
    
@login_required
@user_passes_test(is_hr_user)
def view_detailed_applications(request, job_pk=None):
    """Lists all detailed applications (with search and job filter)."""
    applications = DetailedApplication.objects.filter(link__created_by=request.user)
    
    job_id = request.GET.get('job', '').strip()
    query = request.GET.get('q', '').strip()

    job = None # Initialize job as None
    if job_id:
        applications = applications.filter(link__job__id=job_id)
        # 💡 We must fetch the job object here so we can pass it to the template
        job = get_object_or_404(Job, pk=job_id, created_by=request.user)

    if query:
        applications = applications.filter(
            Q(full_name__icontains=query) |
            Q(email__icontains=query)
        )

    applications = applications.order_by('-submitted_at')

    context = {
        'applications': applications,
        'search_query': query or '',
        'job': job,
    }
    return render(request, 'jobs/detailed_application_list.html', context)

@login_required
@user_passes_test(is_hr_user)
def view_general_applications(request):
    """Show applications submitted via general links (no specific job)."""
    applications = DetailedApplication.objects.filter(link__job__isnull=True).order_by('-submitted_at')
    
    context = {
        'applications': applications,
        'jobs': Job.objects.filter(created_by=request.user),  # needed for the dropdown filter
        'is_general_page': True,
    }
    return render(request, 'jobs/detailed_application_list.html', context)

@login_required
@user_passes_test(is_hr_user)
def view_general_submissions(request):
    """Displays general CVs not linked to any specific job, with search and department filter."""
    query = request.GET.get('q', '').strip()
    department = request.GET.get('department', '').strip()

    submissions = CVSubmission.objects.filter(job__isnull=True).order_by('-submitted_at')

    # 🔍 Apply filters
    if query:
        submissions = submissions.filter(
            Q(applicant_name__icontains=query) |
            Q(applicant_email__icontains=query)
        )

    if department:
        submissions = submissions.filter(department=department)
        
    for cv in submissions:
        if not cv.viewed:
            cv.viewed = True
            cv.save(update_fields=['viewed'])

    # ✅ Dropdown departments (sorted & distinct)
    departments = (
        CVSubmission.objects.filter(job__isnull=True)
        .exclude(department__exact='')
        .values_list('department', flat=True)
        .distinct()
        .order_by('department')
    )

    context = {
        'job': None,  # cv_list.html expects job
        'submissions': submissions,
        'query': query,
        'departments': departments,
        'selected_department': department,
        'filter_enabled': True,  # 🔹 Show filter in general CVs page
    }
    return render(request, 'jobs/cv_list.html', context)

@login_required
@user_passes_test(is_hr_user)
def update_application_status(request, pk):
    """Handles saving applicant details and interview statuses + stage progression."""
    application = get_object_or_404(DetailedApplication, pk=pk, link__created_by=request.user)
    if not application.viewed:
        application.viewed = True
        application.save(update_fields=['viewed'])

    # Store old statuses to check what changed
    old_statuses = {
        'phone': application.phone_status,
        'hr': application.hr_status,
        'technical': application.technical_status,
        'ceo': application.ceo_status,
    }

    details_form = DetailedApplicationForm(request.POST or None, instance=application)
    status_form = ApplicationStatusUpdateForm(request.POST or None, instance=application)

    if request.method == 'POST':
        payload = request.POST.dict()
        # --- Save Applicant Details ---
        if 'save_details' in payload:
            if details_form.is_valid():
                details_form.save()
                messages.success(request, f"✅ Applicant details for {application.full_name} updated successfully.")
            else:
                messages.error(request, "❌ Please correct the applicant details form.")

        # --- Save Interview Status ---
        elif 'save_status' in payload:
            if status_form.is_valid():
                application = status_form.save(commit=False)

                # --- Determine overall status automatically ---
                if application.ceo_status == DetailedApplication.STATUS_PASSED:
                    application.overall_status = DetailedApplication.OVERALL_STATUS_HIRED
                elif any(
                    s == DetailedApplication.STATUS_FAILED
                    for s in [
                        application.phone_status,
                        application.hr_status,
                        application.technical_status,
                        application.ceo_status,
                    ]
                ):
                    application.overall_status = DetailedApplication.OVERALL_STATUS_REJECTED
                else:
                    application.overall_status = DetailedApplication.OVERALL_STATUS_REVIEW

                application.save()
                # --- Check for changes and send emails ---
                new_statuses = {
                    'phone': application.phone_status,
                    'hr': application.hr_status,
                    'technical': application.technical_status,
                    'ceo': application.ceo_status,
                }

                stage_names = {
                    'phone': 'Phone Interview',
                    'hr': 'HR Interview',
                    'technical': 'Technical Interview',
                    'ceo': 'CEO Interview',
                }
                messages.success(request, f"✅ Interview status for {application.full_name} updated successfully.")
                for stage_key in stage_names.keys():
                    old_s = old_statuses[stage_key]
                    new_s = new_statuses[stage_key]

                    # If status changed from 'pending' to something else
                    if old_s == DetailedApplication.STATUS_PENDING and new_s != DetailedApplication.STATUS_PENDING:
                        stage_name = stage_names[stage_key]
                        comment = getattr(application, f"{stage_key}_comment")
                        try:
                            send_applicant_notification(application, stage_name, new_s, comment)
                        except Exception as e:
                            messages.error(request, f"Failed to send email: {e}")
            else:
                messages.error(request, "❌ Please correct errors in the interview status form.")
        
        return redirect('update-application-status', pk=application.pk)

    return render(request, 'jobs/application_status_form.html', {
        'details_form': details_form,
        'status_form': status_form,
        'application': application,
    })

@login_required
@user_passes_test(is_hr_user)
def ajax_search_applications(request):
    """Live search for detailed applications (works for specific job or all)."""
    query = request.GET.get("q", "").strip()
    job_id = request.GET.get("job", "").strip() # This can now be an ID, "general", or ""
    status = request.GET.get("status", "").strip()

    applications = DetailedApplication.objects.filter(link__created_by=request.user)

    if job_id == "general":
        # Filter for general applications only
        applications = applications.filter(link__job__isnull=True)
    elif job_id:
        # Filter for a specific job ID
        applications = applications.filter(link__job__id=job_id)
        
    # ✅ Search inside that job only
    if query:
        applications = applications.filter(
            Q(full_name__icontains=query) |
            Q(email__icontains=query)
        )

    if status:
        applications = applications.filter(overall_status=status)

    applications = applications.select_related("link__job").only(
        "id", "full_name", "phone_status", "hr_status",
        "technical_status", "ceo_status", "overall_status", "link__job__title"
    )[:30]

    data = [
        {
            "id": app.id,
            "full_name": app.full_name,
            "job_title": getattr(app.link.job, "title", "General Application"),
            
            # Use render_to_string to pre-build the icon HTML
            "phone_status_html": render_to_string('jobs/includes/status_icon.html', {'status': app.phone_status}),
            "hr_status_html": render_to_string('jobs/includes/status_icon.html', {'status': app.hr_status}),
            "technical_status_html": render_to_string('jobs/includes/status_icon.html', {'status': app.technical_status}),
            "ceo_status_html": render_to_string('jobs/includes/status_icon.html', {'status': app.ceo_status}),
            
            "overall_status": app.overall_status,
        }
        for app in applications
    ]

    return JsonResponse({"results": data})

def ajax_search_jobs(request):
    query = request.GET.get("q", "").strip()
    department = request.GET.get("department", "").strip()
    location = request.GET.get("location", "").strip()

    jobs = Job.objects.filter(is_active=True)

    if query:
        jobs = jobs.filter(
            Q(title__icontains=query) | Q(description__icontains=query) | Q(location__icontains=query)
        )
    if department:
        jobs = jobs.filter(department=department)

    if location:
        jobs = jobs.filter(location=location)

    jobs = jobs.order_by("-created_at")[:30]

    data = {
        "results": [
            {
                "id": job.id,
                "title": job.title,
                "location": job.location or "—",
                "description": (job.description[:120] + "...") if len(job.description) > 120 else job.description,
                "created_since": timesince(job.created_at) + " ago",
            }
            for job in jobs
        ]
    }
    return JsonResponse(data)

# 1- CVs database - folders(departments)
@login_required
@user_passes_test(is_hr_user)
def cv_database_folders(request):
    """
    Displays a 'Folder' view of all CVs grouped by department.
    """
    # Group by department and count how many CVs are in each
    departments = (
        CVSubmission.objects
        .values('department')
        .annotate(count=Count('id'))
        .order_by('department')
    )
    
    return render(request, 'jobs/cv_database_folders.html', {
        'departments': departments
    })

@login_required
@user_passes_test(is_hr_user)
def view_department_cvs(request, department_name):
    """
    Lists all CVs belonging to a specific department folder.
    """
    submissions = CVSubmission.objects.filter(department=department_name).order_by('-submitted_at')
    
    # Optional: Add search functionality specific to this folder
    query = request.GET.get('q', '').strip()
    if query:
        submissions = submissions.filter(
            Q(applicant_name__icontains=query) |
            Q(applicant_email__icontains=query)
        )

    context = {
        'submissions': submissions,
        'department_name': department_name,
        'query': query,
        'job': None, # We pass None because this isn't for a specific job post
    }
    # We reuse your existing cv_list.html but you might need to tweak it slightly
    # to show "Department: Marketing" instead of "Job: X"
    return render(request, 'jobs/cv_list.html', context)