import secrets, string, os, uuid, hashlib, hmac, base64, json, mimetypes, asyncio, urllib.request, urllib.error
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Query, Header, UploadFile, File, Request
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import select, func, text, or_
from .config import settings
from .db import Base, engine, get_db, SessionLocal
from .models import Report, Status, Staff, AuditEvent, InternalNote, AdminUser, Attachment, InteragencyTransfer
from .schemas import ReportCreate, ReportCreated, StatusUpdate, StaffCreate, AssignmentUpdate, NoteCreate

app=FastAPI(title='Элдик Көзөмөл API',version='3.0.0',description='Система учёта обращений и внутреннего контроля. Не является государственной приёмной.')
origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Authorization','Content-Type','X-Actor-Name'])
security=HTTPBearer(auto_error=False)
ROLES={'superadmin':6,'admin':5,'manager':4,'operator':3,'viewer':1}
ROLE_LABELS={'superadmin':'Суперадминистратор','admin':'Администратор','manager':'Руководитель','operator':'Оператор','viewer':'Наблюдатель'}
UPLOAD_DIR=Path(settings.upload_dir)

def _detect_file_type(data: bytes) -> str | None:
    """Detect supported file formats from their signatures, not browser MIME metadata."""
    if data.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP": return "image/webp"
    if data.startswith(b"%PDF-"): return "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        # DOCX is a ZIP container; require the standard Word document entry.
        import zipfile, io
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names=set(z.namelist())
                if "[Content_Types].xml" in names and "word/document.xml" in names:
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except Exception:
            return None
    # Legacy DOC compound-file signature.
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"): return "application/msword"
    if len(data) >= 12 and data[4:8] == b"ftyp": return "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"): return "video/webm"
    return None

ALLOWED_UPLOAD_TYPES={
    "image/jpeg","image/png","image/webp","application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "video/mp4","video/webm",
}

def validate_upload(data: bytes, claimed_type: str, max_bytes: int) -> str:
    if not data: raise HTTPException(400, "Файл пустой")
    if len(data)>max_bytes: raise HTTPException(413, f"Максимальный размер файла: {settings.max_upload_mb} МБ")
    detected=_detect_file_type(data)
    if detected not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(415, "Формат файла не поддерживается или содержимое не соответствует формату")
    if claimed_type and claimed_type.split(';',1)[0].strip().lower() not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(415, "Тип файла не разрешён")
    return detected

def now(): return datetime.now(timezone.utc)
def iso(v): return v.isoformat() if v else None
def hash_password(password:str)->str:
    salt=secrets.token_bytes(16); rounds=310000
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,rounds)
    return f"pbkdf2_sha256${rounds}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"
def verify_password(password:str,encoded:str)->bool:
    try:
        _,rounds,salt,digest=encoded.split('$')
        got=hashlib.pbkdf2_hmac('sha256',password.encode(),base64.urlsafe_b64decode(salt),int(rounds))
        return hmac.compare_digest(base64.urlsafe_b64encode(got).decode(),digest)
    except Exception:return False
def make_token(user:AdminUser)->str:
    payload={'sub':user.id,'role':user.role,'exp':int((now()+timedelta(hours=8)).timestamp())}
    raw=base64.urlsafe_b64encode(json.dumps(payload,separators=(',',':')).encode()).decode().rstrip('=')
    sig=hmac.new(settings.app_secret.encode(),raw.encode(),hashlib.sha256).digest()
    return raw+'.'+base64.urlsafe_b64encode(sig).decode().rstrip('=')
def decode_token(token:str):
    try:
        raw,sig=token.split('.',1)
        expected=base64.urlsafe_b64encode(hmac.new(settings.app_secret.encode(),raw.encode(),hashlib.sha256).digest()).decode().rstrip('=')
        if not hmac.compare_digest(sig,expected): raise ValueError()
        payload=json.loads(base64.urlsafe_b64decode(raw+'='*((4-len(raw)%4)%4)))
        if int(payload['exp'])<int(now().timestamp()):raise ValueError()
        return payload
    except Exception: raise HTTPException(401,'Сеанс истёк. Войдите снова.')

def current_user(credentials:HTTPAuthorizationCredentials|None=Depends(security),db:Session=Depends(get_db)):
    if not credentials: raise HTTPException(401,'Войдите в систему')
    payload=decode_token(credentials.credentials)
    user=db.get(AdminUser,payload.get('sub'))
    if not user or not user.active: raise HTTPException(401,'Учётная запись отключена')
    return user
def require_roles(*roles):
    def dep(user:AdminUser=Depends(current_user)):
        if ROLES.get(user.role,0)<min(ROLES[r] for r in roles): raise HTTPException(403,'Недостаточно прав')
        return user
    return dep
