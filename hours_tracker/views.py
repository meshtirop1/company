from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum
from django.contrib import messages
from .models import CustomUser, WorkHours, Holiday, Settings
import calendar
from datetime import datetime
from django.http import HttpResponseRedirect
from django.urls import reverse
import logging

logger = logging.getLogger(__name__)

def home(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"home - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'home_{lang}.html'
    if request.user.is_authenticated:
        return redirect('calendar')
    return redirect('login')

def login_view(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"login_view - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'login_{lang}.html'
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('calendar')
        messages.error(request, 'Invalid email or password.' if lang == 'en' else '잘못된 이메일 또는 비밀번호입니다.')
    else:
        form = AuthenticationForm()
    return render(request, template, {'form': form})

@login_required
def logout_view(request):
    if request.method == 'POST':
        logout(request)
        return redirect('login')
    return redirect('calendar')

@login_required
def calendar_view(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"calendar_view - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'calendar_{lang}.html'
    logger.debug(f"calendar_view - Rendering template: {template}")
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    cal = calendar.monthcalendar(year, month)
    work_hours = WorkHours.objects.filter(user=request.user, date__year=year, date__month=month)
    holidays = Holiday.objects.filter(date__year=year, date__month=month)
    total_hours = sum(h.hours for h in work_hours if not h.is_absence)
    total_salary = total_hours * request.user.hourly_wage
    weeks = []
    for week in cal:
        week_days = []
        for day in week:
            if day == 0:
                week_days.append({'day': None})
            else:
                day_data = {'day': day, 'hours': None, 'is_absence': False, 'holiday': None}
                for wh in work_hours:
                    if wh.date.day == day:
                        day_data['hours'] = wh.hours
                        day_data['is_absence'] = wh.is_absence
                for holiday in holidays:
                    if holiday.date.day == day:
                        day_data['holiday'] = holiday.name
                week_days.append(day_data)
        weeks.append(week_days)
    context = {
        'weeks': weeks,
        'year': year,
        'month': month,
        'total_hours': total_hours,
        'total_salary': total_salary,
        'prev_year': year if month > 1 else year - 1,
        'prev_month': month - 1 if month > 1 else 12,
        'next_year': year if month < 12 else year + 1,
        'next_month': month + 1 if month < 12 else 1,
        'month_name': calendar.month_name[month] if lang == 'en' else f'{month}월',
    }
    return render(request, template, context)

@login_required
def employee_calendar_view(request, user_id):
    lang = request.session.get('language', 'en')
    logger.debug(f"employee_calendar_view - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'calendar_{lang}.html'
    logger.debug(f"employee_calendar_view - Rendering template: {template}")
    if not request.user.is_superuser:
        return redirect('calendar')
    try:
        employee = CustomUser.objects.get(id=user_id, is_employee=True)
    except CustomUser.DoesNotExist:
        messages.error(request, 'Employee not found or not an employee.' if lang == 'en' else '직원이 없거나 직원이 아닙니다.')
        return redirect('superuser_dashboard')

    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    cal = calendar.monthcalendar(year, month)
    work_hours = WorkHours.objects.filter(user=employee, date__year=year, date__month=month)
    holidays = Holiday.objects.filter(date__year=year, date__month=month)
    total_hours = sum(h.hours for h in work_hours if not h.is_absence)
    total_salary = total_hours * employee.hourly_wage
    weeks = []
    for week in cal:
        week_days = []
        for day in week:
            if day == 0:
                week_days.append({'day': None})
            else:
                day_data = {'day': day, 'hours': None, 'is_absence': False, 'holiday': None}
                for wh in work_hours:
                    if wh.date.day == day:
                        day_data['hours'] = wh.hours
                        day_data['is_absence'] = wh.is_absence
                for holiday in holidays:
                    if holiday.date.day == day:
                        day_data['holiday'] = holiday.name
                week_days.append(day_data)
        weeks.append(week_days)
    context = {
        'weeks': weeks,
        'year': year,
        'month': month,
        'total_hours': total_hours,
        'total_salary': total_salary,
        'prev_year': year if month > 1 else year - 1,
        'prev_month': month - 1 if month > 1 else 12,
        'next_year': year if month < 12 else year + 1,
        'next_month': month + 1 if month < 12 else 1,
        'month_name': calendar.month_name[month] if lang == 'en' else f'{month}월',
        'employee_email': employee.email,
    }
    return render(request, template, context)

@login_required
def admin_panel(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"admin_panel - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'admin_panel_{lang}.html'
    logger.debug(f"admin_panel - Rendering template: {template}")
    if not (request.user.is_admin or request.user.is_superuser):
        return redirect('calendar')
    return render(request, template)

@login_required
def bulk_hours_view(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"bulk_hours_view - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'bulk_hours_{lang}.html'
    logger.debug(f"bulk_hours_view - Rendering template: {template}")
    if not (request.user.is_admin or request.user.is_superuser):
        return redirect('calendar')
    users = CustomUser.objects.filter(is_employee=True)
    default_date = timezone.now().date()
    selected_date_str = request.POST.get('date', default_date.isoformat())
    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = default_date
        messages.error(request, 'Invalid date format. Using today\'s date.' if lang == 'en' else '잘못된 날짜 형식입니다. 오늘 날짜를 사용합니다.')

    if request.method == 'POST':
        try:
            hours = request.POST.get('bulk_hours')
            if hours:
                hours = float(hours)
                if hours < 0:
                    messages.error(request, 'Hours cannot be negative.' if lang == 'en' else '근무 시간은 음수일 수 없습니다.')
                else:
                    for user in users:
                        WorkHours.objects.update_or_create(
                            user=user, date=selected_date, defaults={'hours': hours, 'is_absence': False}
                        )
                    messages.success(request, 'Bulk hours updated successfully.' if lang == 'en' else '일괄 근무 시간이 성공적으로 업데이트되었습니다.')
            else:
                messages.error(request, 'Please provide a valid number of hours.' if lang == 'en' else '유효한 근무 시간을 입력해 주세요.')
        except ValueError as e:
            messages.error(request, f'Invalid input: {str(e)}.' if lang == 'en' else f'잘못된 입력: {str(e)}.')

    work_hours = WorkHours.objects.filter(date=selected_date)
    context = {
        'users': users,
        'selected_date': selected_date,
        'work_hours': work_hours,
    }
    return render(request, template, context)

@login_required
def individual_hours_view(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"individual_hours_view - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'individual_hours_{lang}.html'
    logger.debug(f"individual_hours_view - Rendering template: {template}")
    if not (request.user.is_admin or request.user.is_superuser):
        return redirect('calendar')
    users = CustomUser.objects.filter(is_employee=True)
    default_date = timezone.now().date()
    selected_date_str = request.POST.get('date', default_date.isoformat())
    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = default_date
        messages.error(request, 'Invalid date format. Using today\'s date.' if lang == 'en' else '잘못된 날짜 형식입니다. 오늘 날짜를 사용합니다.')

    if request.method == 'POST':
        try:
            for user in users:
                hours = request.POST.get(f'hours_{user.id}')
                is_absence = f'absence_{user.id}' in request.POST
                if is_absence:
                    WorkHours.objects.update_or_create(
                        user=user, date=selected_date, defaults={'hours': 0, 'is_absence': True}
                    )
                elif hours:
                    hours = float(hours)
                    if hours < 0:
                        messages.error(request, f'Hours for {user.email} cannot be negative.' if lang == 'en' else f'{user.email}의 근무 시간은 음수일 수 없습니다.')
                    else:
                        WorkHours.objects.update_or_create(
                            user=user, date=selected_date, defaults={'hours': hours, 'is_absence': False}
                        )
            messages.success(request, 'Individual hours/absences updated successfully.' if lang == 'en' else '개인 근무 시간/결근이 성공적으로 업데이트되었습니다.')
        except ValueError as e:
            messages.error(request, f'Invalid input: {str(e)}.' if lang == 'en' else f'잘못된 입력: {str(e)}.')

    work_hours = WorkHours.objects.filter(date=selected_date)
    context = {
        'users': users,
        'selected_date': selected_date,
        'work_hours': work_hours,
    }
    return render(request, template, context)

@login_required
def bulk_absence_view(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"bulk_absence_view - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'bulk_absence_{lang}.html'
    logger.debug(f"bulk_absence_view - Rendering template: {template}")
    if not (request.user.is_admin or request.user.is_superuser):
        return redirect('calendar')
    users = CustomUser.objects.filter(is_employee=True)
    default_date = timezone.now().date()
    selected_date_str = request.POST.get('date', default_date.isoformat())
    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = default_date
        messages.error(request, 'Invalid date format. Using today\'s date.' if lang == 'en' else '잘못된 날짜 형식입니다. 오늘 날짜를 사용합니다.')

    if request.method == 'POST':
        try:
            for user in users:
                WorkHours.objects.update_or_create(
                    user=user, date=selected_date, defaults={'hours': 0, 'is_absence': True}
                )
            messages.success(request, 'All employees marked as absent.' if lang == 'en' else '모든 직원이 결근으로 표시되었습니다.')
        except ValueError as e:
            messages.error(request, f'Invalid input: {str(e)}.' if lang == 'en' else f'잘못된 입력: {str(e)}.')

    work_hours = WorkHours.objects.filter(date=selected_date)
    context = {
        'users': users,
        'selected_date': selected_date,
        'work_hours': work_hours,
    }
    return render(request, template, context)

@login_required
def superuser_dashboard(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"superuser_dashboard - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'superuser_dashboard_{lang}.html'
    logger.debug(f"superuser_dashboard - Rendering template: {template}")
    if not request.user.is_superuser:
        return redirect('calendar')
    users = CustomUser.objects.filter(is_employee=True)
    user_data = []
    total_salary = 0
    for user in users:
        total_hours = WorkHours.objects.filter(user=user, is_absence=False).aggregate(
            total_hours=Sum('hours')
        )['total_hours'] or 0
        absences = WorkHours.objects.filter(user=user, is_absence=True).count()
        user_salary = total_hours * user.hourly_wage
        total_salary += user_salary
        user_data.append({
            'user_id': user.id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'account_number': user.account_number,
            'is_contracted': user.is_contracted,
            'visa_type': user.visa_type,
            'bank_name': user.bank_name,
            'total_hours': total_hours,
            'absences': absences,
            'salary': user_salary,
        })
    context = {
        'user_data': user_data,
        'total_salary': total_salary,
    }
    return render(request, template, context)

@login_required
def manage_users(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"manage_users - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'manage_users_{lang}.html'
    logger.debug(f"manage_users - Rendering template: {template}")
    if not (request.user.is_admin or request.user.is_superuser):
        return redirect('calendar')
    if request.method == 'POST':
        if 'set_minimum_wage' in request.POST:
            minimum_wage = request.POST.get('minimum_wage', 0.00)
            Settings.objects.update_or_create(id=1, defaults={'minimum_wage': minimum_wage})
            messages.success(request, 'Minimum wage updated successfully.' if lang == 'en' else '최저 임금이 성공적으로 업데이트되었습니다.')
        elif 'delete_user' in request.POST:
            user_id = request.POST.get('delete_user')
            try:
                user = CustomUser.objects.get(id=user_id)
                if request.user.is_superuser or (request.user.is_admin and not user.is_superuser):
                    user.delete()
                    messages.success(request, 'User deleted successfully.' if lang == 'en' else '사용자가 성공적으로 삭제되었습니다.')
                else:
                    messages.error(request, 'You do not have permission to delete this user.' if lang == 'en' else '이 사용자를 삭제할 권한이 없습니다.')
            except CustomUser.DoesNotExist:
                messages.error(request, 'User not found.' if lang == 'en' else '사용자를 찾을 수 없습니다.')
    users = CustomUser.objects.all()
    settings, created = Settings.objects.get_or_create(id=1)
    context = {
        'users': users,
        'minimum_wage': settings.minimum_wage,
    }
    return render(request, template, context)

@login_required
def register_employee(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"register_employee - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'register_employee_{lang}.html'
    logger.debug(f"register_employee - Rendering template: {template}")
    if not (request.user.is_admin or request.user.is_superuser):
        return redirect('calendar')
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        account_number = request.POST.get('account_number', '')
        is_contracted = 'is_contracted' in request.POST
        visa_type = request.POST.get('visa_type', '')
        bank_name = request.POST.get('bank_name', '')
        hourly_wage = request.POST.get('hourly_wage', 0.00)
        is_employee = 'is_employee' in request.POST
        is_admin = 'is_admin' in request.POST
        if email and password:
            try:
                CustomUser.objects.create_user(
                    email=email, username=email, password=password,
                    first_name=first_name, last_name=last_name, account_number=account_number,
                    is_contracted=is_contracted, visa_type=visa_type, bank_name=bank_name,
                    hourly_wage=hourly_wage, is_employee=is_employee, is_admin=is_admin
                )
                messages.success(request, 'Employee registered successfully.' if lang == 'en' else '직원이 성공적으로 등록되었습니다.')
                return redirect('manage_users')
            except Exception as e:
                messages.error(request, f'Failed to register employee: {str(e)}.' if lang == 'en' else f'직원 등록 실패: {str(e)}.')
    return render(request, template)


@login_required
def manage_holidays(request):
    lang = request.session.get('language', 'en')
    logger.debug(f"manage_holidays - Session language: {lang}, Session key: {request.session.session_key}")
    template = f'manage_holidays_{lang}.html'
    logger.debug(f"manage_holidays - Rendering template: {template}")

    if not (request.user.is_admin):  # Make sure 'is_admin' is a valid check on your user model
        messages.error(request,
                       "You do not have permission to access this page." if lang == 'en' else "이 페이지에 접근할 권한이 없습니다.")
        return redirect('calendar')  # Or another appropriate URL like 'home'

    if request.method == 'POST':
        action_taken = False  # Flag to see if we should redirect

        if 'add_holiday' in request.POST:
            action_taken = True
            date_str = request.POST.get('date')
            name = request.POST.get('name')

            # Basic validation (since you're not using a Django Form)
            if not date_str or not name:
                messages.error(request, 'Date and name are required.' if lang == 'en' else '날짜와 이름은 필수입니다.')
            else:
                try:
                    # This is where an invalid date_str format can cause an error
                    Holiday.objects.create(date=date_str, name=name)
                    messages.success(request, 'Holiday added successfully.' if lang == 'en' else '공휴일이 성공적으로 추가되었습니다.')
                except Exception as e:
                    logger.error(f"Failed to add holiday. Date: '{date_str}', Name: '{name}', Error: {str(e)}")
                    messages.error(request,
                                   f'Failed to add holiday: {str(e)}.' if lang == 'en' else f'공휴일 추가 실패: {str(e)}.')

        elif 'delete_holiday' in request.POST:
            action_taken = True
            holiday_id = request.POST.get('delete_holiday')  # This assumes the button's value is the holiday ID

            if not holiday_id:
                messages.error(request,
                               'No holiday ID provided for deletion.' if lang == 'en' else '삭제할 공휴일 ID가 제공되지 않았습니다.')
            else:
                try:
                    holiday = Holiday.objects.get(id=holiday_id)
                    holiday_name = holiday.name  # For a more informative message
                    holiday.delete()
                    messages.success(request,
                                     f"Holiday '{holiday_name}' deleted successfully." if lang == 'en' else f"공휴일 '{holiday_name}'이(가) 성공적으로 삭제되었습니다.")
                except Holiday.DoesNotExist:
                    messages.error(request, 'Holiday not found.' if lang == 'en' else '공휴일을 찾을 수 없습니다.')
                except Exception as e:
                    logger.error(f"Failed to delete holiday ID {holiday_id}. Error: {str(e)}")
                    messages.error(request,
                                   f'Failed to delete holiday: {str(e)}.' if lang == 'en' else f'공휴일 삭제 실패: {str(e)}.')

        if action_taken:
            # After processing the add or delete action, redirect to the same page (GET request)
            return redirect('manage_holidays')  # Replace 'manage_holidays' with the actual URL name

    # This part now primarily handles GET requests, or POST requests that didn't match an action (though ideally all POSTs should redirect)
    holidays = Holiday.objects.all().order_by('date')  # Good to order them for consistent display
    context = {
        'holidays': holidays,
    }
    return render(request, template, context)

def set_language(request):
    logger.debug(f"set_language called with method: {request.method}, session_key: {request.session.session_key}")
    logger.debug(f"set_language - Current session language: {request.session.get('language', 'none')}")
    logger.debug(f"set_language - Raw POST data: {request.POST}")
    if request.method == 'POST':
        logger.debug(f"set_language - Full POST body: {request.body}")
        language = request.POST.get('language')
        next_url = request.POST.get('next', reverse('home'))
        logger.debug(f"set_language - Parsed POST data - Language: {language}, Next: {next_url}")
        if language in ['en', 'ko']:
            request.session['language'] = language
            request.session.modified = True
            logger.debug(f"set_language - Session updated - new language: {request.session['language']}")
        else:
            logger.warning(f"set_language - Invalid or missing language: {language}")
        logger.debug(f"set_language - Redirecting to: {next_url}")
        response = HttpResponseRedirect(next_url)
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
    logger.debug("set_language - Non-POST request, redirecting to home")
    return redirect('home')


# In your views.py (e.g., main_app/views.py)
from django.shortcuts import render
from django.conf import settings
from django.template.exceptions import TemplateDoesNotExist
import logging

logger = logging.getLogger(__name__)


def custom_page_not_found_view(request, exception):
    # The 'exception' argument is required by Django for 404 handlers
    lang = request.session.get('language', getattr(settings, 'LANGUAGE_CODE', 'en'))
    template_name = f'404_{lang}.html'

    logger.warning(
        f"Page not found (404): {request.path}. Attempting to render {template_name}. Exception: {exception}")

    try:
        return render(request, template_name, status=404)
    except TemplateDoesNotExist:
        logger.error(f"Template {template_name} not found. Falling back to 404_en.html.")
        return render(request, '404_en.html', status=404)  # Fallback
    except Exception as e:
        logger.error(f"Error rendering {template_name}: {e}. Falling back to 404_en.html.")
        return render(request, '404_en.html', status=404)


def custom_server_error_view(request):
    lang = request.session.get('language', getattr(settings, 'LANGUAGE_CODE', 'en'))
    template_name = f'500_{lang}.html'

    logger.error(f"Server error (500) encountered for path: {request.path}. Attempting to render {template_name}.")

    try:
        return render(request, template_name, status=500)
    except TemplateDoesNotExist:
        logger.error(f"Template {template_name} not found. Falling back to 500_en.html.")
        return render(request, '500_en.html', status=500)  # Fallback
    except Exception as e:
        # Be very careful here not to cause another error.
        logger.error(f"Critical error rendering {template_name}: {e}. Falling back to basic 500_en.html.")
        # In a dire situation, you might return a HttpResponse with plain text if 500_en.html also fails.
        return render(request, '500_en.html', status=500)