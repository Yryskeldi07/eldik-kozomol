import secrets, string, os, uuid, hashlib, hmac, base64, json, mimetypes
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
from .models import Report, Status, Staff, AuditEvent, InternalNote, AdminUser, Attachment
from .schemas import ReportCreate, ReportCreated, StatusUpdate, StaffCreate, AssignmentUpdate, NoteCreate

app=FastAPI(title='Ð­Ð»Ð´Ð¸Ðº ÐšÓ©Ð·Ó©Ð¼Ó©Ð» API',version='2.0.0',description='ÐÐµÐ·Ð°Ð²Ð¸ÑÐ¸Ð¼Ð°Ñ ÑÐ¸ÑÑ‚ÐµÐ¼Ð° ÑƒÑ‡Ñ‘Ñ‚Ð° ÑÐ¾Ð¾Ð±Ñ‰ÐµÐ½Ð¸Ð¹. ÐÐµ ÑÐ²Ð»ÑÐµÑ‚ÑÑ Ð³Ð¾ÑÑƒÐ´Ð°Ñ€ÑÑ‚Ð²ÐµÐ½Ð½Ð¾Ð¹ Ð¿Ñ€Ð¸Ñ‘Ð¼Ð½Ð¾Ð¹.')
origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Authorization','Content-Type','X-Actor-Name'])
security=HTTPBearer(auto_error=False)
ROLES={'superadmin':6,'admin':5,'manager':4,'operator':3,'viewer':1}
ROLE_LABELS={'superadmin':'Ð¡ÑƒÐ¿ÐµÑ€Ð°Ð´Ð¼Ð¸Ð½Ð¸ÑÑ‚Ñ€Ð°Ñ‚Ð¾Ñ€','admin':'ÐÐ´Ð¼Ð¸Ð½Ð¸ÑÑ‚Ñ€Ð°Ñ‚Ð¾Ñ€','manager':'Ð ÑƒÐºÐ¾Ð²Ð¾Ð´Ð¸Ñ‚ÐµÐ»ÑŒ','operator':'ÐžÐ¿ÐµÑ€Ð°Ñ‚Ð¾Ñ€','viewer':'ÐÐ°Ð±Ð»ÑŽÐ´Ð°Ñ‚ÐµÐ»ÑŒ'}
UPLOAD_DIR=Path(settings.upload_dir)

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
    except Exception: raise HTTPException(401,'Ð¡ÐµÐ°Ð½Ñ Ð¸ÑÑ‚Ñ‘Ðº. Ð’Ð¾Ð¹Ð´Ð¸Ñ‚Ðµ ÑÐ½Ð¾Ð²Ð°.')

def current_user(credentials:HTTPAuthorizationCredentials|None=Depends(security),db:Session=Depends(get_db)):
    if not credentials: raise HTTPException(401,'Ð’Ð¾Ð¹Ð´Ð¸Ñ‚Ðµ Ð² ÑÐ¸ÑÑ‚ÐµÐ¼Ñƒ')
    payload=decode_token(credentials.credentials)
    user=db.get(AdminUser,payload.get('sub'))
    if not user or not user.active: raise HTTPException(401,'Ð£Ñ‡Ñ‘Ñ‚Ð½Ð°Ñ Ð·Ð°Ð¿Ð¸ÑÑŒ Ð¾Ñ‚ÐºÐ»ÑŽÑ‡ÐµÐ½Ð°')
    return user
def require_roles(*roles):
    def dep(user:AdminUser=Depends(current_user)):
        if ROLES.get(user.role,0)<min(ROLES[r] for r in roles): raise HTTPException(403,'ÐÐµÐ´Ð¾ÑÑ‚Ð°Ñ‚Ð¾Ñ‡Ð½Ð¾ Ð¿Ñ€Ð°Ð²')
        return user
    return dep