def make_code(): return 'EK-'+''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(10))
def find_report(db,code):
    r=db.scalar(select(Report).where(Report.public_code==code))
    if not r: raise HTTPException(404,'Обращение не найдено')
    return r
def audit(db,r,who,action,details):
    db.add(AuditEvent(report_id=r.id,actor=who,action=action,details=details))
def report_dict(r,detail=False):
    d={'public_code':r.public_code,'status':r.status.value,'language':r.language,'category':r.category,'region':r.region,'district':r.district,'created_at':iso(r.created_at),'updated_at':iso(r.updated_at),'assigned_staff_id':r.assigned_staff_id,'priority':r.priority,'due_at':iso(r.due_at)}
    return d|({'description':r.description} if detail else {})
def user_dict(u):
    return {'id':u.id,'username':u.username,'email':u.email,'full_name':u.full_name,'role':u.role,'role_label':ROLE_LABELS.get(u.role,u.role),'active':u.active,'created_at':iso(u.created_at),'last_login_at':iso(u.last_login_at)}
@app.on_event('startup')
def startup():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE reports ADD COLUMN IF NOT EXISTS assigned_staff_id VARCHAR(36) REFERENCES staff(id)"))
        c.execute(text("ALTER TABLE reports ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()"))
        c.execute(text("ALTER TABLE reports ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal'"))
        c.execute(text("ALTER TABLE reports ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ"))
    # Bootstrap one immutable owner account. Change the initial password immediately after first login.
    if settings.superadmin_password and len(settings.superadmin_password)>=14:
        from sqlalchemy import select
        with SessionLocal() as db:
            existing=db.scalar(select(AdminUser).where(AdminUser.role=='superadmin'))
            if not existing:
                db.add(AdminUser(username=settings.superadmin_username,email=settings.superadmin_email,full_name='\u0412\u043b\u0430\u0434\u0435\u043b\u0435\u0446 \u0441\u0438\u0441\u0442\u0435\u043c\u044b',password_hash=hash_password(settings.superadmin_password),role='superadmin',active=True))
                db.commit()

@app.get('/',include_in_schema=False)
def public_site(request:Request):
    html=(Path(__file__).parents[1]/'web'/'index.html').read_text(encoding='utf-8')
    base=str(request.base_url).rstrip('/')
    html=html.replace('__SITE_URL__',base)
    return Response(html,media_type='text/html; charset=utf-8')

@app.get('/assets/{filename}', include_in_schema=False)
def public_assets(filename: str):
    allowed_files = {
        'eldik-emblem.png',
        'hero-kyrgyzstan.jpg',
    }
    if filename not in allowed_files:
        raise HTTPException(404, 'Файл не найден')

    asset_path = Path(__file__).parents[1] / 'web' / 'assets' / filename
    if not asset_path.is_file():
        raise HTTPException(404, 'Файл не найден')

    return FileResponse(asset_path)


@app.get('/robots.txt',include_in_schema=True)
def robots(request:Request):
    base=str(request.base_url).rstrip('/')
    return Response(f'User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /api/\nSitemap: {base}/sitemap.xml\n',media_type='text/plain')

@app.get('/sitemap.xml',include_in_schema=True)
def sitemap(request:Request):
    base=str(request.base_url).rstrip('/')
    xml=f'''<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url></urlset>'''
    return Response(xml,media_type='application/xml')
@app.get('/config.js',include_in_schema=False)
def public_config(): return Response("window.ELDIK_API_BASE = window.location.origin;",media_type='application/javascript')
@app.get('/admin/',include_in_schema=False)
def admin_page(): return FileResponse(Path(__file__).with_name('admin.html'))
@app.get('/health')
def health(): return {'status':'ok','service':'eldik-kozomol-api','version':'3.0.0'}
@app.post('/api/v1/auth/login')
def login(p:dict,db:Session=Depends(get_db)):
    ident=str(p.get('username','')).strip().lower(); password=str(p.get('password',''))
    user=db.scalar(select(AdminUser).where(or_(func.lower(AdminUser.username)==ident,func.lower(AdminUser.email)==ident)))
    if not user or not user.active or not verify_password(password,user.password_hash): raise HTTPException(401,'Неверный логин или пароль')
    user.last_login_at=now();db.commit()
    return {'access_token':make_token(user),'token_type':'bearer','user':user_dict(user)}
@app.get('/api/v1/auth/me')
def me(user:AdminUser=Depends(current_user)): return user_dict(user)
@app.post('/api/v1/auth/change-password')
def change_password(p:dict,user:AdminUser=Depends(current_user),db:Session=Depends(get_db)):
    old=str(p.get('old_password',''));new=str(p.get('new_password',''))
    if not verify_password(old,user.password_hash):raise HTTPException(400,'Текущий пароль неверен')
    if len(new)<14:raise HTTPException(400,'Новый пароль должен содержать не менее 14 символов')
    user.password_hash=hash_password(new);db.commit();return {'ok':True}
