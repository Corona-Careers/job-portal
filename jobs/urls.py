from django.urls import path
from . import views
from django.shortcuts import render

urlpatterns = [
    # Applicant Facing URLs
    path('', views.JobListView.as_view(), name='job-list'),
    path('job/<int:pk>/', views.JobDetailView.as_view(), name='job-detail'),
    path('apply/<uuid:token>/', views.application_form_view, name='application-form'),
    path('application-success/', lambda request: render(request, 'jobs/application_success.html'), name='application-success'),
    # HR Facing URLs
    path('hr/dashboard/', views.hr_dashboard, name='hr-dashboard'),
    path('hr/job/new/', views.JobCreateView.as_view(), name='job-create'),
    path('hr/job/<int:pk>/update/', views.JobUpdateView.as_view(), name='job-update'),
    path('hr/job/<int:pk>/delete/', views.JobDeleteView.as_view(), name='job-delete'),
    path('hr/job/<int:pk>/toggle-status/', views.toggle_job_status, name='job-toggle-status'),
    path('hr/job/<int:job_pk>/submissions/', views.view_cv_submissions, name='view-cv-submissions'),
    path('hr/links/generate/', views.generate_application_link, name='generate-link'),
    path('hr/applications/', views.view_detailed_applications, name='view-detailed-applications'), 
    path('dashboard/application/<int:pk>/status/', views.update_application_status, name='update-application-status'),
    path('applications/search/', views.ajax_search_applications, name='ajax-search-applications'),
    path('jobs/search/', views.ajax_search_jobs, name='ajax-search-jobs'),
    path('generate-link-from-cv/<int:cv_id>/', views.generate_link_from_cv, name='generate-link-from-cv'),
    path('hr/general-submissions/', views.view_general_submissions, name='view-general-submissions'),
    path('hr/general-applications/', views.view_general_applications, name='view-general-applications'),
    path('apply/general/', views.JobDetailView.as_view(), name='general-application'),
    path('hr/cv-database/', views.cv_database_folders, name='cv-database-folders'),
    path('hr/cv-database/<str:department_name>/', views.view_department_cvs, name='view-department-cvs'),
]   