def make_code(): return 'EK-'+''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(10))
def find_report(db,code):
    r=db.scalar(select(Report).where(Report.public_code==code))
    if not r: raise HTTPException(404,'ÐžÐ±Ñ€Ð°Ñ‰ÐµÐ½Ð¸Ðµ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾')
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
    UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
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
def health(): return {'status':'ok','service':'eldik-kozomol-api','version':'2.0.0'}
@app.post('/api/v1/auth/login')
def login(p:dict,db:Session=Depends(get_db)):
    ident=str(p.get('username','')).strip().lower(); password=str(p.get('password',''))
    user=db.scalar(select(AdminUser).where(or_(func.lower(AdminUser.username)==ident,func.lower(AdminUser.email)==ident)))
    if not user or not user.active or not verify_password(password,user.password_hash): raise HTTPException(401,'ÐÐµÐ²ÐµÑ€Ð½Ñ‹Ð¹ Ð»Ð¾Ð³Ð¸Ð½ Ð¸Ð»Ð¸ Ð¿Ð°Ñ€Ð¾Ð»ÑŒ')
    user.last_login_at=now();db.commit()
    return {'access_token':make_token(user),'token_type':'bearer','user':user_dict(user)}
@app.get('/api/v1/auth/me')
def me(user:AdminUser=Depends(current_user)): return user_dict(user)
@app.post('/api/v1/auth/change-password')
def change_password(p:dict,user:AdminUser=Depends(current_user),db:Session=Depends(get_db)):
    old=str(p.get('old_password',''));new=str(p.get('new_password',''))
    if not verify_password(old,user.password_hash):raise HTTPException(400,'Ð¢ÐµÐºÑƒÑ‰Ð¸Ð¹ Ð¿Ð°Ñ€Ð¾Ð»ÑŒ Ð½ÐµÐ²ÐµÑ€ÐµÐ½')
    if len(new)<14:raise HTTPException(400,'ÐÐ¾Ð²Ñ‹Ð¹ Ð¿Ð°Ñ€Ð¾Ð»ÑŒ Ð´Ð¾Ð»Ð¶ÐµÐ½ ÑÐ¾Ð´ÐµÑ€Ð¶Ð°Ñ‚ÑŒ Ð½Ðµ Ð¼ÐµÐ½ÐµÐµ 14 ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð²')
    user.password_hash=hash_password(new);db.commit();return {'ok':True}
@app.post('/api/v1/reports',response_model=ReportCreated,status_code=201)
def create_report(p:ReportCreate,db:Session=Depends(get_db)):
    r=Report(public_code=make_code(),**p.model_dump(),status=Status.new);db.add(r);db.commit()
    return ReportCreated(public_code=r.public_code,status='new',message='ÐžÐ±Ñ€Ð°Ñ‰ÐµÐ½Ð¸Ðµ Ð·Ð°Ñ€ÐµÐ³Ð¸ÑÑ‚Ñ€Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð¾. Ð¡Ð¾Ñ…Ñ€Ð°Ð½Ð¸Ñ‚Ðµ Ð½Ð¾Ð¼ÐµÑ€ Ð´Ð»Ñ Ð¿Ñ€Ð¾Ð²ÐµÑ€ÐºÐ¸ ÑÑ‚Ð°Ñ‚ÑƒÑÐ°.')
@app.get('/api/v1/reports/{public_code}')
def public_status(public_code:str,db:Session=Depends(get_db)):
    r=find_report(db,public_code);return {'public_code':r.public_code,'status':r.status.value,'created_at':iso(r.created_at)}
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
        except ValueError:raise HTTPException(400,'ÐÐµÐ¸Ð·Ð²ÐµÑÑ‚Ð½Ñ‹Ð¹ ÑÑ‚Ð°Ñ‚ÑƒÑ')
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
    return d
@app.patch('/api/v1/admin/reports/{code}/status')
def change_status(code:str,p:StatusUpdate,user:AdminUser=Depends(require_roles('operator')),db:Session=Depends(get_db)):
    r=find_report(db,code);old=r.status.value;r.status=Status(p.status);audit(db,r,user.username,'Ð˜Ð·Ð¼ÐµÐ½ÐµÐ½Ð¸Ðµ ÑÑ‚Ð°Ñ‚ÑƒÑÐ°',f'{old} â†’ {p.status}');db.commit();return {'public_code':code,'status':r.status.value}