def public_upload_token(code:str)->str:
    # Token is scoped to one public report code and signed with the server secret.
    message=('eldik-public-upload:'+code).encode('utf-8')
    return hmac.new(settings.app_secret.encode('utf-8'),message,hashlib.sha256).hexdigest()


@app.post('/api/v1/reports',status_code=201)
def create_report(p:ReportCreate,db:Session=Depends(get_db)):
    r=Report(public_code=make_code(),**p.model_dump(),status=Status.new);db.add(r);db.commit();db.refresh(r)
    return {'public_code':r.public_code,'status':'new','message':'Обращение зарегистрировано. Сохраните номер для проверки статуса.','upload_token':public_upload_token(r.public_code)}
@app.get('/api/v1/reports/{public_code}')
def public_status(public_code:str,db:Session=Depends(get_db)):
    r=find_report(db,public_code);return {'public_code':r.public_code,'status':r.status.value,'created_at':iso(r.created_at)}
@app.post('/api/v1/reports/{public_code}/attachments')
async def public_upload_attachment(
    public_code:str,
    upload_token:str=Query(...),
    file:UploadFile=File(...),
    db:Session=Depends(get_db),
):
    report=find_report(db,public_code)
    expected=public_upload_token(public_code)
    if not hmac.compare_digest(upload_token,expected):
        raise HTTPException(403,'Недействительный ключ загрузки файлов')

    allowed={
        'image/jpeg','image/png','image/webp',
        'application/pdf','application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'video/mp4','video/webm',
    }
    claimed_type=(file.content_type or '').lower().split(';',1)[0].strip()
    limit=settings.max_upload_mb*1024*1024
    data=await file.read(limit+1)
    content_type=validate_upload(data, claimed_type, limit)

    original_name=Path(file.filename or 'evidence').name[:255] or 'evidence'
    suffix=Path(original_name).suffix.lower()[:10]
    stored=f'{uuid.uuid4().hex}{suffix}'
    await asyncio.to_thread(_supabase_upload,data,stored,content_type)
    try:
        attachment=Attachment(
            report_id=report.id,original_name=original_name,stored_name=stored,
            content_type=content_type,size=len(data),uploaded_by='public',
        )
        db.add(attachment)
        audit(db,report,'public','Доказательство',f'Загружен файл: {original_name}')
        db.commit()
        db.refresh(attachment)
    except Exception:
        db.rollback()
        try:
            supabase_url,service_key,bucket=_supabase_storage_config()
            delete_request=urllib.request.Request(
                _storage_object_url(supabase_url,bucket,stored),
                headers={'apikey':service_key,'Authorization':f'Bearer {service_key}'},
                method='DELETE',
            )
            await asyncio.to_thread(lambda: urllib.request.urlopen(delete_request,timeout=30).read())
        except Exception:
            pass
        raise
    return {'id':attachment.id,'name':attachment.original_name,'size':attachment.size,'content_type':attachment.content_type}


@app.get('/api/v1/admin/stats')
def stats(user:AdminUser=Depends(require_roles('viewer')),db:Session=Depends(get_db)):
    total=db.scalar(select(func.count()).select_from(Report)) or 0
    statuses={s.value:db.scalar(select(func.count()).select_from(Report).where(Report.status==s)) or 0 for s in Status}
    overdue=db.scalar(select(func.count()).select_from(Report).where(Report.due_at<now(),Report.status!=Status.closed)) or 0
    return {'total':total,'statuses':statuses,'overdue':overdue}
@app.get('/api/v1/admin/reports')
def reports(status:str|None=None,category:str|None=None,region:str|None=None,search:str|None=Query(default=None,max_length=100),assigned_staff_id:str|None=None,priority:str|None=None,limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0),user:AdminUser=Depends(require_roles('viewer')),db:Session=Depends(get_db)):
    q=select(Report)
    if status:
        try:q=q.where(Report.status==Status(status))
        except ValueError:raise HTTPException(400,'Неизвестный статус')
    if category:q=q.where(Report.category==category)
    if region:q=q.where(Report.region.ilike(f'%{region}%'))
    if assigned_staff_id:q=q.where(Report.assigned_staff_id==assigned_staff_id)
    if priority:q=q.where(Report.priority==priority)
    if search:q=q.where(Report.public_code.ilike(f'%{search}%')|Report.description.ilike(f'%{search}%')|Report.district.ilike(f'%{search}%'))
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows=db.scalars(q.order_by(Report.created_at.desc()).offset(offset).limit(limit)).all()
    staff={s.id:s.full_name for s in db.scalars(select(Staff)).all()}
    items=[]
    for r in rows:
        d=report_dict(r);d['assigned_staff_name']=staff.get(r.assigned_staff_id);items.append(d)
    return {'items':items,'total':total,'limit':limit,'offset':offset}
