"""Report identity metadata never goes into model prompts or public user lists."""
from datetime import datetime, timezone
from .models import UserReportProfile

GENDERS={'male':'男','female':'女','other':'其他','undisclosed':'不便透露'}


def save_registration_profile(db,uid,body):
    fields={key:getattr(body,key) for key in ('full_name','gender','age','emergency_contact_name','emergency_contact_phone')}
    if not any(value is not None for value in fields.values()):return
    db.add(UserReportProfile(user_id=uid,**fields,
        emergency_contact_authorized_at=datetime.now(timezone.utc).replace(tzinfo=None)
            if body.emergency_contact_name and body.emergency_contact_authorized else None))


def report_profile(db,uid):
    row=db.get(UserReportProfile,uid)
    return dict(full_name=row.full_name if row else None,gender=row.gender if row else None,
        gender_label=GENDERS.get(row.gender) if row else None,age=row.age if row else None,
        emergency_contact_name=row.emergency_contact_name if row and row.emergency_contact_authorized_at else None,
        emergency_contact_phone=row.emergency_contact_phone if row and row.emergency_contact_authorized_at else None)


def contact_ready(db,uid):
    value=report_profile(db,uid)
    return bool(value['emergency_contact_name'] and value['emergency_contact_phone'])


def replace_profile(db,uid,body):
    from sqlalchemy import delete
    db.execute(delete(UserReportProfile).where(UserReportProfile.user_id==uid))
    save_registration_profile(db,uid,body)