@app.patch('/api/v1/admin/reports/{code}/workflow')
def workflow(code:str,p:dict,user:AdminUser=Depends(require_roles('manager')),db:Session=Depends(get_db)):
    r=find_report(db,code)
    priority=p.get('priority',r.priority)
    if priority not in ('low','normal','high','critical'):raise HTTPException(400,'ÐÐµÐºÐ¾Ñ€Ñ€ÐµÐºÑ‚Ð½Ñ‹Ð¹ Ð¿Ñ€Ð¸Ð¾Ñ€Ð¸Ñ‚ÐµÑ‚')
    r.priority=priority
    due=p.get('due_at')
    if due:
        try:r.due_at=datetime.fromisoformat(due.replace('Z','+00:00'))
        except Exception:raise HTTPException(400,'ÐÐµÐºÐ¾Ñ€Ñ€ÐµÐºÑ‚Ð½Ð°Ñ Ð´Ð°Ñ‚Ð° ÑÑ€Ð¾ÐºÐ°')
    elif 'due_at' in p:r.due_at=None
    audit(db,r,user.username,'Ð˜Ð·Ð¼ÐµÐ½ÐµÐ½Ð¸Ðµ ÐºÐ¾Ð½Ñ‚Ñ€Ð¾Ð»Ñ',f'ÐŸÑ€Ð¸Ð¾Ñ€Ð¸Ñ‚ÐµÑ‚: {priority}; ÑÑ€Ð¾Ðº: {iso(r.due_at)}');db.commit();return {'ok':True}
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
        if not s or not s.active:raise HTTPException(400,'Ð¡Ð¾Ñ‚Ñ€ÑƒÐ´Ð½Ð¸Ðº Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ Ð¸Ð»Ð¸ Ð½ÐµÐ°ÐºÑ‚Ð¸Ð²ÐµÐ½')
        r.assigned_staff_id=s.id;desc=f'ÐÐ°Ð·Ð½Ð°Ñ‡ÐµÐ½ Ð¸ÑÐ¿Ð¾Ð»Ð½Ð¸Ñ‚ÐµÐ»ÑŒ: {s.full_name}'
    else:r.assigned_staff_id=None;desc='ÐžÑ‚Ð²ÐµÑ‚ÑÑ‚Ð²ÐµÐ½Ð½Ñ‹Ð¹ ÑÐ¾Ñ‚Ñ€ÑƒÐ´Ð½Ð¸Ðº ÑÐ½ÑÑ‚'
    audit(db,r,user.username,'ÐÐ°Ð·Ð½Ð°Ñ‡ÐµÐ½Ð¸Ðµ Ð¸ÑÐ¿Ð¾Ð»Ð½Ð¸Ñ‚ÐµÐ»Ñ',desc);db.commit();return {'assigned_staff_id':r.assigned_staff_id}
@app.post('/api/v1/admin/reports/{code}/notes')
def add_note(code:str,p:dict,user:AdminUser=Depends(require_roles('operator')),db:Session=Depends(get_db)):
    body=str(p.get('body','')).strip()
    if not body or len(body)>5000:raise HTTPException(400,'Ð—Ð°Ð¼ÐµÑ‚ÐºÐ° Ð´Ð¾Ð»Ð¶Ð½Ð° ÑÐ¾Ð´ÐµÑ€Ð¶Ð°Ñ‚ÑŒ 1â€“5000 ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð²')
    r=find_report(db,code);db.add(InternalNote(report_id=r.id,author=user.username,body=body));audit(db,r,user.username,'Ð’Ð½ÑƒÑ‚Ñ€ÐµÐ½Ð½ÑÑ Ð·Ð°Ð¼ÐµÑ‚ÐºÐ°','Ð”Ð¾Ð±Ð°Ð²Ð»ÐµÐ½Ð° Ð²Ð½ÑƒÑ‚Ñ€ÐµÐ½Ð½ÑÑ Ð·Ð°Ð¼ÐµÑ‚ÐºÐ°');db.commit();return {'ok':True}