@app.get('/api/v1/admin/reports/{code}')
def detail(code:str,user:AdminUser=Depends(require_roles('viewer')),db:Session=Depends(get_db)):
    r=find_report(db,code);d=report_dict(r,True)
    s=db.get(Staff,r.assigned_staff_id) if r.assigned_staff_id else None;d['assigned_staff_name']=s.full_name if s else None
    d['notes']=[{'author':n.author,'body':n.body,'created_at':iso(n.created_at)} for n in db.scalars(select(InternalNote).where(InternalNote.report_id==r.id).order_by(InternalNote.created_at.desc())).all()]
    d['history']=[{'actor':e.actor,'action':e.action,'details':e.details,'created_at':iso(e.created_at)} for e in db.scalars(select(AuditEvent).where(AuditEvent.report_id==r.id).order_by(AuditEvent.created_at.desc())).all()]
    d['attachments']=[{'id':a.id,'name':a.original_name,'size':a.size,'content_type':a.content_type,'created_at':iso(a.created_at)} for a in db.scalars(select(Attachment).where(Attachment.report_id==r.id).order_by(Attachment.created_at.desc())).all()]
    transfers=db.scalars(select(InteragencyTransfer).where(InteragencyTransfer.report_id==r.id).order_by(InteragencyTransfer.created_at.desc())).all()
    d['transfer_history']=[transfer_dict(t) for t in transfers]
    d['transfers']=d['transfer_history']
    return d
@app.patch('/api/v1/admin/reports/{code}/status')
def change_status(code:str,p:StatusUpdate,user:AdminUser=Depends(require_roles('operator')),db:Session=Depends(get_db)):
    r=find_report(db,code);old=r.status.value;r.status=Status(p.status);audit(db,r,user.username,'Изменение статуса',f'{old} → {p.status}');db.commit();return {'public_code':code,'status':r.status.value}
@app.patch('/api/v1/admin/reports/{code}/workflow')
def workflow(code:str,p:dict,user:AdminUser=Depends(require_roles('manager')),db:Session=Depends(get_db)):
    r=find_report(db,code)
    priority=p.get('priority',r.priority)
    if priority not in ('low','normal','high','critical'):raise HTTPException(400,'Некорректный приоритет')
    r.priority=priority
    due=p.get('due_at')
    if due:
        try:r.due_at=datetime.fromisoformat(due.replace('Z','+00:00'))
        except Exception:raise HTTPException(400,'Некорректная дата срока')
    elif 'due_at' in p:r.due_at=None
    audit(db,r,user.username,'Изменение контроля',f'Приоритет: {priority}; срок: {iso(r.due_at)}');db.commit();return {'ok':True}
@app.get('/api/v1/admin/staff')
def staff_list(user:AdminUser=Depends(require_roles('viewer')),db:Session=Depends(get_db)):
    return [{'id':s.id,'full_name':s.full_name,'position':s.position,'department':s.department,'active':s.active} for s in db.scalars(select(Staff).order_by(Staff.full_name)).all()]
@app.post('/api/v1/admin/staff')
def staff_create(p:StaffCreate,user:AdminUser=Depends(require_roles('manager')),db:Session=Depends(get_db)):
    s=Staff(**p.model_dump());db.add(s);db.commit();db.refresh(s);return {'id':s.id,'full_name':s.full_name,'position':s.position,'department':s.department,'active':s.active}
@app.patch('/api/v1/admin/reports/{code}/assignment')
def assign(code:str,p:AssignmentUpdate,user:AdminUser=Depends(require_roles('manager')),db:Session=Depends(get_db)):
    r=find_report(db,code)
    if p.staff_id:
        s=db.get(Staff,p.staff_id)
        if not s or not s.active:raise HTTPException(400,'Сотрудник не найден или неактивен')
        r.assigned_staff_id=s.id;desc=f'Назначен исполнитель: {s.full_name}'
    else:r.assigned_staff_id=None;desc='Ответственный сотрудник снят'
    audit(db,r,user.username,'Назначение исполнителя',desc);db.commit();return {'assigned_staff_id':r.assigned_staff_id}
