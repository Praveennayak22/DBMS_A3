import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import (
    authenticate_user,
    create_session,
    current_user_dependency,
    is_cds_user,
    is_admin_user,
    is_recruiter_user,
    log_audit,
    require_admin,
    require_cds_access,
    require_recruiter_access,
)
from .db import execute, fetch_all, fetch_one, get_connection, initialize_database
from .schemas import (
    ApplicationCreate,
    ApplicationUpdate,
    AuthResponse,
    CompanyCreate,
    CompanyUpdate,
    GroupCreate,
    GroupMembershipRequest,
    JobCreate,
    JobUpdate,
    LoginRequest,
    MemberCreate,
    MemberUpdate,
)

app = FastAPI(title="Module B RBAC API", version="1.0.0")
BASE_DIR = Path(__file__).resolve().parents[1]
UI_DIR = BASE_DIR / "ui"
UI_PAGES = {
    "index": "index.html",
    "portfolio": "portfolio.html",
    "members": "members.html",
    "groups": "groups.html",
    "companies-jobs": "companies_jobs.html",
    "applications": "applications.html",
    "audit": "audit.html",
}

if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static")


@app.on_event("startup")
def startup_event():
    apply_indexes = os.getenv("MODULE_B_APPLY_INDEXES", "1") == "1"
    initialize_database(apply_indexes=apply_indexes)


@app.get("/")
def root():
    index_path = UI_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Welcome to test APIs"}


@app.get("/ui/{page_name}")
def serve_ui_page(page_name: str):
    file_name = UI_PAGES.get(page_name)
    if not file_name:
        raise HTTPException(status_code=404, detail="Page not found")

    page_path = UI_DIR / file_name
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="Page file missing")
    return FileResponse(page_path)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def chrome_devtools_probe():
    return Response(status_code=204)


@app.post("/login")
def login(payload: LoginRequest):
    user = authenticate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_session(user["user_id"])
    session = fetch_one("SELECT expires_at FROM sessions WHERE session_token = ?", (token,))
    return {
        "message": "Login successful",
        "session_token": token,
        "username": user["username"],
        "role": user["role"],
        "expiry": session["expires_at"],
    }


@app.get("/isAuth", response_model=AuthResponse)
def is_auth(user=Depends(current_user_dependency)):
    return AuthResponse(
        message="User is authenticated",
        username=user["username"],
        role=user["role"],
        expiry=datetime.fromisoformat(user["expires_at"]),
    )


@app.get("/me/student")
def get_my_student_member_id(user=Depends(current_user_dependency)):
    row = fetch_one("SELECT student_id AS member_id FROM students WHERE user_id = ?", (user["user_id"],))
    if not row:
        raise HTTPException(status_code=404, detail="Student profile not found")
    return dict(row)


def _as_program_set(programs: Optional[str]) -> set[str]:
    if not programs:
        return set()
    return {item.strip().lower() for item in programs.split(",") if item and item.strip()}


def _check_student_job_eligibility(student_id: int, job_id: int) -> Optional[str]:
    student = fetch_one(
        """
        SELECT student_id, latest_cpi, active_backlogs, program, graduating_year
        FROM students
        WHERE student_id = ?
        """,
        (student_id,),
    )
    if not student:
        return "Student profile not found"

    criteria = fetch_one(
        """
        SELECT min_cpi, allowed_backlogs, eligible_programs, eligible_year
        FROM eligibility_criteria
        WHERE job_id = ?
        """,
        (job_id,),
    )
    if not criteria:
        return None

    min_cpi = criteria["min_cpi"]
    if min_cpi is not None:
        if student["latest_cpi"] is None or float(student["latest_cpi"]) < float(min_cpi):
            return f"CPI eligibility not met (required >= {min_cpi})"

    allowed_backlogs = criteria["allowed_backlogs"]
    if allowed_backlogs is not None:
        student_backlogs = int(student["active_backlogs"] or 0)
        if student_backlogs > int(allowed_backlogs):
            return f"Backlog eligibility not met (allowed <= {allowed_backlogs})"

    eligible_programs = _as_program_set(criteria["eligible_programs"])
    if eligible_programs:
        student_program = (student["program"] or "").strip().lower()
        if student_program not in eligible_programs:
            return "Program is not eligible for this job"

    eligible_year = criteria["eligible_year"]
    if eligible_year is not None:
        if student["graduating_year"] is None or int(student["graduating_year"]) != int(eligible_year):
            return f"Graduating year eligibility not met (required {eligible_year})"

    return None