@app.post('/api/v1/admin/reports/{code}/attachments')
async def upload_attachment(code:str,file:UploadFile=File(...),user:AdminUser=Depends(require_roles('operator')),db:Session=Depends(get_db)):
    r=find_report(db,code)
    allowed={'image/jpeg','image/png','image/webp','application/pdf','application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
    if file.content_type not in allowed:raise HTTPException(415,'Ð Ð°Ð·Ñ€ÐµÑˆÐµÐ½Ñ‹ JPG, PNG, WEBP, PDF, DOC Ð¸ DOCX')
    data=await file.read(settings.max_upload_mb*1024*1024+1)
    if len(data)>settings.max_upload_mb*1024*1024:raise HTTPException(413,f'ÐœÐ°ÐºÑÐ¸Ð¼Ð°Ð»ÑŒÐ½Ñ‹Ð¹ Ñ€Ð°Ð·Ð¼ÐµÑ€ Ñ„Ð°Ð¹Ð»Ð°: {settings.max_upload_mb} ÐœÐ‘')
    stored=f'{uuid.uuid4().hex}{Path(file.filename or "file").suffix.lower()[:10]}'
    (UPLOAD_DIR/stored).write_bytes(data)
    a=Attachment(report_id=r.id,original_name=Path(file.filename or 'file').name[:255],stored_name=stored,content_type=file.content_type,size=len(data),uploaded_by=user.username)
    db.add(a);audit(db,r,user.username,'Ð’Ð»Ð¾Ð¶ÐµÐ½Ð¸Ðµ',f'Ð—Ð°Ð³Ñ€ÑƒÐ¶ÐµÐ½ Ñ„Ð°Ð¹Ð»: {a.original_name}');db.commit()
    return {'id':a.id,'name':a.original_name}
@app.get('/api/v1/admin/attachments/{attachment_id}')
def download_attachment(attachment_id:str,user:AdminUser=Depends(require_roles('viewer')),db:Session=Depends(get_db)):
    a=db.get(Attachment,attachment_id)
    if not a:raise HTTPException(404,'Ð¤Ð°Ð¹Ð» Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½')
    path=UPLOAD_DIR/a.stored_name
    if not path.exists():raise HTTPException(404,'Ð¤Ð°Ð¹Ð» Ð¾Ñ‚ÑÑƒÑ‚ÑÑ‚Ð²ÑƒÐµÑ‚ Ð² Ñ…Ñ€Ð°Ð½Ð¸Ð»Ð¸Ñ‰Ðµ')
    return FileResponse(path,filename=a.original_name,media_type=a.content_type)
@app.get('/api/v1/admin/users')
def users_list(user:AdminUser=Depends(require_roles('superadmin')),db:Session=Depends(get_db)):
    return [user_dict(u) for u in db.scalars(select(AdminUser).order_by(AdminUser.created_at)).all()]
@app.post('/api/v1/admin/users')
def user_create(p:dict,user:AdminUser=Depends(require_roles('superadmin')),db:Session=Depends(get_db)):
    username=str(p.get('username','')).strip();email=str(p.get('email','')).strip().lower();password=str(p.get('password',''));role=str(p.get('role','operator'))
    if not username or len(username)>80 or '@' in username:raise HTTPException(400,'Ð£ÐºÐ°Ð¶Ð¸Ñ‚Ðµ ÐºÐ¾Ñ€Ñ€ÐµÐºÑ‚Ð½Ñ‹Ð¹ Ð»Ð¾Ð³Ð¸Ð½')
    if '@' not in email or len(email)>254:raise HTTPException(400,'Ð£ÐºÐ°Ð¶Ð¸Ñ‚Ðµ ÐºÐ¾Ñ€Ñ€ÐµÐºÑ‚Ð½Ñ‹Ð¹ email')
    if role not in ('admin','manager','operator','viewer'):raise HTTPException(400,'ÐÐµÐ´Ð¾Ð¿ÑƒÑÑ‚Ð¸Ð¼Ð°Ñ Ñ€Ð¾Ð»ÑŒ. SUPERADMIN Ð½ÐµÐ»ÑŒÐ·Ñ Ð½Ð°Ð·Ð½Ð°Ñ‡Ð¸Ñ‚ÑŒ Ñ‡ÐµÑ€ÐµÐ· Ð¿Ð°Ð½ÐµÐ»ÑŒ.')
    if len(password)<14:raise HTTPException(400,'ÐŸÐ°Ñ€Ð¾Ð»ÑŒ Ð´Ð¾Ð»Ð¶ÐµÐ½ ÑÐ¾Ð´ÐµÑ€Ð¶Ð°Ñ‚ÑŒ Ð½Ðµ Ð¼ÐµÐ½ÐµÐµ 14 ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð²')
    if db.scalar(select(AdminUser).where(or_(func.lower(AdminUser.username)==username.lower(),func.lower(AdminUser.email)==email.lower()))):raise HTTPException(409,'Ð›Ð¾Ð³Ð¸Ð½ Ð¸Ð»Ð¸ email ÑƒÐ¶Ðµ Ð·Ð°Ð½ÑÑ‚')
    u=AdminUser(username=username,email=email,full_name=str(p.get('full_name',''))[:160],password_hash=hash_password(password),role=role,active=True);db.add(u);db.commit();db.refresh(u);return user_dict(u)
@app.patch('/api/v1/admin/users/{user_id}')
def user_update(user_id:str,p:dict,user:AdminUser=Depends(require_roles('superadmin')),db:Session=Depends(get_db)):
    target=db.get(AdminUser,user_id)
    if not target:raise HTTPException(404,'ÐŸÐ¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ñ‚ÐµÐ»ÑŒ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½')
    if target.role=='superadmin':raise HTTPException(403,'Ð£Ñ‡Ñ‘Ñ‚Ð½ÑƒÑŽ Ð·Ð°Ð¿Ð¸ÑÑŒ SUPERADMIN Ð½ÐµÐ»ÑŒÐ·Ñ Ð¼ÐµÐ½ÑÑ‚ÑŒ Ñ‡ÐµÑ€ÐµÐ· Ð¿Ð°Ð½ÐµÐ»ÑŒ')
    if 'active' in p:target.active=bool(p['active'])
    if 'username' in p:
        username=str(p['username']).strip()
        if not username or len(username)>80 or '@' in username:raise HTTPException(400,'Ð£ÐºÐ°Ð¶Ð¸Ñ‚Ðµ ÐºÐ¾Ñ€Ñ€ÐµÐºÑ‚Ð½Ñ‹Ð¹ Ð»Ð¾Ð³Ð¸Ð½')
        duplicate=db.scalar(select(AdminUser).where(func.lower(AdminUser.username)==username.lower(),AdminUser.id!=target.id))
        if duplicate:raise HTTPException(409,'Ð­Ñ‚Ð¾Ñ‚ Ð»Ð¾Ð³Ð¸Ð½ ÑƒÐ¶Ðµ Ð·Ð°Ð½ÑÑ‚')
        target.username=username
    if 'email' in p:
        email=str(p['email']).strip().lower()
        if '@' not in email or len(email)>254:raise HTTPException(400,'Ð£ÐºÐ°Ð¶Ð¸Ñ‚Ðµ ÐºÐ¾Ñ€Ñ€ÐµÐºÑ‚Ð½Ñ‹Ð¹ email')
        duplicate=db.scalar(select(AdminUser).where(func.lower(AdminUser.email)==email.lower(),AdminUser.id!=target.id))
        if duplicate:raise HTTPException(409,'Ð­Ñ‚Ð¾Ñ‚ email ÑƒÐ¶Ðµ Ð·Ð°Ð½ÑÑ‚')
        target.email=email
    if 'full_name' in p:target.full_name=str(p['full_name']).strip()[:160]
    if 'role' in p:
        if p['role'] not in ('admin','manager','operator','viewer'):raise HTTPException(400,'ÐÐµÐ´Ð¾Ð¿ÑƒÑÑ‚Ð¸Ð¼Ð°Ñ Ñ€Ð¾Ð»ÑŒ')
        target.role=p['role']
    if p.get('new_password'):
        new_password=str(p['new_password'])
        if len(new_password)<14:raise HTTPException(400,'ÐŸÐ°Ñ€Ð¾Ð»ÑŒ Ð½Ðµ Ð¼ÐµÐ½ÐµÐµ 14 ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð²')
        target.password_hash=hash_password(new_password)
    db.commit();return user_dict(target)
@app.get('/api/v1/admin/audit')
def global_audit(limit:int=Query(100,ge=1,le=500),user:AdminUser=Depends(require_roles('superadmin')),db:Session=Depends(get_db)):
    rows=db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return [{'report_id':e.report_id,'actor':e.actor,'action':e.action,'details':e.details,'created_at':iso(e.created_at)} for e in rows]