@app.post('/api/v1/admin/reports/{code}/notes')
def add_note(code:str,p:dict,user:AdminUser=Depends(require_roles('operator')),db:Session=Depends(get_db)):
    body=str(p.get('body','')).strip()
    if not body or len(body)>5000:raise HTTPException(400,'Заметка должна содержать 1–5000 символов')
    r=find_report(db,code);db.add(InternalNote(report_id=r.id,author=user.username,body=body));audit(db,r,user.username,'Внутренняя заметка','Добавлена внутренняя заметка');db.commit();return {'ok':True}
def _supabase_storage_config():
    supabase_url = os.getenv('SUPABASE_URL', '').strip().rstrip('/')
    service_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    bucket = os.getenv('SUPABASE_BUCKET', 'eldik-uploads').strip()
    if not supabase_url or not service_key:
        raise HTTPException(503, 'Supabase Storage не настроен: проверьте SUPABASE_URL и SUPABASE_SERVICE_ROLE_KEY')
    return supabase_url, service_key, bucket


def _storage_object_url(supabase_url: str, bucket: str, stored_name: str) -> str:
    safe_bucket = quote(bucket, safe='')
    safe_path = '/'.join(quote(part, safe='') for part in stored_name.split('/'))
    return f'{supabase_url}/storage/v1/object/{safe_bucket}/{safe_path}'


def _supabase_upload(data: bytes, stored_name: str, content_type: str) -> None:
    supabase_url, service_key, bucket = _supabase_storage_config()
    request = urllib.request.Request(
        _storage_object_url(supabase_url, bucket, stored_name),
        data=data,
        headers={
            'apikey': service_key,
            'Authorization': f'Bearer {service_key}',
            'Content-Type': content_type or 'application/octet-stream',
            'x-upsert': 'false',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode('utf-8', errors='replace')[:1000]
        raise HTTPException(502, f'Ошибка Supabase Storage при загрузке: {details}') from exc
    except Exception as exc:
        raise HTTPException(502, f'Не удалось связаться с Supabase Storage: {str(exc)[:300]}') from exc


def _supabase_download(stored_name: str) -> bytes:
    supabase_url, service_key, bucket = _supabase_storage_config()
    request = urllib.request.Request(
        _storage_object_url(supabase_url, bucket, stored_name),
        headers={
            'apikey': service_key,
            'Authorization': f'Bearer {service_key}',
        },
        method='GET',
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(404, 'Файл отсутствует в Supabase Storage') from exc
        details = exc.read().decode('utf-8', errors='replace')[:1000]
        raise HTTPException(502, f'Ошибка Supabase Storage при скачивании: {details}') from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f'Не удалось связаться с Supabase Storage: {str(exc)[:300]}') from exc


@app.post('/api/v1/admin/reports/{code}/attachments')
async def upload_attachment(code:str,file:UploadFile=File(...),user:AdminUser=Depends(require_roles('operator')),db:Session=Depends(get_db)):
    r=find_report(db,code)
    claimed_type=(file.content_type or '').lower().split(';',1)[0].strip()
    data=await file.read(settings.max_upload_mb*1024*1024+1)
    detected_type=validate_upload(data, claimed_type, settings.max_upload_mb*1024*1024)
    original_name=Path(file.filename or 'file').name[:255]
    stored=f'{uuid.uuid4().hex}{Path(original_name).suffix.lower()[:10]}'
    await asyncio.to_thread(_supabase_upload, data, stored, file.content_type or 'application/octet-stream')
    try:
        a=Attachment(report_id=r.id,original_name=original_name,stored_name=stored,content_type=detected_type,size=len(data),uploaded_by=user.username)
        db.add(a)
        audit(db,r,user.username,'Вложение',f'Загружен файл: {a.original_name}')
        db.commit()
        db.refresh(a)
    except Exception:
        db.rollback()
        # Do not leave an orphaned object if the database write fails.
        try:
            supabase_url, service_key, bucket = _supabase_storage_config()
            delete_request = urllib.request.Request(
                _storage_object_url(supabase_url, bucket, stored),
                headers={'apikey': service_key, 'Authorization': f'Bearer {service_key}'},
                method='DELETE',
            )
            await asyncio.to_thread(lambda: urllib.request.urlopen(delete_request, timeout=30).read())
        except Exception:
            pass
        raise
    return {'id':a.id,'name':a.original_name}


@app.get('/api/v1/admin/attachments/{attachment_id}')
async def download_attachment(attachment_id:str,user:AdminUser=Depends(require_roles('viewer')),db:Session=Depends(get_db)):
    a=db.get(Attachment,attachment_id)
    if not a:
        raise HTTPException(404,'Файл не найден')
    data=await asyncio.to_thread(_supabase_download, a.stored_name)
    return Response(
        content=data,
        media_type=a.content_type or 'application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{quote(a.original_name)}"'}
    )
@app.delete('/api/v1/admin/attachments/{attachment_id}')
async def delete_attachment(
    attachment_id: str,
    user: AdminUser = Depends(require_roles('operator')),
    db: Session = Depends(get_db),
):
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(404, 'Файл не найден')
    report = db.get(Report, attachment.report_id)
    if not report:
        raise HTTPException(404, 'Обращение, к которому прикреплён файл, не найдено')

    supabase_url, service_key, bucket = _supabase_storage_config()
    request = urllib.request.Request(
        _storage_object_url(supabase_url, bucket, attachment.stored_name),
        headers={'apikey': service_key, 'Authorization': f'Bearer {service_key}'},
        method='DELETE',
    )
    try:
        await asyncio.to_thread(lambda: urllib.request.urlopen(request, timeout=60).read())
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            details = exc.read().decode('utf-8', errors='replace')[:1000]
            raise HTTPException(502, f'Ошибка Supabase Storage при удалении: {details}') from exc
    except Exception as exc:
        raise HTTPException(502, f'Не удалось удалить файл из Supabase Storage: {str(exc)[:300]}') from exc

    original_name = attachment.original_name
    try:
        audit(db, report, user.username, 'Удаление вложения', f'Удалён файл: {original_name}')
        db.delete(attachment)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, 'Объект удалён из хранилища, но запись базы не обновлена. Обратитесь к администратору.') from exc
    return {'ok': True, 'message': 'Файл удалён'}