def _recruiter_can_manage_application(application_id: int, recruiter_user_id: int) -> bool:
    row = fetch_one(
        """
        SELECT 1
        FROM applications a
        JOIN job_postings j ON a.job_id = j.job_id
        JOIN companies c ON j.company_id = c.company_id
        WHERE a.application_id = ? AND c.user_id = ?
        LIMIT 1
        """,
        (application_id, recruiter_user_id),
    )
    return bool(row)


@app.get("/portfolio/{member_id}")
def get_member_portfolio(member_id: int, request: Request, user=Depends(current_user_dependency)):
    row = fetch_one(
        """
        SELECT s.student_id AS member_id, s.user_id, s.bio, s.skills, s.portfolio_visibility, u.full_name, u.email
        FROM students s JOIN users u ON s.user_id = u.user_id
        WHERE s.student_id = ?
        """,
        (member_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    if is_admin_user(user) or is_cds_user(user):
        return dict(row)

    # Regular users can view their own profile.
    if int(row["user_id"]) == int(user["user_id"]):
        return dict(row)

    # Group/public visibility checks for non-owner users.
    if row["portfolio_visibility"] == "public":
        return dict(row)

    if row["portfolio_visibility"] == "group":
        shared_group = fetch_one(
            """
            SELECT 1
            FROM user_groups ug1
            JOIN user_groups ug2 ON ug1.group_id = ug2.group_id
            WHERE ug1.user_id = ? AND ug2.user_id = ?
            LIMIT 1
            """,
            (user["user_id"], row["user_id"]),
        )
        if shared_group:
            return dict(row)

    log_audit(user["user_id"], "DENY", "students", str(member_id), request.url.path, "forbidden")
    raise HTTPException(status_code=403, detail="Not allowed to view this portfolio")


@app.patch("/portfolio/{member_id}")
def update_member_portfolio(member_id: int, payload: MemberUpdate, request: Request, user=Depends(current_user_dependency)):
    row = fetch_one("SELECT student_id AS member_id, user_id FROM students WHERE student_id = ?", (member_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    if not is_admin_user(user) and int(row["user_id"]) != int(user["user_id"]):
        log_audit(user["user_id"], "DENY", "students", str(member_id), request.url.path, "forbidden")
        raise HTTPException(status_code=403, detail="Not allowed to modify this portfolio")

    updates = []
    params = []
    data = payload.model_dump(exclude_none=True)
    for key, value in data.items():
        updates.append(f"{key} = ?")
        params.append(value)

    if not updates:
        return {"message": "Nothing to update"}

    params.append(member_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE students SET {', '.join(updates)} WHERE student_id = ?", tuple(params))
        conn.commit()

    log_audit(user["user_id"], "UPDATE", "students", str(member_id), request.url.path, "success")
    return {"message": "Portfolio updated"}


@app.get("/members")
def list_members(user=Depends(current_user_dependency)):
    if user["role"] != "Alumni" and not is_cds_user(user):
        raise HTTPException(status_code=403, detail="Not allowed to view candidate list")

    rows = fetch_all(
        """
        SELECT s.student_id AS member_id, u.user_id, u.full_name, u.email,
               s.latest_cpi, s.program, s.discipline, s.graduating_year,
               s.active_backlogs, s.bio, s.skills, s.portfolio_visibility
        FROM students s
        JOIN users u ON s.user_id = u.user_id
        ORDER BY s.graduating_year DESC, s.latest_cpi DESC, u.full_name ASC
        """
    )
    return [dict(r) for r in rows]


@app.post("/members")
def create_member(payload: MemberCreate, request: Request, user=Depends(current_user_dependency)):
    require_admin(user, request.url.path, "users/students")

    role = fetch_one("SELECT role_id FROM roles WHERE role_name = ?", (payload.role_name,))
    if not role:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = fetch_one(
        "SELECT user_id FROM users WHERE username = ? OR email = ?",
        (payload.username, payload.email),
    )
    if existing:
        raise HTTPException(status_code=409, detail="Username or email already exists")

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO users(username, email, password_hash, role_id, full_name, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING user_id
            """,
            (
                payload.username,
                payload.email,
                payload.password,
                role["role_id"],
                payload.full_name,
                1 if payload.is_active else 0,
            ),
        )
        user_id = cur.fetchone()["user_id"]

        # Keep credentials in users only; students table stores profile/academic data.
        cur = conn.execute(
            """
            INSERT INTO students(user_id, latest_cpi, program, discipline, graduating_year, active_backlogs, bio, skills, portfolio_visibility)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING student_id
            """,
            (
                user_id,
                payload.latest_cpi,
                payload.program,
                payload.discipline,
                payload.graduating_year,
                payload.active_backlogs,
                payload.bio,
                payload.skills,
                payload.portfolio_visibility,
            ),
        )
        member_id = cur.fetchone()["student_id"]

        for group_id in payload.group_ids:
            group = conn.execute("SELECT group_id FROM groups WHERE group_id = ?", (group_id,)).fetchone()
            if not group:
                raise HTTPException(status_code=404, detail=f"Group {group_id} not found")
            conn.execute(
                "INSERT OR IGNORE INTO user_groups(user_id, group_id) VALUES (?, ?)",
                (user_id, group_id),
            )

        conn.commit()

    log_audit(user["user_id"], "INSERT", "users/students", str(member_id), request.url.path, "success")
    return {"message": "Member created", "member_id": member_id, "user_id": user_id}


@app.delete("/members/{member_id}")
def delete_member(member_id: int, request: Request, user=Depends(current_user_dependency)):
    require_admin(user, request.url.path, "users/students")

    member = fetch_one("SELECT user_id FROM students WHERE student_id = ?", (member_id,))
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    with get_connection() as conn:
        cur = conn.execute("DELETE FROM users WHERE user_id = ?", (member["user_id"],))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")

    log_audit(user["user_id"], "DELETE", "users/students", str(member_id), request.url.path, "success")
    return {"message": "Member deleted"}


@app.get("/recruiters")
def list_recruiters(user=Depends(current_user_dependency)):
    if not is_admin_user(user) and not is_cds_user(user):
        raise HTTPException(status_code=403, detail="Not allowed to view recruiters")

    rows = fetch_all(
        """
        SELECT u.user_id, u.username, u.email, u.full_name, u.is_active
        FROM users u
        JOIN roles r ON u.role_id = r.role_id
        WHERE r.role_name = 'Recruiter'
        ORDER BY u.user_id
        """
    )
    return [dict(r) for r in rows]


@app.post("/recruiters")
def create_recruiter(payload: MemberCreate, request: Request, user=Depends(current_user_dependency)):
    require_admin(user, request.url.path, "users")

    recruiter_role = fetch_one("SELECT role_id FROM roles WHERE role_name = 'Recruiter'")
    if not recruiter_role:
        raise HTTPException(status_code=500, detail="Recruiter role missing")

    existing = fetch_one(
        "SELECT user_id FROM users WHERE username = ? OR email = ?",
        (payload.username, payload.email),
    )
    if existing:
        raise HTTPException(status_code=409, detail="Username or email already exists")

    recruiter_id = execute(
        """
        INSERT INTO users(username, email, password_hash, role_id, full_name, is_active, status)
        VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')
        """,
        (
            payload.username,
            payload.email,
            payload.password,
            recruiter_role["role_id"],
            payload.full_name,
            1 if payload.is_active else 0,
        ),
    )
    log_audit(user["user_id"], "INSERT", "users/recruiters", str(recruiter_id), request.url.path, "success")
    return {"message": "Recruiter created", "recruiter_user_id": recruiter_id}


@app.delete("/recruiters/{recruiter_user_id}")
def delete_recruiter(recruiter_user_id: int, request: Request, user=Depends(current_user_dependency)):
    require_admin(user, request.url.path, "users/recruiters")

    recruiter = fetch_one(
        """
        SELECT u.user_id
        FROM users u
        JOIN roles r ON u.role_id = r.role_id
        WHERE u.user_id = ? AND r.role_name = 'Recruiter'
        """,
        (recruiter_user_id,),
    )
    if not recruiter:
        raise HTTPException(status_code=404, detail="Recruiter not found")

    with get_connection() as conn:
        cur = conn.execute("DELETE FROM users WHERE user_id = ?", (recruiter_user_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Recruiter not found")

    log_audit(user["user_id"], "DELETE", "users/recruiters", str(recruiter_user_id), request.url.path, "success")
    return {"message": "Recruiter deleted"}


@app.post("/groups")
def create_group(payload: GroupCreate, request: Request, user=Depends(current_user_dependency)):
    require_admin(user, request.url.path, "groups")
    group_id = execute("INSERT INTO groups(group_name) VALUES (?)", (payload.group_name,))
    log_audit(user["user_id"], "INSERT", "groups", str(group_id), request.url.path, "success")
    return {"message": "Group created", "group_id": group_id}


@app.get("/groups")
def list_groups(user=Depends(current_user_dependency)):
    rows = fetch_all(
        """
        SELECT g.group_id, g.group_name, COUNT(ug.user_id) AS member_count
        FROM groups g
        LEFT JOIN user_groups ug ON g.group_id = ug.group_id
        GROUP BY g.group_id, g.group_name
        ORDER BY g.group_id
        """
    )
    return [dict(r) for r in rows]


@app.post("/groups/{group_id}/members")
def add_group_member(group_id: int, payload: GroupMembershipRequest, request: Request, user=Depends(current_user_dependency)):
    require_admin(user, request.url.path, "user_groups")

    member = fetch_one("SELECT user_id FROM students WHERE student_id = ?", (payload.member_id,))
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    group = fetch_one("SELECT group_id FROM groups WHERE group_id = ?", (group_id,))
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    execute(
        "INSERT OR IGNORE INTO user_groups(user_id, group_id) VALUES (?, ?)",
        (member["user_id"], group_id),
    )
    log_audit(user["user_id"], "INSERT", "user_groups", f"{member['user_id']}:{group_id}", request.url.path, "success")
    return {"message": "Member added to group"}


@app.delete("/groups/{group_id}/members/{member_id}")
def remove_group_member(group_id: int, member_id: int, request: Request, user=Depends(current_user_dependency)):
    require_admin(user, request.url.path, "user_groups")

    member = fetch_one("SELECT user_id FROM students WHERE student_id = ?", (member_id,))
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM user_groups WHERE user_id = ? AND group_id = ?",
            (member["user_id"], group_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Group membership not found")

    log_audit(user["user_id"], "DELETE", "user_groups", f"{member['user_id']}:{group_id}", request.url.path, "success")
    return {"message": "Member removed from group"}


@app.post("/companies")
def create_company(payload: CompanyCreate, request: Request, user=Depends(current_user_dependency)):
    require_recruiter_access(user, request.url.path, "companies")
    recruiter_role = fetch_one("SELECT role_id FROM roles WHERE role_name = ?", ("Recruiter",))
    if not recruiter_role:
        raise HTTPException(status_code=500, detail="Recruiter role missing")

    existing_company_for_user = fetch_one("SELECT company_id FROM companies WHERE user_id = ?", (user["user_id"],))
    if user["role"] == "Recruiter":
        if existing_company_for_user:
            return {
                "message": "Company already exists for recruiter",
                "company_id": existing_company_for_user["company_id"],
            }
        company_user_id = user["user_id"]
    else:
        if existing_company_for_user:
            generated_username = f"recruiter_{int(datetime.now().timestamp())}"
            generated_email = f"{generated_username}@local.dev"
            company_user_id = execute(
                """
                INSERT INTO users(username, email, password_hash, role_id, full_name, is_active, status)
                VALUES (?, ?, ?, ?, ?, 1, 'ACTIVE')
                """,
                (generated_username, generated_email, "recruiter123", recruiter_role["role_id"], f"Recruiter {generated_username}"),
            )
        else:
            company_user_id = user["user_id"]

    record_id = execute(
        "INSERT INTO companies(user_id, company_name, industry_sector) VALUES (?, ?, ?)",
        (company_user_id, payload.company_name, payload.domain),
    )
    log_audit(user["user_id"], "INSERT", "companies", str(record_id), request.url.path, "success")
    return {"message": "Company created", "company_id": record_id}


@app.get("/companies/me")
def get_my_company(user=Depends(current_user_dependency)):
    require_recruiter_access(user, "/companies/me", "companies")
    row = fetch_one(
        """
        SELECT company_id, company_name, industry_sector AS domain, user_id AS created_by, NULL AS created_at
        FROM companies
        WHERE user_id = ?
        """,
        (user["user_id"],),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Company not found for this recruiter")
    return dict(row)


@app.get("/companies")
def list_companies(user=Depends(current_user_dependency)):
    if user["role"] == "Recruiter":
        rows = fetch_all(
            """
            SELECT company_id, company_name, industry_sector AS domain, user_id AS created_by, NULL AS created_at
            FROM companies
            WHERE user_id = ?
            ORDER BY company_id
            """,
            (user["user_id"],),
        )
    else:
        rows = fetch_all(
            """
            SELECT company_id, company_name, industry_sector AS domain, user_id AS created_by, NULL AS created_at
            FROM companies
            ORDER BY company_id
            """
        )
    return [dict(r) for r in rows]


@app.patch("/companies/{company_id}")
def update_company(company_id: int, payload: CompanyUpdate, request: Request, user=Depends(current_user_dependency)):
    require_recruiter_access(user, request.url.path, "companies")
    existing = fetch_one("SELECT company_id, user_id FROM companies WHERE company_id = ?", (company_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Company not found")

    if user["role"] == "Recruiter" and int(existing["user_id"]) != int(user["user_id"]):
        log_audit(user["user_id"], "DENY", "companies", str(company_id), request.url.path, "forbidden")
        raise HTTPException(status_code=403, detail="Not allowed to modify this company")

    data = payload.model_dump(exclude_none=True)
    if not data:
        return {"message": "Nothing to update"}

    with get_connection() as conn:
        updates = []
        params = []
        for key, value in data.items():
            col = "industry_sector" if key == "domain" else key
            updates.append(f"{col} = ?")
            params.append(value)
        params.append(company_id)
        conn.execute(f"UPDATE companies SET {', '.join(updates)} WHERE company_id = ?", tuple(params))
        conn.commit()

    log_audit(user["user_id"], "UPDATE", "companies", str(company_id), request.url.path, "success")
    return {"message": "Company updated"}


@app.delete("/companies/{company_id}")
def delete_company(company_id: int, request: Request, user=Depends(current_user_dependency)):
    require_recruiter_access(user, request.url.path, "companies")

    existing = fetch_one("SELECT company_id, user_id FROM companies WHERE company_id = ?", (company_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Company not found")

    if user["role"] == "Recruiter" and int(existing["user_id"]) != int(user["user_id"]):
        log_audit(user["user_id"], "DENY", "companies", str(company_id), request.url.path, "forbidden")
        raise HTTPException(status_code=403, detail="Not allowed to delete this company")

    with get_connection() as conn:
        cur = conn.execute("DELETE FROM companies WHERE company_id = ?", (company_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Company not found")

    log_audit(user["user_id"], "DELETE", "companies", str(company_id), request.url.path, "success")
    return {"message": "Company deleted"}


@app.post("/jobs")
def create_job(payload: JobCreate, request: Request, user=Depends(current_user_dependency)):
    require_recruiter_access(user, request.url.path, "job_postings")
    company = fetch_one("SELECT company_id, user_id FROM companies WHERE company_id = ?", (payload.company_id,))
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if user["role"] == "Recruiter" and int(company["user_id"]) != int(user["user_id"]):
        log_audit(user["user_id"], "DENY", "job_postings", None, request.url.path, "forbidden")
        raise HTTPException(status_code=403, detail="Recruiter can post jobs only for own company")

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO job_postings(company_id, designation, location, deadline, posted_date)
            VALUES (?, ?, ?, ?, ?)
            RETURNING job_id
            """,
            (payload.company_id, payload.title, payload.location, payload.deadline, datetime.now().date().isoformat()),
        )
        record_id = cur.fetchone()["job_id"]
        conn.execute(
            "INSERT INTO eligibility_criteria(job_id, min_cpi) VALUES (?, ?)",
            (record_id, payload.min_cpi),
        )
        conn.commit()

    log_audit(user["user_id"], "INSERT", "job_postings", str(record_id), request.url.path, "success")
    return {"message": "Job created", "job_id": record_id}


@app.get("/jobs")
def list_jobs(min_cpi: Optional[float] = None, user=Depends(current_user_dependency)):
    if user["role"] == "Recruiter":
        base_sql = """
            SELECT j.job_id, j.designation AS title, j.location, e.min_cpi, j.deadline, c.company_name
            FROM job_postings j
            JOIN companies c ON j.company_id = c.company_id
            LEFT JOIN eligibility_criteria e ON e.job_id = j.job_id
            WHERE c.user_id = ?
        """
        if min_cpi is None:
            rows = fetch_all(base_sql + " ORDER BY j.deadline", (user["user_id"],))
        else:
            rows = fetch_all(base_sql + " AND e.min_cpi <= ? ORDER BY j.deadline", (user["user_id"], min_cpi))
    elif min_cpi is None:
        rows = fetch_all(
            """
            SELECT j.job_id, j.designation AS title, j.location, e.min_cpi, j.deadline, c.company_name
            FROM job_postings j
            JOIN companies c ON j.company_id = c.company_id
            LEFT JOIN eligibility_criteria e ON e.job_id = j.job_id
            ORDER BY j.deadline
            """
        )
    else:
        rows = fetch_all(
            """
            SELECT j.job_id, j.designation AS title, j.location, e.min_cpi, j.deadline, c.company_name
            FROM job_postings j
            JOIN companies c ON j.company_id = c.company_id
            LEFT JOIN eligibility_criteria e ON e.job_id = j.job_id
            WHERE e.min_cpi <= ?
            ORDER BY j.deadline
            """,
            (min_cpi,),
        )
    return [dict(r) for r in rows]


@app.patch("/jobs/{job_id}")
def update_job(job_id: int, payload: JobUpdate, request: Request, user=Depends(current_user_dependency)):
    require_recruiter_access(user, request.url.path, "job_postings")
    existing = fetch_one(
        """
        SELECT j.job_id, c.user_id
        FROM job_postings j
        JOIN companies c ON c.company_id = j.company_id
        WHERE j.job_id = ?
        """,
        (job_id,),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Job not found")

    if user["role"] == "Recruiter" and int(existing["user_id"]) != int(user["user_id"]):
        log_audit(user["user_id"], "DENY", "job_postings", str(job_id), request.url.path, "forbidden")
        raise HTTPException(status_code=403, detail="Recruiter can modify only own company jobs")

    data = payload.model_dump(exclude_none=True)
    if not data:
        return {"message": "Nothing to update"}

    with get_connection() as conn:
        job_updates = []
        job_params = []

        if "title" in data:
            job_updates.append("designation = ?")
            job_params.append(data["title"])
        if "location" in data:
            job_updates.append("location = ?")
            job_params.append(data["location"])
        if "deadline" in data:
            job_updates.append("deadline = ?")
            job_params.append(data["deadline"])

        if job_updates:
            job_params.append(job_id)
            conn.execute(f"UPDATE job_postings SET {', '.join(job_updates)} WHERE job_id = ?", tuple(job_params))

        if "min_cpi" in data:
            existing_criteria = conn.execute("SELECT criteria_id FROM eligibility_criteria WHERE job_id = ?", (job_id,)).fetchone()
            if existing_criteria:
                conn.execute("UPDATE eligibility_criteria SET min_cpi = ? WHERE job_id = ?", (data["min_cpi"], job_id))
            else:
                conn.execute("INSERT INTO eligibility_criteria(job_id, min_cpi) VALUES (?, ?)", (job_id, data["min_cpi"]))

        conn.commit()

    log_audit(user["user_id"], "UPDATE", "job_postings", str(job_id), request.url.path, "success")
    return {"message": "Job updated"}


@app.delete("/jobs/{job_id}")
def delete_job(job_id: int, request: Request, user=Depends(current_user_dependency)):
    require_recruiter_access(user, request.url.path, "job_postings")

    existing = fetch_one(
        """
        SELECT j.job_id, c.user_id
        FROM job_postings j
        JOIN companies c ON c.company_id = j.company_id
        WHERE j.job_id = ?
        """,
        (job_id,),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Job not found")

    if user["role"] == "Recruiter" and int(existing["user_id"]) != int(user["user_id"]):
        log_audit(user["user_id"], "DENY", "job_postings", str(job_id), request.url.path, "forbidden")
        raise HTTPException(status_code=403, detail="Recruiter can delete only own company jobs")

    with get_connection() as conn:
        cur = conn.execute("DELETE FROM job_postings WHERE job_id = ?", (job_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Job not found")

    log_audit(user["user_id"], "DELETE", "job_postings", str(job_id), request.url.path, "success")
    return {"message": "Job deleted"}


@app.get("/applications")
def list_applications(user=Depends(current_user_dependency)):
    rows = fetch_all(
        """
        SELECT a.application_id, a.job_id, a.status, a.applied_at, s.student_id AS member_id, u.full_name,
               j.designation AS title, c.company_name, c.user_id AS recruiter_user_id
        FROM applications a
        JOIN students s ON a.student_id = s.student_id
        JOIN users u ON s.user_id = u.user_id
        JOIN job_postings j ON a.job_id = j.job_id
        JOIN companies c ON j.company_id = c.company_id
        ORDER BY a.applied_at DESC
        """
    )
    if is_admin_user(user) or is_cds_user(user):
        return [dict(r) for r in rows]

    if user["role"] == "Recruiter":
        return [dict(r) for r in rows if int(r["recruiter_user_id"]) == int(user["user_id"])]

    own_member = fetch_one("SELECT student_id AS member_id FROM students WHERE user_id = ?", (user["user_id"],))
    if not own_member:
        return []
    return [dict(r) for r in rows if int(r["member_id"]) == int(own_member["member_id"])]


@app.post("/applications")
def create_application(payload: ApplicationCreate, request: Request, user=Depends(current_user_dependency)):
    student_id = payload.student_id
    if is_admin_user(user):
        if student_id is None:
            raise HTTPException(status_code=400, detail="student_id is required for admin-created applications")
    else:
        own_member = fetch_one("SELECT student_id FROM students WHERE user_id = ?", (user["user_id"],))
        if not own_member:
            log_audit(user["user_id"], "DENY", "applications", None, request.url.path, "forbidden")
            raise HTTPException(status_code=403, detail="Only students with a profile can apply")
        student_id = own_member["student_id"]

    job = fetch_one("SELECT job_id FROM job_postings WHERE job_id = ?", (payload.job_id,))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not is_admin_user(user):
        eligibility_error = _check_student_job_eligibility(int(student_id), int(payload.job_id))
        if eligibility_error:
            raise HTTPException(status_code=403, detail=eligibility_error)

    existing = fetch_one(
        "SELECT application_id FROM applications WHERE job_id = ? AND student_id = ?",
        (payload.job_id, student_id),
    )
    if existing:
        raise HTTPException(status_code=409, detail="Application already exists for this job and student")

    record_id = execute(
        "INSERT INTO applications(job_id, student_id, applied_at, status) VALUES (?, ?, ?, ?)",
        (payload.job_id, student_id, datetime.now().date().isoformat(), payload.status),
    )
    log_audit(user["user_id"], "INSERT", "applications", str(record_id), request.url.path, "success")
    return {"message": "Application created", "application_id": record_id}


@app.patch("/applications/{application_id}")
def update_application(application_id: int, payload: ApplicationUpdate, request: Request, user=Depends(current_user_dependency)):
    app_row = fetch_one(
        "SELECT application_id, student_id FROM applications WHERE application_id = ?",
        (application_id,),
    )
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")

    if not is_admin_user(user):
        if is_recruiter_user(user):
            if not _recruiter_can_manage_application(application_id, user["user_id"]):
                log_audit(user["user_id"], "DENY", "applications", str(application_id), request.url.path, "forbidden")
                raise HTTPException(status_code=403, detail="Recruiter can update only own job applications")
        else:
            log_audit(user["user_id"], "DENY", "applications", str(application_id), request.url.path, "forbidden")
            raise HTTPException(status_code=403, detail="Not allowed to modify this application")

    with get_connection() as conn:
        conn.execute(
            "UPDATE applications SET status = ? WHERE application_id = ?",
            (payload.status, application_id),
        )
        conn.commit()

    log_audit(user["user_id"], "UPDATE", "applications", str(application_id), request.url.path, "success")
    return {"message": "Application updated"}


@app.delete("/applications/{application_id}")
def delete_application(application_id: int, request: Request, user=Depends(current_user_dependency)):
    app_row = fetch_one(
        "SELECT application_id, student_id FROM applications WHERE application_id = ?",
        (application_id,),
    )
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")

    if not is_admin_user(user):
        log_audit(user["user_id"], "DENY", "applications", str(application_id), request.url.path, "forbidden")
        raise HTTPException(status_code=403, detail="Only admin can delete applications")

    with get_connection() as conn:
        conn.execute("DELETE FROM applications WHERE application_id = ?", (application_id,))
        conn.commit()

    log_audit(user["user_id"], "DELETE", "applications", str(application_id), request.url.path, "success")
    return {"message": "Application deleted"}


@app.get("/audit-logs")
def get_audit_logs(limit: int = 100, user=Depends(current_user_dependency)):
    require_cds_access(user, "/audit-logs", "audit_logs")
    rows = fetch_all(
        """
        SELECT log_id, actor_user_id, action, table_name, record_id, request_path, status, logged_at
        FROM audit_logs
        ORDER BY logged_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(r) for r in rows]
