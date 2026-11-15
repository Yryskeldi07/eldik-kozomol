from pydantic import BaseModel, Field
from typing import Literal
Category=Literal['corruption','crime','abuse','cybercrime','other']
ReportStatusValue=Literal['new','review','referred','need_info','closed']
class ReportCreate(BaseModel):
    language: Literal['ru','ky']='ru'
    category: Category
    region: str|None=Field(default=None,max_length=100)
    district: str|None=Field(default=None,max_length=100)
    description: str=Field(min_length=30,max_length=10000)
class ReportCreated(BaseModel): public_code:str; status:str; message:str
class StatusUpdate(BaseModel): status:ReportStatusValue
class StaffCreate(BaseModel):
    full_name:str=Field(min_length=3,max_length=160)
    position:str=Field(min_length=2,max_length=120)
    department:str|None=Field(default=None,max_length=160)
class AssignmentUpdate(BaseModel): staff_id:str|None=None
class NoteCreate(BaseModel): author:str=Field(min_length=2,max_length=160); body:str=Field(min_length=1,max_length=5000)