# -------------------- Межведомственная маршрутизация --------------------
ALLOWED_RECIPIENTS={"ГУУР МВД КР","СВР МВД КР","Академия МВД КР","СОП"}
TRANSFER_TYPES={"execution","review","assistance","joint","information"}
TRANSFER_STATUSES={"pending","accepted","rejected","completed"}

@app.post('/api/v1/admin/reports/{code}/transfers', status_code=201)
def create_transfer(code:str,p:dict,user:AdminUser=Depends(require_roles('manager')),db:Session=Depends(get_db)):
    report=find_report(db,code)

    # The admin panel sends to_department/destination_department and due_at.
    recipient=str(p.get('recipient_department') or p.get('to_department') or p.get('destination_department') or '').strip()
    if not recipient or len(recipient)>160:
        raise HTTPException(400,'Укажите корректное подразделение-получателя')
    # Known recipients are explicitly recognized. A custom destination is recorded as a
    # manually specified destination; this API does not transmit data to that agency.
    if recipient not in ALLOWED_RECIPIENTS and not p.get('department_code') == 'Другое подразделение':
        raise HTTPException(400,'Выберите разрешённое подразделение-получателя или укажите другое подразделение')

    transfer_type=str(p.get('transfer_type','review'))
    if transfer_type not in TRANSFER_TYPES:
        raise HTTPException(400,'Некорректный тип передачи')

    reason=str(p.get('reason','')).strip()
    legal_basis=str(p.get('legal_basis') or reason).strip()
    if len(reason)<5 or len(reason)>5000:
        raise HTTPException(400,'Основание передачи должно содержать 5–5000 символов')
    if len(legal_basis)<5 or len(legal_basis)>5000:
        raise HTTPException(400,'Укажите правовое основание передачи (5–5000 символов)')

    deadline_value=p.get('deadline') or p.get('due_at')
    deadline=None
    if deadline_value:
        try:
            deadline=datetime.fromisoformat(str(deadline_value).replace('Z','+00:00'))
            if deadline.tzinfo is None:
                deadline=deadline.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(400,'Некорректная дата срока')
        if deadline < now()-timedelta(minutes=1):
            raise HTTPException(400,'Срок передачи не может быть в прошлом')

    priority=str(p.get('priority','normal'))
    if priority not in ('low','normal','high','critical'):
        raise HTTPException(400,'Некорректный приоритет')

    staff_id=p.get('to_staff_id') or p.get('destination_staff_id')
    recipient_person=str(p.get('recipient_person') or '').strip()
    staff_obj=None
    if staff_id:
        staff_obj=db.get(Staff,str(staff_id))
        if not staff_obj or not staff_obj.active:
            raise HTTPException(400,'Сотрудник-получатель не найден или неактивен')
        recipient_person=staff_obj.full_name

    receiving_unit=str(p.get('receiving_unit') or '').strip()
    if len(receiving_unit)>160:
        raise HTTPException(400,'Название внутреннего подразделения не должно превышать 160 символов')

    transfer=InteragencyTransfer(
        report_id=report.id,
        recipient_department=recipient,
        recipient_person=recipient_person[:160],
        recipient_staff_id=staff_obj.id if staff_obj else None,
        receiving_unit=receiving_unit,
        transfer_type=transfer_type,
        legal_basis=legal_basis,
        reason=reason,
        priority=priority,
        deadline=deadline,
        created_by=user.username,
        status='pending'
    )
    db.add(transfer)
    audit(db,report,user.username,'Межведомственная передача',
          f'{recipient}; тип: {transfer_type}; срок: {iso(deadline)}')
    db.commit()
    db.refresh(transfer)
    return transfer_dict(transfer)

