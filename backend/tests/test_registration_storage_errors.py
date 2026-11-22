from sqlalchemy.exc import OperationalError
from app.database import get_db
from app.main import app


def test_edge_registration_reports_unavailable_server_without_leaking_details(actors,monkeypatch):
    actor,_=actors
    monkeypatch.setenv('ROBOT_CARE_DEPLOYMENT_ROLE','edge')
    def offline():
        raise OperationalError('private query',{},RuntimeError('private diagnostic detail'))
    app.dependency_overrides[get_db]=offline
    try:
        result=actor.client.post('/api/auth/register',json={'username':'storage_error_example','password':'fictional-only'})
        assert result.status_code==503
        assert result.json()['code']=='server_storage_unavailable'
        assert '服务器数据库' in result.json()['detail']
        assert 'private query' not in result.text and 'diagnostic detail' not in result.text
    finally:
        app.dependency_overrides.pop(get_db,None)
