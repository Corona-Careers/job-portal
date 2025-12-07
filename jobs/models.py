import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Job(models.Model):
    """
    Represents a job posting in the system.
    """
    DEPARTMENT_CHOICES = [
        ('marketing', 'Marketing'),
        ('hr', 'Human Resources'),
        ('it', 'Information Technology'),
        ('finance', 'Finance'),
        ('sales', 'Sales'),
        ('production', 'Production'),
    ]
    title = models.CharField(max_length=200)
    department = models.CharField(max_length=50, choices=DEPARTMENT_CHOICES, blank=True, null=True)
    description = models.TextField()
    requirements = models.TextField()
    location = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True, help_text="Designates whether the job is currently active and visible to applicants.")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posted_jobs')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

class CVSubmission(models.Model):
    """
    Represents a CV submitted by an applicant for a specific job.
    """
    DEPARTMENT_CHOICES = [
        ('HR', 'Human Resources'),
        ('IT', 'Information Technology'),
        ('Finance', 'Finance'),
        ('Sales', 'Sales'),
        ('Marketing', 'Marketing'),
        ('Operations', 'Operations'),
    ]
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, related_name='submissions',
    null=True, blank=True)
    applicant_name = models.CharField(max_length=150)
    applicant_email = models.EmailField()
    cv_file = models.FileField(upload_to='cvs/')
    department = models.CharField(max_length=50, choices=DEPARTMENT_CHOICES, default='HR')
    submitted_at = models.DateTimeField(auto_now_add=True)
    viewed = models.BooleanField(default=False)
    def save(self, *args, **kwargs):
        # 1. Clean the department name before saving
        if self.department:
            # strip() removes spaces at the end
            # title() makes it "Marketing", "Sales", "It" (You might prefer .upper() for "IT")
            
            clean_dept = self.department.strip()
            
            # Special case for IT to be uppercase
            if clean_dept.lower() == 'it':
                self.department = 'IT'
            elif clean_dept.lower() == 'hr':
                self.department = 'HR'
            else:
                self.department = clean_dept.title() # Marketing, Sales, etc.
                
        super().save(*args, **kwargs)
    def __str__(self):
        return f"CV for {self.job.title} from {self.applicant_name}"

class ApplicationLink(models.Model):
    """
    Represents a temporary, single-use link for a detailed application.
    Can be linked to a specific job or be a general application link.
    """
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, blank=True, related_name='application_links')
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='generated_links')
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        job_title = self.job.title if self.job else "General Application"
        return f"Link for {job_title} - Expires {self.expires_at.strftime('%Y-%m-%d %H:%M')}"

class DetailedApplication(models.Model):
    full_name = models.CharField(max_length=255, db_index=True)
    email = models.EmailField(db_index=True)
    """
    Represents a detailed application submitted through a temporary link.
    """
    STATUS_PENDING = 'pending'
    STATUS_PASSED = 'passed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PASSED, 'Passed'),
        (STATUS_FAILED, 'Failed'),
    ]

    OVERALL_STATUS_REVIEW = 'review'
    OVERALL_STATUS_HIRED = 'hired'
    OVERALL_STATUS_REJECTED = 'rejected'
    OVERALL_STATUS_CHOICES = [
        (OVERALL_STATUS_REVIEW, 'In Review'),
        (OVERALL_STATUS_HIRED, 'Hired'),
        (OVERALL_STATUS_REJECTED, 'Rejected'),
    ]

    link = models.OneToOneField(ApplicationLink, on_delete=models.CASCADE, related_name='application_details')
    full_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone_number = models.CharField(max_length=20)
    cover_letter = models.TextField(blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    viewed = models.BooleanField(default=False)
    interview_date = models.DateTimeField(null=True, blank=True, help_text="Date and time of the next interview")

    # --- New Status Fields ---
    overall_status = models.CharField(
        max_length=10, 
        choices=OVERALL_STATUS_CHOICES, 
        default=OVERALL_STATUS_REVIEW
    )

    phone_status = models.CharField(
        max_length=10, 
        choices=STATUS_CHOICES, 
        default=STATUS_PENDING
    )
    phone_comment = models.TextField(blank=True, null=True, verbose_name="Phone Interview Comment")
    
    hr_status = models.CharField(
        max_length=10, 
        choices=STATUS_CHOICES, 
        default=STATUS_PENDING
    )
    hr_comment = models.TextField(blank=True, null=True, verbose_name="HR Interview Comment")
    
    technical_status = models.CharField(
        max_length=10, 
        choices=STATUS_CHOICES, 
        default=STATUS_PENDING
    )
    technical_comment = models.TextField(blank=True, null=True, verbose_name="Technical Interview Comment")
    
    ceo_status = models.CharField(
        max_length=10, 
        choices=STATUS_CHOICES, 
        default=STATUS_PENDING
    )
    ceo_comment = models.TextField(blank=True, null=True, verbose_name="CEO Interview Comment")

    @property
    def current_stage(self):
        """
        Derives the current active stage based on the status of previous stages.
        This enforces the sequential logic.
        """
        if self.overall_status != self.OVERALL_STATUS_REVIEW:
            return 5  # 5 means 'Completed' (Hired/Rejected)

        if self.phone_status == self.STATUS_PENDING:
            return 1  # Phone
        
        if self.phone_status == self.STATUS_PASSED and self.hr_status == self.STATUS_PENDING:
            return 2  # HR
        
        if self.hr_status == self.STATUS_PASSED and self.technical_status == self.STATUS_PENDING:
            return 3  # Technical
            
        if self.technical_status == self.STATUS_PASSED and self.ceo_status == self.STATUS_PENDING:
            return 4  # CEO
            
        return 5 # Completed

    def __str__(self):
        return f"Detailed application from {self.full_name}"