@app.get('/api/v1/admin/reports/{code}/transfers')
def list_transfers(code:str,user:AdminUser=Depends(require_roles('viewer')),db:Session=Depends(get_db)):
    report=find_report(db,code)
    rows=db.scalars(select(InteragencyTransfer).where(
        InteragencyTransfer.report_id==report.id
    ).order_by(InteragencyTransfer.created_at.desc())).all()
    return [transfer_dict(x) for x in rows]

def _set_transfer_decision(transfer_id:str,decision:str,user:AdminUser,db:Session):
    transfer=db.get(InteragencyTransfer,transfer_id)
    if not transfer:
        raise HTTPException(404,'Передача не найдена')
    if transfer.status!='pending':
        raise HTTPException(409,'Решение по этой передаче уже принято')
    transfer.status=decision
    transfer.updated_at=now()
    report=db.get(Report,transfer.report_id)
    label='Приём межведомственной передачи подтверждён' if decision=='accepted' else 'Межведомственная передача отклонена'
    audit(db,report,user.username,label,transfer.recipient_department)
    db.commit()
    db.refresh(transfer)
    return transfer_dict(transfer)

@app.post('/api/v1/admin/transfers/{transfer_id}/accept')
def accept_transfer(transfer_id:str,user:AdminUser=Depends(require_roles('manager')),db:Session=Depends(get_db)):
    return _set_transfer_decision(transfer_id,'accepted',user,db)

@app.post('/api/v1/admin/transfers/{transfer_id}/reject')
def reject_transfer(transfer_id:str,user:AdminUser=Depends(require_roles('manager')),db:Session=Depends(get_db)):
    return _set_transfer_decision(transfer_id,'rejected',user,db)

@app.patch('/api/v1/admin/transfers/{transfer_id}')
def update_transfer(transfer_id:str,p:dict,user:AdminUser=Depends(require_roles('manager')),db:Session=Depends(get_db)):
    transfer=db.get(InteragencyTransfer,transfer_id)
    if not transfer:
        raise HTTPException(404,'Передача не найдена')
    status=str(p.get('status',transfer.status))
    if status not in TRANSFER_STATUSES:
        raise HTTPException(400,'Некорректный статус передачи')
    comment=str(p.get('comment','')).strip()
    if len(comment)>2000:
        raise HTTPException(400,'Комментарий слишком длинный')
    transfer.status=status
    if comment:
        transfer.last_comment=comment
    transfer.updated_at=now()
    report=db.get(Report,transfer.report_id)
    audit(db,report,user.username,'Изменение статуса передачи',
          f'{transfer.recipient_department}: {status}; {comment}')
    db.commit()
    db.refresh(transfer)
    return transfer_dict(transfer)

def transfer_dict(t):
    return {
        'id':t.id,
        'report_id':t.report_id,
        'recipient_department':t.recipient_department,
        'to_department':t.recipient_department,
        'destination_department':t.recipient_department,
        'recipient_person':t.recipient_person,
        'to_staff_name':t.recipient_person or None,
        'destination_staff_name':t.recipient_person or None,
        'to_staff_id':t.recipient_staff_id,
        'destination_staff_id':t.recipient_staff_id,
        'transfer_type':t.transfer_type,
        'legal_basis':t.legal_basis,
        'reason':t.reason,
        'priority':t.priority,
        'deadline':iso(t.deadline),
        'due_at':iso(t.deadline),
        'receiving_unit':t.receiving_unit or '',
        'recipient_staff_id':t.recipient_staff_id,
        'status':t.status,
        'created_by':t.created_by,
        'last_comment':t.last_comment,
        'response_note':t.last_comment,
        'created_at':iso(t.created_at),
        'updated_at':iso(t.updated_at)
    }

@app.get('/api/v1/admin/analytics/summary')
def analytics_summary(user:AdminUser=Depends(require_roles('manager')),db:Session=Depends(get_db)):
    total=db.scalar(select(func.count()).select_from(Report)) or 0
    by_region=db.execute(select(Report.region,func.count()).group_by(Report.region).order_by(func.count().desc())).all()
    by_category=db.execute(select(Report.category,func.count()).group_by(Report.category).order_by(func.count().desc())).all()
    by_priority=db.execute(select(Report.priority,func.count()).group_by(Report.priority)).all()
    by_status=db.execute(select(Report.status,func.count()).group_by(Report.status)).all()
    overdue=db.scalar(select(func.count()).select_from(Report).where(Report.due_at<now(),Report.status!=Status.closed)) or 0
    return {'total':total,'overdue':overdue,'regions':[{'name':n or 'Не указан', 'count':c} for n,c in by_region],'categories':[{'name':n or 'Не указана','count':c} for n,c in by_category],'priorities':[{'name':n,'count':c} for n,c in by_priority],'statuses':[{'name':n.value if hasattr(n,'value') else str(n),'count':c} for n,c in by_status]}

