from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, date, timedelta
from sqlalchemy import func, and_, or_, extract
import calendar
from app import db
from app.models import User, Employee, Attendance, LeaveRequest, Payroll, Notification, PreRegisteredEmployee

bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    """Decorator to ensure user is admin/HR"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin():
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/dashboard')
@admin_required
def dashboard():
    """Admin dashboard with statistics"""
    # Employee statistics
    total_employees = Employee.query.filter_by(status='Active').count()
    total_departments = db.session.query(func.count(func.distinct(Employee.department))).scalar()
    
    # Today's attendance
    today = date.today()
    today_present = Attendance.query.filter_by(date=today, status='Present').count()
    today_absent = Attendance.query.filter(
        Attendance.date == today,
        Attendance.status.in_(['Absent', 'Half-day'])
    ).count()
    today_on_leave = Attendance.query.filter_by(date=today, status='Leave').count()
    
    # Pending leave requests
    pending_leaves = LeaveRequest.query.filter_by(status='Pending').count()
    
    # This month's payroll status
    current_month = datetime.now().month
    current_year = datetime.now().year
    processed_payrolls = Payroll.query.filter_by(
        month=current_month,
        year=current_year,
        status='Processed'
    ).count()
    pending_payrolls = total_employees - processed_payrolls
    
    # Recent activities
    recent_employees = Employee.query.order_by(Employee.created_at.desc()).limit(5).all()
    recent_leaves = LeaveRequest.query.order_by(LeaveRequest.created_at.desc()).limit(5).all()
    
    # Department-wise employee count
    dept_stats = db.session.query(
        Employee.department,
        func.count(Employee.id).label('count')
    ).filter(Employee.status == 'Active').group_by(Employee.department).all()
    
    return render_template('admin/dashboard.html',
                         total_employees=total_employees,
                         total_departments=total_departments,
                         today_present=today_present,
                         today_absent=today_absent,
                         today_on_leave=today_on_leave,
                         pending_leaves=pending_leaves,
                         processed_payrolls=processed_payrolls,
                         pending_payrolls=pending_payrolls,
                         recent_employees=recent_employees,
                         recent_leaves=recent_leaves,
                         dept_stats=dept_stats)

@bp.route('/employees')
@admin_required
def employees():
    """List all employees"""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    department = request.args.get('department', '')
    status = request.args.get('status', 'Active')
    
    query = Employee.query
    
    if search:
        query = query.join(User).filter(
            or_(
                Employee.first_name.ilike(f'%{search}%'),
                Employee.last_name.ilike(f'%{search}%'),
                User.employee_id.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%')
            )
        )
    
    if department:
        query = query.filter_by(department=department)
    
    if status:
        query = query.filter_by(status=status)
    
    employees_list = query.order_by(Employee.created_at.desc()).paginate(
        page=page,
        per_page=current_app.config['ITEMS_PER_PAGE'],
        error_out=False
    )
    
    # Get all departments for filter
    departments = db.session.query(Employee.department).distinct().all()
    departments = [d[0] for d in departments if d[0]]
    
    return render_template('admin/employees.html',
                         employees=employees_list,
                         departments=departments,
                         search=search,
                         selected_dept=department,
                         selected_status=status)

@bp.route('/employees/<int:employee_id>')
@admin_required
def employee_detail(employee_id):
    """View employee details"""
    employee = Employee.query.get_or_404(employee_id)
    
    # Get recent attendance
    recent_attendance = Attendance.query.filter_by(
        employee_id=employee.id
    ).order_by(Attendance.date.desc()).limit(10).all()
    
    # Get recent leaves
    recent_leaves = LeaveRequest.query.filter_by(
        employee_id=employee.id
    ).order_by(LeaveRequest.created_at.desc()).limit(5).all()
    
    # Get latest payroll
    latest_payroll = Payroll.query.filter_by(
        employee_id=employee.id
    ).order_by(Payroll.year.desc(), Payroll.month.desc()).first()
    
    return render_template('admin/employee_detail.html',
                         employee=employee,
                         recent_attendance=recent_attendance,
                         recent_leaves=recent_leaves,
                         latest_payroll=latest_payroll)

@bp.route('/employees/<int:employee_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_employee(employee_id):
    """Edit employee details"""
    employee = Employee.query.get_or_404(employee_id)
    
    if request.method == 'POST':
        # Update employee details
        employee.first_name = request.form.get('first_name', '').strip()
        employee.last_name = request.form.get('last_name', '').strip()
        employee.phone = request.form.get('phone', '').strip()
        employee.address = request.form.get('address', '').strip()
        employee.department = request.form.get('department', '').strip()
        employee.designation = request.form.get('designation', '').strip()
        employee.employment_type = request.form.get('employment_type', '')
        employee.status = request.form.get('status', 'Active')
        
        # Update date fields if provided
        dob_str = request.form.get('date_of_birth')
        if dob_str:
            try:
                employee.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        doj_str = request.form.get('date_of_joining')
        if doj_str:
            try:
                employee.date_of_joining = datetime.strptime(doj_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        employee.gender = request.form.get('gender', '')
        employee.updated_at = datetime.utcnow()
        
        # Update user role if changed
        new_role = request.form.get('role')
        if new_role and new_role in ['Admin', 'HR', 'Employee']:
            employee.user.role = new_role
        
        db.session.commit()
        flash('Employee details updated successfully', 'success')
        return redirect(url_for('admin.employee_detail', employee_id=employee.id))
    
    return render_template('admin/edit_employee.html', employee=employee)

@bp.route('/employees/<int:employee_id>/deactivate', methods=['POST'])
@admin_required
def deactivate_employee(employee_id):
    """Deactivate employee"""
    employee = Employee.query.get_or_404(employee_id)
    employee.status = 'Inactive'
    employee.user.is_active = False
    db.session.commit()
    
    flash(f'Employee {employee.full_name} has been deactivated', 'success')
    return redirect(url_for('admin.employees'))

@bp.route('/attendance')
@admin_required
def attendance():
    """View all attendance records"""
    page = request.args.get('page', 1, type=int)
    date_str = request.args.get('date', '')
    employee_id = request.args.get('employee_id', type=int)
    
    query = db.session.query(Attendance, Employee).join(Employee)
    
    if date_str:
        try:
            filter_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            query = query.filter(Attendance.date == filter_date)
        except ValueError:
            pass
    else:
        # Default to today
        query = query.filter(Attendance.date == date.today())
    
    if employee_id:
        query = query.filter(Attendance.employee_id == employee_id)
    
    attendance_records = query.order_by(Attendance.date.desc()).paginate(
        page=page,
        per_page=current_app.config['ITEMS_PER_PAGE'],
        error_out=False
    )
    
    return render_template('admin/attendance.html',
                         attendance_records=attendance_records,
                         filter_date=date_str)

@bp.route('/hr-attendance', methods=['GET'])
@admin_required
def hr_attendance():
    """HR Attendance management page"""
    selected_date_str = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    selected_department = request.args.get('department', '')
    
    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except:
        selected_date = date.today()
        selected_date_str = selected_date.strftime('%Y-%m-%d')
    
    # Get all active employees
    query = Employee.query.filter_by(status='Active')
    if selected_department:
        query = query.filter_by(department=selected_department)
    
    employees = query.order_by(Employee.first_name).all()
    
    # Get existing attendance for the selected date
    existing_records = Attendance.query.filter_by(date=selected_date).all()
    existing_attendance = {record.employee_id: record for record in existing_records}
    
    # Get all departments
    departments = db.session.query(Employee.department).filter_by(status='Active').distinct().order_by(Employee.department).all()
    departments = [dept[0] for dept in departments if dept[0]]
    
    selected_date_formatted = selected_date.strftime('%A, %d %B %Y')
    
    return render_template('admin/hr_attendance.html',
                         employees=employees,
                         selected_date=selected_date_str,
                         selected_date_formatted=selected_date_formatted,
                         selected_department=selected_department,
                         departments=departments,
                         existing_attendance=existing_attendance)

@bp.route('/hr-attendance/save', methods=['POST'])
@admin_required
def save_hr_attendance():
    """Save attendance data from HR attendance page"""
    try:
        data = request.get_json()
        attendance_date_str = data.get('date')
        attendance_list = data.get('attendance', [])
        
        if not attendance_date_str or not attendance_list:
            return jsonify({'success': False, 'message': 'Invalid data provided'}), 400
        
        attendance_date = datetime.strptime(attendance_date_str, '%Y-%m-%d').date()
        saved_count = 0
        updated_count = 0
        
        for item in attendance_list:
            employee_id = item.get('employee_id')
            status = item.get('status')
            check_in_str = item.get('check_in')
            check_out_str = item.get('check_out')
            remarks = item.get('remarks', '').strip()
            
            # Check if attendance already exists
            existing = Attendance.query.filter_by(
                employee_id=employee_id,
                date=attendance_date
            ).first()
            
            if existing:
                # Update existing record
                existing.status = status
                existing.remarks = remarks
                if check_in_str and status not in ['Absent', 'Leave']:
                    existing.check_in = datetime.strptime(check_in_str, '%H:%M').time()
                else:
                    existing.check_in = None
                    
                if check_out_str and status not in ['Absent', 'Leave']:
                    existing.check_out = datetime.strptime(check_out_str, '%H:%M').time()
                else:
                    existing.check_out = None
                    
                existing.updated_at = datetime.utcnow()
                updated_count += 1
            else:
                # Create new record
                attendance = Attendance(
                    employee_id=employee_id,
                    date=attendance_date,
                    status=status,
                    remarks=remarks
                )
                
                if check_in_str and status not in ['Absent', 'Leave']:
                    attendance.check_in = datetime.strptime(check_in_str, '%H:%M').time()
                    
                if check_out_str and status not in ['Absent', 'Leave']:
                    attendance.check_out = datetime.strptime(check_out_str, '%H:%M').time()
                
                db.session.add(attendance)
                saved_count += 1
        
        db.session.commit()
        
        message = f'Attendance saved successfully! {saved_count} new records created'
        if updated_count > 0:
            message += f', {updated_count} records updated'
        
        return jsonify({
            'success': True,
            'message': message,
            'saved': saved_count,
            'updated': updated_count
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error saving attendance: {str(e)}'
        }), 500

@bp.route('/attendance/mark', methods=['GET', 'POST'])
@admin_required
def mark_attendance():
    """Manually mark attendance"""
    if request.method == 'POST':
        employee_id = request.form.get('employee_id', type=int)
        date_str = request.form.get('date')
        status = request.form.get('status')
        remarks = request.form.get('remarks', '').strip()
        
        if not employee_id or not date_str or not status:
            flash('All fields are required', 'error')
            return redirect(url_for('admin.mark_attendance'))
        
        try:
            attendance_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            # Check if attendance already exists
            existing = Attendance.query.filter_by(
                employee_id=employee_id,
                date=attendance_date
            ).first()
            
            if existing:
                # Update existing
                existing.status = status
                existing.remarks = remarks
                existing.updated_at = datetime.utcnow()
                flash('Attendance updated successfully', 'success')
            else:
                # Create new
                attendance = Attendance(
                    employee_id=employee_id,
                    date=attendance_date,
                    status=status,
                    remarks=remarks
                )
                db.session.add(attendance)
                flash('Attendance marked successfully', 'success')
            
            db.session.commit()
            return redirect(url_for('admin.attendance'))
        except ValueError:
            flash('Invalid date format', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to mark attendance: {str(e)}', 'error')
    
    employees = Employee.query.filter_by(status='Active').order_by(Employee.first_name).all()
    return render_template('admin/mark_attendance.html',
                         employees=employees,
                         attendance_statuses=current_app.config['ATTENDANCE_STATUS'])

@bp.route('/attendance/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_attendance(id):
    """Edit attendance record"""
    attendance = Attendance.query.get_or_404(id)
    
    if request.method == 'POST':
        date_str = request.form.get('date')
        status = request.form.get('status')
        check_in_str = request.form.get('check_in')
        check_out_str = request.form.get('check_out')
        remarks = request.form.get('remarks', '').strip()
        
        try:
            attendance.date = datetime.strptime(date_str, '%Y-%m-%d').date()
            attendance.status = status
            attendance.remarks = remarks
            
            # Handle check in/out times
            if check_in_str:
                attendance.check_in = datetime.strptime(check_in_str, '%H:%M').time()
            else:
                attendance.check_in = None
                
            if check_out_str:
                attendance.check_out = datetime.strptime(check_out_str, '%H:%M').time()
            else:
                attendance.check_out = None
            
            attendance.updated_at = datetime.utcnow()
            db.session.commit()
            
            flash('Attendance updated successfully', 'success')
            return redirect(url_for('admin.attendance'))
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to update attendance: {str(e)}', 'error')
    
    return render_template('admin/edit_attendance.html', attendance=attendance)

@bp.route('/attendance/<int:id>/delete', methods=['POST'])
@admin_required
def delete_attendance(id):
    """Delete attendance record"""
    attendance = Attendance.query.get_or_404(id)
    
    try:
        db.session.delete(attendance)
        db.session.commit()
        flash('Attendance record deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete attendance: {str(e)}', 'error')
    
    return redirect(url_for('admin.attendance'))

@bp.route('/attendance/bulk', methods=['POST'])
@admin_required
def mark_bulk_attendance():
    """Mark attendance for multiple employees at once"""
    date_str = request.form.get('date')
    status = request.form.get('status', 'Present')
    department = request.form.get('department', '').strip()
    
    try:
        attendance_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Get employees based on department filter
        query = Employee.query.filter_by(status='Active')
        if department:
            query = query.filter_by(department=department)
        
        employees = query.all()
        marked_count = 0
        
        for employee in employees:
            # Check if attendance already exists
            existing = Attendance.query.filter_by(
                employee_id=employee.id,
                date=attendance_date
            ).first()
            
            if not existing:
                attendance = Attendance(
                    employee_id=employee.id,
                    date=attendance_date,
                    status=status,
                    remarks=f'Bulk attendance marked by admin'
                )
                if status == 'Present':
                    attendance.check_in = datetime.strptime('09:00', '%H:%M').time()
                    attendance.check_out = datetime.strptime('17:00', '%H:%M').time()
                db.session.add(attendance)
                marked_count += 1
        
        db.session.commit()
        flash(f'Attendance marked for {marked_count} employees', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to mark bulk attendance: {str(e)}', 'error')
    
    return redirect(url_for('admin.mark_attendance'))

@bp.route('/leave-requests')
@admin_required
def leave_requests():
    """View all leave requests"""
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', 'Pending')
    
    query = db.session.query(LeaveRequest, Employee).join(Employee)
    
    if status_filter:
        query = query.filter(LeaveRequest.status == status_filter)
    
    leave_requests_list = query.order_by(LeaveRequest.created_at.desc()).paginate(
        page=page,
        per_page=current_app.config['ITEMS_PER_PAGE'],
        error_out=False
    )
    
    return render_template('admin/leave_requests.html',
                         leave_requests=leave_requests_list,
                         status_filter=status_filter)

@bp.route('/leave-requests/<int:leave_id>/approve', methods=['POST'])
@admin_required
def approve_leave(leave_id):
    """Approve leave request"""
    leave_request = LeaveRequest.query.get_or_404(leave_id)
    
    if leave_request.status != 'Pending':
        flash('This leave request has already been processed', 'warning')
        return redirect(url_for('admin.leave_requests'))
    
    admin_comment = request.form.get('admin_comment', '').strip()
    
    leave_request.status = 'Approved'
    leave_request.approved_by = current_user.id
    leave_request.approved_at = datetime.utcnow()
    leave_request.admin_comment = admin_comment
    leave_request.updated_at = datetime.utcnow()
    
    # Mark attendance as Leave for the approved dates
    current_date = leave_request.start_date
    while current_date <= leave_request.end_date:
        attendance = Attendance.query.filter_by(
            employee_id=leave_request.employee_id,
            date=current_date
        ).first()
        
        if attendance:
            attendance.status = 'Leave'
            attendance.remarks = f"Leave approved: {leave_request.leave_type}"
        else:
            attendance = Attendance(
                employee_id=leave_request.employee_id,
                date=current_date,
                status='Leave',
                remarks=f"Leave approved: {leave_request.leave_type}"
            )
            db.session.add(attendance)
        
        current_date += timedelta(days=1)
    
    # Create notification
    notification = Notification(
        employee_id=leave_request.employee_id,
        title='Leave Request Approved',
        message=f'Your {leave_request.leave_type} from {leave_request.start_date} to {leave_request.end_date} has been approved.',
        type='success',
        link=url_for('employee.leave')
    )
    db.session.add(notification)
    db.session.commit()
    
    flash('Leave request approved successfully', 'success')
    return redirect(url_for('admin.leave_requests'))

@bp.route('/leave-requests/<int:leave_id>/reject', methods=['POST'])
@admin_required
def reject_leave(leave_id):
    """Reject leave request"""
    leave_request = LeaveRequest.query.get_or_404(leave_id)
    
    if leave_request.status != 'Pending':
        flash('This leave request has already been processed', 'warning')
        return redirect(url_for('admin.leave_requests'))
    
    admin_comment = request.form.get('admin_comment', '').strip()
    
    if not admin_comment:
        flash('Please provide a reason for rejection', 'error')
        return redirect(url_for('admin.leave_requests'))
    
    leave_request.status = 'Rejected'
    leave_request.approved_by = current_user.id
    leave_request.approved_at = datetime.utcnow()
    leave_request.admin_comment = admin_comment
    leave_request.updated_at = datetime.utcnow()
    
    # Create notification
    notification = Notification(
        employee_id=leave_request.employee_id,
        title='Leave Request Rejected',
        message=f'Your {leave_request.leave_type} from {leave_request.start_date} to {leave_request.end_date} has been rejected. Reason: {admin_comment}',
        type='danger',
        link=url_for('employee.leave')
    )
    db.session.add(notification)
    db.session.commit()
    
    flash('Leave request rejected', 'success')
    return redirect(url_for('admin.leave_requests'))

@bp.route('/payroll')
@admin_required
def payroll():
    """View all payroll records"""
    page = request.args.get('page', 1, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    year = request.args.get('year', datetime.now().year, type=int)
    
    payroll_records = db.session.query(Payroll, Employee).join(Employee).filter(
        Payroll.month == month,
        Payroll.year == year
    ).order_by(Employee.first_name).paginate(
        page=page,
        per_page=current_app.config['ITEMS_PER_PAGE'],
        error_out=False
    )
    
    return render_template('admin/payroll.html',
                         payroll_records=payroll_records,
                         selected_month=month,
                         selected_year=year,
                         months=range(1, 13),
                         years=range(2020, 2031))

@bp.route('/payroll/create', methods=['GET', 'POST'])
@admin_required
def create_payroll():
    """Create payroll for an employee"""
    if request.method == 'POST':
        employee_id = request.form.get('employee_id', type=int)
        month = request.form.get('month', type=int)
        year = request.form.get('year', type=int)
        
        # Salary components
        basic_salary = float(request.form.get('basic_salary', 0))
        hra = float(request.form.get('hra', 0))
        da = float(request.form.get('da', 0))
        ta = float(request.form.get('ta', 0))
        medical_allowance = float(request.form.get('medical_allowance', 0))
        other_allowances = float(request.form.get('other_allowances', 0))
        
        # Deductions
        pf = float(request.form.get('pf', 0))
        tax = float(request.form.get('tax', 0))
        insurance = float(request.form.get('insurance', 0))
        other_deductions = float(request.form.get('other_deductions', 0))
        
        # Check if payroll already exists
        existing = Payroll.query.filter_by(
            employee_id=employee_id,
            month=month,
            year=year
        ).first()
        
        if existing:
            flash('Payroll for this employee and period already exists', 'error')
            return redirect(url_for('admin.create_payroll'))
        
        try:
            payroll = Payroll(
                employee_id=employee_id,
                month=month,
                year=year,
                basic_salary=basic_salary,
                hra=hra,
                da=da,
                ta=ta,
                medical_allowance=medical_allowance,
                other_allowances=other_allowances,
                pf=pf,
                tax=tax,
                insurance=insurance,
                other_deductions=other_deductions,
                status='Processed'
            )
            payroll.calculate_totals()
            db.session.add(payroll)
            
            # Create notification
            notification = Notification(
                employee_id=employee_id,
                title='Payroll Processed',
                message=f'Your salary for {calendar.month_name[month]} {year} has been processed. Net Salary: ₹{payroll.net_salary:,.2f}',
                type='info',
                link=url_for('employee.payroll')
            )
            db.session.add(notification)
            db.session.commit()
            
            flash('Payroll created successfully', 'success')
            return redirect(url_for('admin.payroll'))
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to create payroll: {str(e)}', 'error')
    
    employees = Employee.query.filter_by(status='Active').order_by(Employee.first_name).all()
    return render_template('admin/create_payroll.html',
                         employees=employees,
                         months=range(1, 13),
                         years=range(2020, 2031),
                         current_month=datetime.now().month,
                         current_year=datetime.now().year)

@bp.route('/payroll/<int:payroll_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_payroll(payroll_id):
    """Edit payroll record"""
    payroll = Payroll.query.get_or_404(payroll_id)
    
    if request.method == 'POST':
        payroll.basic_salary = float(request.form.get('basic_salary', 0))
        payroll.hra = float(request.form.get('hra', 0))
        payroll.da = float(request.form.get('da', 0))
        payroll.ta = float(request.form.get('ta', 0))
        payroll.medical_allowance = float(request.form.get('medical_allowance', 0))
        payroll.other_allowances = float(request.form.get('other_allowances', 0))
        payroll.pf = float(request.form.get('pf', 0))
        payroll.tax = float(request.form.get('tax', 0))
        payroll.insurance = float(request.form.get('insurance', 0))
        payroll.other_deductions = float(request.form.get('other_deductions', 0))
        
        payroll.calculate_totals()
        payroll.updated_at = datetime.utcnow()
        db.session.commit()
        
        flash('Payroll updated successfully', 'success')
        return redirect(url_for('admin.payroll'))
    
    return render_template('admin/edit_payroll.html', payroll=payroll)

@bp.route('/reports')
@admin_required
def reports():
    """Reports dashboard"""
    return render_template('admin/reports.html')

@bp.route('/reports/attendance')
@admin_required
def attendance_report():
    """Generate attendance report"""
    month = request.args.get('month', datetime.now().month, type=int)
    year = request.args.get('year', datetime.now().year, type=int)
    
    # Get all active employees
    employees = Employee.query.filter_by(status='Active').all()
    
    # Calculate statistics for each employee
    report_data = []
    for emp in employees:
        stats = db.session.query(
            Attendance.status,
            func.count(Attendance.id).label('count')
        ).filter(
            Attendance.employee_id == emp.id,
            extract('month', Attendance.date) == month,
            extract('year', Attendance.date) == year
        ).group_by(Attendance.status).all()
        
        status_dict = {status: count for status, count in stats}
        report_data.append({
            'employee': emp,
            'present': status_dict.get('Present', 0),
            'absent': status_dict.get('Absent', 0),
            'half_day': status_dict.get('Half-day', 0),
            'leave': status_dict.get('Leave', 0),
            'total': sum(status_dict.values())
        })
    
    return render_template('admin/attendance_report.html',
                         report_data=report_data,
                         month=month,
                         year=year,
                         months=range(1, 13),
                         years=range(2020, 2031))

@bp.route('/reports/leave')
@admin_required
def leave_report():
    """Generate leave report"""
    year = request.args.get('year', datetime.now().year, type=int)
    
    # Get leave statistics
    leave_stats = db.session.query(
        Employee,
        func.count(LeaveRequest.id).label('total_requests'),
        func.sum(func.case((LeaveRequest.status == 'Approved', LeaveRequest.days), else_=0)).label('approved_days'),
        func.sum(func.case((LeaveRequest.status == 'Rejected', 1), else_=0)).label('rejected_count'),
        func.sum(func.case((LeaveRequest.status == 'Pending', 1), else_=0)).label('pending_count')
    ).outerjoin(LeaveRequest, Employee.id == LeaveRequest.employee_id).filter(
        Employee.status == 'Active',
        or_(LeaveRequest.id == None, extract('year', LeaveRequest.created_at) == year)
    ).group_by(Employee.id).all()
    
    return render_template('admin/leave_report.html',
                         leave_stats=leave_stats,
                         year=year,
                         years=range(2020, 2031))

@bp.route('/reports/payroll')
@admin_required
def payroll_report():
    """Generate payroll report"""
    month = request.args.get('month', datetime.now().month, type=int)
    year = request.args.get('year', datetime.now().year, type=int)
    
    # Get payroll data
    payroll_data = db.session.query(Payroll, Employee).join(Employee).filter(
        Payroll.month == month,
        Payroll.year == year
    ).order_by(Employee.first_name).all()
    
    # Calculate totals
    total_gross = sum(p.gross_salary for p, e in payroll_data)
    total_deductions = sum((p.pf + p.tax + p.insurance + p.other_deductions) for p, e in payroll_data)
    total_net = sum(p.net_salary for p, e in payroll_data)
    
    return render_template('admin/payroll_report.html',
                         payroll_data=payroll_data,
                         month=month,
                         year=year,
                         months=range(1, 13),
                         years=range(2020, 2031),
                         total_gross=total_gross,
                         total_deductions=total_deductions,
                         total_net=total_net)

@bp.route('/pre-registered-employees')
@admin_required
def pre_registered_employees():
    """Manage pre-registered employees"""
    employees = PreRegisteredEmployee.query.order_by(PreRegisteredEmployee.created_at.desc()).all()
    return render_template('admin/pre_registered_employees.html', employees=employees)

@bp.route('/add-pre-registered-employee', methods=['GET', 'POST'])
@admin_required
def add_pre_registered_employee():
    """Add a new pre-registered employee"""
    if request.method == 'POST':
        employee_id = request.form.get('employee_id', '').strip()
        email = request.form.get('email', '').strip().lower()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        department = request.form.get('department', '').strip()
        designation = request.form.get('designation', '').strip()
        
        # Validation
        errors = []
        if not employee_id:
            errors.append('Employee ID is required')
        if not email:
            errors.append('Email is required')
        if not first_name or not last_name:
            errors.append('First name and last name are required')
        
        # Check if employee ID or email already exists
        if PreRegisteredEmployee.query.filter_by(employee_id=employee_id).first():
            errors.append('Employee ID already exists in pre-registration list')
        if PreRegisteredEmployee.query.filter_by(email=email).first():
            errors.append('Email already exists in pre-registration list')
        if User.query.filter_by(employee_id=employee_id).first():
            errors.append('Employee ID already registered')
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('admin/add_pre_registered_employee.html')
        
        try:
            pre_emp = PreRegisteredEmployee(
                employee_id=employee_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                department=department,
                designation=designation,
                added_by=current_user.id
            )
            db.session.add(pre_emp)
            db.session.commit()
            
            flash(f'Employee {employee_id} pre-registered successfully. They can now sign up using this ID and email.', 'success')
            return redirect(url_for('admin.pre_registered_employees'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding pre-registered employee: {str(e)}', 'error')
    
    return render_template('admin/add_pre_registered_employee.html')

@bp.route('/delete-pre-registered-employee/<int:id>', methods=['POST'])
@admin_required
def delete_pre_registered_employee(id):
    """Delete a pre-registered employee"""
    pre_emp = PreRegisteredEmployee.query.get_or_404(id)
    
    if pre_emp.is_registered:
        flash('Cannot delete - employee has already completed registration', 'error')
        return redirect(url_for('admin.pre_registered_employees'))
    
    try:
        db.session.delete(pre_emp)
        db.session.commit()
        flash('Pre-registered employee deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting: {str(e)}', 'error')
    
    return redirect(url_for('admin.pre_registered_employees'))