@app.get('/api/v1/admin/security/overview')
def security_overview(user:AdminUser=Depends(require_roles('superadmin')),db:Session=Depends(get_db)):
    active=db.scalar(select(func.count()).select_from(AdminUser).where(AdminUser.active==True)) or 0
    inactive=db.scalar(select(func.count()).select_from(AdminUser).where(AdminUser.active==False)) or 0
    recent=db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(50)).all()
    return {'active_users':active,'inactive_users':inactive,'recent_admin_actions':[{'actor':e.actor,'action':e.action,'details':e.details,'created_at':iso(e.created_at)} for e in recent]}

@app.get('/api/v1/admin/users')
def users_list(user:AdminUser=Depends(require_roles('superadmin')),db:Session=Depends(get_db)):
    return [user_dict(u) for u in db.scalars(select(AdminUser).order_by(AdminUser.created_at)).all()]
@app.post('/api/v1/admin/users')
def user_create(p:dict,user:AdminUser=Depends(require_roles('superadmin')),db:Session=Depends(get_db)):
    username=str(p.get('username','')).strip();email=str(p.get('email','')).strip().lower();password=str(p.get('password',''));role=str(p.get('role','operator'))
    if not username or len(username)>80 or '@' in username:raise HTTPException(400,'Укажите корректный логин')
    if '@' not in email or len(email)>254:raise HTTPException(400,'Укажите корректный email')
    if role not in ('admin','manager','operator','viewer'):raise HTTPException(400,'Недопустимая роль. SUPERADMIN нельзя назначить через панель.')
    if len(password)<14:raise HTTPException(400,'Пароль должен содержать не менее 14 символов')
    if db.scalar(select(AdminUser).where(or_(func.lower(AdminUser.username)==username.lower(),func.lower(AdminUser.email)==email.lower()))):raise HTTPException(409,'Логин или email уже занят')
    u=AdminUser(username=username,email=email,full_name=str(p.get('full_name',''))[:160],password_hash=hash_password(password),role=role,active=True);db.add(u);db.commit();db.refresh(u);return user_dict(u)
@app.patch('/api/v1/admin/users/{user_id}')
def user_update(user_id:str,p:dict,user:AdminUser=Depends(require_roles('superadmin')),db:Session=Depends(get_db)):
    target=db.get(AdminUser,user_id)
    if not target:raise HTTPException(404,'Пользователь не найден')
    if target.role=='superadmin':raise HTTPException(403,'Учётную запись SUPERADMIN нельзя менять через панель')
    if 'active' in p:target.active=bool(p['active'])
    if 'username' in p:
        username=str(p['username']).strip()
        if not username or len(username)>80 or '@' in username:raise HTTPException(400,'Укажите корректный логин')
        duplicate=db.scalar(select(AdminUser).where(func.lower(AdminUser.username)==username.lower(),AdminUser.id!=target.id))
        if duplicate:raise HTTPException(409,'Этот логин уже занят')
        target.username=username
    if 'email' in p:
        email=str(p['email']).strip().lower()
        if '@' not in email or len(email)>254:raise HTTPException(400,'Укажите корректный email')
        duplicate=db.scalar(select(AdminUser).where(func.lower(AdminUser.email)==email.lower(),AdminUser.id!=target.id))
        if duplicate:raise HTTPException(409,'Этот email уже занят')
        target.email=email
    if 'full_name' in p:target.full_name=str(p['full_name']).strip()[:160]
    if 'role' in p:
        if p['role'] not in ('admin','manager','operator','viewer'):raise HTTPException(400,'Недопустимая роль')
        target.role=p['role']
    if p.get('new_password'):
        new_password=str(p['new_password'])
        if len(new_password)<14:raise HTTPException(400,'Пароль не менее 14 символов')
        target.password_hash=hash_password(new_password)
    db.commit();return user_dict(target)
@app.get('/api/v1/admin/audit')
def global_audit(limit:int=Query(100,ge=1,le=500),user:AdminUser=Depends(require_roles('superadmin')),db:Session=Depends(get_db)):
    rows=db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return [{'report_id':e.report_id,'actor':e.actor,'action':e.action,'details':e.details,'created_at':iso(e.created_at)} for e in rows]


